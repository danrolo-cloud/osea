from django.conf import settings

# Which navigation item to highlight for each page, by the page's URL name.
_SECTIONS = {
    "home": "home",
    "sign_up": "sign_up",
    "login": "sign_in",
    "admin_dashboard": "dashboard",
    "coach_dashboard": "dashboard",
    "request_school": "dashboard",
    "my_school": "dashboard",
    "profile": "account",
    "password_change": "account",
    "password_change_done": "account",
    "access_requests": "access",
    "access_request": "access",
    "coach_list": "coaches",
    "coach_detail": "coaches",
    "school_list": "schools",
    "school_create": "schools",
    "school_detail": "schools",
    "school_edit": "schools",
    "membership_edit": "schools",
    "board_list": "boards",
    "board_create": "boards",
    "board_edit": "boards",
    "year_list": "years",
    "year_create": "years",
    "year_edit": "years",
    "activity_log": "activity",
    "exports": "exports",
    "style_guide": "style",
}


def site(request):
    match = getattr(request, "resolver_match", None)
    return {
        "environment_label": settings.OSEA_ENVIRONMENT_LABEL,
        "nav_section": _SECTIONS.get(match.url_name if match else "", ""),
    }
