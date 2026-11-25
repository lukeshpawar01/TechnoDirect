"""Automatic data refresh built into the web server - works wherever the dashboard runs (runserver on a laptop,
the Windows server, gunicorn on Render, ...). No Task Scheduler, cron, Celery or Redis needed.

A background thread starts with the web server (technodirect/wsgi.py, serve.py) and once a minute checks:
  * refresh   - the latest SYNC_TIMES slot (default 10:30 and 15:30 IST) has passed with no refresh started since
                -> `scheduled_refresh` (Supabase TD data, BlueOrigin from Dropbox, the other sources, derived tables)
  * forecast  - from the 27th, 11:00 IST: next month's suggested targets don't exist yet -> TD Target Forecaster
Because it compares with what already ran (in the database), a server that was off or asleep at 10:30 catches up as
soon as it starts, and several server processes (gunicorn workers) never run the same job twice: the import lock
(ingestion/locks.py) lets one through and the others then see the run in the database.

AUTO_REFRESH=false in .env turns it off (e.g. a second server pointed at the same database).
"""
import datetime as dt
import io
import logging
import threading
import time

from django.conf import settings
from django.db import connections
from django.utils import timezone

log = logging.getLogger(__name__)

CHECK_EVERY = 60  # seconds
FIRST_CHECK_AFTER = 30  # let the server finish starting
RETRY_AFTER = dt.timedelta(minutes=30)  # a job that just failed or was skipped is not retried every minute
FORECAST_DAY, FORECAST_HOUR = 27, 11

_started = False
_start_lock = threading.Lock()
_last_attempt = {}


def refresh_due(now=None):
    """The scheduled slot that still needs its refresh, or None."""
    from ingestion.models import SyncRun
    from ingestion.schedule import REFRESH_SOURCE, last_scheduled

    slot = last_scheduled(now)
    if slot is None:
        return None
    # a Supabase-only import (supabase_live) is not the full refresh. Filtered in Python: a JSON-key exclude would also
    # drop runs that have no "via" at all (SQL NULL)
    runs = SyncRun.objects.filter(source=REFRESH_SOURCE, started_at__gte=slot).values_list("details", flat=True)
    ran = any((d or {}).get("via") != "supabase_live" for d in runs)
    return None if ran else slot


def forecast_due(now=None):
    """First day of the month to forecast when it is due (27th, 11:00 IST onwards, not yet stored), else None."""
    from warehouse.models import TargetForecast

    now = timezone.localtime(now or timezone.now())
    if now.day < FORECAST_DAY or (now.day == FORECAST_DAY and now.hour < FORECAST_HOUR):
        return None
    month = (now.date().replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    return None if TargetForecast.objects.filter(month=month).exists() else month


def mis_due(now=None):
    """Today's MIS email is due: recipients set, not sent today, and a refresh succeeded today."""
    from analytics import daily_mis
    from ingestion.models import SyncRun
    from ingestion.schedule import REFRESH_SOURCE

    today = timezone.localtime(now or timezone.now()).date()
    if not daily_mis.due(today):
        return False
    start = timezone.make_aware(dt.datetime.combine(today, dt.time.min))
    return SyncRun.objects.filter(source=REFRESH_SOURCE, status="success", finished_at__gte=start).exists()


def _attempt(job, now, every=RETRY_AFTER):
    last = _last_attempt.get(job)
    if last and now - last < every:
        return False
    _last_attempt[job] = now
    return True


EDITS_BACKUP_EVERY = dt.timedelta(minutes=15)
# finance edits the settlement tracker all day: re-read it this often (imported only when it changed)
SETTLEMENT_SHEET_EVERY = dt.timedelta(minutes=30)


def tick(now=None):
    """One check: run whatever is due. Returns the jobs started (for tests and the log)."""
    from django.core.management import call_command

    from ingestion import edit_store

    now = now or timezone.now()
    done = []
    # dashboard edits -> Supabase (only changed rows; also catches changes made by commands, not just the API)
    if edit_store.configured() and _attempt("edits-backup", now, EDITS_BACKUP_EVERY):
        try:
            res = edit_store.push()
            if res["sent"] or res["deleted"]:
                done.append("edits-backup")
        except Exception:  # noqa: BLE001 - Supabase unreachable: the refresh below still runs; retried in 15 min
            log.exception("edits backup failed")
    slot = refresh_due(now)
    if slot and _attempt(f"refresh:{slot.isoformat()}", now):
        log.info("auto refresh: running the %s refresh", timezone.localtime(slot).strftime("%H:%M"))
        out = io.StringIO()
        call_command("scheduled_refresh", stdout=out)
        log.info("auto refresh: %s", out.getvalue().strip()[-500:])
        done.append("refresh")
    # daily MIS email: once a day, after the day's first successful refresh (only when MIS_RECIPIENTS is set)
    if slot is None and mis_due(now) and _attempt("daily-mis", now):
        from analytics import daily_mis

        try:
            sent = daily_mis.send()
            if sent:
                log.info("daily MIS sent to %s", ", ".join(sent))
                done.append("daily-mis")
        except Exception:  # noqa: BLE001 - retried in 30 min
            log.exception("daily MIS failed")
    if slot is None and _attempt("settlement-sheet", now, SETTLEMENT_SHEET_EVERY):
        from django.conf import settings

        from ingestion import gsheets
        from ingestion.locks import import_lock

        if getattr(settings, "SETTLEMENT_SHEET_URL", "") and gsheets.configured() and not settings.TESTING:
            with import_lock() as got:
                if got:  # never alongside the full refresh
                    try:
                        from masters.settlement import refresh_if_changed

                        res = refresh_if_changed(triggered_by="schedule")
                        if res["status"] == "success":
                            done.append("settlement-sheet")
                    except Exception:  # noqa: BLE001 - retried next time
                        log.exception("settlement sheet refresh failed")
    month = forecast_due(now)
    if month and _attempt(f"forecast:{month.isoformat()}", now):
        from ingestion.locks import import_lock
        from ingestion.tasks import forecast_next_month_targets

        with import_lock() as got:
            if got:
                log.info("auto refresh: forecasting targets for %s", month)
                forecast_next_month_targets()
                done.append("forecast")
    return done


def restore_edits_if_new():
    """A new server (empty database) first gets the dashboard edits back from Supabase, before any import."""
    from ingestion import edit_store

    if edit_store.configured() and edit_store.local_is_empty():
        res = edit_store.restore()
        log.info("new database: restored %s edited records from Supabase", res.get("restored"))


def _loop():
    time.sleep(FIRST_CHECK_AFTER)
    try:
        restore_edits_if_new()
    except Exception:  # noqa: BLE001
        log.exception("restoring the dashboard edits from Supabase failed")
    finally:
        connections.close_all()
    while True:
        try:
            restore_edits_if_new()  # retried every minute until a new server has its edits back
        except Exception:  # noqa: BLE001
            log.exception("restoring the dashboard edits from Supabase failed - will retry")
        finally:
            connections.close_all()
        try:
            tick()
        except Exception:  # noqa: BLE001 - never let the thread die; try again next minute
            log.exception("auto refresh check failed")
        finally:
            connections.close_all()  # this thread's DB connections
        time.sleep(CHECK_EVERY)


def start():
    """Start the background checker once per process (no-op when AUTO_REFRESH is off)."""
    global _started
    if not getattr(settings, "AUTO_REFRESH", True):
        return False
    with _start_lock:
        if _started:
            return False
        _started = True
    threading.Thread(target=_loop, name="td-auto-refresh", daemon=True).start()
    log.info("auto refresh on: data refresh at %s IST",
             ", ".join(f"{h:02d}:{m:02d}" for h, m in settings.SYNC_TIMES))
    return True
