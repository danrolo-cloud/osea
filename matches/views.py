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

from . import services
from .forms import ProposeTimeForm
from .models import Match, TimeProposal


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
