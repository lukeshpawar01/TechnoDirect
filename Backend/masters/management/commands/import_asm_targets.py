"""Load monthly ASM sales targets (lakhs) from the Technodirect Order Tracking workbook. See masters/asm_targets.py."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analytics.cache import bump_cache_version
from masters.asm_targets import import_asm_targets, reconcile


class Command(BaseCommand):
    help = "Import monthly ASM targets (TD Target, lakhs) from the order-tracking workbook; --check compares achieved."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--check", action="store_true", help="Compare the sheet's achieved with dashboard sales")

    def handle(self, *args, **o):
        if not Path(o["file"]).is_file():
            raise CommandError(f"File not found: {o['file']}")
        if o["check"]:
            rows = reconcile(o["file"])
            close = sum(1 for r in rows if abs(r[3] - r[4]) <= max(0.5, 0.1 * r[3]))
            for m, sheet_name, asm, sheet_v, ours in rows:
                flag = "" if abs(sheet_v - ours) <= max(0.5, 0.1 * sheet_v) else "  <-- differs"
                self.stdout.write(f"  {m} {sheet_name:<20} {asm:<12} sheet {sheet_v:>7.2f} L  dashboard {ours:>7.2f} L{flag}")
            self.stdout.write(f"  within 10% (or 0.5 L): {close} of {len(rows)}")
            return
        with transaction.atomic():
            res = import_asm_targets(o["file"], dry_run=o["dry_run"])
            if o["dry_run"]:
                transaction.set_rollback(True)
        for m in res["months"]:
            self.stdout.write(
                f"  {m['month']} [{m['tab']:<8}] ASMs {m['asm_targets']:>2}  sum {m['sum_l']:>6.1f} L  "
                f"sheet total {m['total_l'] if m['total_l'] is not None else '-':>6}  unassigned {m['unassigned_l']:.1f} L"
                + ("  (kept distributor tracker)" if m["kept_distributor_tracker"] else "")
                + (f"  skipped: {', '.join(m['skipped'])}" if m["skipped"] else "") + f"  {m['written']}")
        if not o["dry_run"]:
            bump_cache_version()
        self.stdout.write(self.style.SUCCESS(f"[asm targets] {'dry run' if o['dry_run'] else 'done'}: {res['written']}"))
