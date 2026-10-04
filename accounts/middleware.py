from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.utils.translation import gettext as _

from . import two_factor

PROTECTED_PREFIXES = ("/manage/", "/back-office/")


class RequireAdminTwoFactor:
    """
    OSEA administrators must turn on two-step sign-in before they can use any
    administrator page. Until they do, those pages send them to the setup page.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            settings.OSEA_REQUIRE_ADMIN_2FA
            and user is not None
            and user.is_authenticated
            and (user.is_osea_admin or user.is_staff)
            and request.path.startswith(PROTECTED_PREFIXES)
            and not two_factor.is_enabled(user)
        ):
            messages.warning(request, _("Turn on two-step sign-in to use OSEA's administrator pages."))
            return redirect("accounts:two_factor_setup")
        return self.get_response(request)
