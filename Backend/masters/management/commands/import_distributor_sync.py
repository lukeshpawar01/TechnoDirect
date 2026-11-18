"""Import distributor stock-sync dates from the "TechnoD Distributors" sheet. See masters/distributor_sync.py."""
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Import 'TechnoDirect Data - TechnoD Distributors.csv' (Inventory Updated = stock sync date)"

    def add_arguments(self, parser):
        parser.add_argument("--file", default="", help="Sheet CSV (default: .env DISTRIBUTOR_SYNC_SHEET)")

    def handle(self, *args, **opts):
        from django.utils import timezone

        from ingestion.models import SyncWatermark
        from masters.distributor_sync import file_signature, import_file

        path = opts["file"] or getattr(settings, "DISTRIBUTOR_SYNC_SHEET", "")
        if not path:
            raise CommandError("Pass --file or set DISTRIBUTOR_SYNC_SHEET in .env")
        rep = import_file(path)
        SyncWatermark.put("distributor_sync:file", timezone.now(), cursor=file_signature(path))
        self.stdout.write(json.dumps(rep, indent=2, default=str, ensure_ascii=False))
