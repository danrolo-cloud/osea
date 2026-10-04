import csv

from django.http import HttpResponse
from django.utils import timezone

# Spreadsheet programs treat cells starting with these characters as formulas,
# which a malicious entry (e.g. a school name) could abuse. Such cells get a
# leading apostrophe so they always open as plain text.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def csv_response(name, header, rows):
    stamp = timezone.localtime().strftime("%Y-%m-%d")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="osea-{name}-{stamp}.csv"'
    response.write("﻿")  # lets Excel read accented characters correctly
    writer = csv.writer(response)
    writer.writerow(header)
    for row in rows:
        writer.writerow([safe_cell(value) for value in row])
    return response
