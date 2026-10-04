"""Back-office (fallback) screens. Day-to-day work happens at /manage/, which also logs every change."""

from django.contrib import admin

from .models import Match, Stage, TimeProposal


@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = ["name", "competition", "format", "division", "is_published"]
    list_filter = ["format", "is_published"]


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ["number", "stage", "round_label", "home", "away", "scheduled_at", "status"]
    list_filter = ["stage", "status"]


@admin.register(TimeProposal)
class TimeProposalAdmin(admin.ModelAdmin):
    list_display = ["match", "proposed_time", "proposing_team", "status", "created_at"]
    list_filter = ["status"]
