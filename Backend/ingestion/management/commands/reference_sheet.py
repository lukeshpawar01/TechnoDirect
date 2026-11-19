"""Fixed sheets kept in Supabase (schema `reference`). See ingestion/reference_sheets.py.

    python manage.py reference_sheet upload <name> <file.csv|.tsv|.xlsx> [--columns "A,B"]   store / replace a sheet
    python manage.py reference_sheet list                                  what is stored
    python manage.py reference_sheet download <name> [--to file]           get it back as a file

Then any importer reads it from Supabase:  python manage.py import_sales_team supabase:sales_team
"""
import shutil

from django.core.management.base import BaseCommand, CommandError

from ingestion import reference_sheets as R


class Command(BaseCommand):
    help = "Store fixed sheets in Supabase (schema reference) and read them back"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["upload", "list", "download"])
        parser.add_argument("name", nargs="?")
        parser.add_argument("file", nargs="?")
        parser.add_argument("--to", default="", help="download: where to save the file")
        parser.add_argument("--columns", default="",
                            help='upload: keep only these columns, comma-separated (e.g. leave out phone / email / address)')
        parser.add_argument("--formulas", action="store_true",
                            help="upload a workbook with its formulas as text (=G4-G5) instead of the calculated values")

    def handle(self, *args, **o):
        if not R.configured():
            raise CommandError("SUPABASE_EDITS_USER / SUPABASE_EDITS_PASSWORD are not set in Backend/.env")
        try:
            if o["action"] == "upload":
                if not o["name"] or not o["file"]:
                    raise CommandError("upload needs a name and a file")
                cols = [c for c in o["columns"].split(",") if c.strip()] or None
                for part in R.upload(o["name"], o["file"], columns=cols, formulas=o["formulas"]):
                    self.stdout.write(f"  {part['table']:<55} {part['rows']:>6,} rows" + (f"  (tab {part['tab']})" if part["tab"] else ""))
                self.stdout.write(self.style.SUCCESS(f"Stored '{o['name']}' in Supabase. Importers can now read supabase:{o['name']}"))
            elif o["action"] == "list":
                rows = R.SupabaseReference().catalog()
                if not rows:
                    self.stdout.write("Nothing stored yet.")
                for r in rows:
                    tab = f" / tab {r['tab']}" if r["tab"] else ""
                    self.stdout.write(f"  {r['name']:<28}{tab:<26} {r['rows']:>6,} rows  from {r['source_file']}  "
                                      f"({r['loaded_at']:%Y-%m-%d %H:%M})")
            else:
                if not o["name"]:
                    raise CommandError("download needs a name")
                path = R.to_local_file(o["name"])
                if o["to"]:
                    shutil.move(path, o["to"])
                    path = o["to"]
                self.stdout.write(self.style.SUCCESS(f"Saved {path}"))
        except R.ReferenceError as exc:
            raise CommandError(str(exc)) from None
