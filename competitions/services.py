"""
Registration rules.

Every change to a registration or roster goes through these functions, so
the competition's rules are always enforced on the server, every change is
written to the activity log, and coaches are emailed about decisions.

Registration life cycle:

    draft ──submit──▶ submitted ──approve──▶ approved
      ▲                 │  │                   │
      └──── unsubmit ───┘  ├─waitlist─▶ waitlisted ──approve──▶ approved
                           └─request changes─▶ changes requested ──submit──▶ submitted
    Any status ──withdraw──▶ withdrawn

  - Drafts can be edited while registration is open.
  - "Changes requested" can be edited and resubmitted until the roster deadline.
  - Approved rosters change only through roster change requests, approved by
    an administrator, until the roster deadline. Administrators can always
    edit a roster directly; those edits are logged.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from audit.log import record
from schools.models import CoachAccess, Membership
from schools.permissions import schools_for

from .models import Competition, Registration, RosterChange, RosterEntry

Status = Registration.Status
ACTIVE = [s for s in Status.values if s != Status.WITHDRAWN]


# ------------------------------------------------------------------ helpers


def _fail(*messages):
    raise ValidationError([str(m) for m in messages])


def _coach_emails(registration):
    emails = set(
        CoachAccess.objects.approved().filter(school=registration.school).values_list("coach__email", flat=True)
    )
    if registration.created_by.is_active:
        emails.add(registration.created_by.email)
    return sorted(emails)


def _notify(request, registration, subject, template, **context):
    recipients = _coach_emails(registration)
    if not recipients:
        return
    link = request.build_absolute_uri(reverse("competitions:registration", args=[registration.pk]))
    body = render_to_string(template, {"registration": registration, "link": link, **context})
    transaction.on_commit(lambda: send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients))


def _set_status(registration, status, admin=None):
    old = registration.get_status_display()
    registration.status = status
    if admin is not None:
        registration.decided_at = timezone.now()
        registration.decided_by = admin
    return {"status": [str(old), str(registration.get_status_display())]}


def coach_can_edit(registration, now=None):
    """Can a coach change this registration's team name and roster right now?"""
    now = now or timezone.now()
    competition = registration.competition
    if registration.status == Status.DRAFT:
        return competition.registration_state(now) == Competition.RegistrationState.OPEN
    if registration.status == Status.CHANGES_REQUESTED:
        return now < competition.roster_deadline
    return False


def coach_can_request_roster_change(registration):
    return registration.status == Status.APPROVED and registration.competition.roster_changes_allowed


def _require_coach_access(user, registration):
    if not schools_for(user).filter(pk=registration.school_id).exists():
        _fail(_("You don't have access to this school."))


# ------------------------------------------------------------------ rule checks


def player_problems(competition, student, gamer_tag, rank, *, registration=None):
    """Reasons a student can't be on a team in this competition (empty if they can)."""
    problems = []
    if registration is not None and student.school_id != registration.school_id:
        problems.append(_("%(s)s is not a student at this school.") % {"s": student})
    if not student.is_active:
        problems.append(_("%(s)s is marked as no longer at the school.") % {"s": student})
    if not competition.grade_is_eligible(student.grade):
        problems.append(
            _("%(s)s is in grade %(g)s; this competition is for %(range)s.")
            % {"s": student, "g": student.grade, "range": competition.grade_range_label}
        )
    if competition.require_gamer_tag and not gamer_tag.strip():
        problems.append(
            _("%(label)s is required for %(s)s.") % {"label": competition.game.gamer_tag_label, "s": student}
        )
    if competition.rank_requirement == Competition.RankRequirement.REQUIRED and not rank.strip():
        problems.append(_("%(label)s is required for %(s)s.") % {"label": competition.game.rank_label, "s": student})
    other = RosterEntry.objects.filter(
        student=student, registration__competition=competition, registration__status__in=ACTIVE
    )
    if registration is not None:
        other = other.exclude(registration=registration)
    other = other.select_related("registration").first()
    if other:
        problems.append(
            _("%(s)s is already on another team in this competition (%(team)s).")
            % {"s": student, "team": other.registration.team_name}
        )
    return problems


def roster_problems(registration):
    """Everything that would stop this registration from being submitted."""
    competition = registration.competition
    problems = []
    if not competition.school_is_eligible(registration.school):
        problems.append(
            _("%(school)s is not eligible: this competition is open to %(levels)s schools.")
            % {"school": registration.school.name, "levels": competition.allowed_levels_display().lower()}
        )
    entries = list(registration.roster.select_related("student"))
    size = len(entries)
    if size < competition.roster_min:
        problems.append(
            _("The roster has %(n)s player(s); at least %(min)s are needed.")
            % {"n": size, "min": competition.roster_min}
        )
    if size > competition.roster_max:
        problems.append(
            _("The roster has %(n)s players; the most allowed is %(max)s.") % {"n": size, "max": competition.roster_max}
        )
    for entry in entries:
        problems.extend(
            player_problems(competition, entry.student, entry.gamer_tag, entry.rank, registration=registration)
        )
    return problems


def membership_for(registration):
    return Membership.objects.filter(
        school=registration.school, school_year=registration.competition.school_year
    ).first()


def approval_problems(registration):
    """Everything that would stop an administrator from approving this registration."""
    problems = roster_problems(registration)
    membership = membership_for(registration)
    if membership is None or not membership.in_good_standing:
        problems.append(
            _("%(school)s's %(year)s membership isn't confirmed. Confirm it or record an exception first.")
            % {"school": registration.school.name, "year": registration.competition.school_year}
        )
    competition = registration.competition
    if competition.max_teams:
        approved = competition.registrations.filter(status=Status.APPROVED).exclude(pk=registration.pk).count()
        if approved >= competition.max_teams:
            problems.append(
                _("The competition is full (%(n)s teams). Waitlist this team or raise the limit.")
                % {"n": competition.max_teams}
            )
    return problems


# ------------------------------------------------------------------ coach actions


@transaction.atomic
def create_registration(user, competition, school, team_name):
    team_name = team_name.strip()
    if not competition.is_published or not competition.registration_is_open:
        _fail(_("Registration for this competition isn't open."))
    if not schools_for(user).filter(pk=school.pk).exists():
        _fail(_("You don't have access to this school."))
    if not competition.school_is_eligible(school):
        _fail(
            _("%(school)s can't enter: this competition is open to %(levels)s schools.")
            % {"school": school.name, "levels": competition.allowed_levels_display().lower()}
        )
    if competition.max_teams_per_school:
        existing = competition.registrations.filter(school=school, status__in=ACTIVE).count()
        if existing >= competition.max_teams_per_school:
            _fail(
                _("Each school can enter at most %(n)s team(s) in this competition.")
                % {"n": competition.max_teams_per_school}
            )
    if not team_name:
        _fail(_("Enter a team name."))
    if competition.registrations.filter(team_name__iexact=team_name).exists():
        _fail(_("Another team in this competition is already called “%(name)s”.") % {"name": team_name})
    try:
        registration = Registration.objects.create(
            competition=competition, school=school, team_name=team_name, created_by=user
        )
    except IntegrityError:
        _fail(_("Another team in this competition is already called “%(name)s”.") % {"name": team_name})
    record(
        user, "registration.created", f"Started registration for {registration} in {competition}", target=registration
    )
    return registration


@transaction.atomic
def rename_team(registration, user, team_name, *, by_admin=False):
    team_name = team_name.strip()
    if not by_admin:
        _require_coach_access(user, registration)
        if not coach_can_edit(registration):
            _fail(_("This registration can't be changed right now."))
    if not team_name:
        _fail(_("Enter a team name."))
    clash = registration.competition.registrations.filter(team_name__iexact=team_name).exclude(pk=registration.pk)
    if clash.exists():
        _fail(_("Another team in this competition is already called “%(name)s”.") % {"name": team_name})
    old = registration.team_name
    if old == team_name:
        return registration
    registration.team_name = team_name
    registration.save(update_fields=["team_name", "updated_at"])
    record(
        user,
        "registration.renamed",
        f"Renamed team {old} to {team_name}",
        target=registration,
        changes={"team name": [old, team_name]},
    )
    return registration


@transaction.atomic
def add_player(registration, user, student, gamer_tag="", rank="", *, by_admin=False):
    registration = Registration.objects.select_for_update().get(pk=registration.pk)
    competition = registration.competition
    if not by_admin:
        _require_coach_access(user, registration)
        if not coach_can_edit(registration):
            _fail(_("This roster can't be changed right now."))
    if registration.status == Status.WITHDRAWN:
        _fail(_("This team has withdrawn."))
    if registration.roster.filter(student=student).exists():
        _fail(_("%(s)s is already on this roster.") % {"s": student})
    if registration.roster.count() >= competition.roster_max:
        _fail(_("The roster is full (%(max)s players).") % {"max": competition.roster_max})
    problems = player_problems(competition, student, gamer_tag, rank, registration=registration)
    if problems:
        _fail(*problems)
    entry = RosterEntry.objects.create(
        registration=registration, student=student, gamer_tag=gamer_tag.strip(), rank=rank.strip()
    )
    record(
        user,
        "registration.player_added",
        f"Added {student} to {registration.team_name}",
        target=registration,
        changes={"player": ["", f"{student} ({gamer_tag.strip() or 'no in-game name'})"]},
    )
    return entry


@transaction.atomic
def remove_player(entry, user, *, by_admin=False):
    registration = entry.registration
    if not by_admin:
        _require_coach_access(user, registration)
        if not coach_can_edit(registration):
            _fail(_("This roster can't be changed right now."))
    student = entry.student
    entry.delete()
    record(
        user,
        "registration.player_removed",
        f"Removed {student} from {registration.team_name}",
        target=registration,
        changes={"player": [str(student), ""]},
    )


@transaction.atomic
def submit(request, registration, user, consent_confirmed):
    registration = Registration.objects.select_for_update().get(pk=registration.pk)
    _require_coach_access(user, registration)
    if registration.status not in (Status.DRAFT, Status.CHANGES_REQUESTED) or not coach_can_edit(registration):
        _fail(_("This registration can't be submitted right now."))
    if not consent_confirmed:
        _fail(_("Confirm that consent forms are on file for every player."))
    problems = roster_problems(registration)
    if problems:
        _fail(*problems)
    changes = _set_status(registration, Status.SUBMITTED)
    now = timezone.now()
    registration.submitted_at = now
    registration.submitted_by = user
    registration.consent_confirmed_at = now
    registration.consent_confirmed_by = user
    registration.save()
    record(
        user,
        "registration.submitted",
        f"Submitted {registration.team_name} ({registration.school.name}) for {registration.competition}",
        target=registration,
        changes=changes,
    )
    return registration


@transaction.atomic
def unsubmit(registration, user):
    """Coach takes a submitted registration back to draft to make changes, while registration is open."""
    _require_coach_access(user, registration)
    if registration.status != Status.SUBMITTED or not registration.competition.registration_is_open:
        _fail(_("Only submitted registrations can be reopened, and only while registration is open."))
    changes = _set_status(registration, Status.DRAFT)
    registration.save()
    record(
        user,
        "registration.reopened",
        f"Reopened {registration.team_name} as a draft",
        target=registration,
        changes=changes,
    )
    return registration


@transaction.atomic
def withdraw(request, registration, user, reason="", *, by_admin=False):
    if not by_admin:
        _require_coach_access(user, registration)
    if registration.status == Status.WITHDRAWN:
        _fail(_("This team has already withdrawn."))
    if by_admin and not reason.strip():
        _fail(_("Give a reason for withdrawing this team."))
    changes = _set_status(registration, Status.WITHDRAWN, admin=user if by_admin else None)
    if reason.strip():
        registration.admin_message = reason.strip() if by_admin else registration.admin_message
        changes["reason"] = ["", reason.strip()]
    registration.save()
    record(
        user,
        "registration.withdrawn",
        f"Withdrew {registration.team_name} ({registration.school.name})",
        target=registration,
        changes=changes,
    )
    if by_admin:
        _notify(
            request,
            registration,
            f"{registration.team_name} has been withdrawn",
            "competitions/emails/registration_decision.txt",
        )
    return registration


# ------------------------------------------------------------------ administrator decisions


def _check_division(registration, division):
    if division is not None and division.competition_id != registration.competition_id:
        _fail(_("That division belongs to a different competition."))


@transaction.atomic
def approve(request, registration, admin, division=None, message=""):
    registration = Registration.objects.select_for_update().get(pk=registration.pk)
    if registration.status not in (Status.SUBMITTED, Status.WAITLISTED):
        _fail(_("Only submitted or waitlisted registrations can be approved."))
    _check_division(registration, division)
    problems = approval_problems(registration)
    if problems:
        _fail(*problems)
    changes = _set_status(registration, Status.APPROVED, admin)
    if division is not None and division != registration.division:
        changes["division"] = [str(registration.division or ""), str(division)]
        registration.division = division
    registration.admin_message = message.strip()
    registration.save()
    record(
        admin,
        "registration.approved",
        f"Approved {registration.team_name} ({registration.school.name})",
        target=registration,
        changes=changes,
    )
    _notify(
        request, registration, f"{registration.team_name} is approved", "competitions/emails/registration_decision.txt"
    )
    return registration


@transaction.atomic
def waitlist(request, registration, admin, message=""):
    if registration.status not in (Status.SUBMITTED,):
        _fail(_("Only submitted registrations can be waitlisted."))
    changes = _set_status(registration, Status.WAITLISTED, admin)
    registration.admin_message = message.strip()
    registration.save()
    record(
        admin,
        "registration.waitlisted",
        f"Waitlisted {registration.team_name} ({registration.school.name})",
        target=registration,
        changes=changes,
    )
    _notify(
        request,
        registration,
        f"{registration.team_name} is on the waitlist",
        "competitions/emails/registration_decision.txt",
    )
    return registration


@transaction.atomic
def request_changes(request, registration, admin, message):
    if registration.status not in (Status.SUBMITTED, Status.WAITLISTED):
        _fail(_("Changes can only be requested on submitted or waitlisted registrations."))
    if not message.strip():
        _fail(_("Tell the coach what needs to change."))
    changes = _set_status(registration, Status.CHANGES_REQUESTED, admin)
    registration.admin_message = message.strip()
    changes["message"] = ["", registration.admin_message]
    registration.save()
    record(
        admin,
        "registration.changes_requested",
        f"Asked {registration.school.name} to change {registration.team_name}",
        target=registration,
        changes=changes,
    )
    _notify(
        request,
        registration,
        f"Changes needed: {registration.team_name}",
        "competitions/emails/registration_decision.txt",
    )
    return registration


@transaction.atomic
def assign_division(registration, admin, division):
    if registration.status == Status.WITHDRAWN:
        _fail(_("This team has withdrawn."))
    _check_division(registration, division)
    if registration.division == division:
        return registration
    changes = {"division": [str(registration.division or ""), str(division or "")]}
    registration.division = division
    registration.save(update_fields=["division", "updated_at"])
    record(
        admin,
        "registration.division_assigned",
        f"Placed {registration.team_name} in {division or 'no division'}",
        target=registration,
        changes=changes,
    )
    return registration


# ------------------------------------------------------------------ roster changes after approval


@transaction.atomic
def request_roster_change(registration, user, *, player_in=None, player_out=None, gamer_tag="", rank="", reason=""):
    _require_coach_access(user, registration)
    if not coach_can_request_roster_change(registration):
        _fail(_("Roster changes can only be requested for approved teams before the roster deadline."))
    if player_in is None and player_out is None:
        _fail(_("Choose a player to add, a player to remove, or both."))
    if not reason.strip():
        _fail(_("Give a reason for the change."))
    if player_out is not None and not registration.roster.filter(student=player_out).exists():
        _fail(_("%(s)s isn't on this roster.") % {"s": player_out})
    if player_in is not None:
        if registration.roster.filter(student=player_in).exists():
            _fail(_("%(s)s is already on this roster.") % {"s": player_in})
        problems = player_problems(registration.competition, player_in, gamer_tag, rank, registration=registration)
        if problems:
            _fail(*problems)
    pending = registration.roster_changes.filter(status=RosterChange.Status.PENDING)
    involved = {p.pk for p in (player_in, player_out) if p is not None}
    if pending.filter(player_in__in=involved).exists() or pending.filter(player_out__in=involved).exists():
        _fail(_("There's already a pending change for this player."))
    change = RosterChange.objects.create(
        registration=registration,
        player_in=player_in,
        player_out=player_out,
        gamer_tag=gamer_tag.strip(),
        rank=rank.strip(),
        reason=reason.strip(),
        requested_by=user,
    )
    record(
        user,
        "roster_change.requested",
        f"Requested roster change for {registration.team_name}: {change.description}",
        target=registration,
        changes={"reason": ["", change.reason]},
    )
    return change


@transaction.atomic
def approve_roster_change(request, change, admin, note=""):
    change = RosterChange.objects.select_for_update().get(pk=change.pk)
    registration = change.registration
    competition = registration.competition
    if change.status != RosterChange.Status.PENDING:
        _fail(_("This change has already been decided."))
    if registration.status != Status.APPROVED:
        _fail(_("The team is no longer approved."))
    size = registration.roster.count()
    if change.player_out is not None:
        entry = registration.roster.filter(student=change.player_out).first()
        if entry is None:
            _fail(_("%(s)s is no longer on the roster.") % {"s": change.player_out})
        size -= 1
    if change.player_in is not None:
        if registration.roster.filter(student=change.player_in).exists():
            _fail(_("%(s)s is already on the roster.") % {"s": change.player_in})
        problems = player_problems(
            competition, change.player_in, change.gamer_tag, change.rank, registration=registration
        )
        if problems:
            _fail(*problems)
        size += 1
    if size > competition.roster_max:
        _fail(
            _("This change would leave %(n)s players; the most allowed is %(max)s.")
            % {"n": size, "max": competition.roster_max}
        )
    if size < competition.roster_min:
        _fail(
            _("This change would leave %(n)s players; at least %(min)s are needed.")
            % {"n": size, "min": competition.roster_min}
        )

    if change.player_out is not None:
        registration.roster.filter(student=change.player_out).delete()
    if change.player_in is not None:
        RosterEntry.objects.create(
            registration=registration, student=change.player_in, gamer_tag=change.gamer_tag, rank=change.rank
        )
    change.status = RosterChange.Status.APPROVED
    change.decided_at = timezone.now()
    change.decided_by = admin
    change.decision_note = note.strip()
    change.save()
    record(
        admin,
        "roster_change.approved",
        f"Approved roster change for {registration.team_name}: {change.description}",
        target=registration,
    )
    _notify(
        request,
        registration,
        f"Roster change approved: {registration.team_name}",
        "competitions/emails/roster_change_decision.txt",
        change=change,
    )
    return change


@transaction.atomic
def decline_roster_change(request, change, admin, note):
    if change.status != RosterChange.Status.PENDING:
        _fail(_("This change has already been decided."))
    if not note.strip():
        _fail(_("Tell the coach why the change was declined."))
    change.status = RosterChange.Status.DECLINED
    change.decided_at = timezone.now()
    change.decided_by = admin
    change.decision_note = note.strip()
    change.save()
    record(
        admin,
        "roster_change.declined",
        f"Declined roster change for {change.registration.team_name}: {change.description}",
        target=change.registration,
        changes={"message": ["", change.decision_note]},
    )
    _notify(
        request,
        change.registration,
        f"Roster change declined: {change.registration.team_name}",
        "competitions/emails/roster_change_decision.txt",
        change=change,
    )
    return change
