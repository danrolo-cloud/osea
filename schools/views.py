"""Teacher coach screens for their schools."""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from accounts.permissions import coach_required
from audit.log import record

from .forms import SchoolAccessRequestForm
from .models import CoachAccess, SchoolYear
from .permissions import get_school_or_403


@coach_required
def request_school(request):
    form = SchoolAccessRequestForm(request.POST or None, coach=request.user)
    if request.method == "POST" and form.is_valid():
        access = form.save(coach=request.user)
        record(
            request.user,
            "access.requested",
            f"{request.user.get_full_name()} asked to coach at {access.school_label}",
            target=access,
        )
        messages.success(request, _("Request sent. OSEA will review it and email you."))
        return redirect("core:dashboard")
    return render(request, "schools/request_school.html", {"form": form})


@coach_required
def my_school(request, pk):
    # Refuses (403) unless this coach's access to the school is approved.
    school = get_school_or_403(request.user, pk)
    year = SchoolYear.current()
    membership = school.memberships.filter(school_year=year).first() if year else None
    co_coaches = (
        CoachAccess.objects.approved().filter(school=school).exclude(coach=request.user).select_related("coach")
    )
    return render(
        request,
        "schools/my_school.html",
        {"school": school, "year": year, "membership": membership, "co_coaches": co_coaches},
    )
