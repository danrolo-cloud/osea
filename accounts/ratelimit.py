"""
Limits on repeated attempts (sign-in, sign-up, password reset, codes).

Counts are kept in the database cache, so they work even if the site runs on
more than one server. Email addresses and IP addresses are stored only as
one-way hashes, and every count expires on its own after its time window.
"""

import hashlib

from django.conf import settings
from django.core.cache import cache

# (most attempts allowed, window in seconds)
LIMITS = {
    "signin-email": (5, 15 * 60),  # wrong passwords for one account
    "signin-ip": (20, 15 * 60),  # wrong passwords from one network address
    "signup-ip": (5, 60 * 60),
    "reset-ip": (5, 60 * 60),
    "reset-email": (3, 60 * 60),
    "verify-resend": (3, 60 * 60),
    "code-user": (5, 15 * 60),  # wrong two-step sign-in codes
}


def _key(scope, identity):
    digest = hashlib.sha256(f"{scope}:{identity}".lower().encode()).hexdigest()
    return f"ratelimit:{digest}"


def is_limited(scope, identity):
    limit, _window = LIMITS[scope]
    return (cache.get(_key(scope, identity)) or 0) >= limit


def hit(scope, identity):
    """Count one attempt. Returns True if this attempt is over the limit."""
    limit, window = LIMITS[scope]
    key = _key(scope, identity)
    cache.add(key, 0, window)
    try:
        count = cache.incr(key)
    except ValueError:  # expired between add and incr
        cache.set(key, 1, window)
        count = 1
    return count > limit


def clear(scope, identity):
    cache.delete(_key(scope, identity))


def client_ip(request):
    """
    The visitor's network address. Behind a hosting provider's proxy the real
    address arrives in a header the provider sets (configured with
    OSEA_CLIENT_IP_HEADER); otherwise the direct connection address is used.
    """
    header = getattr(settings, "OSEA_CLIENT_IP_HEADER", "")
    if header and request.META.get(header):
        return request.META[header].split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")
