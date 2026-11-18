"""The 10:00 / 18:00 refresh for the single-server (Windows) setup, run by Task Scheduler (deploy/windows).

1. If the app exports in TD_EXPORT_DIR (Order_Data.csv, Customer_Data.csv, ...) changed since the last run, they are
   re-imported with `import_csv_data`, which ends with the full refresh chain.
2. Otherwise only the refresh chain runs (`run_sync all`). It re-imports the BlueOrigin sheets, the settlement
   tracker and the distributor sync sheet when their files changed, and then rebuilds the derived tables.

A lock file stops two runs overlapping (e.g. a manual run during the scheduled one).
"""
import hashlib
import os
import time
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

EXPORTS = ["Order_Data.csv", "Customer_Data.csv", "Sales_Data.csv", "Product_Data.csv", "Inventory_Data.csv",
           "Distributor_Data.csv", "Loyality_Data.csv"]
LOCK_MAX_AGE = 3 * 3600  # a lock older than this is from a crashed run


def exports_signature(folder):
    h = hashlib.sha1()
    found = 0
    for name in EXPORTS:
        p = Path(folder) / name
        if p.is_file():
            st = p.stat()
            h.update(f"{name}|{st.st_size}|{int(st.st_mtime)}".encode())
            found += 1
    return h.hexdigest() if found else ""


class Command(BaseCommand):
    help = "Scheduled refresh: re-import changed app exports (TD_EXPORT_DIR), then run the refresh chain"

    def add_arguments(self, parser):
        parser.add_argument("--force-import", action="store_true", help="Re-import the exports even if unchanged")

    def handle(self, *args, **opts):
        from django.utils import timezone

        from ingestion.models import SyncWatermark
        from ingestion.tasks import refresh_all_inline

        lock = Path(settings.BASE_DIR) / "data" / "scheduled_refresh.lock"
        if lock.exists() and time.time() - lock.stat().st_mtime < LOCK_MAX_AGE:
            self.stdout.write("Another refresh is running - skipped.")
            return
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(str(os.getpid()))
        try:
            folder = settings.TD_EXPORT_DIR
            sig = exports_signature(folder) if folder and os.path.isdir(folder) else ""
            wm = SyncWatermark.objects.filter(key="td_exports:files").first()
            if sig and (opts["force_import"] or not wm or wm.cursor != sig):
                self.stdout.write(f"App exports changed - importing from {folder}")
                call_command("import_csv_data", dir=folder)  # ends with refresh_all
                SyncWatermark.put("td_exports:files", timezone.now(), cursor=sig)
            else:
                self.stdout.write("App exports unchanged - running the refresh chain")
                self.stdout.write(str(refresh_all_inline(triggered_by="schedule")))
        finally:
            lock.unlink(missing_ok=True)
