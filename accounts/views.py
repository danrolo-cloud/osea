from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from audit.log import changes_between, record, snapshot
from schools.forms import SchoolAccessRequestForm

from . import ratelimit, two_factor
from .forms import CoachSignUpForm, EmailAuthenticationForm, ProfileForm
from .models import User
from .verification import mark_verified, send_verification_email, user_from_token


def sign_up(request):
    """New teacher coaches create an account and ask for access to their school in one step."""
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    account_form = CoachSignUpForm(request.POST or None, prefix="account")
    school_form = SchoolAccessRequestForm(request.POST or None, prefix="school")

    if request.method == "POST" and ratelimit.is_limited("signup-ip", ratelimit.client_ip(request)):
        messages.error(request, _("Too many new accounts from this network. Please try again in an hour."))
        return render(request, "accounts/sign_up.html", {"account_form": account_form, "school_form": school_form})
    if request.method == "POST" and account_form.is_valid() and school_form.is_valid():
        ratelimit.hit("signup-ip", ratelimit.client_ip(request))
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
    elif ratelimit.hit("verify-resend", str(request.user.pk)):
        messages.error(request, _("We've sent several links already. Check your junk folder, or try again later."))
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
    context = {
        "form": form,
        "two_factor_on": two_factor.is_enabled(request.user),
        "backup_codes_left": two_factor.backup_codes_left(request.user),
        "two_factor_required": request.user.is_osea_admin and settings.OSEA_REQUIRE_ADMIN_2FA,
    }
    return render(request, "accounts/profile.html", context)


# ---------------------------------------------------------------- sign-in with limits and two-step codes

PENDING = "two_factor_pending"
PENDING_SECONDS = 10 * 60


class SignInView(auth_views.LoginView):
    """
    Sign-in with two protections:
      - after 5 wrong passwords for an account (or 20 from one network address)
        in 15 minutes, sign-in pauses for that account or address;
      - people with two-step sign-in turned on must also enter a code.
    """

    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        email = request.POST.get("username", "").strip().lower()
        if ratelimit.is_limited("signin-email", email) or ratelimit.is_limited(
            "signin-ip", ratelimit.client_ip(request)
        ):
            form = self.get_form()
            form.errors.clear()
            return self.render_to_response(self.get_context_data(form=form, limited=True))
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        ratelimit.hit("signin-email", self.request.POST.get("username", "").strip().lower())
        ratelimit.hit("signin-ip", ratelimit.client_ip(self.request))
        return super().form_invalid(form)

    def form_valid(self, form):
        user = form.get_user()
        ratelimit.clear("signin-email", user.email)
        if two_factor.is_enabled(user):
            self.request.session[PENDING] = {
                "user": user.pk,
                "backend": user.backend,
                "started": timezone.now().timestamp(),
                "next": self.get_redirect_url(),
            }
            return redirect("accounts:two_factor_verify")
        return super().form_valid(form)


def two_factor_verify(request):
    pending = request.session.get(PENDING)
    if not pending or timezone.now().timestamp() - pending["started"] > PENDING_SECONDS:
        request.session.pop(PENDING, None)
        messages.info(request, _("Please sign in again."))
        return redirect("accounts:login")
    user = User.objects.filter(pk=pending["user"], is_active=True).first()
    if user is None:
        return redirect("accounts:login")

    error = ""
    if request.method == "POST":
        if ratelimit.is_limited("code-user", str(user.pk)):
            error = _("Too many wrong codes. Wait 15 minutes, then sign in again.")
        elif two_factor.verify(user, request.POST.get("code", "")):
            request.session.pop(PENDING, None)
            ratelimit.clear("code-user", str(user.pk))
            login(request, user, backend=pending["backend"])
            next_url = pending.get("next") or ""
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect("core:dashboard")
        else:
            ratelimit.hit("code-user", str(user.pk))
            error = _("That code didn't work. Check your authenticator app and try again.")
    return render(request, "accounts/two_factor_verify.html", {"error": error})


@login_required
def two_factor_setup(request):
    if two_factor.is_enabled(request.user):
        return redirect("accounts:profile")
    device = two_factor.start_setup(request.user)
    link = two_factor.setup_link(device)
    error = ""
    if request.method == "POST":
        codes = two_factor.confirm_setup(device, request.POST.get("code", ""))
        if codes:
            request.session["new_backup_codes"] = codes
            return redirect("accounts:backup_codes")
        error = _("That code didn't work. Make sure you scanned the code above, then enter the newest 6 digits.")
    context = {"qr": mark_safe(two_factor.qr_svg(link)), "secret": device.secret, "error": error}
    return render(request, "accounts/two_factor_setup.html", context)


@login_required
def backup_codes(request):
    codes = request.session.pop("new_backup_codes", None)
    if codes is None:
        return redirect("accounts:profile")
    return render(request, "accounts/backup_codes.html", {"codes": codes})


@login_required
@require_POST
def backup_codes_renew(request):
    if not two_factor.is_enabled(request.user):
        return redirect("accounts:profile")
    request.session["new_backup_codes"] = two_factor.regenerate_backup_codes(request.user)
    return redirect("accounts:backup_codes")


@login_required
@require_POST
def two_factor_off(request):
    if request.user.is_osea_admin and settings.OSEA_REQUIRE_ADMIN_2FA:
        messages.error(request, _("OSEA administrators must keep two-step sign-in on."))
    elif not two_factor.verify(request.user, request.POST.get("code", "")):
        messages.error(request, _("Enter a current code from your app to turn two-step sign-in off."))
    else:
        two_factor.turn_off(request.user, request.user)
        messages.success(request, _("Two-step sign-in is off."))
    return redirect("accounts:profile")


class LimitedPasswordResetView(auth_views.PasswordResetView):
    """Same response whether or not the email exists; quietly stops sending after a few requests."""

    def form_valid(self, form):
        email = form.cleaned_data["email"].strip().lower()
        ip_over = ratelimit.hit("reset-ip", ratelimit.client_ip(self.request))
        email_over = ratelimit.hit("reset-email", email)
        if ip_over or email_over:
            return redirect(self.get_success_url())
        return super().form_valid(form)
