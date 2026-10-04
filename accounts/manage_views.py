"""OSEA administrator accounts: add administrators, turn accounts off, reset two-step sign-in."""

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from audit.log import record

from . import two_factor
from .models import User
from .permissions import admin_required


class NewAdminForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        help_texts = {"email": gettext_lazy("They'll get an email with a link to choose their own password.")}

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                gettext_lazy("Someone already has an account with this email. Each person has one role.")
            )
        return email


def _send_set_password_email(request, user):
    link = request.build_absolute_uri(
        reverse(
            "accounts:password_reset_confirm",
            args=[urlsafe_base64_encode(force_bytes(user.pk)), default_token_generator.make_token(user)],
        )
    )
    body = render_to_string("accounts/emails/new_admin.txt", {"user": user, "link": link, "by": request.user})
    send_mail("You've been added as an OSEA administrator", body, settings.DEFAULT_FROM_EMAIL, [user.email])


@admin_required
def admin_list(request):
    admins = User.objects.filter(role=User.Role.ADMIN).order_by("-is_active", "last_name")
    enabled = set(User.objects.filter(two_factor__confirmed_at__isnull=False).values_list("pk", flat=True))
    for admin in admins:
        admin.has_two_step = admin.pk in enabled
    return render(request, "accounts/manage/admin_list.html", {"admins": admins, "form": NewAdminForm()})


@admin_required
@require_POST
def admin_create(request):
    form = NewAdminForm(request.POST)
    if not form.is_valid():
        admins = User.objects.filter(role=User.Role.ADMIN).order_by("-is_active", "last_name")
        return render(request, "accounts/manage/admin_list.html", {"admins": admins, "form": form})
    with transaction.atomic():
        user = form.save(commit=False)
        user.role = User.Role.ADMIN
        user.set_unusable_password()
        user.save()
        record(
            request.user, "account.admin_added", f"Added {user.get_full_name()} as an OSEA administrator", target=user
        )
    _send_set_password_email(request, user)
    messages.success(request, _("Administrator added. They've been emailed a link to set their password."))
    return redirect("accounts:admin_list")


@admin_required
@require_POST
def admin_set_active(request, pk):
    admin = get_object_or_404(User, pk=pk, role=User.Role.ADMIN)
    make_active = request.POST.get("active") == "1"
    if admin == request.user:
        messages.error(request, _("You can't turn off your own account."))
    elif not make_active and not User.objects.filter(role=User.Role.ADMIN, is_active=True).exclude(pk=admin.pk):
        messages.error(request, _("OSEA needs at least one active administrator."))
    elif admin.is_active != make_active:
        admin.is_active = make_active
        admin.save(update_fields=["is_active"])
        verb = "Turned on" if make_active else "Turned off"
        record(
            request.user,
            "account.admin_activated" if make_active else "account.admin_deactivated",
            f"{verb} the administrator account for {admin.get_full_name()}",
            target=admin,
        )
        messages.success(request, _("Account updated."))
    return redirect("accounts:admin_list")


@admin_required
@require_POST
def admin_reset_two_step(request, pk):
    person = get_object_or_404(User, pk=pk)
    reason = request.POST.get("reason", "").strip()
    if person == request.user:
        messages.error(request, _("Manage your own two-step sign-in from your Account page."))
    elif not reason:
        messages.error(request, _("Give a reason, e.g. lost phone."))
    else:
        two_factor.turn_off(person, request.user, reason=reason)
        messages.success(request, _("Two-step sign-in reset. They'll set it up again at their next sign-in."))
    return redirect("accounts:admin_list")
