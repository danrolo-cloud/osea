from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from schools.permissions import schools_for

from .models import Registration


def registrations_for(user):
    """Registrations this person may see: all for administrators, their approved schools' for coaches."""
    if user.is_authenticated and user.is_osea_admin:
        return Registration.objects.all()
    return Registration.objects.filter(school__in=schools_for(user))


def get_registration_or_403(user, pk):
    registration = get_object_or_404(
        Registration.objects.select_related("competition__game", "competition__school_year", "school", "division"),
        pk=pk,
    )
    if not registrations_for(user).filter(pk=registration.pk).exists():
        raise PermissionDenied
    return registration
