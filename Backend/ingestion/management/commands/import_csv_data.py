"""Import the TechnoDirect CSV exports (customers, products, inventory, sales, loyalty) into the warehouse.

    python manage.py import_csv_data                       # files in data/import/
    python manage.py import_csv_data --dir "C:/exports"     # another folder
    python manage.py import_csv_data --wipe-all             # first time: remove every existing warehouse row
                                                            # (old demo data, demo users, targets, ASMs) first

Re-running with newer exports upserts; admin-maintained mappings and targets are kept.
"""
import datetime as dt
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from analytics.derivations import run_all_derivations
from ingestion.csv_import import CsvImporter
from ingestion.models import SyncRun, SyncWatermark
from ingestion.schedule import REFRESH_SOURCE
from masters.models import ReconciliationRef, ensure_default_metrics
from warehouse.models import (
    Asm,
    Category,
    CrmTicket,
    DataQualityIssue,
    Distributor,
    InventorySnapshot,
    LoyaltyEvent,
    Order,
    OrderLine,
    Payment,
    PendingOrderJob,
    Pincode,
    Product,
    ProductVariant,
    Region,
    Retailer,
    RetailerMonth,
    State,
    Target,
)

IMPORT_SOURCE = "csv_import"
OLD_DEMO_USERS = ["head@technodirect.local", "rm.south2@technodirect.local", "asm.ka@technodirect.local",
                  "heera@technodirect.local"]


class Command(BaseCommand):
    help = "Load the CSV exports into the warehouse (upsert), then rebuild derived tables."

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=str(Path(settings.BASE_DIR) / "data" / "import"),
                            help="Folder holding the TD_*.csv exports (default: data/import)")
        parser.add_argument("--wipe-all", action="store_true",
                            help="Delete ALL warehouse data, targets, ASMs, sync history and the old demo users first")
        parser.add_argument("--source-tz", default="UTC", help="Time zone of the export timestamps (default UTC)")
        parser.add_argument("--snapshot-date", help="Inventory snapshot date YYYY-MM-DD (default: file date)")
        parser.add_argument("--no-derive", action="store_true")

    def handle(self, *args, **o):
        if not Path(o["dir"]).is_dir():
            raise CommandError(f"Folder not found: {o['dir']}")
        snap = dt.date.fromisoformat(o["snapshot_date"]) if o["snapshot_date"] else None
        if o["wipe_all"]:
            self.wipe()
        started = timezone.now()
        run = SyncRun.objects.create(source=IMPORT_SOURCE, status="running", started_at=started,
                                     triggered_by="import_csv_data")
        try:
            result = CsvImporter(o["dir"], o["source_tz"], snap, stdout=self.stdout).run()
        except Exception as exc:
            run.status, run.error, run.finished_at = "failed", str(exc)[:2000], timezone.now()
            run.save()
            raise
        ensure_default_metrics()
        if not o["no_derive"]:
            self.stdout.write("[import] rebuilding retailer aggregates, retailer months, data-quality checks...")
            result["derivations"] = run_all_derivations()
        run.status, run.finished_at = "success", timezone.now()
        run.rows = result["rows"].get("orders", 0) + result["rows"].get("retailers", 0)
        run.details = result
        run.save()
        SyncRun.objects.create(source=REFRESH_SOURCE, status="success", started_at=started,
                               finished_at=timezone.now(), details={"via": IMPORT_SOURCE},
                               triggered_by="import_csv_data")
        for k, v in result["rows"].items():
            self.stdout.write(f"  {k:<26} {v}")
        if result.get("derivations"):
            self.stdout.write(f"  derivations: {result['derivations']}")
        self.stdout.write(self.style.SUCCESS("[import] done."))

    @transaction.atomic
    def wipe(self):
        for m in [DataQualityIssue, RetailerMonth, LoyaltyEvent, Payment, OrderLine, CrmTicket, PendingOrderJob,
                  Order, InventorySnapshot, Target, ReconciliationRef, Retailer, Pincode, ProductVariant, Product,
                  Category, Distributor, Asm, State, Region, SyncRun, SyncWatermark]:
            m.objects.all().delete()
        n = User.objects.filter(email__in=OLD_DEMO_USERS).delete()[0]
        self.stdout.write(f"[import] wiped all warehouse data and {n} old demo user(s)")
