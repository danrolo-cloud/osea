from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from accounts.permissions import admin_required

from .models import AuditEvent

AREAS = [
    ("access", _("Coach access")),
    ("coach", _("Coach accounts")),
    ("school", _("Schools")),
    ("membership", _("Memberships")),
    ("board", _("School boards")),
    ("year", _("School years")),
    ("competition", _("Competition settings")),
    ("registration", _("Registrations and rosters")),
    ("roster_change", _("Roster change requests")),
    ("stage", _("Stages")),
    ("match", _("Matches and times")),
    ("announcement", _("Announcements")),
    ("student", _("Students")),
    ("export", _("Exports")),
    ("account", _("Account changes")),
]


@admin_required
def activity_log(request):
    q = request.GET.get("q", "").strip()
    area = request.GET.get("area", "")
    events = AuditEvent.objects.select_related("actor")
    if area in dict(AREAS):
        events = events.filter(action__startswith=f"{area}.")
    if q:
        events = events.filter(Q(summary__icontains=q) | Q(actor_label__icontains=q) | Q(target_label__icontains=q))
    page = Paginator(events, 50).get_page(request.GET.get("page"))
    return render(request, "audit/activity_log.html", {"page": page, "q": q, "area": area, "areas": AREAS})
