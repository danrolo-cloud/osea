"""
Helpers for writing to the activity log.

    from audit.log import record, snapshot, changes_between

    before = snapshot(school, ["name", "level"])
    ... save the form ...
    record(request.user, "school.updated", f"Updated {school}", target=school,
           changes=changes_between(before, snapshot(school, ["name", "level"])))
"""

import datetime
from decimal import Decimal

from .models import AuditEvent


def _display(obj, field_name):
    field = obj._meta.get_field(field_name)
    value = getattr(obj, field_name)
    if value is None or value == "":
        return ""
    if isinstance(value, list | tuple):
        return ", ".join(str(item) for item in value)
    if field.choices:
        return str(getattr(obj, f"get_{field_name}_display")())  # str() turns translatable labels into plain text
    if field.is_relation:
        return str(value)
    if isinstance(value, bool):
        return "yes" if value else "no"
    if getattr(field, "decimal_places", None) is not None:  # money: always two decimals
        return f"{Decimal(value):.{field.decimal_places}f}"
    if isinstance(value, datetime.date | datetime.datetime):
        return str(value)
    return value if isinstance(value, int | float | str) else str(value)


def snapshot(obj, fields):
    """Readable values of the given fields, for comparing before and after a change."""
    return {name: _display(obj, name) for name in fields}


def changes_between(before, after):
    """{field: [old, new]} for every field whose value changed."""
    return {name: [before.get(name, ""), value] for name, value in after.items() if before.get(name, "") != value}


def record(actor, action, summary, target=None, changes=None):
    actor = actor if getattr(actor, "is_authenticated", False) else None
    return AuditEvent.objects.create(
        actor=actor,
        actor_label=(f"{actor.get_full_name()} <{actor.email}>" if actor else "System"),
        action=action,
        summary=summary[:500],
        target_type=(target._meta.model_name if target is not None else ""),
        target_id=(str(target.pk) if target is not None else ""),
        target_label=(str(target)[:255] if target is not None else ""),
        changes=changes or {},
    )


def history_for(obj):
    return AuditEvent.objects.filter(target_type=obj._meta.model_name, target_id=str(obj.pk)).select_related("actor")
