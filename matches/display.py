"""Arranging matches for display: rounds in playing order, brackets in columns."""

from itertools import groupby

from django.utils.translation import gettext as _

BRACKET_ORDER = {"": 0, "winners": 1, "losers": 2, "final": 3}


def grouped_rounds(matches):
    """[(heading, bracket, [matches]), ...] in playing order, for schedule lists and bracket views."""
    ordered = sorted(matches, key=lambda m: (BRACKET_ORDER[m.bracket], m.round_number, m.number))
    groups = []
    for (bracket, _round), items in groupby(ordered, key=lambda m: (m.bracket, m.round_number)):
        items = list(items)
        groups.append((items[0].round_label or _("Round %(n)s") % {"n": items[0].round_number}, bracket, items))
    return groups
