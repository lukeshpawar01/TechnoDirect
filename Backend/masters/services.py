"""Side-effects of mapping changes (pincode -> state / ASM / distributor)."""
from collections import defaultdict

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
