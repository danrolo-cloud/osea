"""
Two-step sign-in with an authenticator app.

Codes follow the standard used by every authenticator app (TOTP, RFC 6238):
a new 6-digit code every 30 seconds. A code is accepted for 30 seconds either
side of now, to allow for a slightly wrong clock, and can only be used once.

Each person also gets 10 one-time backup codes, shown once and stored only
as hashes, for when their phone isn't available.
"""

import io
import secrets

import pyotp
import qrcode
import qrcode.image.svg
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from audit.log import record

from .models import BackupCode, TwoFactor

BACKUP_CODE_COUNT = 10


def is_enabled(user):
    return TwoFactor.objects.filter(user=user, confirmed_at__isnull=False).exists()


def start_setup(user):
    """The not-yet-confirmed setup for this person, creating one with a new secret if needed."""
    device, _created = TwoFactor.objects.get_or_create(user=user, defaults={"secret": pyotp.random_base32()})
    if device.confirmed_at is None and not device.secret:
        device.secret = pyotp.random_base32()
        device.save()
    return device


def setup_link(device):
    return pyotp.TOTP(device.secret).provisioning_uri(name=device.user.email, issuer_name="OSEA")


def qr_svg(text):
    image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue().decode()


def _normalize(code):
    return "".join(ch for ch in (code or "") if ch.isalnum()).lower()


def _match_totp(device, code, now=None):
    """The time step the code belongs to, or None if it's wrong or already used."""
    code = _normalize(code)
    if len(code) != 6 or not code.isdigit():
        return None
    totp = pyotp.TOTP(device.secret)
    now = now or timezone.now()
    current = totp.timecode(now)
    for offset in (0, -1, 1):
        step = current + offset
        if totp.generate_otp(step) == code:
            if device.last_used_step is not None and step <= device.last_used_step:
                return None  # already used: stops someone replaying a code they saw
            return step
    return None


def _new_backup_codes(user):
    user.backup_codes.all().delete()
    codes = []
    for _ in range(BACKUP_CODE_COUNT):
        raw = secrets.token_hex(4)  # 8 characters
        codes.append(f"{raw[:4]}-{raw[4:]}")
        BackupCode.objects.create(user=user, code_hash=make_password(raw))
    return codes


@transaction.atomic
def confirm_setup(device, code):
    """Finish setup with a code from the app. Returns the backup codes to show once, or None."""
    step = _match_totp(device, code)
    if step is None:
        return None
    device.confirmed_at = timezone.now()
    device.last_used_step = step
    device.save()
    record(
        device.user,
        "account.two_factor_on",
        f"{device.user.get_full_name()} turned on two-step sign-in",
        target=device.user,
    )
    return _new_backup_codes(device.user)


@transaction.atomic
def verify(user, code):
    """Check a sign-in code: 'app', 'backup' (a backup code was used up) or None."""
    device = TwoFactor.objects.select_for_update().filter(user=user, confirmed_at__isnull=False).first()
    if device is None:
        return None
    step = _match_totp(device, code)
    if step is not None:
        device.last_used_step = step
        device.save(update_fields=["last_used_step"])
        return "app"
    raw = _normalize(code)
    if len(raw) == 8:
        for backup in user.backup_codes.filter(used_at__isnull=True):
            if check_password(raw, backup.code_hash):
                backup.used_at = timezone.now()
                backup.save(update_fields=["used_at"])
                record(
                    user,
                    "account.backup_code_used",
                    f"{user.get_full_name()} signed in with a backup code",
                    target=user,
                )
                return "backup"
    return None


def backup_codes_left(user):
    return user.backup_codes.filter(used_at__isnull=True).count()


@transaction.atomic
def regenerate_backup_codes(user):
    codes = _new_backup_codes(user)
    record(user, "account.backup_codes_renewed", f"{user.get_full_name()} made new backup codes", target=user)
    return codes


@transaction.atomic
def turn_off(user, actor, reason=""):
    """Remove two-step sign-in (the person themselves, or an administrator after a lost phone)."""
    TwoFactor.objects.filter(user=user).delete()
    user.backup_codes.all().delete()
    who = "their own" if actor == user else f"{user.get_full_name()}'s"
    record(
        actor,
        "account.two_factor_off",
        f"Turned off {who} two-step sign-in",
        target=user,
        changes={"reason": ["", reason]} if reason else None,
    )
