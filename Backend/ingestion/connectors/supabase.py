"""Live TD data from Supabase (project "technosport") -> warehouse.

Supabase holds the ID-keyed TD tables (orders, sales, customers, distributors, products, inventory_snapshot,
loyalty_ledger). Each sync reads them through the read-only login and runs the TD mapping on the rows, so every
number is computed
exactly as before (ingestion/td_import.py).

Supabase's own loader records each table's last refresh in etl_watermark. When that hasn't changed since our last
import, the sync is skipped (details.unchanged) - so it can run every 30 minutes cheaply.
"""
import datetime as dt
import logging
from decimal import Decimal

from django.conf import settings
from django.db import connections
from django.utils import timezone

from ingestion.models import SyncWatermark
from ingestion.td_import import TdImporter

from . import supabase_queries as Q
from .base import BaseConnector

log = logging.getLogger(__name__)
ETL_KEY = "supabase:etl"


def as_text(v):
    """A Postgres value -> the text form the TD mapping parses (ISO dates, true/false, plain decimals)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, dt.datetime):
        if v.tzinfo is not None:
            v = v.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return v.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return format(v, "f")
    return str(v).strip()


def fetch(sql):
    """(column names, rows) from the Supabase database."""
    with connections["supabase"].cursor() as cur:
        cur.execute(sql)
        return [c[0] for c in cur.description], cur.fetchall()


class SupabaseTdImporter(TdImporter):
    """The TD mapping, reading the Supabase tables."""

    def __init__(self, fetch_fn=fetch, source_tz="UTC", stdout=None):
        super().__init__(source_tz, stdout)
        self.fetch = fetch_fn

    def read_rows(self):
        data, self.sources = {}, {}
        for kind, (table, _cols) in Q.TABLES.items():
            cols, rows = self.fetch(Q.select_sql(kind))
            data[kind] = [{c: as_text(v) for c, v in zip(cols, r)} for r in rows]
            self.sources[kind] = f"supabase:{table} ({len(rows):,} rows)"
        self.inventory_synced_at = timezone.now()
        return data


class SupabaseConnector(BaseConnector):
    source = "supabase"

    def is_configured(self):
        return "supabase" in settings.DATABASES

    @staticmethod
    def etl_state(fetch_fn=fetch):
        """(signature, latest refresh) of Supabase's own loader, or ("", None) when etl_watermark is unreadable."""
        try:
            _cols, rows = fetch_fn(Q.ETL_CHANGED_SQL)
        except Exception as exc:  # noqa: BLE001 - no bookkeeping table: always import
            log.warning("Supabase etl_watermark unreadable (%s): importing anyway", type(exc).__name__)
            return "", None
        latest, earliest, n = rows[0]
        if not latest:
            return "", None
        return f"{as_text(latest)}|{as_text(earliest)}|{n}", latest

    def sync(self, run, fetch_fn=fetch):
        from masters.models import ensure_default_metrics

        sig, latest = self.etl_state(fetch_fn)
        wm = SyncWatermark.objects.filter(key=ETL_KEY).first()
        refreshed = timezone.localtime(latest).isoformat(timespec="seconds") if latest else None
        if sig and wm and wm.cursor == sig:
            run.details = {"unchanged": True, "supabase_refreshed_at": refreshed,
                           "message": "No new data in Supabase since the last import"}
            return 0
        result = SupabaseTdImporter(fetch_fn).run()
        ensure_default_metrics()
        run.details = {"rows": result["rows"], "tables": result["files"], "warnings": result["warnings"][:20],
                       "supabase_refreshed_at": refreshed}
        SyncWatermark.put(ETL_KEY, timezone.now(), cursor=sig)
        return result["rows"].get("orders", 0) + result["rows"].get("retailers", 0)
