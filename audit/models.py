from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models
from django.utils.translation import gettext_lazy as _


class AuditEvent(models.Model):
    """
    One entry in the activity log: who did what, to which record, and when.

    Entries are permanent. They cannot be edited or deleted, through the
    site or the back office, so the log can be trusted.
    """

    created_at = models.DateTimeField(_("when"), auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("who"),
        null=True,
        blank=True,
        on_delete=models.PROTECT,  # people with history are deactivated, never deleted
        related_name="audit_events",
    )
    # A copy of the person's name at the time, in case it changes later.
    actor_label = models.CharField(max_length=255, blank=True)
    action = models.CharField(_("action"), max_length=64, db_index=True)
    summary = models.CharField(_("summary"), max_length=500)
    target_type = models.CharField(max_length=50, blank=True)
    target_id = models.CharField(max_length=50, blank=True)
    target_label = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["target_type", "target_id"])]
        verbose_name = _("activity log entry")
        verbose_name_plural = _("activity log")

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_label}: {self.summary}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionDenied("Activity log entries cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Activity log entries cannot be deleted.")
