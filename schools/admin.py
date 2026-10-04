"""
Back-office (fallback) screens. Day-to-day work happens in the OSEA admin
screens at /manage/, which also write to the activity log; changes made
here are recorded only in Django's own back-office history.
"""

from django.contrib import admin

from .models import CoachAccess, Membership, School, SchoolBoard, SchoolYear


@admin.register(SchoolBoard)
class SchoolBoardAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active"]
    search_fields = ["name"]


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ["name", "city", "board", "level", "is_active"]
    list_filter = ["level", "is_active", "board"]
    search_fields = ["name", "city"]


@admin.register(SchoolYear)
class SchoolYearAdmin(admin.ModelAdmin):
    list_display = ["name", "start_date", "end_date", "is_current"]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["school", "school_year", "status", "paid_on", "amount"]
    list_filter = ["school_year", "status"]
    search_fields = ["school__name"]
    readonly_fields = ["updated_at", "updated_by"]


@admin.register(CoachAccess)
class CoachAccessAdmin(admin.ModelAdmin):
    list_display = ["coach", "school", "requested_school_name", "status", "requested_at"]
    list_filter = ["status"]
    search_fields = ["coach__email", "coach__last_name", "school__name", "requested_school_name"]
    readonly_fields = ["requested_at", "decided_at", "decided_by"]
