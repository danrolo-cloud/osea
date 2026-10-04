import datetime

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from accounts.permissions import admin_required, coach_required
from audit.models import AuditEvent
from competitions.models import Competition, Registration, RosterChange
from competitions.views import announcements_for
from matches.manage_views import overdue
from matches.models import Match
from matches.results import needs_admin
from matches.views import awaiting_my_answer, coach_matches, results_to_report, results_waiting_for_me
from schools.manage_views import schools_needing_membership_attention
from schools.models import CoachAccess, Membership, SchoolYear


@require_GET
def home(request):
    competitions = (
        Competition.objects.filter(is_published=True, registration_closes_at__gt=timezone.now())
        .select_related("game")
        .order_by("registration_opens_at")[:4]
    )
    return render(request, "core/home.html", {"competitions": competitions})


@login_required
def dashboard(request):
    """Send each person to the dashboard for their role."""
    if request.user.is_osea_admin:
        return redirect("core:admin_dashboard")
    if request.user.is_coach:
        return redirect("core:coach_dashboard")
    raise PermissionDenied


@admin_required
def admin_dashboard(request):
    year = SchoolYear.current()
    pending = CoachAccess.objects.pending().select_related("coach", "school__board").order_by("requested_at")
    membership_attention = schools_needing_membership_attention(year)
    context = {
        "year": year,
        "pending_requests": pending[:5],
        "pending_count": pending.count(),
        "membership_attention": membership_attention[:5],
        "membership_attention_count": membership_attention.count(),
        "recent_activity": AuditEvent.objects.select_related("actor")[:6],
        "to_review": Registration.objects.filter(status=Registration.Status.SUBMITTED)
        .select_related("competition", "school")
        .order_by("submitted_at")[:6],
        "to_review_count": Registration.objects.filter(status=Registration.Status.SUBMITTED).count(),
        "pending_roster_changes": RosterChange.objects.filter(status=RosterChange.Status.PENDING).select_related(
            "registration__competition", "registration__school"
        )[:6],
        "deadlines": upcoming_deadlines(),
        "results_attention": needs_admin()[:8],
        "overdue_matches": overdue(
            Match.objects.filter(stage__is_published=True, status=Match.Status.OPEN, scheduled_at__isnull=True)
            .exclude(home__isnull=True)
            .exclude(away__isnull=True)
            .select_related("stage__competition", "home", "away")
        )[:8],
    }
    return render(request, "core/admin_dashboard.html", context)


def upcoming_deadlines(days=21):
    """Registration openings, closings and roster deadlines in the next few weeks, soonest first."""
    now = timezone.now()
    soon = now + datetime.timedelta(days=days)
    items = []
    competitions = Competition.objects.filter(is_published=True).filter(
        Q(registration_opens_at__range=(now, soon))
        | Q(registration_closes_at__range=(now, soon))
        | Q(roster_deadline__range=(now, soon))
    )
    for c in competitions:
        for when, label in [
            (c.registration_opens_at, "Registration opens"),
            (c.registration_closes_at, "Registration closes"),
            (c.roster_deadline, "Roster deadline"),
        ]:
            if now <= when <= soon:
                items.append({"when": when, "label": label, "competition": c})
    return sorted(items, key=lambda item: item["when"])


@coach_required
def coach_dashboard(request):
    year = SchoolYear.current()
    access_list = list(request.user.school_access.select_related("school").order_by("status", "requested_at"))
    approved = [a for a in access_list if a.status == CoachAccess.Status.APPROVED and a.school.is_active]
    memberships = {}
    if year and approved:
        memberships = {
            m.school_id: m for m in Membership.objects.filter(school_year=year, school__in=[a.school for a in approved])
        }
    for access in approved:
        access.membership = memberships.get(access.school_id)
    my_schools = [a.school for a in approved]
    registrations = (
        Registration.objects.filter(school__in=my_schools)
        .exclude(status=Registration.Status.WITHDRAWN)
        .select_related("competition", "school", "division")
        .order_by("competition__registration_closes_at")
    )
    open_now = [
        c
        for c in Competition.objects.filter(
            is_published=True,
            registration_opens_at__lte=timezone.now(),
            registration_closes_at__gt=timezone.now(),
        ).select_related("game")
        if any(c.school_is_eligible(s) for s in my_schools)
    ]
    matches = list(coach_matches(request.user))
    now = timezone.now()
    context = {
        "awaiting": awaiting_my_answer(request.user),
        "results_to_confirm": results_waiting_for_me(request.user),
        "results_to_report": results_to_report(request.user),
        "to_schedule": [m for m in matches if m.state == Match.State.TO_SCHEDULE],
        "next_matches": [m for m in matches if m.state == Match.State.SCHEDULED and m.scheduled_at >= now][:4],
        "announcements": announcements_for(request.user)[:5],
        "year": year,
        "registrations_to_finish": [
            r for r in registrations if r.status in (Registration.Status.DRAFT, Registration.Status.CHANGES_REQUESTED)
        ],
        "registrations": registrations,
        "open_competitions": open_now,
        "approved": approved,
        "pending": [a for a in access_list if a.status == CoachAccess.Status.PENDING],
        "closed": [a for a in access_list if a.status in (CoachAccess.Status.DECLINED, CoachAccess.Status.REVOKED)],
        "needs_verification": not request.user.email_verified_at,
    }
    return render(request, "core/coach_dashboard.html", context)


@admin_required
def style_guide(request):
    return render(request, "core/style_guide.html")


@never_cache
@require_GET
def healthz(request):
    """Used by the hosting provider to check the site and database are up."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return HttpResponse("ok", content_type="text/plain")
