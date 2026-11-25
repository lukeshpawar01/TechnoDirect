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
                     "app_sales": 0.0, "td_ever": False}
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

    from warehouse.models import Retailer

    linked = {r["td_retailer_id"] for r in rows.values() if r["td_retailer_id"]}
    if not linked:
        return
    ever = set(Retailer.objects.filter(id__in=linked, first_order_date__isnull=False).values_list("id", flat=True))
    for r in rows.values():
        r["td_ever"] = r["td_retailer_id"] in ever
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


# --- Expected TD from BlueOrigin ------------------------------------------------------------------------------------
# BO sheets carry everything a distributor sold to a retailer, app orders included, so a retailer's "TD share" is
# app sales / BO purchase. The expected TD of a tier is what the tier would bring if every distributor reached the TD
# share the best quarter of distributors ALREADY reach in that tier (an internal, proven benchmark - not a guess):
#   cell = one distributor x one tier, eligible when it buys >= BENCH_MIN_MONTHLY a month from >= BENCH_MIN_RETAILERS
#   benchmark[tier] = 75th percentile of the eligible cells' TD shares (network-wide, the same months as the window)
#   expected[cell] = max(BO purchase x benchmark, actual TD)  - a cell already above the benchmark keeps its actual
#   gap = expected - actual (headroom; never negative)
# Fewer than BENCH_MIN_CELLS eligible cells in a tier -> the benchmark of all cells pooled.
# Offline-only distributors (Distributor.bo_only: not on the app) can't take TD orders: they are left out of the
# benchmark and carry no expected TD; their BO purchase is reported apart as "offline_only_bo".
BENCH_PCTL = 0.75
BENCH_MIN_MONTHLY = 200_000
BENCH_MIN_RETAILERS = 5
BENCH_MIN_CELLS = 4


def _percentile(values, p):
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def _cells(rows):
    """{(distributor_id, tier): {"purchase", "app", "retailers"}} - retailers counted when they bought in BO."""
    cells = defaultdict(lambda: {"purchase": 0.0, "app": 0.0, "retailers": 0})
    for r in rows:
        c = cells[(r["distributor_id"], r["tier"])]
        c["purchase"] += r["purchase"]
        c["app"] += r["app_sales"]
        c["retailers"] += 1 if r["purchase"] > 0 else 0
    return cells


def benchmarks(w):
    """{tier: {"share", "cells", "basis"}} from the whole network (the user's filters and scope do not move it)."""
    from .filters import system_filters

    cells = _cells(frame(system_filters(), w).values())
    months = w["months"] or 1
    off = _offline_only()
    eligible = defaultdict(list)
    for (dist, tier), c in cells.items():
        if dist in off:
            continue
        if c["purchase"] / months >= BENCH_MIN_MONTHLY and c["retailers"] >= BENCH_MIN_RETAILERS:
            eligible[tier].append(min(c["app"] / c["purchase"], 1.0))
    pooled = _percentile([s for v in eligible.values() for s in v], BENCH_PCTL) or 0.0
    out = {}
    for t in TIERS:
        shares = eligible.get(t, [])
        if len(shares) >= BENCH_MIN_CELLS:
            out[t] = {"share": _percentile(shares, BENCH_PCTL), "cells": len(shares), "basis": "tier"}
        else:
            out[t] = {"share": pooled, "cells": len(shares), "basis": "pooled"}
    return out


def _offline_only():
    from warehouse.models import Distributor

    return set(Distributor.objects.filter(bo_only=True).values_list("id", flat=True))


def _expected(rows, bench, months, off):
    """Totals of a set of frame rows: BO purchase, actual TD, expected TD, gap (all per month)."""
    purchase = actual = expected = offline = 0.0
    for (dist, tier), c in _cells(rows).items():
        if dist in off:
            offline += c["purchase"]
            e = c["app"]
        else:
            e = max(c["purchase"] * bench[tier]["share"], c["app"])
        purchase, actual, expected = purchase + c["purchase"], actual + c["app"], expected + e
    m = months or 1
    retailers = [r for r in rows if r["purchase"] > 0]
    linked = [r for r in retailers if r["td_retailer_id"]]
    # wallet share (window totals, as in the Way Forward deck): matched retailers = BO retailers linked to an app
    # retailer that has ever ordered on TD; TD share of their whole TechnoSport purchase (BO includes app orders)
    matched = [r for r in linked if r.get("td_ever")]
    w_td, w_bo = sum(r["app_sales"] for r in matched), sum(r["purchase"] for r in matched)
    return {"bo_purchase": round(purchase / m, 2), "td_actual": round(actual / m, 2),
            "td_expected": round(expected / m, 2), "gap": round((expected - actual) / m, 2),
            "offline_only_bo": round(offline / m, 2), "td_share_pct": _pct(actual, purchase), "expected_share_pct": _pct(expected, purchase),
            "bo_retailers": len(retailers), "on_td": len(linked),
            "td_buyers": sum(1 for r in linked if r["app_sales"] > 0),
            "wallet_retailers": len(matched), "wallet_td": round(w_td, 2), "wallet_bo": round(w_bo, 2),
            "wallet_gap": round(w_bo - w_td, 2), "wallet_pct": _pct(w_td, w_bo)}


def wallet_by_quarter(f, w):
    """Blended TD wallet share per quarter: TD sales / BO purchase of the matched retailers (BO retailers linked to an
    app retailer that has ever ordered on TD), within the user's filters and scope - the Way Forward deck's measure.
    BO purchase includes app orders, so this is how much of their TechnoSport buying runs through the app."""
    from django.db.models.functions import TruncMonth

    from warehouse.models import BoRetailerMonth, Order

    links = dict(retailers_qs(f, w).filter(td_retailer_id__isnull=False, td_retailer__first_order_date__isnull=False)
                 .values_list("id", "td_retailer_id"))
    if not links:
        return []
    bo = defaultdict(float)  # (td retailer, quarter) -> BO purchase (all its BO records)
    for bid, m, v in BoRetailerMonth.objects.filter(bo_retailer_id__in=list(links)).values_list(
            "bo_retailer_id", "month", "value"):
        bo[(links[bid], quarter_start(m))] += float(v)
    first, last = data_range()
    td = defaultdict(float)
    for rid, m, v in (Order.objects.filter(is_qualifying=True, retailer_id__in=set(links.values()),
                                           placed_date__gte=quarter_start(first),
                                           placed_date__lte=add_months(quarter_start(last), 3) - dt.timedelta(days=1))
                      .annotate(m=TruncMonth("placed_date")).values_list("retailer_id", "m").annotate(s=Sum("gross_value"))):
        td[(rid, quarter_start(m.date() if hasattr(m, "date") else m))] += float(v or 0)
    per_q = defaultdict(lambda: {"retailers": 0, "td": 0.0, "bo": 0.0})
    for key in set(bo) | set(td):
        a = per_q[key[1]]
        a["retailers"] += 1
        a["td"] += td.get(key, 0.0)
        a["bo"] += bo.get(key, 0.0)
    return [{"quarter": fy_quarter_label(q), "start": q.isoformat(), "retailers": a["retailers"],
             "td": round(a["td"], 2), "bo": round(a["bo"], 2), "gap": round(a["bo"] - a["td"], 2),
             "wallet_pct": _pct(a["td"], a["bo"])}
            for q, a in sorted(per_q.items()) if a["bo"] > 0 and q >= min((k for k, x in per_q.items() if x["td"] > 0),
                                                                         default=q)]  # from TD's first quarter


def potential(f, group_by="tier"):
    """TD actual vs expected by BlueOrigin tier, and the same rolled up by tier / region / RSM / ASM / state /
    distributor (BO's own hierarchy). Monthly averages over the BO window."""
    from warehouse.models import Asm, Distributor, Order, Region, Rsm, State

    from .rsm import region_rsm_map

    w = window(f)
    if w is None:
        return {"available": False}
    bench = benchmarks(w)
    off = _offline_only()
    rows = list(frame(f, w).values())
    months = w["months"]
    by_tier = []
    for t in TIERS:
        s = _expected([r for r in rows if r["tier"] == t], bench, months, off)
        s.update(tier=t, benchmark_pct=round(bench[t]["share"] * 100, 1), benchmark_cells=bench[t]["cells"],
                 benchmark_basis=bench[t]["basis"])
        by_tier.append(s)
    # TD retailers not found in BlueOrigin: actual only (no BO purchase to measure against)
    end_day = add_months(w["end"], 1) - dt.timedelta(days=1)
    not_bo = f.orders(start=w["start"], end=end_day).filter(retailer__tier="").aggregate(s=Sum("gross_value"))["s"]
    not_in_bo = round(float(not_bo or 0) / (months or 1), 2) if (not f.tiers or "None" in f.tiers) else 0.0

    group_by = group_by if group_by in GROUPS else "asm"
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
    for r in rows:
        groups[key(r)].append(r)
    out = []
    for k, rs in groups.items():
        s = _expected(rs, bench, months, off)
        if not s["bo_purchase"] and not s["td_actual"]:
            continue
        s.update(id=k, name=names.get(k) or ("Unassigned" if group_by in ("asm", "rsm") else "Unknown"),
                 gap_by_tier={t: _expected([r for r in rs if r["tier"] == t], bench, months, off)["gap"] for t in TIERS})
        out.append(s)
    out.sort(key=lambda x: -x["gap"])
    return {"available": True, "window": window_meta(w), "by_tier": by_tier, "total": _expected(rows, bench, months, off),
            "not_in_bo_td": not_in_bo, "group_by": group_by, "rows": out,
            "wallet_by_quarter": wallet_by_quarter(f, w),
            "method": {"percentile": int(BENCH_PCTL * 100), "min_monthly": BENCH_MIN_MONTHLY,
                       "min_retailers": BENCH_MIN_RETAILERS}}
