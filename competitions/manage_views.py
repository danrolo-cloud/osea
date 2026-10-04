"""OSEA administrator screens for games, competitions, divisions and registrations."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from accounts.permissions import admin_required
from audit.log import changes_between, history_for, record, snapshot
from core.csv_export import csv_response

from . import services
from .forms import AddPlayerForm, CompetitionForm, DivisionForm, GameForm, RegistrationDecisionForm, TeamNameForm
from .models import Competition, Division, Game, Registration, RosterChange, RosterEntry

GAME_FIELDS = ["name", "gamer_tag_label", "rank_label", "is_active"]
DIVISION_FIELDS = ["name", "description", "order"]


def _error_messages(request, error):
    for text in error.messages:
        messages.error(request, text)


# ---------- Games ----------


@admin_required
def game_list(request):
    games = Game.objects.annotate(competition_count=Count("competitions"))
    return render(request, "competitions/manage/game_list.html", {"games": games})


@admin_required
def game_form(request, pk=None):
    game = get_object_or_404(Game, pk=pk) if pk else None
    before = snapshot(game, GAME_FIELDS) if game else {}
    form = GameForm(request.POST or None, instance=game)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        changes = changes_between(before, snapshot(saved, GAME_FIELDS))
        if changes:
            record(
                request.user,
                "game.updated" if game else "game.created",
                f"{'Updated' if game else 'Added'} game {saved}",
                target=saved,
                changes=changes,
            )
        messages.success(request, _("Game saved."))
        return redirect("competitions:game_list")
    return render(request, "competitions/manage/game_form.html", {"form": form, "game": game})


# ---------- Competitions ----------


@admin_required
def competition_list(request):
    competitions = Competition.objects.select_related("game", "school_year").annotate(
        submitted=Count("registrations", filter=Q(registrations__status=Registration.Status.SUBMITTED)),
        approved=Count("registrations", filter=Q(registrations__status=Registration.Status.APPROVED)),
    )
    return render(request, "competitions/manage/competition_list.html", {"competitions": competitions})


@admin_required
def competition_form(request, pk=None):
    competition = get_object_or_404(Competition, pk=pk) if pk else None
    form = CompetitionForm(request.POST or None, instance=competition)
    fields = CompetitionForm.Meta.fields
    before = snapshot(competition, fields) if competition else {}
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        changes = changes_between(before, snapshot(saved, fields))
        if changes:
            record(
                request.user,
                "competition.updated" if competition else "competition.created",
                f"{'Updated' if competition else 'Created'} competition {saved}",
                target=saved,
                changes=changes,
            )
        messages.success(request, _("Competition saved."))
        return redirect("competitions:manage_competition", pk=saved.pk)
    if not Game.objects.exists():
        messages.info(request, _("Add a game first; every competition belongs to one."))
    return render(request, "competitions/manage/competition_form.html", {"form": form, "competition": competition})


@admin_required
def competition_detail(request, pk):
    competition = get_object_or_404(Competition.objects.select_related("game", "school_year"), pk=pk)
    status = request.GET.get("status", "")
    registrations = competition.registrations.select_related("school", "division").annotate(roster_size=Count("roster"))
    if status in Registration.Status.values:
        registrations = registrations.filter(status=status)
    else:
        status = ""
        registrations = registrations.exclude(status=Registration.Status.WITHDRAWN)
    counts = dict(competition.registrations.values_list("status").annotate(n=Count("id")).values_list("status", "n"))
    context = {
        "competition": competition,
        "registrations": registrations.order_by("division__order", "team_name"),
        "status": status,
        "status_choices": Registration.Status.choices,
        "counts": counts,
        "divisions": competition.divisions.annotate(team_count=Count("registrations")),
        "division_form": DivisionForm(),
        "pending_changes": RosterChange.objects.filter(
            registration__competition=competition, status=RosterChange.Status.PENDING
        ).select_related("registration__school", "player_in", "player_out"),
        "history": history_for(competition)[:20],
    }
    return render(request, "competitions/manage/competition_detail.html", context)


@admin_required
@require_POST
def assign_divisions(request, pk):
    """Save the division chosen for each team in the competition's registration table."""
    competition = get_object_or_404(Competition, pk=pk)
    divisions = {str(d.pk): d for d in competition.divisions.all()}
    changed = 0
    for registration in competition.registrations.exclude(status=Registration.Status.WITHDRAWN):
        key = f"division-{registration.pk}"
        if key not in request.POST:
            continue
        division = divisions.get(request.POST[key])
        if division != registration.division:
            services.assign_division(registration, request.user, division)
            changed += 1
    messages.success(request, _("Divisions saved (%(n)s changed).") % {"n": changed})
    return redirect("competitions:manage_competition", pk=pk)


# ---------- Divisions ----------


@admin_required
def division_form(request, competition_pk, pk=None):
    competition = get_object_or_404(Competition, pk=competition_pk)
    division = get_object_or_404(Division, pk=pk, competition=competition) if pk else None
    before = snapshot(division, DIVISION_FIELDS) if division else {}
    form = DivisionForm(request.POST or None, instance=division)
    if request.method == "POST" and form.is_valid():
        if (
            competition.divisions.filter(name__iexact=form.cleaned_data["name"])
            .exclude(pk=getattr(division, "pk", None))
            .exists()
        ):
            form.add_error("name", _("This competition already has a division with that name."))
        else:
            saved = form.save(commit=False)
            saved.competition = competition
            saved.save()
            record(
                request.user,
                "division.updated" if division else "division.created",
                f"{'Updated' if division else 'Added'} division {saved} in {competition}",
                target=competition,
                changes=changes_between(before, snapshot(saved, DIVISION_FIELDS)),
            )
            messages.success(request, _("Division saved."))
            return redirect("competitions:manage_competition", pk=competition.pk)
    return render(
        request,
        "competitions/manage/division_form.html",
        {"form": form, "competition": competition, "division": division},
    )


@admin_required
@require_POST
def division_delete(request, competition_pk, pk):
    division = get_object_or_404(Division, pk=pk, competition_id=competition_pk)
    try:
        division.delete()
    except ProtectedError:
        messages.error(request, _("Move this division's teams to another division before deleting it."))
    else:
        record(
            request.user,
            "division.deleted",
            f"Deleted division {division} from {division.competition}",
            target=division.competition,
        )
        messages.success(request, _("Division deleted."))
    return redirect("competitions:manage_competition", pk=competition_pk)


# ---------- Registration review ----------


@admin_required
def registration_review(request, pk):
    registration = get_object_or_404(
        Registration.objects.select_related(
            "competition__game",
            "competition__school_year",
            "school__board",
            "division",
            "created_by",
            "submitted_by",
            "consent_confirmed_by",
        ),
        pk=pk,
    )
    decision_form = RegistrationDecisionForm(request.POST or None, registration=registration)
    if request.method == "POST":
        action = request.POST.get("action")
        if decision_form.is_valid():
            division = decision_form.cleaned_data["division"]
            message = decision_form.cleaned_data["message"]
            try:
                if action == "approve":
                    services.approve(request, registration, request.user, division=division, message=message)
                    messages.success(request, _("Approved. The school's coaches have been emailed."))
                elif action == "waitlist":
                    services.waitlist(request, registration, request.user, message=message)
                    messages.success(request, _("Waitlisted. The school's coaches have been emailed."))
                elif action == "request_changes":
                    services.request_changes(request, registration, request.user, message=message)
                    messages.success(request, _("Changes requested. The school's coaches have been emailed."))
                elif action == "division":
                    services.assign_division(registration, request.user, division)
                    messages.success(request, _("Division saved."))
                elif action == "withdraw":
                    services.withdraw(request, registration, request.user, reason=message, by_admin=True)
                    messages.success(request, _("Team withdrawn. The school's coaches have been emailed."))
                return redirect("competitions:manage_registration", pk=pk)
            except ValidationError as error:
                for text in error.messages:
                    decision_form.add_error(None, text)

    roster = registration.roster.select_related("student").order_by("student__first_name")
    context = {
        "registration": registration,
        "competition": registration.competition,
        "roster": roster,
        "decision_form": decision_form,
        "add_form": AddPlayerForm(registration=registration, prefix="add"),
        "rename_form": TeamNameForm(initial={"team_name": registration.team_name}),
        "problems": services.approval_problems(registration)
        if registration.status in (Registration.Status.SUBMITTED, Registration.Status.WAITLISTED)
        else services.roster_problems(registration),
        "membership": services.membership_for(registration),
        "roster_changes": registration.roster_changes.select_related("player_in", "player_out", "requested_by"),
        "history": history_for(registration),
    }
    return render(request, "competitions/manage/registration_review.html", context)


@admin_required
@require_POST
def admin_add_player(request, pk):
    registration = get_object_or_404(Registration, pk=pk)
    form = AddPlayerForm(request.POST, registration=registration, prefix="add")
    if form.is_valid():
        try:
            with transaction.atomic():  # a new student is only kept if they're added successfully
                student = form.get_or_create_student(request.user)
                services.add_player(
                    registration,
                    request.user,
                    student,
                    form.cleaned_data.get("gamer_tag", ""),
                    form.cleaned_data.get("rank", ""),
                    by_admin=True,
                )
            messages.success(request, _("Player added."))
        except ValidationError as error:
            _error_messages(request, error)
    else:
        for errors in form.errors.values():
            for text in errors:
                messages.error(request, text)
    return redirect("competitions:manage_registration", pk=pk)


@admin_required
@require_POST
def admin_remove_player(request, pk, entry_pk):
    entry = get_object_or_404(RosterEntry, pk=entry_pk, registration_id=pk)
    services.remove_player(entry, request.user, by_admin=True)
    messages.success(request, _("Player removed."))
    return redirect("competitions:manage_registration", pk=pk)


@admin_required
@require_POST
def admin_rename(request, pk):
    registration = get_object_or_404(Registration, pk=pk)
    try:
        services.rename_team(registration, request.user, request.POST.get("team_name", ""), by_admin=True)
        messages.success(request, _("Team name saved."))
    except ValidationError as error:
        _error_messages(request, error)
    return redirect("competitions:manage_registration", pk=pk)


@admin_required
@require_POST
def roster_change_decide(request, pk):
    change = get_object_or_404(RosterChange.objects.select_related("registration"), pk=pk)
    note = request.POST.get("note", "")
    try:
        if request.POST.get("action") == "approve":
            services.approve_roster_change(request, change, request.user, note=note)
            messages.success(request, _("Roster change approved and applied."))
        else:
            services.decline_roster_change(request, change, request.user, note=note)
            messages.success(request, _("Roster change declined."))
    except ValidationError as error:
        _error_messages(request, error)
    if request.POST.get("return_to") == "competition":
        return redirect("competitions:manage_competition", pk=change.registration.competition_id)
    return redirect("competitions:manage_registration", pk=change.registration_id)


# ---------- Exports ----------


@admin_required
def export_registrations(request, pk):
    competition = get_object_or_404(Competition, pk=pk)
    registrations = competition.registrations.select_related("school", "division").annotate(roster_size=Count("roster"))
    header = ["Team", "School", "City", "Status", "Division", "Roster size", "Submitted", "Decided"]
    rows = (
        [
            r.team_name,
            r.school.name,
            r.school.city,
            r.get_status_display(),
            r.division or "",
            r.roster_size,
            f"{r.submitted_at:%Y-%m-%d}" if r.submitted_at else "",
            f"{r.decided_at:%Y-%m-%d}" if r.decided_at else "",
        ]
        for r in registrations.order_by("team_name")
    )
    record(request.user, "export.downloaded", f"Downloaded the team list for {competition}", target=competition)
    return csv_response(f"teams-{competition.pk}", header, rows)


@admin_required
def export_rosters(request, pk):
    competition = get_object_or_404(Competition.objects.select_related("game"), pk=pk)
    entries = (
        RosterEntry.objects.filter(registration__competition=competition)
        .exclude(registration__status=Registration.Status.WITHDRAWN)
        .select_related("registration__school", "registration__division", "student")
    )
    header = [
        "Team",
        "School",
        "Status",
        "Division",
        "Student",
        "Grade",
        competition.game.gamer_tag_label,
        competition.game.rank_label,
    ]
    rows = (
        [
            e.registration.team_name,
            e.registration.school.name,
            e.registration.get_status_display(),
            e.registration.division or "",
            str(e.student),
            e.student.grade,
            e.gamer_tag,
            e.rank,
        ]
        for e in entries.order_by("registration__team_name", "student__first_name")
    )
    record(
        request.user,
        "export.downloaded",
        f"Downloaded rosters (student information) for {competition}",
        target=competition,
    )
    return csv_response(f"rosters-{competition.pk}", header, rows)
