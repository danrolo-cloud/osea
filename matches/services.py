"""
Scheduling rules.

  - Administrators generate a stage's matches from its format, or add matches
    by hand, and publish the stage when it's ready.
  - Coaches agree on match times themselves: one team's coach proposes a time,
    the other team's coach accepts (or declines, or suggests another). An
    accepted time is final until either side proposes a new one and the other
    accepts. No administrator approval is needed.
  - Administrators can set or change any match time, and cancel or restore matches.

Every change is written to the activity log.
"""

import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from audit.log import record
from competitions.services import coach_emails
from schools.permissions import schools_for

from . import generators
from .models import Match, Stage, StageTeam, TimeProposal

TORONTO = ZoneInfo("America/Toronto")


def _fail(*messages):
    raise ValidationError([str(m) for m in messages])


def _when(value):
    return timezone.localtime(value).strftime("%a %b %-d, %-I:%M %p")


def _notify(request, registrations, subject, template, **context):
    recipients = sorted({email for r in registrations if r is not None for email in coach_emails(r)})
    if not recipients:
        return
    match = context.get("match")
    link = request.build_absolute_uri(reverse("matches:coach_match", args=[match.pk])) if match else ""
    body = render_to_string(template, {"link": link, **context})
    transaction.on_commit(lambda: send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients))


# ------------------------------------------------------------------ who's who


def coached_sides(user, match):
    """Which sides of the match ("home", "away") this person coaches. Empty if neither."""
    if not user.is_authenticated:
        return []
    my_schools = set(schools_for(user).values_list("pk", flat=True))
    return [side for side in ("home", "away") if getattr(match, side) and getattr(match, side).school_id in my_schools]


def visible_to_coach(user, match):
    return match.stage.is_published and bool(coached_sides(user, match))


# ------------------------------------------------------------------ building a stage


def _window(start_date, days, window):
    start = datetime.datetime.combine(start_date, datetime.time.min, tzinfo=TORONTO)
    play_from = start + datetime.timedelta(days=(window - 1) * days)
    play_by = start + datetime.timedelta(days=window * days) - datetime.timedelta(minutes=1)
    return play_from, play_by


@transaction.atomic
def generate_stage(stage, admin, seeded_teams, *, first_day, days_per_round):
    """Create every match the stage's format needs (round 1 only for Swiss)."""
    stage = Stage.objects.select_for_update().get(pk=stage.pk)
    if stage.matches.exists():
        _fail(_("This stage already has matches. Clear them first to generate again."))
    if stage.format == Stage.Format.CUSTOM:
        _fail(_("Custom stages don't generate matches; add them by hand."))
    eligible = set(stage.eligible_teams().values_list("pk", flat=True))
    if any(team.pk not in eligible for team in seeded_teams):
        _fail(_("Only approved teams in this stage's division can be included."))
    if len({t.pk for t in seeded_teams}) != len(seeded_teams):
        _fail(_("Each team can only be seeded once."))
    if days_per_round < 1:
        _fail(_("Each round needs at least one day."))

    builders = {
        Stage.Format.ROUND_ROBIN: lambda teams: generators.round_robin(teams),
        Stage.Format.DOUBLE_ROUND_ROBIN: lambda teams: generators.round_robin(teams, twice=True),
        Stage.Format.SINGLE_ELIMINATION: generators.single_elimination,
        Stage.Format.DOUBLE_ELIMINATION: generators.double_elimination,
        Stage.Format.SWISS: generators.swiss_first_round,
    }
    try:
        plans = builders[stage.format](list(seeded_teams))
    except ValueError as error:
        _fail(str(error))

    stage.entries.all().delete()
    StageTeam.objects.bulk_create(
        [StageTeam(stage=stage, registration=team, seed=seed) for seed, team in enumerate(seeded_teams, start=1)]
    )
    created = {}
    for number, plan in enumerate(plans, start=1):
        play_from, play_by = _window(first_day, days_per_round, plan["window"])
        match = Match.objects.create(
            stage=stage, number=number, round_number=plan["window"], round_label=plan["label"],
            bracket=plan["bracket"], home=plan["home"], away=plan["away"], play_from=play_from, play_by=play_by,
            home_source=created[plan["home_from"][0]] if plan["home_from"] else None,
            home_source_outcome=plan["home_from"][1] if plan["home_from"] else "",
            away_source=created[plan["away_from"][0]] if plan["away_from"] else None,
            away_source_outcome=plan["away_from"][1] if plan["away_from"] else "",
        )  # fmt: skip
        created[plan["key"]] = match
    resolve_stage(stage)
    record(
        admin,
        "stage.generated",
        f"Generated {len(plans)} matches for {stage} ({stage.get_format_display()})",
        target=stage.competition,
        changes={"teams": ["", ", ".join(t.team_name for t in seeded_teams)]},
    )
    return list(created.values())


@transaction.atomic
def clear_stage(stage, admin):
    count = stage.matches.count()
    stage.matches.all().delete()
    stage.entries.all().delete()
    record(admin, "stage.cleared", f"Removed all {count} matches from {stage}", target=stage.competition)
    return count


def _slot(match, side):
    """(known, team): whether this side is decided yet, and which team (None means nobody: a bye)."""
    source = getattr(match, f"{side}_source")
    if source is None:
        return True, getattr(match, side)
    if not source.is_settled:
        return False, None
    if getattr(match, f"{side}_source_outcome") == Match.Outcome.LOSER:
        return True, source.loser
    return True, source.winner


def resolve_stage(stage):
    """
    Bring every linked slot up to date with the matches that feed it, and turn
    matches with only one team into byes (that team goes through). Runs after
    any result is entered, corrected or reopened. Matches are processed in
    number order, which always comes after the matches that feed them.
    """
    for match in stage.matches.order_by("number"):
        if match.status == Match.Status.CANCELLED or match.has_result:
            continue
        changed = False
        known = {}
        for side in ("home", "away"):
            is_known, team = _slot(match, side)
            known[side] = is_known
            if getattr(match, f"{side}_source_id"):
                new = team if is_known else None
                if getattr(match, side) != new:
                    setattr(match, side, new)
                    changed = True
        linked = match.home_source_id or match.away_source_id
        one_sided = (match.home is None) != (match.away is None)
        if known["home"] and known["away"] and (one_sided or (linked and match.home is None and match.away is None)):
            winner = match.home or match.away  # None when both slots are empty: nobody advances
            if match.status != Match.Status.BYE or match.winner != winner:
                match.status, match.winner, changed = Match.Status.BYE, winner, True
        elif match.status == Match.Status.BYE:
            match.status, match.winner, changed = Match.Status.OPEN, None, True
        if changed:
            match.save()


# ------------------------------------------------------------------ administrator match changes


@transaction.atomic
def add_match(stage, admin, *, home, away, round_number, round_label, play_from=None, play_by=None):
    if home is not None and away is not None and home == away:
        _fail(_("A team can't play itself."))
    for team in (home, away):
        if team is not None and team.competition_id != stage.competition_id:
            _fail(_("Both teams must be in this competition."))
    number = (stage.matches.order_by("-number").values_list("number", flat=True).first() or 0) + 1
    match = Match.objects.create(
        stage=stage, number=number, home=home, away=away, round_number=round_number, round_label=round_label,
        play_from=play_from, play_by=play_by,
        status=Match.Status.BYE if (home is None) != (away is None) else Match.Status.OPEN,
        winner=(home or away) if (home is None) != (away is None) else None,
    )  # fmt: skip
    record(
        admin,
        "match.created",
        f"Added {match} ({match.slot_label('home')} v {match.slot_label('away')}) to {stage}",
        target=stage.competition,
    )
    return match


@transaction.atomic
def set_time(request, match, admin, when):
    """An administrator sets, changes or clears a match time directly."""
    old = match.scheduled_at
    if old == when:
        return match
    match.scheduled_at = when
    match.save(update_fields=["scheduled_at", "updated_at"])
    match.proposals.filter(status=TimeProposal.Status.PENDING).update(status=TimeProposal.Status.REPLACED)
    record(
        admin,
        "match.time_set",
        f"OSEA set {match} of {match.stage} to {_when(when) if when else 'no time'}",
        target=match.stage.competition,
        changes={"time": [_when(old) if old else "", _when(when) if when else ""]},
    )
    if when and match.stage.is_published:
        _notify(
            request,
            match.teams(),
            f"Match time set: {match.slot_label('home')} v {match.slot_label('away')}",
            "matches/emails/time_set.txt",
            match=match,
        )
    return match


@transaction.atomic
def cancel_match(request, match, admin, reason):
    if match.status == Match.Status.CANCELLED:
        _fail(_("This match is already cancelled."))
    if not reason.strip():
        _fail(_("Give a reason for cancelling."))
    match.status = Match.Status.CANCELLED
    match.cancel_reason = reason.strip()
    match.save(update_fields=["status", "cancel_reason", "updated_at"])
    match.proposals.filter(status=TimeProposal.Status.PENDING).update(status=TimeProposal.Status.REPLACED)
    record(
        admin,
        "match.cancelled",
        f"Cancelled {match} of {match.stage}",
        target=match.stage.competition,
        changes={"reason": ["", match.cancel_reason]},
    )
    if match.stage.is_published:
        _notify(
            request,
            match.teams(),
            f"Match cancelled: {match.slot_label('home')} v {match.slot_label('away')}",
            "matches/emails/cancelled.txt",
            match=match,
        )
    return match


@transaction.atomic
def restore_match(match, admin):
    if match.status != Match.Status.CANCELLED:
        _fail(_("Only cancelled matches can be restored."))
    match.status = Match.Status.OPEN
    match.cancel_reason = ""
    match.save(update_fields=["status", "cancel_reason", "updated_at"])
    resolve_stage(match.stage)
    record(admin, "match.restored", f"Restored {match} of {match.stage}", target=match.stage.competition)
    return match


# ------------------------------------------------------------------ coaches agreeing on a time


def _require_open(match):
    if not match.stage.is_published:
        _fail(_("This match hasn't been published yet."))
    if not match.is_playable:
        _fail(_("Times can only be arranged for matches between two known teams that aren't cancelled."))


@transaction.atomic
def propose_time(request, match, user, when, note=""):
    match = Match.objects.select_for_update().get(pk=match.pk)
    _require_open(match)
    sides = coached_sides(user, match)
    if not sides:
        _fail(_("Only coaches of the two teams can arrange this match."))
    if when <= timezone.now():
        _fail(_("Choose a time in the future."))
    team = getattr(match, sides[0])
    match.proposals.filter(status=TimeProposal.Status.PENDING).update(status=TimeProposal.Status.REPLACED)
    proposal = TimeProposal.objects.create(
        match=match, proposed_time=when, proposing_team=team, proposed_by=user, note=note.strip()
    )
    record(
        user,
        "match.time_proposed",
        f"{team.team_name} proposed {_when(when)} for {match} of {match.stage}",
        target=match.stage.competition,
    )
    other = match.away if team == match.home else match.home
    _notify(
        request,
        [other],
        f"New match time proposed: {match.home.team_name} v {match.away.team_name}",
        "matches/emails/time_proposed.txt",
        match=match,
        proposal=proposal,
    )
    return proposal


def _respondable(proposal, user):
    if proposal.status != TimeProposal.Status.PENDING:
        _fail(_("This proposal has already been answered or replaced."))
    _require_open(proposal.match)
    match = proposal.match
    other_side = "away" if proposal.proposing_team_id == match.home_id else "home"
    if other_side not in coached_sides(user, match):
        _fail(_("Only the other team's coaches can answer this proposal."))


@transaction.atomic
def accept_proposal(request, proposal, user):
    proposal = TimeProposal.objects.select_for_update().select_related("match__stage").get(pk=proposal.pk)
    _respondable(proposal, user)
    if proposal.proposed_time <= timezone.now():
        _fail(_("That time has already passed. Propose a new one."))
    match = proposal.match
    old = match.scheduled_at
    match.scheduled_at = proposal.proposed_time
    match.save(update_fields=["scheduled_at", "updated_at"])
    proposal.status = TimeProposal.Status.ACCEPTED
    proposal.responded_at, proposal.responded_by = timezone.now(), user
    proposal.save()
    verb = "Rescheduled" if old else "Scheduled"
    record(
        user,
        "match.time_agreed",
        f"{verb} {match} of {match.stage}: {match.home.team_name} v "
        f"{match.away.team_name} at {_when(match.scheduled_at)}",
        target=match.stage.competition,
        changes={"time": [_when(old) if old else "", _when(match.scheduled_at)]},
    )
    _notify(
        request,
        [proposal.proposing_team],
        f"Match time agreed: {match.home.team_name} v {match.away.team_name}",
        "matches/emails/time_agreed.txt",
        match=match,
        proposal=proposal,
    )
    return match


@transaction.atomic
def decline_proposal(request, proposal, user, note=""):
    proposal = TimeProposal.objects.select_for_update().select_related("match__stage").get(pk=proposal.pk)
    _respondable(proposal, user)
    proposal.status = TimeProposal.Status.DECLINED
    proposal.responded_at, proposal.responded_by = timezone.now(), user
    proposal.response_note = note.strip()
    proposal.save()
    match = proposal.match
    record(
        user,
        "match.time_declined",
        f"Declined proposed time {_when(proposal.proposed_time)} for {match} of {match.stage}",
        target=match.stage.competition,
    )
    _notify(
        request,
        [proposal.proposing_team],
        f"Proposed time declined: {match.home.team_name} v {match.away.team_name}",
        "matches/emails/time_declined.txt",
        match=match,
        proposal=proposal,
    )
    return proposal


@transaction.atomic
def withdraw_proposal(proposal, user):
    if proposal.status != TimeProposal.Status.PENDING:
        _fail(_("This proposal has already been answered or replaced."))
    side = "home" if proposal.proposing_team_id == proposal.match.home_id else "away"
    if side not in coached_sides(user, proposal.match):
        _fail(_("Only the proposing team's coaches can withdraw this proposal."))
    proposal.status = TimeProposal.Status.WITHDRAWN
    proposal.save(update_fields=["status"])
    record(
        user,
        "match.time_withdrawn",
        f"Withdrew proposed time for {proposal.match} of {proposal.match.stage}",
        target=proposal.match.stage.competition,
    )
    return proposal
