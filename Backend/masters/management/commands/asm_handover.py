"""Record an ASM handover for a distributor (resignation, new joiner, re-allocation) without rewriting history.

    python manage.py asm_handover "Virat Sports Wear" --asm Valluru --from 2026-10-01
    python manage.py asm_handover "Virat Sports Wear" --asm vacant --from 2023-01-01 --to 2025-01-31

Orders placed from --from (to --to) are credited to that ASM; earlier orders stay with whoever had them.
The distributor's current ASM, its pincodes' ASM and the retailers there follow whoever is in charge today.
"""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from analytics.cache import bump_cache_version
from analytics.derivations import attribute_orders_to_distributor_asm
from ingestion.csv_import import norm
from masters.services import assign_distributor_asm, remap_retailers_for_pincodes
from warehouse.models import Asm, Distributor, Pincode


def find_distributor(name):
    n = norm(name)
    for d in Distributor.objects.all():
        if n in {norm(x) for x in [d.name, d.code, *(d.aliases or [])]}:
            return d
    raise CommandError(f"No distributor called '{name}'")


def find_asm(name):
    if name.lower() in ("vacant", "none", "-"):
        return None
    a = Asm.objects.filter(Q(name__iexact=name) | Q(full_name__iexact=name) | Q(code__iexact=name)).first()
    if a is None:
        raise CommandError(f"No ASM called '{name}' (create it first, e.g. from the ASM tracker)")
    return a


class Command(BaseCommand):
    help = "Hand a distributor over to another ASM from a date, keeping earlier orders with the previous ASM."

    def add_arguments(self, parser):
        parser.add_argument("distributor")
        parser.add_argument("--asm", required=True, help="ASM name / full name / code, or 'vacant'")
        parser.add_argument("--from", dest="start", required=True, help="First day, YYYY-MM-DD")
        parser.add_argument("--to", dest="end", help="Last day, YYYY-MM-DD (default: open / until the next one)")
        parser.add_argument("--notes", default="")

    def handle(self, *args, **o):
        d = find_distributor(o["distributor"])
        asm = find_asm(o["asm"])
        start = dt.date.fromisoformat(o["start"])
        end = dt.date.fromisoformat(o["end"]) if o["end"] else None
        with transaction.atomic():
            before = d.asm_id
            assign_distributor_asm(d, asm, start, end, notes=o["notes"] or "asm_handover")
            d.refresh_from_db()
            if d.asm_id != before:  # pincodes / retailers follow the ASM in charge today
                pins = Pincode.objects.filter(distributor_p1=d, asm_id__in=[before, None] if before else [None])
                codes = list(pins.values_list("pincode", flat=True))
                pins.update(asm_id=d.asm_id)
                remap_retailers_for_pincodes(codes)
        moved = attribute_orders_to_distributor_asm()
        bump_cache_version()
        for a in d.asm_history.select_related("asm").order_by("start"):
            self.stdout.write(f"  {a.start} -> {str(a.end or 'now'):<10}  {a.asm.name if a.asm else 'vacant'}  ({a.notes})")
        self.stdout.write(f"  current ASM: {d.asm.name if d.asm_id else 'none'} | orders re-credited: {moved}")
        self.stdout.write(self.style.SUCCESS("[handover] done."))
