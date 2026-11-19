"""Distributor stock-sync dates, from the "TechnoDirect Data - TechnoD Distributors" sheet (CSV export).

Columns used:
- Distributor
- Inventory Updated: the date (M/D/YYYY) the distributor's stock was last updated on the app
- Status: Inventory Live / Inventory Pending / Not onboarded
- Taken By: Manually / CK (Channel Konnect) / ZOHO
- Frequency: how often the stock is updated

This date is the distributor's stock sync date everywhere (analytics/stocksync.py). The inventory import time is
only a fallback for distributors that are not in the sheet. Sheet names are matched by name/alias. A new spelling
is added to the distributor's aliases, following the "map incoming files automatically" rule.
"""
import csv
import datetime as dt
import hashlib
import logging
import os
import re

log = logging.getLogger(__name__)

# sheet short names that are not a prefix/alias of the master name (seen 2026-11-18)
KNOWN = {"bkentps": "BK Enterprises", "savo": "Savo Investments"}


def parse_date(raw):
    s = (raw or "").strip()
    for fmt in ("%m/%d/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def file_signature(path):
    st = os.stat(path)
    return hashlib.sha1(f"{os.path.basename(path)}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()


def normalize_rows(rows):
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in rows]


def import_file(path):
    """The sheet's CSV export -> import_rows."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return import_rows(normalize_rows(list(csv.DictReader(fh))))


def import_rows(rows):
    """Update stock_updated_on / inventory_status / stock_upload_mode / stock_update_frequency from the sheet rows
    (normalised headers): the live Google Sheet or the CSV export. Returns a report."""
    from analytics.cache import bump_cache_version
    from ingestion.normalize import norm
    from warehouse.models import Distributor

    dists = list(Distributor.objects.all())
    index = {}
    for d in dists:
        for x in [d.name, d.code, *(d.aliases or [])]:
            if x:
                index.setdefault(norm(x), d)
    by_name = {d.name: d for d in dists}
    updated, unmatched, aliased, seen = [], [], [], set()
    for r in rows:
        name = r.get("distributor", "")
        if not name:
            continue
        n = norm(name)
        d = index.get(n) or by_name.get(KNOWN.get(n, ""))
        if d is None:  # unique prefix match ("Kumar" -> "Kumar Enterprises")
            cands = [x for x in dists if norm(x.name).startswith(n) and len(n) >= 4]
            d = cands[0] if len(cands) == 1 else None
        if d is None:
            unmatched.append(name)
            continue
        if d.id in seen:
            continue
        seen.add(d.id)
        if n not in {norm(x) for x in [d.name, d.code, *(d.aliases or [])] if x}:
            d.aliases = [*(d.aliases or []), name]
            aliased.append(f"{name} -> {d.name}")
        d.stock_updated_on = parse_date(r.get("inventory updated"))
        d.inventory_status = r.get("status", "")[:32]
        d.stock_upload_mode = re.sub(r"\s+", " ", r.get("taken by", ""))[:32]
        d.stock_update_frequency = r.get("frequency", "")[:32]
        d.save(update_fields=["aliases", "stock_updated_on", "inventory_status", "stock_upload_mode",
                              "stock_update_frequency", "updated_at"])
        updated.append(d.name)
    bump_cache_version()
    return {"rows": len(rows), "updated": len(updated), "unmatched": unmatched, "aliases_added": aliased,
            "latest": max((d.stock_updated_on for d in Distributor.objects.exclude(stock_updated_on=None)), default=None)}


def refresh_if_changed(path=None, triggered_by="schedule"):
    """Scheduled refresh step: re-import when the sheet export changed."""
    from django.conf import settings
    from django.utils import timezone

    from ingestion.models import SyncRun, SyncWatermark

    from ingestion import gsheets

    url = getattr(settings, "DISTRIBUTOR_SYNC_SHEET_URL", "")
    if not path and url and gsheets.configured():
        # the live Google Sheet (the CSV file is not used)
        try:
            rows = normalize_rows(gsheets.read_table(url))
        except Exception as exc:  # noqa: BLE001 - the previous import stays on the dashboard
            run = SyncRun.objects.create(source="distributor_sync", status="failed", triggered_by=triggered_by,
                                         error=f"Google Sheet: {exc}"[:4000], finished_at=timezone.now())
            return {"source": "distributor_sync", "status": "failed", "rows": 0, "run_id": run.pk}
        sig, via = "gs:" + gsheets.signature(rows), "google_sheet"

        def load():
            return import_rows(rows)
    else:
        path = path or getattr(settings, "DISTRIBUTOR_SYNC_SHEET", "")
        if not path or not os.path.isfile(path):
            return {"source": "distributor_sync", "status": "not_configured", "rows": 0, "run_id": None}
        sig, via = file_signature(path), "file"

        def load():
            return import_file(path)
    wm = SyncWatermark.objects.filter(key="distributor_sync:file").first()
    if wm and wm.cursor == sig:
        return {"source": "distributor_sync", "status": "skipped", "rows": 0, "run_id": None}
    run = SyncRun.objects.create(source="distributor_sync", status="running", triggered_by=triggered_by)
    try:
        rep = load()
        run.status, run.rows = "success", rep["updated"]
        run.details = {k: (str(v) if k == "latest" else v) for k, v in rep.items()}
        run.details["via"] = via
        SyncWatermark.put("distributor_sync:file", timezone.now(), cursor=sig)
    except Exception as exc:  # noqa: BLE001
        log.exception("Distributor sync sheet import failed")
        run.status, run.error = "failed", str(exc)[:4000]
    run.finished_at = timezone.now()
    run.save()
    return {"source": "distributor_sync", "status": run.status, "rows": run.rows, "run_id": run.pk}
