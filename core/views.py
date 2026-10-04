from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from accounts.permissions import admin_required, coach_required


@require_GET
def home(request):
    return render(request, "core/home.html")


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
    return render(request, "core/admin_dashboard.html")


@coach_required
def coach_dashboard(request):
    return render(request, "core/coach_dashboard.html")


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
