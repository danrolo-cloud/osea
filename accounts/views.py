from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from audit.log import changes_between, record, snapshot
from schools.forms import SchoolAccessRequestForm

from .forms import CoachSignUpForm, ProfileForm
from .verification import mark_verified, send_verification_email, user_from_token


def sign_up(request):
    """New teacher coaches create an account and ask for access to their school in one step."""
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    account_form = CoachSignUpForm(request.POST or None, prefix="account")
    school_form = SchoolAccessRequestForm(request.POST or None, prefix="school")

    if request.method == "POST" and account_form.is_valid() and school_form.is_valid():
        with transaction.atomic():
            user = account_form.save()
            access = school_form.save(coach=user)
            record(user, "coach.signed_up", f"{user.get_full_name()} created a coach account", target=user)
            record(
                user,
                "access.requested",
                f"{user.get_full_name()} asked to coach at {access.school_label}",
                target=access,
            )
        send_verification_email(request, user)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, _("Account created. Check your email for a link to confirm your address."))
        return redirect("core:dashboard")

    return render(request, "accounts/sign_up.html", {"account_form": account_form, "school_form": school_form})


def verify_email(request, token):
    user = user_from_token(token)
    if user is None:
        return render(request, "accounts/verify_email_invalid.html", status=400)
    already = bool(user.email_verified_at)
    mark_verified(user)
    if not already:
        record(user, "coach.email_verified", f"{user.get_full_name()} confirmed their email address", target=user)
    messages.success(request, _("Thanks, your email address is confirmed."))
    return redirect("core:dashboard" if request.user.is_authenticated else "accounts:login")


@login_required
@require_POST
def resend_verification(request):
    if request.user.email_verified_at:
        messages.info(request, _("Your email address is already confirmed."))
    else:
        send_verification_email(request, request.user)
        messages.success(request, _("We sent a new confirmation link to %(email)s.") % {"email": request.user.email})
    return redirect("core:dashboard")


@login_required
def profile(request):
    fields = ["first_name", "last_name"]
    before = snapshot(request.user, fields)
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        changes = changes_between(before, snapshot(user, fields))
        if changes:
            record(user, "account.updated", f"{user.get_full_name()} updated their name", target=user, changes=changes)
        messages.success(request, _("Your details are saved."))
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})
