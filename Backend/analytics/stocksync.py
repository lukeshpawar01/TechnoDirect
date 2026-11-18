"""A distributor's stock sync date. Used by the Distributors, Inventory and Overview pages.

Source
    The sheet's "Inventory Updated" date (Distributor.stock_updated_on, masters/distributor_sync.py). The inventory
    import time is a fallback, used only when a distributor is not in the sheet.
Rule
    Current = updated within STOCK_SYNC_DAYS calendar days of today; older = stale; no date = never synced.
"""
import datetime as dt

from django.db.models import Max
from django.utils import timezone

STOCK_SYNC_DAYS = 3


def last_sync(dist_ids):
    """{distributor_id: aware datetime} - sheet date (start of that IST day), else latest inventory sync."""
    from warehouse.models import Distributor, primary_inventory

    ids = list(dist_ids)
    tz = timezone.get_current_timezone()
    out = {i: timezone.make_aware(dt.datetime.combine(d, dt.time()), tz)
           for i, d in Distributor.objects.filter(id__in=ids).exclude(stock_updated_on=None)
           .values_list("id", "stock_updated_on")}
    missing = [i for i in ids if i not in out]
    if missing:
        out.update(dict(primary_inventory().filter(distributor_id__in=missing).values("distributor_id")
                        .annotate(m=Max("synced_at")).values_list("distributor_id", "m")))
    return out


def bucket(at, today=None):
    """'fresh' (within STOCK_SYNC_DAYS days) / 'stale' / 'never'."""
    if not at:
        return "never"
    today = today or timezone.localdate()
    day = timezone.localtime(at).date() if isinstance(at, dt.datetime) else at
    return "fresh" if day >= today - dt.timedelta(days=STOCK_SYNC_DAYS) else "stale"


def iso(at):
    return timezone.localtime(at).isoformat() if at else None


def info(d):
    """Sheet details shown next to the sync date."""
    return {"inventory_status": d.inventory_status or None, "stock_upload_mode": d.stock_upload_mode or None,
            "stock_update_frequency": d.stock_update_frequency or None}
