"""Side-effects of mapping changes (pincode -> state / ASM / distributor)."""
from ingestion.upsert import chunked
from warehouse.models import Order, Pincode, Retailer, RetailerMonth


def remap_retailers_for_pincodes(pincodes):
    """Re-derive territory for retailers in the given pincodes (and their orders / months).

    Territory reporting always follows the CURRENT mapping.
    """
    pincodes = list(set(pincodes))
    touched = 0
    for chunk in chunked(pincodes, 500):
        pins = {p.pincode: p for p in Pincode.objects.filter(pincode__in=chunk).select_related("state")}
        for pin, pm in pins.items():
            region_id = pm.state.region_id if pm.state_id else None
            rets = Retailer.objects.filter(pincode=pin)
            ids = list(rets.values_list("id", flat=True))
            if not ids:
                continue
            rets.update(state_id=pm.state_id, region_id=region_id, asm_id=pm.asm_id,
                        distributor_id=pm.distributor_p1_id)
            Order.objects.filter(retailer_id__in=ids).update(state_id=pm.state_id, region_id=region_id,
                                                             asm_id=pm.asm_id)
            RetailerMonth.objects.filter(retailer_id__in=ids).update(
                state_id=pm.state_id, region_id=region_id, asm_id=pm.asm_id, distributor_id=pm.distributor_p1_id)
            touched += len(ids)
    if touched:
        from analytics.cache import bump_cache_version

        bump_cache_version()
    return touched
