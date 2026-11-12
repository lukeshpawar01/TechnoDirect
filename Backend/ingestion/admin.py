from django.contrib import admin

from .models import SyncRun, SyncWatermark


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = ["source", "status", "started_at", "finished_at", "rows"]
    list_filter = ["source", "status"]


admin.site.register(SyncWatermark)
