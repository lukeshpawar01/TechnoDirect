"""Monthly Business Review (MBR) page 1 and the page 2 goal maths: one month of TD, measured the same way every month.

The month reviewed (`month`, default this month) is compared like for like:
  - a finished month with the whole previous month and the same month last year;
  - the month in progress (days 1..N) with days 1..N of the previous month and of the same month last year,
    plus a month-end projection at the current run rate.

Business metrics come from the qualifying orders (the sales basis used everywhere). Product metrics follow the
retailer journey on the app: KYC (sign-up date stands in for the approval date, as on the Retailer Funnel), first
order, repeat, plus fulfilment quality. Targets are the Targets admin values (sales / orders / new / active retailers).

All of it is computed from one pull of orders, one of all orders (any status) and one of retailers, in Python, so
the 12-month trends cost no extra queries.
"""
import datetime as dt
import math
from collections import defaultdict

from django.utils import timezone

from accounts.scope import DISTRIBUTOR_DIMS
from warehouse.models import Distributor, Region

from .filters import add_months, month_end, month_start, quarter_start
from .metrics import delta_pct, median, num, pct, ratio, target_by_month, target_values

GOAL_DEFAULT = 100_000_000  # ₹10 Cr per month


def month_label(m):
    return m.strftime("%b %Y")


def window(m, days, today):
    """Days 1..days of month m (whole month when days is None), never past today."""
    end = month_end(m) if days is None else min(month_end(m), m + dt.timedelta(days=days - 1))
    return m, min(end, today)


class MonthData:
    """Raw rows for months [lo, hi], indexed for fast windows."""

    def __init__(self, f, lo, hi):
        self.lo, self.hi = lo, hi
        self.orders = list(f.orders(start=lo, end=hi).values_list(
            "retailer_id", "split_group", "placed_date", "gross_value", "units", "distributor_id", "region_id",
            "retailer__first_order_date", "state_id", "asm_id", "asm__rsm_id"))
        self.all_orders = list(f.orders(start=lo, end=hi, qualifying=False).values_list(
            "placed_date", "gross_value", "status", "placed_at", "delivered_at"))
        from .views.funnel import retailer_base

        tz = timezone.get_current_timezone()
        self.retailers = [
            (timezone.localtime(su, tz).date() if su else None, k, fo)
            for su, k, fo in retailer_base(f).values_list("signed_up_at", "kyc_status", "first_order_date")]

    # -- order windows
    def rows(self, s, e):
        return [r for r in self.orders if s <= r[2] <= e]

    def active(self, s, e):
        return {r[0] for r in self.rows(s, e) if r[0]}

    def kyc_base(self, e):
        """KYC-approved retailers signed up by e."""
        return sum(1 for su, k, _ in self.retailers if k == "approved" and su and su <= e)

    def metrics(self, s, e, prev_active):
        """Every scorecard metric for the window [s, e]. prev_active = retailers active in the month before."""
        rows = self.rows(s, e)
        sales = sum(float(r[3] or 0) for r in rows)
        orders = len({r[1] for r in rows})
        units = sum(int(r[4] or 0) for r in rows)
        active = {r[0] for r in rows if r[0]}
        new = {r[0] for r in rows if r[0] and r[7] and s <= r[7] <= e}
        distributors = len({r[5] for r in rows if r[5]})
        retained = active & prev_active
        reactivated = active - new - prev_active
        kyc_base = self.kyc_base(e)
        kyc_new = [(su, fo) for su, k, fo in self.retailers if k == "approved" and su and s <= su <= e]
        ants = sum(1 for su, k, fo in self.retailers if k == "approved" and su and su <= e and (not fo or fo > e))
        allr = [r for r in self.all_orders if s <= r[0] <= e]
        all_value = sum(float(r[1] or 0) for r in allr)
        cancelled = sum(float(r[1] or 0) for r in allr if r[2] == "cancelled")
        days = [(r[4] - r[3]).total_seconds() / 86400 for r in allr if r[2] == "delivered" and r[3] and r[4]
                and r[4] >= r[3]]
        return {
            "sales": num(sales), "orders": orders, "units": units, "active_retailers": len(active),
            "new_retailers": len(new), "repeat_retailers": len(active) - len(new),
            "aov": ratio(sales, orders), "spend_per_retailer": ratio(sales, len(active)),
            "units_per_order": ratio(units, orders), "active_distributors": distributors,
            "kyc_new": len(kyc_new),
            "kyc_to_order_pct": pct(sum(1 for _, fo in kyc_new if fo and fo <= e), len(kyc_new)),
            "kyc_base": kyc_base, "adoption_pct": pct(len(active), kyc_base), "ants": ants,
            "retention_pct": pct(len(retained), len(prev_active)), "reactivated": len(reactivated),
            "cancel_pct": pct(cancelled, all_value), "delivery_days": median(days),
            "_active": active,
        }


# key, label, group, format, higher is better, target metric, definition
ROWS = [
    ("sales", "Sales (GMV)", "business", "inr", True, "sales", "Value of qualifying (paid) orders placed"),
    ("orders", "Orders", "business", "num", True, "orders", "Carts placed (a split cart counts once)"),
    ("aov", "Average order value", "business", "inr", True, None, "Sales ÷ orders"),
    ("active_retailers", "Transacting retailers", "business", "num", True, "active_retailers",
     "Retailers with at least one order in the month"),
    ("new_retailers", "New transacting retailers", "business", "num", True, "new_retailers",
     "First-ever order this month"),
    ("repeat_retailers", "Repeat retailers", "business", "num", True, None, "Transacting retailers who had ordered before"),
    ("spend_per_retailer", "Sales per transacting retailer", "business", "inr", True, None, "Sales ÷ transacting retailers"),
    ("active_distributors", "Distributors with sales", "business", "num", True, None, "Distributors who received an order"),
    ("units_per_order", "Units per order", "business", "dec", True, None, "Units ÷ orders"),
    ("kyc_new", "New KYC approved", "product", "num", True, None,
     "Retailers signed up this month whose KYC is approved (sign-up date stands in for approval)"),
    ("kyc_to_order_pct", "KYC → first order (same month)", "product", "pct", True, None,
     "Of this month's new KYC retailers, % who placed a first order by month end"),
    ("adoption_pct", "Adoption: KYC base transacting", "product", "pct", True, None,
     "Transacting retailers ÷ all KYC-approved retailers at month end"),
    ("ants", "KYC done, never ordered", "product", "num", False, None, "KYC-approved by month end with no order yet"),
    ("retention_pct", "Month-on-month retention", "product", "pct", True, None,
     "Of last month's transacting retailers, % who ordered again this month"),
    ("reactivated", "Reactivated retailers", "product", "num", True, None,
     "Ordered this month, not last month, and not new"),
    ("cancel_pct", "Cancelled (% of value placed)", "product", "pct", False, None, "Cancelled order value ÷ all order value placed"),
    ("delivery_days", "Order to delivery (median days)", "product", "dec", False, None, "Placed to delivered, delivered orders"),
]
FLOW = {"sales", "orders", "units"}  # values that add up over days: projected at the run rate


def scorecard(f, month):
    today = f.today
    m = month_start(month)
    partial = month_end(m) > today
    days = (today - m).days + 1 if partial else None
    days_total = (month_end(m) - m).days + 1
    lo, hi = add_months(m, -13), min(month_end(m), today)
    data = MonthData(f, lo, hi)

    def win(mm):
        return window(mm, days, today)

    def prev_active_for(mm):  # active in the whole month before mm
        p = add_months(mm, -1)
        return data.active(p, month_end(p))

    cur_s, cur_e = win(m)
    pm, ly = add_months(m, -1), add_months(m, -12)
    cur = data.metrics(cur_s, cur_e, prev_active_for(m))
    prv = data.metrics(*win(pm), prev_active_for(pm))
    yoy = data.metrics(*win(ly), prev_active_for(ly)) if ly >= data.lo else None
    has_yoy = bool(yoy and yoy["orders"])

    # 12-month trend (whole months; the month reviewed is month-to-date when in progress)
    trend_months = [add_months(m, -i) for i in range(11, -1, -1)]
    trend = []
    for mm in trend_months:
        s, e = mm, min(month_end(mm), today)
        trend.append({"month": mm.isoformat()[:7], **{k: v for k, v in data.metrics(s, e, prev_active_for(mm)).items()
                                                       if not k.startswith("_")}})

    tmaps = {metric: target_by_month(f, trend_months, metric) for metric in ("sales", "orders", "new_retailers",
                                                                             "active_retailers")}
    for t in trend:
        mm = dt.date.fromisoformat(t["month"] + "-01")
        t["target_sales"] = num(tmaps["sales"].get(mm)) if tmaps["sales"].get(mm) else None

    rows = []
    for key, label, group, fmt, up, tmetric, definition in ROWS:
        v = cur[key]
        target = tmaps.get(tmetric, {}).get(m) if tmetric and f.targets_comparable else None
        target = float(target) if target else None
        projected = num(v / days * days_total) if partial and key in FLOW and days else None
        best = projected if projected is not None else v
        rows.append({
            "key": key, "label": label, "group": group, "format": fmt, "higher_is_better": up,
            "definition": definition, "value": v, "prev": prv[key], "mom_pct": _change(v, prv[key], fmt),
            "last_year": yoy[key] if has_yoy else None, "yoy_pct": _change(v, yoy[key], fmt) if has_yoy else None,
            "target": num(target) if target else None, "achievement_pct": pct(v, target) if target else None,
            "projected": projected, "projected_pct": pct(projected, target) if target and projected else None,
            "status": _status(best, target, partial and key not in FLOW),
            "trend": [t[key] for t in trend],
        })

    sales_row = rows[0]
    headline = {
        "sales": cur["sales"], "target": sales_row["target"], "achievement_pct": sales_row["achievement_pct"],
        "projected": sales_row["projected"], "projected_pct": sales_row["projected_pct"],
        "mom_pct": sales_row["mom_pct"], "yoy_pct": sales_row["yoy_pct"], "status": sales_row["status"],
        "run_rate_per_day": num(cur["sales"] / days) if partial and days else num(cur["sales"] / days_total),
        "required_per_day": num(max((sales_row["target"] or 0) - cur["sales"], 0) / (days_total - days))
        if partial and sales_row["target"] and days < days_total else None,
    }
    return {
        "month": m.isoformat()[:7], "label": month_label(m), "partial": partial, "days_elapsed": days or days_total,
        "days_total": days_total, "as_of": cur_e.isoformat(),
        "compare": {"prev": _window_label(*win(pm)), "last_year": _window_label(*win(ly)) if has_yoy else None,
                    "current": _window_label(cur_s, cur_e)},
        "targets_note": None if f.targets_comparable else "Targets are set per territory, so they are not shown with a tier or segment filter.",
        "headline": headline, "rows": rows, "trend": trend,
        "territory": territory(f, data, m, win, tmaps if f.targets_comparable else None),
        "movers": movers(data, (cur_s, cur_e), win(pm)),
        "_cur": cur, "_trend": trend,
    }


def _change(v, prev, fmt):
    """% change; percentage-point difference for rates."""
    if v is None or prev is None:
        return None
    if fmt == "pct":
        return round(float(v) - float(prev), 2)
    return delta_pct(v, prev)


def _status(value, target, not_comparable_yet):
    if not target:
        return None
    if not_comparable_yet:
        return "in_progress"
    a = (value or 0) / target * 100
    return "good" if a >= 100 else "warn" if a >= 90 else "bad"


def _window_label(s, e):
    if s.day == 1 and e == month_end(s):
        return month_label(s)
    return f"{s.day}–{e.day} {s:%b %Y}"


TERRITORY_DIMS = ("region", "rsm", "state", "asm")


def territory(f, data, m, win, tmaps):
    """Sales vs target for the month, by region / RSM / state / ASM ({dim: rows}) - the page-1 card's switch.
    RSM = the order's ASM's RSM, else the RSM heading its region (as everywhere else, analytics/rsm.py)."""
    from warehouse.models import Asm, Rsm, State

    from .rsm import region_rsm_map

    reg_rsm = region_rsm_map()
    key = {"region": lambda r: r[6], "state": lambda r: r[8], "asm": lambda r: r[9],
           "rsm": lambda r: r[10] or reg_rsm.get(r[6])}
    models_ = {"region": Region, "rsm": Rsm, "state": State, "asm": Asm}
    s, e = win(m)
    ps, pe = win(add_months(m, -1))
    cur_rows, prev_rows = data.rows(s, e), data.rows(ps, pe)
    allowed = None
    if tmaps is not None:
        allowed = list(Distributor.objects.filter(f.dims_q(DISTRIBUTOR_DIMS, retailer_field=None)).values_list(
            "region_id", "state_id", "asm_id", "asm__rsm_id"))
    out = {}
    for dim in TERRITORY_DIMS:
        k = key[dim]
        cur, prev, active = defaultdict(float), defaultdict(float), defaultdict(set)
        for r in cur_rows:
            cur[k(r)] += float(r[3] or 0)
            if r[0]:
                active[k(r)].add(r[0])
        for r in prev_rows:
            prev[k(r)] += float(r[3] or 0)
        targets = {}
        if allowed is not None:
            pick = {"region": lambda a: a[0], "state": lambda a: a[1], "asm": lambda a: a[2],
                    "rsm": lambda a: a[3] or reg_rsm.get(a[0])}[dim]
            ids = {pick(a) for a in allowed}
            ids = {i for i in ids if i}
            targets = {tid: float(v) for (tid, mm), v in target_values(dim, list(ids), [m], as_of=f.today).items() if v}
        keys = {i for i in set(cur) | set(targets) if cur.get(i) or targets.get(i)}
        names = dict(models_[dim].objects.filter(id__in=[i for i in keys if i]).values_list("id", "name"))
        rows = []
        for tid in keys:
            t = targets.get(tid)
            rows.append({"id": tid, "name": names.get(tid, "Unmapped"), "sales": num(cur.get(tid)),
                         "target": num(t) if t else None, "achievement_pct": pct(cur.get(tid), t) if t else None,
                         "prev": num(prev.get(tid)),
                         "mom_pct": delta_pct(cur.get(tid, 0), prev.get(tid)) if prev.get(tid) else None,
                         "active_retailers": len(active.get(tid, ()))})
        rows.sort(key=lambda r: -r["sales"])
        out[dim] = rows
    return out


def movers(data, cur_w, prev_w, n=5):
    cur, prev = defaultdict(float), defaultdict(float)
    for r in data.rows(*cur_w):
        cur[r[5]] += float(r[3] or 0)
    for r in data.rows(*prev_w):
        prev[r[5]] += float(r[3] or 0)
    ids = (set(cur) | set(prev)) - {None}
    names = dict(Distributor.objects.filter(id__in=ids).values_list("id", "name"))
    rows = [{"id": i, "name": names.get(i, "?"), "sales": num(cur.get(i)), "prev": num(prev.get(i)),
             "change": num(cur.get(i, 0) - prev.get(i, 0))} for i in ids]
    rows.sort(key=lambda r: -r["change"])
    return {"up": [r for r in rows if r["change"] > 0][:n], "down": [r for r in reversed(rows) if r["change"] < 0][:n]}


# ----------------------------------------------------------------------------- page 2: the path to the goal
def default_goal_by(today):
    """Last month of the next FY quarter."""
    nq = add_months(quarter_start(today), 3)
    return add_months(nq, 2)


def path_to_goal(f, card, goal, goal_by):
    """How far the latest complete month is from the goal and what adoption it takes, at today's spend."""
    trend = card["_trend"]
    full = [t for t in trend if not (card["partial"] and t["month"] == card["month"])]
    base = full[-1] if full else trend[-1]
    last3 = full[-3:] or [base]
    spend = sum(t["sales"] for t in last3) / max(sum(t["active_retailers"] for t in last3), 1)
    goal = float(goal)
    needed = math.ceil(goal / spend) if spend else None
    active = base["active_retailers"]
    base_m = dt.date.fromisoformat(base["month"] + "-01")
    months_left = max((goal_by.year - base_m.year) * 12 + goal_by.month - base_m.month, 1)
    growth = (goal / base["sales"]) ** (1 / months_left) - 1 if base["sales"] else None
    kyc_base, ants = card["_cur"]["kyc_base"], card["_cur"]["ants"]

    from .views.funnel import retailer_base, techno_base

    saved = (f.period.start, f.period.end)
    f.period.start, f.period.end = month_start(f.today), f.today
    try:
        tb = techno_base(f, retailer_base(f))
    finally:
        f.period.start, f.period.end = saved
    gap = max((needed or 0) - active, 0)
    scenarios = [{"spend_uplift_pct": u, "spend": num(spend * (1 + u / 100)),
                  "retailers_needed": math.ceil(goal / (spend * (1 + u / 100))) if spend else None}
                 for u in (0, 10, 20, 30, 50)]
    for s in scenarios:
        s["adoption_needed_pct"] = pct(s["retailers_needed"], kyc_base) if s["retailers_needed"] else None
        s["extra_retailers"] = max((s["retailers_needed"] or 0) - active, 0)
    return {
        "goal": num(goal), "goal_by": goal_by.isoformat()[:7], "goal_by_label": month_label(goal_by),
        "base_month": base["month"], "base_label": month_label(base_m), "base_sales": base["sales"],
        "gap_sales": num(max(goal - base["sales"], 0)), "goal_pct": pct(base["sales"], goal),
        "months_left": months_left, "monthly_growth_needed_pct": round(growth * 100, 1) if growth is not None else None,
        "spend_per_retailer": num(spend), "active_retailers": active, "retailers_needed": needed,
        "retailers_gap": gap, "kyc_base": kyc_base, "adoption_pct": base["adoption_pct"],  # same basis as page 1
        "adoption_needed_pct": pct(needed, kyc_base) if needed else None, "ants": ants,
        "ants_share_of_gap_pct": pct(gap, ants) if ants else None,
        "techno_universe": tb["universe"], "techno_transacting": tb["bo_transacting"],
        "techno_not_transacting": tb["universe"] - tb["bo_transacting"],
        "techno_adoption_pct": tb["bo_transacting_pct"],
        "scenarios": scenarios,
        "adoption_trend": [{"month": t["month"], "adoption_pct": t["adoption_pct"], "active_retailers": t["active_retailers"],
                            "kyc_base": t["kyc_base"], "sales": t["sales"]} for t in trend],
    }

