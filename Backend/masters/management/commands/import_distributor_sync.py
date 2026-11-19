"""Import distributor stock-sync dates from the "TechnoD Distributors" sheet. See masters/distributor_sync.py.

    python manage.py import_distributor_sync                 from the live Google Sheet, else the copy in Supabase
    python manage.py import_distributor_sync --file x.csv    a one-off import of a CSV export
"""
import json

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Import the TechnoD Distributors sheet (Inventory Updated = stock sync date)"

    def add_arguments(self, parser):
        parser.add_argument("--file", default="", help="Sheet CSV (default: the live Google Sheet, else the copy in Supabase)")

    def handle(self, *args, **opts):
        from django.utils import timezone

        from ingestion.models import SyncWatermark
        from masters.distributor_sync import file_signature, import_file, refresh_if_changed

        if not opts["file"]:
            step = refresh_if_changed(triggered_by="manual", force=True)
            if step["status"] == "not_configured":
                raise CommandError("No source: set DISTRIBUTOR_SYNC_SHEET_URL (Google) or upload the sheet to Supabase "
                                   "(reference_sheet upload distributor_sync <file>), or pass --file")
            self.stdout.write(json.dumps(step, indent=2))
            return
        rep = import_file(opts["file"])
        SyncWatermark.put("distributor_sync:file", timezone.now(), cursor=file_signature(opts["file"]))
        self.stdout.write(json.dumps(rep, indent=2, default=str, ensure_ascii=False))
