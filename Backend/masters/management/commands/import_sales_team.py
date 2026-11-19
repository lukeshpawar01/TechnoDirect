"""Load the sales hierarchy (RSM -> ASM -> field staff) from the HR Master ASM Tracker. See masters/sales_team.py."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from analytics.cache import bump_cache_version
from masters.sales_team import import_sales_team


class Command(BaseCommand):
    help = "Import RSMs, ASM -> RSM reporting lines and field staff from the Master ASM Tracker CSV."

    def add_arguments(self, parser):
        parser.add_argument("file", help="CSV / xlsx path, or supabase:<name> (a sheet stored with reference_sheet upload)")
        parser.add_argument("--dry-run", action="store_true", help="Show the matching without saving")

    def handle(self, *args, **o):
        from ingestion.reference_sheets import command_file

        o["file"] = command_file(o["file"])  # a file path, or supabase:<name> = the copy stored in Supabase
        if not Path(o["file"]).is_file():
            raise CommandError(f"File not found: {o['file']}")
        res = import_sales_team(o["file"], dry_run=o["dry_run"])
        for line in res.pop("log"):
            self.stdout.write("  " + line)
        for k, v in res.items():
            self.stdout.write(f"  {k:<28} {v}")
        if o["dry_run"]:
            self.stdout.write("dry run: nothing saved")
            return
        bump_cache_version()
        self.stdout.write(self.style.SUCCESS("[sales team] done."))
