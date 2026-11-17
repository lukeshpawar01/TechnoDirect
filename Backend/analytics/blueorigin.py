"""BlueOrigin (offline) analytics: tiers and offline purchase on the TechnoDirect hierarchy.

Window
    BO sheets are monthly values published per quarter, so they lag the app. The selected period is read in whole
    months and clipped to the last BO month. When the period lies entirely after the BO data (e.g. this month), the
    latest BO quarter is shown instead and the payload says so (`window.shifted`).
Tier
    The sheet's "New Tier" of the latest BO quarter starting on or before the window end. A retailer missing from
    that quarter's sheet counts as Untiered.
App vs BO
    The BO sheets record everything a distributor sold to a retailer, app orders included: for phone-matched app
    retailers the monthly BO value equals their app sales within 10% in ~64% of retailer-months (median ratio 1.00,
    checked 2026-11-18). So app sales (gross value of qualifying orders, same months) are a PART of the BO value:
    shown as "ordered on the app" / app share, never added to it.
"""
import datetime as dt
from collections import defaultdict

from django.db.models import Count, Max, Min, Q, Sum

from .filters import add_months, fy_quarter_label, month_start, quarter_start

TIERS = ["Platinum", "Gold", "Silver", "Green", "Yellow", "Untiered"]
BO_DIMS = {"region": "region_id", "state": "state_id", "asm": "asm_id", "distributor": "distributor_id"}


def data_range():
    from warehouse.models import BoRetailerMonth

    r = BoRetailerMonth.objects.aggregate(a=Min("month"), b=Max("month"))
    return r["a"], r["b"]


def window(f):
    """{start, end (first days of months), months, shifted, clipped, data_until, tier_quarter, prev_*}."""
    from warehouse.models import BoRetailerQuarter

    first, last = data_range()
    if last is None:
        return None
    start, end = month_start(f.period.start), month_start(f.period.end)
    shifted = clipped = False
    if start > last:
        start, end, shifted = quarter_start(last), last, True
    elif end > last:
        end, clipped = last, True
    start = max(start, first)
    n = (end.year - start.year) * 12 + end.month - start.month + 1
    tq = BoRetailerQuarter.objects.filter(quarter__lte=end).aggregate(q=Max("quarter"))["q"]
    prev_tq = BoRetailerQuarter.objects.filter(quarter__lt=tq).aggregate(q=Max("quarter"))["q"] if tq else None
    prev_end = add_months(start, -1)
    prev_start = add_months(start, -n)
    return {"start": start, "end": end, "months": n, "shifted": shifted, "clipped": clipped,
            "data_from": first, "data_until": last, "tier_quarter": tq, "prev_tier_quarter": prev_tq,
            "prev_start": prev_start if prev_start >= first else None, "prev_end": prev_end if prev_end >= first else None}


def label_months(a, b):
    fmt = lambda d: d.strftime("%b-%y")  # noqa: E731
    return fmt(a) if a == b else f"{fmt(a)} – {fmt(b)}"


def window_meta(w):
    return {"from": w["start"].isoformat(), "to": w["end"].isoformat(), "label": label_months(w["start"], w["end"]),
            "months": w["months"], "shifted": w["shifted"], "clipped": w["clipped"],
            "data_from": w["data_from"].isoformat(), "data_until": w["data_until"].isoformat(),
            "tier_quarter": fy_quarter_label(w["tier_quarter"]) if w["tier_quarter"] else None,
            "prev_tier_quarter": fy_quarter_label(w["prev_tier_quarter"]) if w["prev_tier_quarter"] else None,
            "prev_label": label_months(w["prev_start"], w["prev_end"]) if w["prev_start"] else None}


def retailers_qs(f, w):
    """BO retailers in scope / filters (hierarchy + tier at the window's tier quarter)."""
    from warehouse.models import BoRetailer, BoRetailerQuarter

    qs = BoRetailer.objects.filter(f.dims_q(BO_DIMS, retailer_field=None))
    if f.tiers and w and w["tier_quarter"]:
        listed = BoRetailerQuarter.objects.filter(quarter=w["tier_quarter"])
        q = Q(id__in=listed.filter(tier__in=f.tiers).values("bo_retailer_id"))
        if "Untiered" in f.tiers:  # not in the quarter's sheet = Untiered
            q |= ~Q(id__in=listed.values("bo_retailer_id"))
        qs = qs.filter(q)
    return qs


def frame(f, w):
    """{bo_retailer_id: row} for every retailer in scope: purchase now / prev, tier now / prev, hierarchy, app link."""
    from warehouse.models import BoRetailerMonth, BoRetailerQuarter

    base = retailers_qs(f, w)
    rows = {r["id"]: {**r, "purchase": 0.0, "prev": 0.0, "tier": "Untiered", "listed": False, "prev_tier": None,
                     "app_sales": 0.0}
            for r in base.values("id", "distributor_id", "asm_id", "state_id", "region_id", "td_retailer_id")}
    ids = base.values("id")
    for bid, s in BoRetailerMonth.objects.filter(bo_retailer_id__in=ids, month__gte=w["start"],
                                                 month__lte=w["end"]).values_list("bo_retailer_id").annotate(
            s=Sum("value")):
        rows[bid]["purchase"] = float(s)
    if w["prev_start"]:
        for bid, s in BoRetailerMonth.objects.filter(bo_retailer_id__in=ids, month__gte=w["prev_start"],
                                                     month__lte=w["prev_end"]).values_list("bo_retailer_id").annotate(
                s=Sum("value")):
            rows[bid]["prev"] = float(s)
    for key, q in (("tier", w["tier_quarter"]), ("prev_tier", w["prev_tier_quarter"])):
        if q:
            for bid, t in BoRetailerQuarter.objects.filter(bo_retailer_id__in=ids, quarter=q).values_list(
                    "bo_retailer_id", "tier"):
                rows[bid][key] = t
                if key == "tier":
                    rows[bid]["listed"] = True
    if w["prev_tier_quarter"]:  # retailers not in the previous sheet: "Not listed" (new to BO)
        for r in rows.values():
            r["prev_tier"] = r["prev_tier"] or "Not listed"
    _app_sales(rows, w)
    return rows


def _app_sales(rows, w):
    """App sales of the linked TechnoDirect retailers in the window's months (each app retailer counted once)."""
    from warehouse.models import Order

    linked = {r["td_retailer_id"] for r in rows.values() if r["td_retailer_id"]}
    if not linked:
        return
    end = add_months(w["end"], 1) - dt.timedelta(days=1)
    sales = dict(Order.objects.filter(is_qualifying=True, retailer_id__in=linked, placed_date__gte=w["start"],
                                      placed_date__lte=end).values_list("retailer_id").annotate(s=Sum("gross_value")))
    seen = set()
    for r in sorted(rows.values(), key=lambda r: -r["purchase"]):
        t = r["td_retailer_id"]
        if t and t not in seen:
            r["app_sales"] = float(sales.get(t) or 0)
            seen.add(t)


def _pct(a, b):
    return round(a / b * 100, 1) if b else None


def _delta(now, prev):
    return round((now - prev) / prev * 100, 1) if prev else None


def summarize(rows):
    """Aggregate of a set of frame rows (used for totals, tiers and hierarchy groups)."""
    active = [r for r in rows if r["purchase"] > 0]
    linked = [r for r in active if r["td_retailer_id"]]
    tiers = defaultdict(int)
    for r in rows:
        tiers[r["tier"]] += 1
    purchase, prev = sum(r["purchase"] for r in rows), sum(r["prev"] for r in rows)
    app_buyers = sum(1 for r in linked if r["app_sales"] > 0)
    return {"purchase": round(purchase, 2), "prev_purchase": round(prev, 2), "delta_pct": _delta(purchase, prev),
            "retailers": len(rows), "active": len(active), "on_app": len(linked), "on_app_pct": _pct(len(linked), len(active)),
            "app_buyers": app_buyers, "app_buyers_pct": _pct(app_buyers, len(active)),
            "app_sales": round(sum(r["app_sales"] for r in rows), 2),
            "tiered": sum(v for k, v in tiers.items() if k != "Untiered"),
            "tiers": {t: tiers.get(t, 0) for t in TIERS}}


def summary(f):
    from warehouse.models import BoRetailerMonth, BoRetailerQuarter

    w = window(f)
    if w is None:
        return {"available": False}
    rows = frame(f, w)
    vals = list(rows.values())
    by_tier = []
    for t in TIERS:
        rs = [r for r in vals if r["tier"] == t]
        s = summarize(rs)
        s.update(tier=t, avg_purchase=round(s["purchase"] / s["active"], 2) if s["active"] else None)
        by_tier.append(s)
    # tier mix by quarter (up to the window's tier quarter, last 8)
    ids = retailers_qs(f, w).values("id")
    mix = defaultdict(lambda: {t: {"retailers": 0, "purchase": 0.0} for t in TIERS})
    for q, t, n, s in (BoRetailerQuarter.objects.filter(bo_retailer_id__in=ids, quarter__lte=w["tier_quarter"])
                       .values_list("quarter", "tier").annotate(n=Count("id"), s=Sum("purchase"))):
        mix[q][t] = {"retailers": n, "purchase": float(s or 0)}
    quarters = sorted(mix)[-8:]
    tier_mix = [{"quarter": q.isoformat(), "label": fy_quarter_label(q), "tiers": mix[q]} for q in quarters]
    # movement between the previous and the current tier quarter
    order = {t: i for i, t in enumerate(TIERS)}
    moves = defaultdict(int)
    up = down = same = new = dropped = 0
    for r in vals:
        if not w["prev_tier_quarter"]:
            break
        a, b = r["prev_tier"], (r["tier"] if r["listed"] else "Not listed")
        if a == "Not listed" and b == "Not listed":
            continue  # in neither sheet
        moves[(a, b)] += 1
        if a == "Not listed":
            new += 1
        elif b == "Not listed":
            dropped += 1  # in the previous sheet, missing from this one (not the same as a downgrade)
        elif order[b] < order[a]:
            up += 1
        elif order[b] > order[a]:
            down += 1
        else:
            same += 1
    movement = {"from_quarter": fy_quarter_label(w["prev_tier_quarter"]) if w["prev_tier_quarter"] else None,
                "to_quarter": fy_quarter_label(w["tier_quarter"]),
                "cells": [{"from": a, "to": b, "retailers": n} for (a, b), n in sorted(moves.items())],
                "upgraded": up, "downgraded": down, "same": same, "new": new, "dropped": dropped}
    # last 12 BO months: offline purchase vs app sales of the linked retailers (whole scope)
    m_end = w["end"]
    m_start = max(add_months(m_end, -11), w["data_from"])
    monthly = {m: {"month": m.isoformat()[:7], "offline": 0.0, "app": 0.0} for m in _months(m_start, m_end)}
    for m, s in BoRetailerMonth.objects.filter(bo_retailer_id__in=ids, month__gte=m_start, month__lte=m_end).values_list(
            "month").annotate(s=Sum("value")):
        monthly[m]["offline"] = float(s)
    linked = {r["td_retailer_id"] for r in vals if r["td_retailer_id"]}
    if linked:
        from django.db.models.functions import TruncMonth

        from warehouse.models import Order

        end_day = add_months(m_end, 1) - dt.timedelta(days=1)
        for r in (Order.objects.filter(is_qualifying=True, retailer_id__in=linked, placed_date__gte=m_start,
                                       placed_date__lte=end_day).annotate(m=TruncMonth("placed_date"))
                  .values("m").annotate(s=Sum("gross_value"))):
            m = r["m"].date() if isinstance(r["m"], dt.datetime) else r["m"]
            if m in monthly:
                monthly[m]["app"] = float(r["s"] or 0)
    return {"available": True, "window": window_meta(w), "kpis": summarize(vals), "by_tier": by_tier,
            "tier_mix": tier_mix, "movement": movement, "monthly": list(monthly.values())}


def _months(a, b):
    out = []
    while a <= b:
        out.append(a)
        a = add_months(a, 1)
    return out


GROUPS = ("region", "rsm", "asm", "state", "distributor")


def hierarchy(f, group_by="asm"):
    from warehouse.models import Asm, Distributor, Region, Rsm, State

    from .rsm import region_rsm_map

    group_by = group_by if group_by in GROUPS else "asm"
    w = window(f)
    if w is None:
        return {"available": False, "rows": []}
    rows = frame(f, w)
    if group_by == "rsm":
        asm_rsm = dict(Asm.objects.values_list("id", "rsm_id"))
        reg_rsm = region_rsm_map()
        key = lambda r: asm_rsm.get(r["asm_id"]) if r["asm_id"] else reg_rsm.get(r["region_id"])  # noqa: E731
        names = dict(Rsm.objects.values_list("id", "name"))
    else:
        field = f"{group_by}_id"
        key = lambda r: r[field]  # noqa: E731
        model = {"region": Region, "asm": Asm, "state": State, "distributor": Distributor}[group_by]
        names = dict(model.objects.values_list("id", "name"))
    groups = defaultdict(list)
    for r in rows.values():
        groups[key(r)].append(r)
    bo_only = set(Distributor.objects.filter(bo_only=True).values_list("id", flat=True)) if group_by == "distributor" else set()
    out = []
    for k, rs in groups.items():
        s = summarize(rs)
        s.update(id=k, name=names.get(k) or ("Unassigned" if group_by in ("asm", "rsm") else "Unknown"),
                 offline_only=k in bo_only)
        out.append(s)
    out.sort(key=lambda x: -x["purchase"])
    return {"available": True, "window": window_meta(w), "group_by": group_by, "rows": out,
            "total": summarize(list(rows.values()))}
