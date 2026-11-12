from django.db import models
from django.utils import timezone

SOURCES = ["medusa", "payu", "google_sheets", "channel_konnect"]


class SyncRun(models.Model):
    STATUS = [
        ("running", "Running"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("not_configured", "Not configured"),
        ("skipped", "Skipped"),
    ]
    source = models.CharField(max_length=32, db_index=True)
    status = models.CharField(max_length=16, choices=STATUS, default="running", db_index=True)
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    rows = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    details = models.JSONField(default=dict, blank=True)
    triggered_by = models.CharField(max_length=254, blank=True, default="schedule")

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["source", "status", "-started_at"])]


class SyncWatermark(models.Model):
    """High-water mark per source / entity (e.g. 'medusa:orders')."""

    key = models.CharField(max_length=64, unique=True)
    value = models.DateTimeField(null=True, blank=True)
    cursor = models.CharField(max_length=255, blank=True, help_text="Opaque cursor if a source needs one")
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get(cls, key):
        wm = cls.objects.filter(key=key).first()
        return wm.value if wm else None

    @classmethod
    def put(cls, key, value, cursor=""):
        cls.objects.update_or_create(key=key, defaults={"value": value, "cursor": cursor})
