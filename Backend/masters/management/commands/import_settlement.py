"""Import the finance team's distributor settlement tracker (full rebuild). See masters/settlement.py."""
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Import 'Technodirect Order Tracking - Tracker.csv' (distributor settlements)"

    def add_arguments(self, parser):
        parser.add_argument("--file", default="", help="Tracker CSV (default: .env SETTLEMENT_TRACKER)")

    def handle(self, *args, **opts):
        from masters.settlement import file_signature, import_file

        path = opts["file"] or getattr(settings, "SETTLEMENT_TRACKER", "")
        if not path:
            raise CommandError("Pass --file or set SETTLEMENT_TRACKER in .env")
        rep = import_file(path)
        try:  # remember the file so the scheduled refresh does not re-import it unchanged
            from django.utils import timezone

            from ingestion.models import SyncWatermark

            SyncWatermark.put("settlement:file", timezone.now(), cursor=file_signature(path))
        except Exception:  # noqa: BLE001
            pass
        self.stdout.write(json.dumps(rep, indent=2, ensure_ascii=False))
