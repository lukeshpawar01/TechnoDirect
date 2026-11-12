"""Celery tasks. Production schedule: `refresh_all` at SYNC_TIMES (default 10:00 & 18:00 IST)."""
import logging

from celery import shared_task
from django.utils import timezone

from .connectors import CONNECTORS, get_connector
from .models import SyncRun
from .schedule import REFRESH_SOURCE

log = logging.getLogger(__name__)


def _run_source(source, triggered_by):
    try:
        run = get_connector(source).run(triggered_by=triggered_by)
        return {"source": source, "status": run.status, "rows": run.rows, "run_id": run.pk}
    except Exception as exc:  # noqa: BLE001 – a failed step must never block the chain
        log.exception("source %s crashed", source)
        run = SyncRun.objects.create(source=source, status="failed", error=str(exc)[:4000],
                                     finished_at=timezone.now(), triggered_by=triggered_by)
        return {"source": source, "status": "failed", "rows": 0, "run_id": run.pk}


def refresh_all_inline(triggered_by="schedule"):
    """Medusa -> PayU -> CRM sheet -> Channel Konnect -> derivations -> cache invalidation.

    Every step is logged as its own SyncRun; the umbrella run (source='refresh_all')
    is 'success' unless a step failed.
    """
    from analytics.cache import bump_cache_version
    from analytics.derivations import run_all_derivations

    umbrella = SyncRun.objects.create(source=REFRESH_SOURCE, status="running", triggered_by=triggered_by)
    steps = [_run_source(s, triggered_by) for s in CONNECTORS]

    deriv = SyncRun.objects.create(source="derivations", status="running", triggered_by=triggered_by)
    try:
        deriv.details = run_all_derivations()
        deriv.status = "success"
    except Exception as exc:  # noqa: BLE001
        log.exception("derivations failed")
        deriv.status, deriv.error = "failed", str(exc)[:4000]
    deriv.finished_at = timezone.now()
    deriv.save()
    steps.append({"source": "derivations", "status": deriv.status, "rows": 0, "run_id": deriv.pk})

    bump_cache_version()
    failed = [s["source"] for s in steps if s["status"] == "failed"]
    umbrella.status = "failed" if failed else "success"
    umbrella.error = f"Failed steps: {', '.join(failed)}" if failed else ""
    umbrella.rows = sum(s["rows"] for s in steps)
    umbrella.details = {"steps": steps}
    umbrella.finished_at = timezone.now()
    umbrella.save()
    return {"status": umbrella.status, "steps": steps, "run_id": umbrella.pk}


def run_single_inline(source, triggered_by="manual"):
    from analytics.cache import bump_cache_version
    from analytics.derivations import run_all_derivations

    res = _run_source(source, triggered_by)
    if res["status"] == "success" and source in ("medusa", "payu"):
        run_all_derivations()
    bump_cache_version()
    return res


@shared_task(name="ingestion.tasks.refresh_all")
def refresh_all(triggered_by="schedule"):
    return refresh_all_inline(triggered_by)


@shared_task(name="ingestion.tasks.sync_source")
def sync_source(source, triggered_by="manual"):
    if source == "all":
        return refresh_all_inline(triggered_by)
    return run_single_inline(source, triggered_by)
