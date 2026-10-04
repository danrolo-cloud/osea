"""OSEA administrator screens for stages, matches and announcements."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from accounts.permissions import admin_required
from audit.log import changes_between, record, snapshot
from competitions.models import Competition

from . import services
from .display import grouped_rounds
from .forms import GenerateForm, MatchForm, ReasonForm, StageForm
from .models import Match, Stage

STAGE_FIELDS = ["name", "format", "division", "order", "best_of", "swiss_rounds", "is_published"]
MATCH_FIELDS = ["home", "away", "round_number", "round_label", "play_from", "play_by"]


def _matches(stage):
    return stage.matches.select_related(
        "home__school", "away__school", "home_source", "away_source", "winner"
    ).order_by("number")


# ---------- Stages ----------


@admin_required
def stage_form(request, competition_pk, pk=None):
    competition = get_object_or_404(Competition, pk=competition_pk)
    stage = get_object_or_404(Stage, pk=pk, competition=competition) if pk else None
    before = snapshot(stage, STAGE_FIELDS) if stage else {}
    form = StageForm(request.POST or None, instance=stage, competition=competition)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        changes = changes_between(before, snapshot(saved, STAGE_FIELDS))
        if changes:
            record(
                request.user,
                "stage.updated" if stage else "stage.created",
                f"{'Updated' if stage else 'Added'} stage {saved.name} in {competition}",
                target=competition,
                changes=changes,
            )
        messages.success(request, _("Stage saved."))
        return redirect("matches:stage", pk=saved.pk)
    return render(request, "matches/manage/stage_form.html", {"form": form, "competition": competition, "stage": stage})


@admin_required
def stage_detail(request, pk):
    stage = get_object_or_404(Stage.objects.select_related("competition", "division"), pk=pk)
    matches = list(_matches(stage))
    seeded = {entry.registration_id: entry.seed for entry in stage.entries.all()}
    teams = list(stage.eligible_teams())
    teams.sort(key=lambda t: (seeded.get(t.pk, 999), t.team_name))
    context = {
        "stage": stage,
        "competition": stage.competition,
        "rounds": grouped_rounds(matches),
        "match_count": len(matches),
        "teams": teams,
        "generate_form": GenerateForm(),
        "overdue": overdue(matches),
    }
    return render(request, "matches/manage/stage_detail.html", context)


def overdue(matches):
    """Playable matches still without an agreed time after their play-by date."""
    now = timezone.now()
    return [
        m for m in matches
        if m.state == Match.State.TO_SCHEDULE and m.play_by and m.play_by < now
    ]  # fmt: skip


@admin_required
@require_POST
def stage_generate(request, pk):
    stage = get_object_or_404(Stage, pk=pk)
    form = GenerateForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            for text in errors:
                messages.error(request, text)
        return redirect("matches:stage", pk=pk)
    # Teams ticked "include", in the seed order the admin entered (ties broken by name).
    chosen = []
    for team in stage.eligible_teams():
        if request.POST.get(f"include-{team.pk}"):
            try:
                seed = int(request.POST.get(f"seed-{team.pk}") or 999)
            except ValueError:
                seed = 999
            chosen.append((seed, team.team_name.lower(), team))
    seeded_teams = [team for _seed, _name, team in sorted(chosen)]
    try:
        created = services.generate_stage(
            stage, request.user, seeded_teams,
            first_day=form.cleaned_data["first_day"], days_per_round=form.cleaned_data["days_per_round"],
        )  # fmt: skip
        messages.success(request, _("%(n)s matches created. Check them, then publish the stage.") % {"n": len(created)})
    except ValidationError as error:
        for text in error.messages:
            messages.error(request, text)
    return redirect("matches:stage", pk=pk)


@admin_required
@require_POST
def stage_clear(request, pk):
    stage = get_object_or_404(Stage, pk=pk)
    count = services.clear_stage(stage, request.user)
    messages.success(request, _("Removed %(n)s matches.") % {"n": count})
    return redirect("matches:stage", pk=pk)


@admin_required
@require_POST
def stage_delete(request, pk):
    stage = get_object_or_404(Stage, pk=pk)
    competition = stage.competition
    if stage.matches.exists():
        messages.error(request, _("Clear the stage's matches before deleting it."))
        return redirect("matches:stage", pk=pk)
    stage.delete()
    record(request.user, "stage.deleted", f"Deleted stage {stage.name} from {competition}", target=competition)
    messages.success(request, _("Stage deleted."))
    return redirect("competitions:manage_competition", pk=competition.pk)


# ---------- Matches ----------


@admin_required
def match_form(request, stage_pk, pk=None):
    stage = get_object_or_404(Stage.objects.select_related("competition"), pk=stage_pk)
    match = get_object_or_404(Match, pk=pk, stage=stage) if pk else None
    form = MatchForm(request.POST or None, instance=match, stage=stage)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            with transaction.atomic():
                if match is None:
                    match = services.add_match(
                        stage, request.user, home=data["home"], away=data["away"],
                        round_number=data["round_number"], round_label=data["round_label"],
                        play_from=data["play_from"], play_by=data["play_by"],
                    )  # fmt: skip
                else:
                    before = snapshot(Match.objects.get(pk=match.pk), MATCH_FIELDS)
                    original = Match.objects.get(pk=match.pk)
                    edited = form.save(commit=False)
                    # A team chosen by hand replaces the automatic "winner of" link for that slot.
                    for side in ("home", "away"):
                        if getattr(edited, f"{side}_id") != getattr(original, f"{side}_id"):
                            setattr(edited, f"{side}_source", None)
                            setattr(edited, f"{side}_source_outcome", "")
                    edited.scheduled_at = original.scheduled_at  # times go through set_time()
                    if edited.status == Match.Status.BYE and edited.home_id and edited.away_id:
                        edited.status, edited.winner = Match.Status.OPEN, None
                    edited.save()
                    services.resolve_stage(stage)
                    changes = changes_between(before, snapshot(edited, MATCH_FIELDS))
                    if changes:
                        record(
                            request.user,
                            "match.updated",
                            f"Edited {edited} of {stage}",
                            target=stage.competition,
                            changes=changes,
                        )
                    match = edited
                if data["scheduled_at"] != match.scheduled_at:
                    services.set_time(request, match, request.user, data["scheduled_at"])
        except ValidationError as error:
            for text in error.messages:
                form.add_error(None, text)
        else:
            messages.success(request, _("Match saved."))
            return redirect("matches:stage", pk=stage.pk)
    return render(request, "matches/manage/match_form.html", {"form": form, "stage": stage, "match": match})


@admin_required
@require_POST
def match_cancel(request, pk):
    match = get_object_or_404(Match, pk=pk)
    form = ReasonForm(request.POST)
    try:
        services.cancel_match(request, match, request.user, form.data.get("reason", ""))
        messages.success(request, _("Match cancelled. The teams' coaches have been emailed."))
    except ValidationError as error:
        for text in error.messages:
            messages.error(request, text)
    return redirect("matches:stage", pk=match.stage_id)


@admin_required
@require_POST
def match_restore(request, pk):
    match = get_object_or_404(Match, pk=pk)
    try:
        services.restore_match(match, request.user)
        messages.success(request, _("Match restored."))
    except ValidationError as error:
        for text in error.messages:
            messages.error(request, text)
    return redirect("matches:stage", pk=match.stage_id)
