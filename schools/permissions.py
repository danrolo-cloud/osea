"""
Who may see which school's data. Every school page calls these on the server.

  - OSEA administrators: every school.
  - Coaches: only schools where an administrator has APPROVED their access.
    Pending, declined and removed requests give no access at all.
"""

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from .models import CoachAccess, School


def schools_for(user):
    if not user.is_authenticated or not user.is_active:
        return School.objects.none()
    if user.is_osea_admin:
        return School.objects.all()
    return School.objects.filter(
        is_active=True,
        coach_access__coach=user,
        coach_access__status=CoachAccess.Status.APPROVED,
    ).distinct()


def can_view_school(user, school):
    return schools_for(user).filter(pk=school.pk).exists()


def get_school_or_403(user, pk):
    school = get_object_or_404(School, pk=pk)
    if not can_view_school(user, school):
        raise PermissionDenied
    return school
