"""
Server-side permission checks.

Every protected page uses one of these decorators. Hiding a button in the
interface is a convenience only; these checks are what actually keep people
out of pages they are not allowed to use.

  - Not signed in       -> sent to the sign-in page.
  - Signed in, wrong role -> "403 Forbidden" error page.
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def _role_required(check):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not check(user):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


admin_required = _role_required(lambda user: user.is_osea_admin)
admin_required.__doc__ = "Only OSEA administrators may use this page."

coach_required = _role_required(lambda user: user.is_coach)
coach_required.__doc__ = "Only teacher coaches may use this page."
