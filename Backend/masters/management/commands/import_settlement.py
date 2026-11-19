"""Import the finance team's distributor settlement tracker (full rebuild). See masters/settlement.py.

    python manage.py import_settlement                 from the live Google Sheet
    python manage.py import_settlement --file x.csv    a one-off import of a CSV export
"""
import json

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Import the distributor settlement tracker (live Google Sheet / --file)"

    def add_arguments(self, parser):
        parser.add_argument("--file", default="", help="Tracker CSV (default: the live Google Sheet)")

    def handle(self, *args, **opts):
        from masters.settlement import file_signature, import_file, refresh_if_changed

        if not opts["file"]:
            step = refresh_if_changed(triggered_by="manual", force=True)
            if step["status"] == "not_configured":
                raise CommandError("Not configured: set SETTLEMENT_SHEET_URL and GOOGLE_SERVICE_ACCOUNT_JSON in .env, "
                                   "or pass --file")
            self.stdout.write(json.dumps(step, indent=2))
            return
        rep = import_file(opts["file"])
        try:  # remember the file so the scheduled refresh does not re-import it unchanged
            from django.utils import timezone

            from ingestion.models import SyncWatermark

            SyncWatermark.put("settlement:file", timezone.now(), cursor=file_signature(opts["file"]))
        except Exception:  # noqa: BLE001
            pass
        self.stdout.write(json.dumps(rep, indent=2, ensure_ascii=False))
