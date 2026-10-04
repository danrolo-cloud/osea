"""
OSEA administrator screens for schools, coaches and memberships.

Every view is wrapped in @admin_required, which is checked on the server.
Every change is written to the activity log.
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import CharField, Count, OuterRef, Q, Subquery, Value
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.permissions import admin_required
from audit.log import changes_between, record, snapshot
from audit.models import AuditEvent
from core.csv_export import csv_response
from core.full_export import build_zip

from . import services
from .forms import AccessDecisionForm, MembershipForm, SchoolBoardForm, SchoolForm, SchoolYearForm
from .models import CoachAccess, Membership, School, SchoolBoard, SchoolYear

SCHOOL_FIELDS = ["name", "city", "board", "level", "is_active", "admin_notes"]
MEMBERSHIP_FIELDS = ["status", "amount", "paid_on", "reference", "notes"]
BOARD_FIELDS = ["name", "email_domains", "is_active"]
YEAR_FIELDS = ["name", "start_date", "end_date", "is_current"]


def _with_current_membership(queryset, year):
    if year is None:
        status = Value(None, output_field=CharField())
    else:
        status = Subquery(Membership.objects.filter(school=OuterRef("pk"), school_year=year).values("status")[:1])
    return queryset.annotate(
        membership_status=status,
        approved_coaches=Count(
            "coach_access", filter=Q(coach_access__status=CoachAccess.Status.APPROVED), distinct=True
        ),
    )


def schools_needing_membership_attention(year):
    """Active schools that have (or want) coaches but no confirmed membership this year."""
    if year is None:
        return School.objects.none()
    involved = Q(coach_access__status__in=[CoachAccess.Status.APPROVED, CoachAccess.Status.PENDING])
    settled = Membership.objects.filter(
        school_year=year, status__in=[Membership.Status.CONFIRMED, Membership.Status.EXEMPT]
    ).values("school")
    return (
        _with_current_membership(School.objects.filter(is_active=True).filter(involved), year)
        .exclude(pk__in=settled)
        .distinct()
        .order_by("name")
    )


# ---------- Coach access requests ----------


@admin_required
def access_requests(request):
    show = request.GET.get("show", "pending")
    queryset = CoachAccess.objects.select_related("coach", "school__board", "decided_by")
    if show == "decided":
        queryset = queryset.exclude(status=CoachAccess.Status.PENDING).order_by("-decided_at")[:100]
    else:
        show = "pending"
        queryset = queryset.pending().order_by("requested_at")
    return render(request, "schools/manage/access_requests.html", {"requests": queryset, "show": show})


@admin_required
def access_request_detail(request, pk):
    access = get_object_or_404(CoachAccess.objects.select_related("coach", "school__board"), pk=pk)
    form = AccessDecisionForm(request.POST or None, initial={"school": access.school})
    if request.method == "POST" and form.is_valid():
        action = request.POST.get("action")
        note = form.cleaned_data["decision_note"]
        try:
            if action == "approve":
                services.approve(request, access, request.user, school=form.cleaned_data["school"], note=note)
                messages.success(request, _("Approved. The coach has been emailed."))
            elif action == "decline":
                services.decline(request, access, request.user, note=note)
                messages.success(request, _("Declined. The coach has been emailed."))
            else:
                messages.error(request, _("Choose approve or decline."))
                return redirect("schools:access_request", pk=pk)
        except ValidationError as error:
            for text in error.messages:
                form.add_error(None, text)
        else:
            return redirect("schools:access_requests")

    others = CoachAccess.objects.approved().filter(school=access.school).exclude(pk=access.pk).select_related("coach")
    return render(
        request,
        "schools/manage/access_request_detail.html",
        {"access": access, "form": form, "other_coaches": others if access.school else []},
    )


@admin_required
@require_POST
def access_revoke(request, pk):
    access = get_object_or_404(CoachAccess, pk=pk)
    try:
        services.revoke(request, access, request.user, note=request.POST.get("decision_note", ""))
        messages.success(request, _("Access removed. The coach has been emailed."))
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("schools:coach_detail", pk=access.coach_id)


# ---------- Coaches ----------


@admin_required
def coach_list(request):
    q = request.GET.get("q", "").strip()
    coaches = User.objects.filter(role=User.Role.COACH).prefetch_related("school_access__school")
    if q:
        coaches = coaches.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(email__icontains=q)
            | Q(school_access__school__name__icontains=q)
        ).distinct()
    page = Paginator(coaches.order_by("last_name", "first_name"), 50).get_page(request.GET.get("page"))
    return render(request, "schools/manage/coach_list.html", {"page": page, "q": q})


@admin_required
def coach_detail(request, pk):
    coach = get_object_or_404(User, pk=pk, role=User.Role.COACH)
    access = coach.school_access.select_related("school", "decided_by")
    history = AuditEvent.objects.filter(
        Q(target_type="user", target_id=str(coach.pk))
        | Q(target_type="coachaccess", target_id__in=[str(a.pk) for a in access])
    ).select_related("actor")[:50]
    return render(
        request, "schools/manage/coach_detail.html", {"coach": coach, "access_list": access, "history": history}
    )


@admin_required
@require_POST
def coach_set_active(request, pk):
    coach = get_object_or_404(User, pk=pk, role=User.Role.COACH)
    make_active = request.POST.get("active") == "1"
    if coach.is_active != make_active:
        coach.is_active = make_active
        coach.save(update_fields=["is_active"])
        verb = "Turned on" if make_active else "Turned off"
        record(
            request.user,
            "coach.activated" if make_active else "coach.deactivated",
            f"{verb} the account for {coach.get_full_name()}",
            target=coach,
            changes={"active": ["no" if make_active else "yes", "yes" if make_active else "no"]},
        )
        messages.success(
            request, _("Account turned on.") if make_active else _("Account turned off. They can no longer sign in.")
        )
    return redirect("schools:coach_detail", pk=pk)


# ---------- Schools ----------


@admin_required
def school_list(request):
    year = SchoolYear.current()
    q = request.GET.get("q", "").strip()
    board = request.GET.get("board", "")
    level = request.GET.get("level", "")
    membership = request.GET.get("membership", "")
    active = request.GET.get("active", "1")

    schools = _with_current_membership(School.objects.select_related("board"), year)
    if q:
        schools = schools.filter(Q(name__icontains=q) | Q(city__icontains=q))
    if board:
        schools = schools.filter(board_id=board) if board != "none" else schools.filter(board__isnull=True)
    if level:
        schools = schools.filter(level=level)
    if active in ("1", "0"):
        schools = schools.filter(is_active=(active == "1"))
    if membership == "none":
        schools = schools.filter(membership_status__isnull=True)
    elif membership:
        schools = schools.filter(membership_status=membership)

    page = Paginator(schools.order_by("name"), 50).get_page(request.GET.get("page"))
    context = {
        "page": page,
        "year": year,
        "boards": SchoolBoard.objects.all(),
        "levels": School.Level.choices,
        "membership_choices": Membership.Status.choices,
        "filters": {"q": q, "board": board, "level": level, "membership": membership, "active": active},
    }
    return render(request, "schools/manage/school_list.html", context)


@admin_required
def school_create(request):
    form = SchoolForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        school = form.save()
        record(
            request.user,
            "school.created",
            f"Added {school} to the directory",
            target=school,
            changes=changes_between({}, snapshot(school, SCHOOL_FIELDS)),
        )
        messages.success(request, _("School added."))
        return redirect("schools:school_detail", pk=school.pk)
    return render(request, "schools/manage/school_form.html", {"form": form})


@admin_required
def school_edit(request, pk):
    school = get_object_or_404(School, pk=pk)
    before = snapshot(school, SCHOOL_FIELDS)
    form = SchoolForm(request.POST or None, instance=school)
    if request.method == "POST" and form.is_valid():
        school = form.save()
        changes = changes_between(before, snapshot(school, SCHOOL_FIELDS))
        if changes:
            record(request.user, "school.updated", f"Updated {school}", target=school, changes=changes)
        messages.success(request, _("School saved."))
        return redirect("schools:school_detail", pk=school.pk)
    return render(request, "schools/manage/school_form.html", {"form": form, "school": school})


@admin_required
def school_detail(request, pk):
    school = get_object_or_404(School.objects.select_related("board"), pk=pk)
    year = SchoolYear.current()
    memberships = school.memberships.select_related("school_year", "updated_by")
    access = school.coach_access.select_related("coach").order_by("status", "coach__last_name")
    history = AuditEvent.objects.filter(
        Q(target_type="school", target_id=str(school.pk))
        | Q(target_type="membership", target_id__in=[str(m.pk) for m in memberships])
        | Q(target_type="coachaccess", target_id__in=[str(a.pk) for a in access])
    ).select_related("actor")[:50]
    context = {
        "school": school,
        "year": year,
        "current_membership": memberships.filter(school_year=year).first() if year else None,
        "memberships": memberships,
        "access_list": access,
        "history": history,
    }
    return render(request, "schools/manage/school_detail.html", context)


@admin_required
def membership_edit(request, pk, year_pk):
    school = get_object_or_404(School, pk=pk)
    year = get_object_or_404(SchoolYear, pk=year_pk)
    membership = Membership.objects.filter(school=school, school_year=year).first()
    is_new = membership is None
    if is_new:
        membership = Membership(school=school, school_year=year)
    before = {} if is_new else snapshot(membership, MEMBERSHIP_FIELDS)

    form = MembershipForm(request.POST or None, instance=membership)
    if request.method == "POST" and form.is_valid():
        membership = form.save(commit=False)
        membership.updated_by = request.user
        membership.save()
        changes = changes_between(before, snapshot(membership, MEMBERSHIP_FIELDS))
        if changes:
            record(
                request.user,
                "membership.created" if is_new else "membership.updated",
                f"Set {school.name}'s {year} membership to {membership.get_status_display().lower()}",
                target=membership,
                changes=changes,
            )
        messages.success(request, _("Membership saved."))
        return redirect("schools:school_detail", pk=school.pk)
    return render(request, "schools/manage/membership_form.html", {"form": form, "school": school, "year": year})


# ---------- School boards ----------


@admin_required
def board_list(request):
    boards = SchoolBoard.objects.annotate(school_count=Count("schools"))
    return render(request, "schools/manage/board_list.html", {"boards": boards})


@admin_required
def board_form(request, pk=None):
    board = get_object_or_404(SchoolBoard, pk=pk) if pk else None
    before = snapshot(board, BOARD_FIELDS) if board else {}
    form = SchoolBoardForm(request.POST or None, instance=board)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        changes = changes_between(before, snapshot(saved, BOARD_FIELDS))
        if changes:
            record(
                request.user,
                "board.updated" if board else "board.created",
                f"{'Updated' if board else 'Added'} school board {saved}",
                target=saved,
                changes=changes,
            )
        messages.success(request, _("School board saved."))
        return redirect("schools:board_list")
    return render(request, "schools/manage/board_form.html", {"form": form, "board": board})


# ---------- School years ----------


@admin_required
def year_list(request):
    return render(request, "schools/manage/year_list.html", {"years": SchoolYear.objects.all()})


@admin_required
def year_form(request, pk=None):
    year = get_object_or_404(SchoolYear, pk=pk) if pk else None
    before = snapshot(year, YEAR_FIELDS) if year else {}
    form = SchoolYearForm(request.POST or None, instance=year, initial={"make_current": bool(year and year.is_current)})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            saved = form.save(commit=False)
            saved.is_current = form.cleaned_data["make_current"]
            if saved.is_current:
                # Only one school year can be current at a time.
                SchoolYear.objects.filter(is_current=True).exclude(pk=saved.pk).update(is_current=False)
            saved.save()
        changes = changes_between(before, snapshot(saved, YEAR_FIELDS))
        if changes:
            record(
                request.user,
                "year.updated" if year else "year.created",
                f"{'Updated' if year else 'Added'} school year {saved}",
                target=saved,
                changes=changes,
            )
        messages.success(request, _("School year saved."))
        return redirect("schools:year_list")
    return render(request, "schools/manage/year_form.html", {"form": form, "year": year})


# ---------- Exports ----------


@admin_required
def exports(request):
    return render(request, "schools/manage/exports.html", {"year": SchoolYear.current()})


@admin_required
def export_everything(request):
    record(request.user, "export.downloaded", "Downloaded the full data export (everything)")
    response = HttpResponse(build_zip(), content_type="application/zip")
    stamp = timezone.localtime().strftime("%Y-%m-%d")
    response["Content-Disposition"] = f'attachment; filename="osea-everything-{stamp}.zip"'
    return response


@admin_required
def export_csv(request, kind):
    year = SchoolYear.current()
    if kind == "schools":
        schools = _with_current_membership(School.objects.select_related("board"), year).order_by("name")
        header = [
            "School",
            "City",
            "Board",
            "Level",
            "Active",
            f"Membership {year}" if year else "Membership",
            "Approved coaches",
            "OSEA notes",
        ]
        rows = (
            [
                s.name,
                s.city,
                s.board.name if s.board else "Independent",
                s.get_level_display(),
                "yes" if s.is_active else "no",
                dict(Membership.Status.choices).get(s.membership_status, "No record"),
                s.approved_coaches,
                s.admin_notes,
            ]
            for s in schools
        )
    elif kind == "coaches":
        access = CoachAccess.objects.select_related("coach", "school", "school__board").order_by(
            "coach__last_name", "coach__first_name"
        )
        header = [
            "First name",
            "Last name",
            "Email",
            "Email confirmed",
            "Account active",
            "School",
            "Board",
            "Access status",
            "Role at school",
            "Requested",
            "Decided",
        ]
        rows = (
            [
                a.coach.first_name,
                a.coach.last_name,
                a.coach.email,
                "yes" if a.coach.email_verified_at else "no",
                "yes" if a.coach.is_active else "no",
                a.school_label,
                a.school.board.name if a.school and a.school.board else "",
                a.get_status_display(),
                a.position,
                f"{a.requested_at:%Y-%m-%d}",
                f"{a.decided_at:%Y-%m-%d}" if a.decided_at else "",
            ]
            for a in access
        )
    elif kind == "memberships":
        memberships = Membership.objects.select_related("school", "school_year").order_by(
            "-school_year__start_date", "school__name"
        )
        header = ["School year", "School", "City", "Status", "Amount", "Date paid", "Reference", "Notes"]
        rows = (
            [
                m.school_year.name,
                m.school.name,
                m.school.city,
                m.get_status_display(),
                m.amount or "",
                m.paid_on or "",
                m.reference,
                m.notes,
            ]
            for m in memberships
        )
    else:
        return redirect("schools:exports")

    record(request.user, "export.downloaded", f"Downloaded the {kind} export")
    return csv_response(kind, header, rows)
