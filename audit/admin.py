from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Read-only in the back office: the log can be viewed, never edited."""

    list_display = ["created_at", "actor_label", "action", "summary"]
    list_filter = ["action"]
    search_fields = ["summary", "actor_label", "target_label"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
