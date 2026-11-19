"""Check the sheet connections - nothing is imported or changed.

    python manage.py sheets_check

* Google service account: key file present, the email to share the live sheets with.
* Live sheets (SETTLEMENT_SHEET_URL, DISTRIBUTOR_SYNC_SHEET_URL): readable? rows, and the columns the importer needs.
* Fixed sheets stored in Supabase (schema reference).
Prints counts and column names only, never the sheet contents.
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from ingestion import gsheets, reference_sheets

LIVE = [
    ("Settlement tracker", "SETTLEMENT_SHEET_URL", "SETTLEMENT_SHEET_TAB", ["order id", "distributor", "order value"]),
    ("TechnoD Distributors", "DISTRIBUTOR_SYNC_SHEET_URL", "DISTRIBUTOR_SYNC_SHEET_TAB", ["distributor", "inventory updated"]),
]


class Command(BaseCommand):
    help = "Check the Google Sheets (live) and Supabase (fixed) sheet connections"

    def handle(self, *args, **o):
        ok = lambda m: self.stdout.write(self.style.SUCCESS(f"  OK   {m}"))  # noqa: E731
        bad = lambda m: self.stdout.write(self.style.ERROR(f"  FAIL {m}"))  # noqa: E731
        self.stdout.write("Live sheets (Google Sheets)")
        if gsheets.configured():
            ok(f"service account key found - share the live sheets (Viewer) with: {gsheets.service_account_email()}")
        else:
            bad("GOOGLE_SERVICE_ACCOUNT_JSON is not set or the key file is missing (see deploy/windows/HOSTING.md)")
        for label, key, tab_key, needed in LIVE:
            url = getattr(settings, key, "")
            if not url:
                self.stdout.write(f"  --   {label}: {key} not set - not imported")
                continue
            if not gsheets.configured():
                continue
            try:
                rows = gsheets.read_table(url, getattr(settings, tab_key, ""))
            except Exception as exc:  # noqa: BLE001
                bad(f"{label}: {exc}")
                continue
            heads = {(k or "").strip().lower() for k in (rows[0] if rows else {})}
            missing = [n for n in needed if n not in heads]
            (bad if missing or not rows else ok)(
                f"{label}: {len(rows):,} rows" + (f" - missing columns: {', '.join(missing)} (is the right tab linked?)"
                                                  if missing else ""))
        self.stdout.write("Fixed sheets (Supabase, schema reference)")
        if not reference_sheets.configured():
            bad("SUPABASE_EDITS_USER / SUPABASE_EDITS_PASSWORD are not set")
            return
        try:
            rows = reference_sheets.SupabaseReference().catalog()
        except Exception as exc:  # noqa: BLE001
            bad(f"{str(exc).splitlines()[0][:200]} - run deploy/supabase_edits.sql in Supabase (adds the reference folder)")
            return
        if not rows:
            self.stdout.write("  --   nothing stored yet (reference_sheet upload <name> <file>)")
        for r in rows:
            ok(f"{r['name']}{' / ' + r['tab'] if r['tab'] else ''}: {r['rows']:,} rows (from {r['source_file']})")
