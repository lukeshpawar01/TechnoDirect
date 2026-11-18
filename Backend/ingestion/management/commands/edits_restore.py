"""Load the dashboard's edits (users, targets, ASMs, handovers, mappings, ...) from Supabase into this database.

    python manage.py edits_restore           only into a new database (no users yet) - also automatic on server start
    python manage.py edits_restore --force   overwrite the matching local records with the Supabase copy

Run it after `migrate` and BEFORE creating any user, or use --force.
"""
from django.core.management.base import BaseCommand, CommandError

from ingestion import edit_store


class Command(BaseCommand):
    help = "Restore the dashboard's edits from Supabase"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Overwrite local records even if users exist")

    def handle(self, *args, **opts):
        if not edit_store.configured():
            raise CommandError("SUPABASE_EDITS_USER / SUPABASE_EDITS_PASSWORD are not set in Backend/.env")
        res = edit_store.restore(force=opts["force"])
        if res.get("skipped"):
            self.stdout.write(res["skipped"])
            return
        self.stdout.write(self.style.SUCCESS(f"Restored {res['restored']:,} records from Supabase:"))
        for label, n in res["tables"].items():
            self.stdout.write(f"  {label:<45} {n:,}")
