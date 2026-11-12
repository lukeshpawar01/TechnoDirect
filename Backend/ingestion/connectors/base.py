"""Connector base: watermark handling, SyncRun bookkeeping, not-configured no-op."""
import logging
import traceback

from django.core.cache import cache
from django.utils import timezone

from ingestion.models import SyncRun, SyncWatermark

log = logging.getLogger(__name__)


class NotConfigured(Exception):
    pass


class BaseConnector:
    source = ""
    lock_seconds = 60 * 30

    def is_configured(self) -> bool:
        raise NotImplementedError

    def sync(self, run: SyncRun) -> int:
        """Pull data; return rows written. Implementations update watermarks themselves."""
        raise NotImplementedError

    # -- watermark helpers ---------------------------------------------------
    def watermark(self, entity="default"):
        return SyncWatermark.get(f"{self.source}:{entity}")

    def set_watermark(self, value, entity="default", cursor=""):
        SyncWatermark.put(f"{self.source}:{entity}", value, cursor)

    # -- runner --------------------------------------------------------------
    def run(self, triggered_by="schedule") -> SyncRun:
        run = SyncRun.objects.create(source=self.source, status="running", triggered_by=triggered_by)
        if not self.is_configured():
            run.status = "not_configured"
            run.finished_at = timezone.now()
            run.details = {"message": f"{self.source} credentials are not configured (placeholders in .env)"}
            run.save()
            return run
        lock_key = f"sync-lock:{self.source}"
        if not cache.add(lock_key, run.pk, self.lock_seconds):
            run.status = "skipped"
            run.finished_at = timezone.now()
            run.details = {"message": "another sync of this source is running"}
            run.save()
            return run
        try:
            rows = self.sync(run)
            run.rows = rows or 0
            run.status = "success"
        except NotConfigured as exc:
            run.status = "not_configured"
            run.details = {**run.details, "message": str(exc)}
        except Exception as exc:  # noqa: BLE001
            log.exception("sync %s failed", self.source)
            run.status = "failed"
            run.error = f"{exc}\n{traceback.format_exc()[-4000:]}"
        finally:
            cache.delete(lock_key)
            run.finished_at = timezone.now()
            run.save()
        return run
