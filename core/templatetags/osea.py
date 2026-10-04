from django import template
from django.utils.html import format_html

register = template.Library()

# Which colour each status uses, so statuses look the same on every screen.
_BADGE = {
    "pending": "warning",
    "approved": "success",
    "confirmed": "success",
    "exempt": "info",
    "declined": "danger",
    "revoked": "danger",
}


@register.simple_tag
def status_badge(value, label=None):
    """{% status_badge access.status access.get_status_display %}"""
    if not value:
        return format_html('<span class="badge badge-neutral">{}</span>', label or "No record")
    return format_html('<span class="badge badge-{}">{}</span>', _BADGE.get(value, "neutral"), label or value)


@register.simple_tag(takes_context=True)
def query_with(context, **changes):
    """Current page's query string with some values replaced (keeps filters when changing page)."""
    params = context["request"].GET.copy()
    for key, value in changes.items():
        params[key] = value
    return "?" + params.urlencode()


@register.filter
def field_label(name):
    """'admin_notes' -> 'Admin notes' for the activity history."""
    return str(name).replace("_", " ").capitalize()
