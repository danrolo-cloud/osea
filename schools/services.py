"""
The rules for approving, declining and removing a coach's access to a school.

Screens call these functions instead of changing records directly, so the
rules, the activity log and the coach's email always happen together.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from audit.log import changes_between, record, snapshot

from .models import CoachAccess

Status = CoachAccess.Status


def _notify(request, access, template, subject):
    body = render_to_string(
        template,
        {"access": access, "coach": access.coach, "link": request.build_absolute_uri(reverse("core:dashboard"))},
    )
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [access.coach.email])


def _decide(access, admin, status, note):
    access.status = status
    access.decided_at = timezone.now()
    access.decided_by = admin
    access.decision_note = note.strip()


@transaction.atomic
def approve(request, access, admin, school=None, note=""):
    access = CoachAccess.objects.select_for_update().get(pk=access.pk)
    if access.status == Status.APPROVED:
        raise ValidationError(_("This coach already has access."))

    before = snapshot(access, ["school", "status"])
    if school is not None and access.school_id != school.pk:
        if CoachAccess.objects.filter(coach=access.coach, school=school).exclude(pk=access.pk).exists():
            raise ValidationError(_("This coach already has a separate request for %(school)s.") % {"school": school})
        access.school = school
    if access.school is None:
        raise ValidationError(_("Link this request to a school in the directory before approving it."))
    if not access.coach.email_verified_at:
        raise ValidationError(_("The coach must confirm their email address before they can be approved."))
    if not access.coach.is_active:
        raise ValidationError(_("This coach's account is turned off."))

    _decide(access, admin, Status.APPROVED, note)
    access.save()
    record(
        admin,
        "access.approved",
        f"Approved {access.coach.get_full_name()} as a coach at {access.school}",
        target=access,
        changes=changes_between(before, snapshot(access, ["school", "status"])),
    )
    transaction.on_commit(
        lambda: _notify(request, access, "schools/emails/access_approved.txt", "Your OSEA coach access is approved")
    )
    return access


@transaction.atomic
def decline(request, access, admin, note):
    access = CoachAccess.objects.select_for_update().get(pk=access.pk)
    if access.status != Status.PENDING:
        raise ValidationError(_("Only requests that are waiting for approval can be declined."))
    if not note.strip():
        raise ValidationError(_("Tell the coach why their request was declined."))
    _decide(access, admin, Status.DECLINED, note)
    access.save()
    record(
        admin,
        "access.declined",
        f"Declined {access.coach.get_full_name()}'s request for {access.school_label}",
        target=access,
        changes={
            "status": [str(Status.PENDING.label), str(Status.DECLINED.label)],
            "message": ["", access.decision_note],
        },
    )
    transaction.on_commit(
        lambda: _notify(request, access, "schools/emails/access_declined.txt", "Your OSEA coach request")
    )
    return access


@transaction.atomic
def revoke(request, access, admin, note):
    access = CoachAccess.objects.select_for_update().get(pk=access.pk)
    if access.status != Status.APPROVED:
        raise ValidationError(_("Only approved access can be removed."))
    if not note.strip():
        raise ValidationError(_("Give a reason for removing access."))
    _decide(access, admin, Status.REVOKED, note)
    access.save()
    record(
        admin,
        "access.revoked",
        f"Removed {access.coach.get_full_name()}'s access to {access.school}",
        target=access,
        changes={
            "status": [str(Status.APPROVED.label), str(Status.REVOKED.label)],
            "message": ["", access.decision_note],
        },
    )
    transaction.on_commit(
        lambda: _notify(request, access, "schools/emails/access_revoked.txt", "Your OSEA coach access has changed")
    )
    return access
