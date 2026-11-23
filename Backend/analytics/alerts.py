"""Business alerts (requirements doc 6.2) shared by the Executive Overview "Exceptions" card and the daily MIS email.

Already in overview.exceptions: orders past the dispatch SLA, stale stock sync, run rate below required, data quality.
Here:
  * behind_target   distributors / regions whose sales this month are well behind the pace their target needs
                    (sales so far < BEHIND_PACE x target x share of the month gone)
  * refunds_pending customer refunds in the finance tracker with no refund date after REFUND_PENDING_DAYS
  * oos_top_sellers SKUs out of stock at a distributor that sold them in the last 30 days (or marked important)
Thresholds are placeholders until the business agrees them (doc 6.2: "thresholds ... agreed with business owners").
"""
import datetime as dt
from collections import defaultdict

from django.db.models import Sum

BEHIND_PACE = 0.7          # below 70% of the pace the monthly target needs
REFUND_PENDING_DAYS = 7    # refund owed for more than a week


def month_pace(today):
    """(first day of month, days gone (through yesterday), days in month)."""
    from .filters import month_end, month_start

    ms = month_start(today)
    return ms, (today - ms).days, (month_end(today) - ms).days + 1


def behind_target(f, level="distributor"):
    """[{id, name, target, sales, expected, pace_pct}] for this month, worst first. level: distributor | region."""
    from warehouse.models import Distributor, Region

    from .metrics import target_values

    if not f.targets_comparable:
        return []
    ms, gone, total = month_pace(f.today)
    if gone <= 0:
        return []
    tv = target_values(level, None, [ms], "sales", f.today)
    targets = {sid: float(v) for (sid, _), v in tv.items() if v}
    if not targets:
        return []
    field = f"{level}_id"
    sales = {r[field]: float(r["s"] or 0) for r in f.orders(start=ms, end=f.today - dt.timedelta(days=1))
             .values(field).annotate(s=Sum("gross_value"))}
    model = Distributor if level == "distributor" else Region
    names = dict(model.objects.filter(id__in=list(targets)).values_list("id", "name"))
    allowed = set(model.objects.filter(id__in=list(targets)).filter(
        f.dims_q({"distributor": "id", "region": "region_id", "state": "state_id", "asm": "asm_id"}
                 if level == "distributor" else {"region": "id"}, retailer_field=None)).values_list("id", flat=True))
    out = []
    for sid, t in targets.items():
        if sid not in allowed:
            continue
        expected = t * gone / total
        s = sales.get(sid, 0.0)
        if s < BEHIND_PACE * expected:
            out.append({"id": sid, "name": names.get(sid, "?"), "target": round(t, 2), "sales": round(s, 2),
                        "expected": round(expected, 2), "pace_pct": round(s / expected * 100, 1) if expected else 0})
    out.sort(key=lambda r: r["pace_pct"])
    return out


def refunds_pending(f):
    """Finance-tracker rows with a customer refund and no refund date, older than REFUND_PENDING_DAYS."""
    from warehouse.models import DistributorSettlement

    from .settlement import SDIMS

    cutoff = f.today - dt.timedelta(days=REFUND_PENDING_DAYS)
    return (DistributorSettlement.objects.filter(f.dims_q(SDIMS, retailer_field=None), customer_refund__gt=0,
                                                 refund_date__isnull=True, order_date__lte=cutoff)
            .exclude(settlement_status="cancelled"))


def oos_top_sellers(f):
    """[(distributor, style, size, units sold in 30 days)] out of stock now but selling (or marked important)."""
    from warehouse.models import Distributor

    from .views.products import latest_inventory, units_last_30d

    sold = units_last_30d(f)
    names = dict(Distributor.objects.values_list("id", "name"))
    out = []
    for did, sku, style, size, important in latest_inventory(f).filter(quantity__lte=0).values_list(
            "distributor_id", "sku", "style", "size", "product__is_important"):
        u = sold.get((did, sku), 0)
        if u > 0 or important:
            out.append({"distributor": names.get(did), "style": style, "size": size, "units_30d": u})
    out.sort(key=lambda r: -r["units_30d"])
    return out


def extra_exceptions(f):
    """The overview Exceptions rows added by this module."""
    from .metrics import fmt_inr

    out = []
    behind = behind_target(f, "distributor")
    if behind:
        worst = ", ".join(f"{b['name']} ({b['pace_pct']:.0f}%)" for b in behind[:3])
        out.append({"code": "distributors_behind_target", "severity": "high", "count": len(behind),
                    "message": f"distributors below {int(BEHIND_PACE * 100)}% of the pace their monthly target "
                               f"needs - {worst}", "link": "/distributors"})
    regions = behind_target(f, "region")
    if regions:
        out.append({"code": "regions_behind_target", "severity": "high", "count": len(regions),
                    "message": "regions behind target pace - " + ", ".join(
                        f"{r['name']} {fmt_inr(r['sales'])} of {fmt_inr(r['expected'])} expected so far" for r in regions[:3]),
                    "link": "/territory?group_by=region"})
    pend = refunds_pending(f)
    n = pend.count()
    if n:
        amt = float(pend.aggregate(s=Sum("customer_refund"))["s"] or 0)
        out.append({"code": "refunds_pending", "severity": "medium", "count": n,
                    "message": f"customer refunds pending over {REFUND_PENDING_DAYS} days ({fmt_inr(amt)})",
                    "link": "/settlements"})
    oos = oos_top_sellers(f)
    if oos:
        out.append({"code": "oos_top_sellers", "severity": "medium", "count": len(oos),
                    "message": "selling SKUs out of stock at their distributor (sold in the last 30 days)",
                    "link": "/inventory"})
    return out
