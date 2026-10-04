"""
Teacher coach screens for matches.

Coaches see matches for their own teams in published stages, and arrange
match times directly with the other team's coaches.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from accounts.permissions import coach_required
from schools.models import CoachAccess
from schools.permissions import schools_for

from . import results, services
from .forms import ProposeTimeForm, ResultForm
from .models import Match, ResultSubmission, TimeProposal


def coach_matches(user):
    """Matches involving this coach's schools' teams, in published stages."""
    schools = schools_for(user)
    return (
        Match.objects.filter(stage__is_published=True)
        .filter(Q(home__school__in=schools) | Q(away__school__in=schools))
        .select_related("stage__competition", "home__school", "away__school", "home_source", "away_source")
        .order_by("scheduled_at", "play_by", "number")
    )


def awaiting_my_answer(user):
    """Time proposals from the other team that this coach can accept or decline."""
    schools = set(schools_for(user).values_list("pk", flat=True))
    pending = TimeProposal.objects.filter(
        status=TimeProposal.Status.PENDING, match__in=coach_matches(user)
    ).select_related("match__home", "match__away", "match__stage__competition", "proposing_team")
    result = []
    for proposal in pending:
        match = proposal.match
        other = match.away if proposal.proposing_team_id == match.home_id else match.home
        if other and other.school_id in schools:
            result.append(proposal)
    return result


@coach_required
def my_matches(request):
    matches = list(coach_matches(request.user))
    now = timezone.now()
    context = {
        "awaiting": awaiting_my_answer(request.user),
        "to_schedule": [m for m in matches if m.state == Match.State.TO_SCHEDULE],
        "upcoming": [m for m in matches if m.state == Match.State.SCHEDULED and m.scheduled_at >= now],
        "waiting": [m for m in matches if m.state == Match.State.WAITING],
        "other": [
            m
            for m in matches
            if m.state in (Match.State.BYE, Match.State.CANCELLED)
            or (m.state == Match.State.SCHEDULED and m.scheduled_at < now)
        ],  # fmt: skip
    }
    return render(request, "matches/my_matches.html", context)


def _get_match(request, pk):
    match = get_object_or_404(
        Match.objects.select_related("stage__competition__game", "home__school", "away__school"), pk=pk
    )
    if not services.visible_to_coach(request.user, match):
        raise PermissionDenied
    return match


@coach_required
def coach_match(request, pk):
    match = _get_match(request, pk)
    sides = services.coached_sides(request.user, match)
    # Coaches of the other team, so the two sides can talk directly if they need to.
    opponents = [getattr(match, side) for side in ("home", "away") if side not in sides and getattr(match, side)]
    opponent_coaches = (
        CoachAccess.objects.approved()
        .filter(school__in=[team.school for team in opponents])
        .select_related("coach", "school")
    )
    pending = match.proposals.filter(status=TimeProposal.Status.PENDING).select_related("proposing_team").first()
    submission = match.submissions.filter(status__in=results.OPEN_SUBMISSION).select_related("submitting_team").first()
    my_teams = [getattr(match, side).pk for side in sides]
    context = {
        "match": match,
        "sides": sides,
        "opponent_coaches": opponent_coaches,
        "pending": pending,
        "can_answer": bool(pending and (len(sides) == 2 or pending.proposing_team_id not in my_teams)),
        "can_withdraw": bool(pending and pending.proposing_team_id in my_teams),
        "proposals": match.proposals.select_related("proposing_team", "proposed_by", "responded_by")[:20],
        "form": ProposeTimeForm() if match.is_playable else None,
        "result_form": ResultForm(match=match) if match.is_playable else None,
        "submission": submission,
        "can_confirm": bool(
            submission
            and submission.status == ResultSubmission.Status.PENDING
            and (len(sides) == 2 or submission.submitting_team_id not in my_teams)
        ),
        "submissions": match.submissions.select_related("submitting_team", "submitted_by", "responded_by")[:10],
    }
    return render(request, "matches/coach_match.html", context)


def _errors(request, error):
    for text in error.messages:
        messages.error(request, text)


@coach_required
@require_POST
def propose(request, pk):
    match = _get_match(request, pk)
    form = ProposeTimeForm(request.POST)
    if form.is_valid():
        try:
            services.propose_time(
                request, match, request.user, form.cleaned_data["proposed_time"], form.cleaned_data["note"]
            )
            messages.success(request, _("Proposed. The other team's coaches have been emailed."))
        except ValidationError as error:
            _errors(request, error)
    else:
        messages.error(request, _("Enter a date and time."))
    return redirect("matches:coach_match", pk=pk)


def _proposal(request, pk, proposal_pk):
    match = _get_match(request, pk)
    return get_object_or_404(TimeProposal, pk=proposal_pk, match=match)


@coach_required
@require_POST
def accept(request, pk, proposal_pk):
    try:
        services.accept_proposal(request, _proposal(request, pk, proposal_pk), request.user)
        messages.success(request, _("Match time agreed. Both teams can see it now."))
    except ValidationError as error:
        _errors(request, error)
    return redirect("matches:coach_match", pk=pk)


@coach_required
@require_POST
def decline(request, pk, proposal_pk):
    try:
        services.decline_proposal(
            request, _proposal(request, pk, proposal_pk), request.user, request.POST.get("note", "")
        )
        messages.success(request, _("Declined. Propose a time that works for you."))
    except ValidationError as error:
        _errors(request, error)
    return redirect("matches:coach_match", pk=pk)


@coach_required
@require_POST
def withdraw(request, pk, proposal_pk):
    try:
        services.withdraw_proposal(_proposal(request, pk, proposal_pk), request.user)
        messages.success(request, _("Proposal withdrawn."))
    except ValidationError as error:
        _errors(request, error)
    return redirect("matches:coach_match", pk=pk)


@coach_required
@require_POST
def submit_result(request, pk):
    match = _get_match(request, pk)
    form = ResultForm(request.POST, match=match)
    if form.is_valid():
        try:
            results.submit_result(
                request, match, request.user, form.cleaned_data["home_games"], form.cleaned_data["away_games"],
                results.parse_game_scores(form.cleaned_data["game_scores"]), form.cleaned_data["note"],
            )  # fmt: skip
            messages.success(request, _("Result sent. The other team's coaches will be asked to confirm it."))
        except ValidationError as error:
            _errors(request, error)
    else:
        messages.error(request, _("Enter the number of games each team won."))
    return redirect("matches:coach_match", pk=pk)


def _submission(request, pk, submission_pk):
    match = _get_match(request, pk)
    return get_object_or_404(ResultSubmission, pk=submission_pk, match=match)


@coach_required
@require_POST
def confirm_result(request, pk, submission_pk):
    try:
        results.confirm_result(request, _submission(request, pk, submission_pk), request.user)
        messages.success(request, _("Confirmed. The result is final."))
    except ValidationError as error:
        _errors(request, error)
    return redirect("matches:coach_match", pk=pk)


@coach_required
@require_POST
def dispute_result(request, pk, submission_pk):
    try:
        results.dispute_result(
            request, _submission(request, pk, submission_pk), request.user, request.POST.get("reason", "")
        )
        messages.success(request, _("Disputed. OSEA will review the result."))
    except ValidationError as error:
        _errors(request, error)
    return redirect("matches:coach_match", pk=pk)


def results_waiting_for_me(user):
    """Results the other team reported that this coach should confirm or dispute."""
    schools = set(schools_for(user).values_list("pk", flat=True))
    pending = ResultSubmission.objects.filter(
        status=ResultSubmission.Status.PENDING, match__in=coach_matches(user)
    ).select_related("match__home", "match__away", "match__stage__competition", "submitting_team")
    waiting = []
    for submission in pending:
        match = submission.match
        other = match.away if submission.submitting_team_id == match.home_id else match.home
        if other and other.school_id in schools:
            waiting.append(submission)
    return waiting


def results_to_report(user):
    """This coach's matches whose agreed time has passed with no result reported yet."""
    now = timezone.now()
    return [
        m for m in coach_matches(user).filter(status=Match.Status.OPEN, scheduled_at__lt=now)
        if not m.submissions.filter(status__in=results.OPEN_SUBMISSION).exists()
    ]  # fmt: skip
