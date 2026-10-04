"""
Teacher coach and public screens for competitions.

Public pages show only what OSEA has chosen to publish: competition details,
and approved team and school names when "show teams publicly" is on. They
never show students, rosters or coach contact details.
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from accounts.permissions import coach_required
from audit.log import changes_between, history_for, record, snapshot
from matches.display import grouped_rounds
from schools.models import Student
from schools.permissions import get_school_or_403, schools_for

from . import services
from .forms import AddPlayerForm, RegistrationStartForm, RosterChangeForm, StudentForm, SubmitForm, TeamNameForm
from .models import Announcement, Competition, Registration
from .permissions import get_registration_or_403

STUDENT_FIELDS = ["first_name", "last_initial", "grade", "is_active"]


def _show_errors(request, error):
    for text in error.messages:
        messages.error(request, text)


# ---------- Public ----------


def competition_list(request):
    competitions = Competition.objects.filter(is_published=True).select_related("game", "school_year")
    return render(request, "competitions/competition_list.html", {"competitions": competitions})


def competition_detail(request, pk):
    competition = get_object_or_404(Competition.objects.select_related("game", "school_year"), pk=pk)
    if not competition.is_published and not (request.user.is_authenticated and request.user.is_osea_admin):
        raise Http404
    public_teams = []
    if competition.show_teams_publicly:
        approved = competition.registrations.filter(status=Registration.Status.APPROVED).select_related(
            "school", "division"
        )
        divisions = {}
        for registration in approved.order_by("division__order", "division__name", "team_name"):
            divisions.setdefault(registration.division, []).append(registration)
        public_teams = list(divisions.items())

    my_registrations, eligible_schools = [], []
    if request.user.is_authenticated and request.user.is_coach:
        my_schools = schools_for(request.user)
        my_registrations = competition.registrations.filter(school__in=my_schools).select_related("school")
        eligible_schools = [s for s in my_schools if competition.school_is_eligible(s)]
    stages = [
        (stage, grouped_rounds(stage.matches.select_related("home", "away", "home_source", "away_source", "winner")))
        for stage in competition.stages.filter(is_published=True).select_related("division")
    ]
    context = {
        "competition": competition,
        "stages": stages,
        "announcements": announcements_for(request.user, competition),
        "public_teams": public_teams,
        "my_registrations": my_registrations,
        "eligible_schools": eligible_schools,
    }
    return render(request, "competitions/competition_detail.html", context)


def announcements_for(user, competition=None):
    """
    Announcements this person may read: public ones, plus coach-only ones for
    competitions (and divisions) where their schools have a team.
    """
    announcements = Announcement.objects.select_related("competition", "division")
    if competition is not None:
        announcements = announcements.filter(competition=competition)
    visible = Q(is_public=True) if competition is not None else Q(pk__in=[])
    if user.is_authenticated and user.is_osea_admin:
        return announcements
    if user.is_authenticated and user.is_coach:
        teams = Registration.objects.filter(school__in=schools_for(user)).exclude(status=Registration.Status.WITHDRAWN)
        for team in teams.values("competition_id", "division_id"):
            visible |= Q(competition_id=team["competition_id"], division__isnull=True)
            if team["division_id"]:
                visible |= Q(competition_id=team["competition_id"], division_id=team["division_id"])
    return announcements.filter(visible)


# ---------- Coach: registering ----------


@coach_required
def register(request, pk):
    competition = get_object_or_404(Competition, pk=pk, is_published=True)
    eligible = schools_for(request.user).filter(level__in=competition.allowed_levels)
    form = RegistrationStartForm(request.POST or None, schools=eligible)
    if request.method == "POST" and form.is_valid():
        try:
            registration = services.create_registration(
                request.user, competition, form.cleaned_data["school"], form.cleaned_data["team_name"]
            )
        except ValidationError as error:
            for text in error.messages:
                form.add_error(None, text)
        else:
            messages.success(request, _("Team started. Add your players, then submit."))
            return redirect("competitions:registration", pk=registration.pk)
    if not competition.registration_is_open:
        messages.info(request, _("Registration for this competition isn't open right now."))
    return render(request, "competitions/register.html", {"competition": competition, "form": form})


@coach_required
def registration_detail(request, pk):
    registration = get_registration_or_403(request.user, pk)
    competition = registration.competition
    can_edit = services.coach_can_edit(registration)
    can_change = services.coach_can_request_roster_change(registration)
    context = {
        "registration": registration,
        "competition": competition,
        "roster": registration.roster.select_related("student"),
        "can_edit": can_edit,
        "can_request_change": can_change,
        "problems": services.roster_problems(registration) if registration.is_active else [],
        "add_form": AddPlayerForm(registration=registration) if can_edit else None,
        "rename_form": TeamNameForm(initial={"team_name": registration.team_name}) if can_edit else None,
        "submit_form": SubmitForm() if can_edit else None,
        "change_form": RosterChangeForm(registration=registration) if can_change else None,
        "roster_changes": registration.roster_changes.select_related("player_in", "player_out"),
        "history": history_for(registration)[:20],
    }
    return render(request, "competitions/registration_detail.html", context)


@coach_required
@require_POST
def add_player(request, pk):
    registration = get_registration_or_403(request.user, pk)
    if not services.coach_can_edit(registration):
        messages.error(request, _("This roster can't be changed right now."))
        return redirect("competitions:registration", pk=pk)
    form = AddPlayerForm(request.POST, registration=registration)
    if form.is_valid():
        try:
            # A new student is only kept if they are successfully added to the roster.
            with transaction.atomic():
                student = form.get_or_create_student(request.user)
                services.add_player(
                    registration,
                    request.user,
                    student,
                    form.cleaned_data.get("gamer_tag", ""),
                    form.cleaned_data.get("rank", ""),
                )
            messages.success(request, _("%(s)s added to the roster.") % {"s": student})
        except ValidationError as error:
            _show_errors(request, error)
    else:
        for errors in form.errors.values():
            for text in errors:
                messages.error(request, text)
    return redirect("competitions:registration", pk=pk)


@coach_required
@require_POST
def remove_player(request, pk, entry_pk):
    registration = get_registration_or_403(request.user, pk)
    entry = get_object_or_404(registration.roster, pk=entry_pk)
    try:
        services.remove_player(entry, request.user)
        messages.success(request, _("Player removed."))
    except ValidationError as error:
        _show_errors(request, error)
    return redirect("competitions:registration", pk=pk)


@coach_required
@require_POST
def rename(request, pk):
    registration = get_registration_or_403(request.user, pk)
    try:
        services.rename_team(registration, request.user, request.POST.get("team_name", ""))
        messages.success(request, _("Team name saved."))
    except ValidationError as error:
        _show_errors(request, error)
    return redirect("competitions:registration", pk=pk)


@coach_required
@require_POST
def submit(request, pk):
    registration = get_registration_or_403(request.user, pk)
    form = SubmitForm(request.POST)
    try:
        services.submit(request, registration, request.user, consent_confirmed=form.is_valid())
        messages.success(request, _("Submitted. OSEA will review your team and email you."))
    except ValidationError as error:
        _show_errors(request, error)
    return redirect("competitions:registration", pk=pk)


@coach_required
@require_POST
def unsubmit(request, pk):
    registration = get_registration_or_403(request.user, pk)
    try:
        services.unsubmit(registration, request.user)
        messages.success(request, _("Back to draft. Remember to submit again when you're done."))
    except ValidationError as error:
        _show_errors(request, error)
    return redirect("competitions:registration", pk=pk)


@coach_required
@require_POST
def withdraw(request, pk):
    registration = get_registration_or_403(request.user, pk)
    try:
        services.withdraw(request, registration, request.user, reason=request.POST.get("reason", ""))
        messages.success(request, _("Your team has been withdrawn."))
    except ValidationError as error:
        _show_errors(request, error)
    return redirect("competitions:registration", pk=pk)


@coach_required
@require_POST
def request_change(request, pk):
    registration = get_registration_or_403(request.user, pk)
    form = RosterChangeForm(request.POST, registration=registration)
    if form.is_valid():
        try:
            services.request_roster_change(
                registration,
                request.user,
                player_in=form.cleaned_data["player_in"],
                player_out=form.cleaned_data["player_out"],
                gamer_tag=form.cleaned_data.get("gamer_tag", ""),
                rank=form.cleaned_data.get("rank", ""),
                reason=form.cleaned_data["reason"],
            )
            messages.success(request, _("Change requested. OSEA will review it."))
        except ValidationError as error:
            _show_errors(request, error)
    else:
        for errors in form.errors.values():
            for text in errors:
                messages.error(request, text)
    return redirect("competitions:registration", pk=pk)


# ---------- Coach: students ----------


@coach_required
def student_list(request, school_pk):
    school = get_school_or_403(request.user, school_pk)
    show = request.GET.get("show", "active")
    students = school.students.all() if show == "all" else school.students.filter(is_active=True)
    return render(request, "competitions/student_list.html", {"school": school, "students": students, "show": show})


@coach_required
def student_form(request, school_pk, pk=None):
    school = get_school_or_403(request.user, school_pk)
    student = get_object_or_404(Student, pk=pk, school=school) if pk else None
    before = snapshot(student, STUDENT_FIELDS) if student else {}
    form = StudentForm(request.POST or None, instance=student)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        saved.school = school
        if not student:
            saved.created_by = request.user
        saved.save()
        changes = changes_between(before, snapshot(saved, STUDENT_FIELDS))
        if changes:
            record(
                request.user,
                "student.updated" if student else "student.created",
                f"{'Updated' if student else 'Added'} student {saved} at {school.name}",
                target=saved,
                changes=changes,
            )
        messages.success(request, _("Student saved."))
        return redirect("competitions:student_list", school_pk=school.pk)
    return render(request, "competitions/student_form.html", {"form": form, "school": school, "student": student})
