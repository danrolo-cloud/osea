"""Back-office (fallback) screens. Day-to-day work happens at /manage/, which also logs every change."""

from django.contrib import admin

from .models import Competition, Division, Game, Registration, RosterChange, RosterEntry


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ["name", "gamer_tag_label", "is_active"]


class DivisionInline(admin.TabularInline):
    model = Division
    extra = 0


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ["name", "game", "school_year", "registration_opens_at", "registration_closes_at", "is_published"]
    list_filter = ["game", "school_year", "is_published"]
    inlines = [DivisionInline]


class RosterEntryInline(admin.TabularInline):
    model = RosterEntry
    extra = 0


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ["team_name", "school", "competition", "status", "division"]
    list_filter = ["competition", "status"]
    search_fields = ["team_name", "school__name"]
    inlines = [RosterEntryInline]


@admin.register(RosterChange)
class RosterChangeAdmin(admin.ModelAdmin):
    list_display = ["registration", "player_in", "player_out", "status", "requested_at"]
    list_filter = ["status"]
