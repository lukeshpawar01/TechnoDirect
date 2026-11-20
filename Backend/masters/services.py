"""Side-effects of mapping changes (pincode -> state / ASM / distributor)."""
from collections import defaultdict

from django.utils.timezone import localdate  # India date (TIME_ZONE), not the server clock

from django.db.models import Q

from ingestion.upsert import chunked
from warehouse.models import CrmTicket, LoyaltyEvent, Order, Pincode, Retailer, RetailerMonth


def _differs(**values):
    """Q matching rows where any of the given fields differs from the target value (NULL-safe)."""
    q = Q()
    for field, v in values.items():
        if v is None:
            q |= Q(**{f"{field}__isnull": False})
        else:
            q |= ~Q(**{field: v}) | Q(**{f"{field}__isnull": True})
    return q


def remap_retailers_for_pincodes(pincodes):
    """Re-derive territory for retailers in the given pincodes (and their orders / retailer-months).

    Territory reporting always follows the CURRENT mapping. Done in bulk: pincodes that map to the same
    (state, region, ASM, P1 distributor) are updated together, and only rows whose values actually change are
    written — a few hundred queries for a full re-map instead of three per pincode.
    """
    wanted = set(pincodes)
    if not wanted:
        return 0
    with_retailers = set(Retailer.objects.filter(pincode__in=wanted).values_list("pincode", flat=True).distinct()) \
        if len(wanted) <= 5000 else wanted & set(Retailer.objects.values_list("pincode", flat=True).distinct())
    groups = defaultdict(list)
    for pin, state_id, region_id, asm_id, dist_id in Pincode.objects.filter(pincode__in=with_retailers).values_list(
            "pincode", "state_id", "state__region_id", "asm_id", "distributor_p1_id"):
        groups[(state_id, region_id, asm_id, dist_id)].append(pin)

    touched = orders = 0
    for (state_id, region_id, asm_id, dist_id), pins in groups.items():
        terr = {"state_id": state_id, "region_id": region_id, "asm_id": asm_id}
        for chunk in chunked(pins, 500):
            touched += Retailer.objects.filter(pincode__in=chunk).filter(
                _differs(**terr, distributor_id=dist_id)).update(**terr, distributor_id=dist_id)
            orders += Order.objects.filter(retailer__pincode__in=chunk).filter(_differs(**terr)).update(**terr)
            # everything else that carries the retailer's territory follows it
            for model in (RetailerMonth, LoyaltyEvent):
                model.objects.filter(retailer__pincode__in=chunk).filter(
                    _differs(**terr, distributor_id=dist_id)).update(**terr, distributor_id=dist_id)
            CrmTicket.objects.filter(retailer__pincode__in=chunk).filter(_differs(**terr)).update(**terr)
    if touched or orders:
        # orders count for the ASM of the distributor that fulfilled them (re-applied after the pincode ASM)
        from analytics.cache import bump_cache_version
        from analytics.derivations import attribute_orders_to_distributor_asm

        attribute_orders_to_distributor_asm()
        bump_cache_version()
    return touched


def assign_distributor_asm(distributor, asm, start, end=None, notes=""):
    """Record that `asm` (None = vacant) manages `distributor` from `start` (to `end`, inclusive).

    Keeps history: the assignment running at `start` is closed the day before, a later one caps this one, and
    the distributor's current ASM becomes whoever is in charge today. The first time a distributor gets a
    history, its existing ASM is kept for the period before `start` (so a handover never rewrites the past).
    """
    import datetime as dt

    from warehouse.models import AsmAssignment

    asm_id = asm.id if asm is not None else None
    hist = AsmAssignment.objects.filter(distributor=distributor)
    if not hist.exists() and distributor.asm_id and distributor.asm_id != asm_id and start > dt.date(2023, 1, 1):
        AsmAssignment.objects.create(distributor=distributor, asm_id=distributor.asm_id, start=dt.date(2023, 1, 1),
                                     end=start - dt.timedelta(days=1), notes="ASM before the first recorded handover")
    same = hist.filter(start=start).first()
    prev = hist.filter(start__lt=start).order_by("-start").first()
    if prev and (prev.end is None or prev.end >= start):
        prev.end = start - dt.timedelta(days=1)
        prev.save(update_fields=["end", "updated_at"])
    nxt = hist.filter(start__gt=start).order_by("start").first()
    if end is None and nxt:
        end = nxt.start - dt.timedelta(days=1)
    if same:
        same.asm_id, same.end, same.notes = asm_id, end, notes[:255] or same.notes
        same.save(update_fields=["asm", "end", "notes", "updated_at"])
    else:
        AsmAssignment.objects.create(distributor=distributor, asm_id=asm_id, start=start, end=end, notes=notes[:255])
    current_asm_id(distributor, save=True)


def current_asm_id(distributor, today=None, save=False):
    """The ASM in charge of a distributor today according to its history (unchanged if it has none)."""
    import datetime as dt

    from django.db.models import Q as Q_

    from warehouse.models import AsmAssignment

    today = today or localdate()
    a = (AsmAssignment.objects.filter(distributor=distributor, start__lte=today)
         .filter(Q_(end__isnull=True) | Q_(end__gte=today)).order_by("-start").first())
    if a is None:
        return distributor.asm_id
    if save and distributor.asm_id != a.asm_id:
        from warehouse.models import Retailer

        distributor.asm_id = a.asm_id
        distributor.save(update_fields=["asm", "updated_at"])
        # the distributor's retailers move with it
        Retailer.objects.filter(distributor=distributor).update(asm_id=a.asm_id)
    return a.asm_id
