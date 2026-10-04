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

from . import results, services, standings
from .display import grouped_rounds
from .forms import GenerateForm, MatchForm, ReasonForm, ResultForm, StageForm
from .models import Match, ResultSubmission, Stage

STAGE_FIELDS = [
    "name", "format", "division", "order", "best_of", "swiss_rounds", "is_published",
    "points_win", "points_loss", "tiebreakers", "bye_counts_as_win", "grand_final_reset",
]  # fmt: skip
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
    table = standings.calculate(stage, matches) if stage.has_standings and matches else []
    entries = {e.registration_id: e for e in stage.entries.all()}
    context = {
        "stage": stage,
        "competition": stage.competition,
        "rounds": grouped_rounds(matches),
        "match_count": len(matches),
        "teams": teams,
        "generate_form": GenerateForm(),
        "overdue": overdue(matches),
        "table": table,
        "entries": entries,
        "any_tied": any(row.tied or (row.team.pk in entries and entries[row.team.pk].tiebreak_rank) for row in table),
        "can_pair_swiss": _swiss_round_complete(stage, matches),
    }
    return render(request, "matches/manage/stage_detail.html", context)


def _swiss_round_complete(stage, matches):
    """True when the latest Swiss round is finished and more rounds remain."""
    if stage.format != Stage.Format.SWISS or not matches:
        return False
    current = max(m.round_number for m in matches)
    finished = all(m.is_settled or m.status == Match.Status.CANCELLED for m in matches if m.round_number == current)
    return finished and current < (stage.swiss_rounds or 0)


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
    context = {"form": form, "stage": stage, "match": match}
    if match is not None:
        context["result_form"] = ResultForm(
            match=match,
            initial={"home_games": match.home_games, "away_games": match.away_games,
                     "game_scores": ", ".join(f"{h}-{a}" for h, a in match.game_scores or [])},
        )  # fmt: skip
        context["submissions"] = match.submissions.select_related("submitting_team", "submitted_by")[:10]
        context["open_submission"] = match.submissions.filter(status__in=results.OPEN_SUBMISSION).first()
    return render(request, "matches/manage/match_form.html", context)


# ---------- Results ----------


@admin_required
def results_queue(request):
    context = {
        "needs_admin": results.needs_admin(),
        "recent": Match.objects.filter(status__in=[Match.Status.COMPLETED, Match.Status.FORFEIT])
        .select_related("stage__competition", "home", "away", "finalized_by")
        .order_by("-finalized_at")[:20],
    }
    return render(request, "matches/manage/results_queue.html", context)


@admin_required
@require_POST
def admin_result(request, pk):
    match = get_object_or_404(Match.objects.select_related("stage"), pk=pk)
    action = request.POST.get("action")
    try:
        if action == "accept":
            submission = get_object_or_404(ResultSubmission, pk=request.POST.get("submission"), match=match)
            results.admin_accept_submission(request, submission, request.user)
            messages.success(request, _("Result is final."))
        elif action == "set":
            form = ResultForm(request.POST, match=match)
            if not form.is_valid():
                raise ValidationError(_("Enter the number of games each team won."))
            results.admin_set_result(
                request, match, request.user, form.cleaned_data["home_games"], form.cleaned_data["away_games"],
                results.parse_game_scores(form.cleaned_data["game_scores"]), form.cleaned_data["note"],
            )  # fmt: skip
            messages.success(request, _("Result saved and final."))
        elif action == "forfeit":
            side = request.POST.get("forfeiting")
            team = match.home if side == "home" else match.away if side == "away" else None
            results.admin_forfeit(request, match, request.user, team, request.POST.get("reason", ""))
            messages.success(request, _("Forfeit recorded."))
        elif action == "reopen":
            results.reopen_result(request, match, request.user, request.POST.get("reason", ""))
            messages.success(request, _("Result reopened."))
    except ValidationError as error:
        for text in error.messages:
            messages.error(request, text)
    if request.POST.get("return_to") == "queue":
        return redirect("matches:results_queue")
    return redirect("matches:match_edit", stage_pk=match.stage_id, pk=match.pk)


@admin_required
@require_POST
def swiss_next_round(request, pk):
    stage = get_object_or_404(Stage, pk=pk)
    try:
        number = results.pair_next_swiss_round(stage, request.user)
        messages.success(request, _("Round %(n)s paired. Check it, then let coaches know.") % {"n": number})
    except ValidationError as error:
        for text in error.messages:
            messages.error(request, text)
    return redirect("matches:stage", pk=pk)


@admin_required
@require_POST
def tiebreak(request, pk):
    """Record OSEA's decision for teams that no tiebreaker separates."""
    stage = get_object_or_404(Stage, pk=pk)
    changed = []
    for entry in stage.entries.select_related("registration"):
        raw = request.POST.get(f"rank-{entry.pk}")
        if raw is None:
            continue
        value = int(raw) if raw.strip().isdigit() else None
        if value != entry.tiebreak_rank:
            changed.append(f"{entry.registration.team_name}: {value or 'none'}")
            entry.tiebreak_rank = value
            entry.save(update_fields=["tiebreak_rank"])
    if changed:
        record(
            request.user,
            "stage.tiebreak_decided",
            f"Recorded tiebreak decision in {stage}",
            target=stage.competition,
            changes={"decision": ["", "; ".join(changed)]},
        )
    messages.success(request, _("Decision saved."))
    return redirect("matches:stage", pk=pk)


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
