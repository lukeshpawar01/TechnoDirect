"""Split (multi-distributor) carts.

When no single distributor has stock for a whole cart, the app splits the cart into one order per distributor.
The parts of one cart:
- are placed by the same retailer on the same day;
- get consecutive display ids (e.g. #24366 Jain Sports + #24367 Singh Sports);
- go to different distributors.

The app export does not carry the cart id, so `Order.split_group` / `is_split` are rebuilt here:

Finance tracker ("Multi Distributor Order" column)
    Its flag decides for every order it lists.
Orders the tracker does not list
    The rule above decides.
Accuracy (checked 2026-11-18 on the tracker's period, Sep–Nov 2026)
    The rule finds all 132 flagged parts (65 carts). It also flags 9 orders that finance did not mark as split,
    and those are overruled by the tracker.

`split_group` is cart-level everywhere in the dashboard (orders = distinct split_group), so a split cart counts
as ONE retailer order while each part keeps its own distributor, value and settlement.
"""
from collections import defaultdict


def _chains(orders):
    """Runs of consecutive display ids per (retailer, day)."""
    by = defaultdict(list)
    for o in orders:
        if o["display_id"].isdigit():
            by[(o["retailer_id"], o["placed_date"])].append(o)
    for v in by.values():
        v.sort(key=lambda x: int(x["display_id"]))
        chain = [v[0]]
        for a in v[1:]:
            if int(a["display_id"]) - int(chain[-1]["display_id"]) == 1:
                chain.append(a)
            else:
                if len(chain) > 1:
                    yield chain
                chain = [a]
        if len(chain) > 1:
            yield chain


def mark_split_carts():
    """Rebuild Order.is_split / split_group. Returns {"carts": n, "orders": n, "changed": n}."""
    from django.db import transaction

    from warehouse.models import DistributorSettlement, Order

    flagged, listed = set(), set()
    for ref, multi in DistributorSettlement.objects.values_list("order_ref", "multi_distributor"):
        listed.add(ref)
        if multi:
            flagged.add(ref)

    orders = list(Order.objects.exclude(retailer=None).values(
        "id", "display_id", "retailer_id", "placed_date", "distributor_id", "source_id"))
    cart_of = {}  # order id -> cart key
    for chain in _chains(orders):
        if any(o["display_id"] in listed for o in chain):
            parts = [o for o in chain if o["display_id"] in flagged or o["display_id"] not in listed]
            if not any(o["display_id"] in flagged for o in parts):
                continue
        else:
            parts = chain if len({o["distributor_id"] for o in chain}) > 1 else []
        if len(parts) > 1:
            key = f"cart:{parts[0]['display_id']}"
            for o in parts:
                cart_of[o["id"]] = key

    changed = 0
    with transaction.atomic():
        stale = Order.objects.filter(is_split=True).exclude(id__in=list(cart_of))
        for o in stale.only("id", "source_id"):
            Order.objects.filter(id=o.id).update(is_split=False, split_group=o.source_id)
            changed += 1
        current = dict(Order.objects.filter(id__in=list(cart_of)).values_list("id", "split_group"))
        by_key = defaultdict(list)
        for oid, key in cart_of.items():
            if current.get(oid) != key:
                by_key[key].append(oid)
        for key, ids in by_key.items():
            changed += Order.objects.filter(id__in=ids).update(is_split=True, split_group=key)
    return {"carts": len(set(cart_of.values())), "orders": len(cart_of), "changed": changed}
