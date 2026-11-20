"""New retailers and BlueOrigin conversions for the Region & ASM scorecard (and its click-through lists).

  New (TD)       retailers whose first-ever TD order falls in the period (the scorecard's existing "New" column);
                 grouped by the territory of that first order
  BO -> TD       of those, retailers that bought offline in BlueOrigin BEFORE the period: BlueOrigin retailers
                 converted to TD. Grouped by the retailer's BlueOrigin territory (its BO distributor / ASM / state /
                 region) - the offline relationship, as in the incentive tracker (user's choice, 20 Nov 2026)
  BO G/P/S       of the BO conversions, the ones with BO tier Gold / Platinum / Silver
"""
from django.db.models import Sum
from django.utils import timezone

from .blueorigin import BO_DIMS
from .filters import month_start
from .rsm import with_rsm

GPS_TIERS = ("Platinum", "Gold", "Silver")
TD_FIELD = {"region": "region_id", "state": "state_id", "asm": "asm_id", "distributor": "distributor_id", "rsm": "rsm_key"}


def new_td(f, group_by):
    """{retailer_id: {"group": id, "order": {...}}} - first-ever TD order in the period, grouped by its territory."""
    p = f.period
    qs = f.orders(start=p.start, end=p.end).filter(placed_date=_first())
    if group_by == "rsm":
        qs = with_rsm(qs)
    out = {}
    for o in qs.order_by("placed_at").values("retailer_id", TD_FIELD[group_by], "display_id", "placed_date",
                                             "gross_value", "distributor__name"):
        out.setdefault(o["retailer_id"], {"group": o[TD_FIELD[group_by]], "order": o})
    return out


def _first():
    from django.db.models import F

    return F("retailer__first_order_date")


def bo_conversions(f, group_by):
    """{retailer_id: {"group": BO territory id, "bo": {...}, "gps": bool}} for the period."""
    from warehouse.models import BoRetailer, BoRetailerMonth, Retailer

    p = f.period
    start = month_start(p.start)
    new_ids = list(Retailer.objects.filter(first_order_date__gte=p.start, first_order_date__lte=p.end)
                   .values_list("id", flat=True))
    before = BoRetailerMonth.objects.filter(month__lt=start, value__gt=0, bo_retailer__td_retailer_id__in=new_ids)
    bos = BoRetailer.objects.filter(f.dims_q(BO_DIMS, retailer_field=None), id__in=before.values("bo_retailer_id"))
    if group_by == "rsm":
        bos = with_rsm(bos)
    tiers = dict(Retailer.objects.filter(id__in=new_ids).values_list("id", "tier"))
    out = {}
    for b in (bos.annotate(p=Sum("months__value")).order_by("-p")
              .values("td_retailer_id", TD_FIELD[group_by], "distributor__name", "asm__name", "tier")):
        rid = b["td_retailer_id"]
        if rid in out:
            continue  # several BO rows for one retailer (same phone): the biggest offline buyer wins
        out[rid] = {"group": b[TD_FIELD[group_by]], "bo": b, "gps": (tiers.get(rid) or "") in GPS_TIERS}
    return out


def counts(f, group_by):
    """{group_id: {"new": n, "bo": n, "gps": n}}."""
    from collections import defaultdict

    c = defaultdict(lambda: {"new": 0, "bo": 0, "gps": 0})
    for v in new_td(f, group_by).values():
        c[v["group"]]["new"] += 1
    for v in bo_conversions(f, group_by).values():
        c[v["group"]]["bo"] += 1
        c[v["group"]]["gps"] += 1 if v["gps"] else 0
    return c


def retailers(f, group_by, group_id, kind, can_see_phone=False):
    """The retailers behind one scorecard number. kind: new / bo / gps; group_id None = Unmapped."""
    from warehouse.models import Order, Retailer

    from .views.funnel import mask_phone

    if kind == "new":
        sel = {rid: v for rid, v in new_td(f, group_by).items() if v["group"] == group_id}
    else:
        sel = {rid: v for rid, v in bo_conversions(f, group_by).items()
               if v["group"] == group_id and (kind == "bo" or v["gps"])}
    ids = list(sel)
    bo = bo_conversions(f, group_by) if kind == "new" else sel
    first = {}
    for o in (Order.objects.filter(is_qualifying=True, retailer_id__in=ids).order_by("placed_at")
              .values("retailer_id", "display_id", "placed_date", "gross_value", "distributor__name")):
        first.setdefault(o["retailer_id"], o)
    rows = []
    for r in Retailer.objects.filter(id__in=ids).values("id", "name", "phone", "city", "state__name", "tier",
                                                         "kyc_status", "signed_up_at"):
        o, b = first.get(r["id"], {}), (bo.get(r["id"]) or {}).get("bo")
        rows.append({
            "retailer_id": r["id"], "retailer": r["name"], "phone": mask_phone(r["phone"], can_see_phone),
            "city": r["city"], "state": r["state__name"], "tier": r["tier"] or "Not in BlueOrigin",
            "bo_existing": b is not None, "bo_distributor": b["distributor__name"] if b else None,
            "bo_asm": b["asm__name"] if b else None,
            "first_order": o.get("display_id"), "first_order_date": o["placed_date"].isoformat() if o else None,
            "first_order_value": float(o.get("gross_value") or 0), "td_distributor": o.get("distributor__name"),
            "kyc_status": r["kyc_status"],
            "signed_up": timezone.localtime(r["signed_up_at"]).date().isoformat() if r["signed_up_at"] else None})
    rows.sort(key=lambda x: (x["first_order_date"] or "", x["retailer"]))
    return rows
