"""Back up the dashboard's edits (users, targets, ASMs, handovers, mappings, ...) to Supabase now.

    python manage.py edits_backup          send what changed (normally automatic: after each edit and every 15 min)
    python manage.py edits_backup --sql    print the Supabase setup SQL (one schema per dashboard module, login)
    python manage.py edits_backup --check  connection test: records per module table in Supabase
"""
from django.core.management.base import BaseCommand, CommandError

from ingestion import edit_store


class Command(BaseCommand):
    help = "Back up the dashboard's edits to Supabase (or print the setup SQL with --sql)"

    def add_arguments(self, parser):
        parser.add_argument("--sql", action="store_true", help="Print the Supabase setup SQL")
        parser.add_argument("--check", action="store_true", help="Test the connection, change nothing")

    def handle(self, *args, **opts):
        if opts["sql"]:
            self.stdout.write(edit_store.setup_sql())
            return
        if not edit_store.configured():
            raise CommandError("SUPABASE_EDITS_USER / SUPABASE_EDITS_PASSWORD are not set in Backend/.env "
                               "(run deploy/supabase_edits.sql in Supabase first).")
        try:
            if opts["check"]:
                counts = edit_store.SupabaseState().counts()
                self.stdout.write(self.style.SUCCESS(f"Connected. {sum(counts.values()):,} edited records in Supabase:"))
                for name, n in counts.items():
                    self.stdout.write(f"  {name:<45} {n:,}")
                return
            res = edit_store.push()
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Supabase: {type(exc).__name__}: {str(exc).splitlines()[0][:300]}") from None
        self.stdout.write(self.style.SUCCESS(f"Backed up: {res['sent']:,} changed records sent, "
                                             f"{res['deleted']:,} deleted."))
        for name, n in res["tables"].items():
            self.stdout.write(f"  {name:<45} {n:,}")
        for name, err in res.get("errors", {}).items():
            self.stdout.write(self.style.ERROR(f"  NOT SAVED {name}: {err}"))
        if res.get("errors"):
            self.stdout.write("Run deploy/supabase_edits.sql again in Supabase > SQL Editor (it adds new module folders).")
