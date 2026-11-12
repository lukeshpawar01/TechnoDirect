"""Refresh schedule helpers (SYNC_TIMES, IST) and freshness evaluation."""
import datetime as dt

from django.conf import settings
from django.utils import timezone

REFRESH_SOURCE = "refresh_all"


def _slot(day, hm):
    return timezone.make_aware(dt.datetime.combine(day, dt.time(hm[0], hm[1])))


def last_scheduled(now=None):
    """Most recent scheduled refresh slot <= now."""
    now = timezone.localtime(now or timezone.now())
    for back in range(0, 3):
        day = now.date() - dt.timedelta(days=back)
        slots = [s for s in (_slot(day, hm) for hm in settings.SYNC_TIMES) if s <= now]
        if slots:
            return max(slots)
    return None


def next_scheduled(now=None):
    now = timezone.localtime(now or timezone.now())
    for fwd in range(0, 3):
        day = now.date() + dt.timedelta(days=fwd)
        slots = [s for s in (_slot(day, hm) for hm in settings.SYNC_TIMES) if s > now]
        if slots:
            return min(slots)
    return None


def seconds_until_next_refresh(now=None):
    nxt = next_scheduled(now)
    if not nxt:
        return 12 * 3600
    return max(60, int((nxt - (now or timezone.now())).total_seconds()))


def evaluate_status(last_run, last_success, now=None):
    """ok | stale | failed for a source (or the overall refresh).

    failed: the most recent run errored.
    stale : the latest scheduled slot passed > REFRESH_GRACE_MINUTES ago without a
            successful run since it (or there has never been a success).
    ok    : otherwise.
    """
    now = now or timezone.now()
    if last_run is not None and last_run.status == "failed":
        return "failed"
    if last_success is None:
        return "stale"
    slot = last_scheduled(now)
    if slot and last_success.finished_at and last_success.finished_at < slot:
        if now - slot > dt.timedelta(minutes=settings.REFRESH_GRACE_MINUTES):
            return "stale"
    return "ok"
