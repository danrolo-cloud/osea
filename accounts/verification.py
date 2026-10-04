"""
Email verification links.

A link contains a signed, time-limited token naming the account and the
email address. It stops working if the address changes or it is older than
three days. Nothing is stored in the database until the link is used.
"""

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import User

SALT = "accounts.verify-email"
MAX_AGE_SECONDS = 3 * 24 * 60 * 60


def make_token(user):
    return signing.dumps({"u": user.pk, "e": user.email}, salt=SALT)


def user_from_token(token):
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE_SECONDS)
    except signing.BadSignature:  # also covers expired links
        return None
    user = User.objects.filter(pk=data.get("u"), is_active=True).first()
    if user is None or user.email != data.get("e"):
        return None
    return user


def mark_verified(user):
    if not user.email_verified_at:
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])


def send_verification_email(request, user):
    link = request.build_absolute_uri(reverse("accounts:verify_email", args=[make_token(user)]))
    body = render_to_string("accounts/emails/verify_email.txt", {"user": user, "link": link})
    send_mail("Confirm your email for OSEA", body, settings.DEFAULT_FROM_EMAIL, [user.email])
