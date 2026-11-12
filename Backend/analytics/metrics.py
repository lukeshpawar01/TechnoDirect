"""Shared metric helpers used by analytics views."""
import datetime as dt
import statistics
from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncMonth

from warehouse.models import Target

from .filters import add_months, month_end, month_start, months_between


# ----------------------------------------------------------------------------- number helpers
def num(x, nd=2):
    if x is None:
        return 0.0
    return round(float(x), nd)


def ratio(a, b, nd=2):
    a, b = float(a or 0), float(b or 0)
    return round(a / b, nd) if b else 0.0


def pct(a, b, nd=2):
    """a as % of b (0-100). None when b is 0."""
    a, b = float(a or 0), float(b or 0)
    return round(a * 100.0 / b, nd) if b else None


def share(a, total, nd=2):
    return pct(a, total, nd) or 0.0


def delta_pct(cur, prev, nd=2):
    if prev is None:
        return None
    cur, prev = float(cur or 0), float(prev or 0)
    return round((cur - prev) * 100.0 / prev, nd) if prev else None


def mkey(d):
    if isinstance(d, dt.datetime):
        d = d.date()
    return d.strftime("%Y-%m")


def as_date(d):
    return d.date() if isinstance(d, dt.datetime) else d


def median(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 2) if values else None


def fmt_inr(v):
    v = float(v or 0)
    if abs(v) >= 1e7:
        return f"₹{v / 1e7:.2f} Cr"
    if abs(v) >= 1e5:
        return f"₹{v / 1e5:.2f} L"
    return f"₹{v:,.0f}"


def launch_month():
    return dt.date.fromisoformat(settings.LAUNCH_DATE)


# ----------------------------------------------------------------------------- order aggregates
ORDER_AGG = {
    "sales": Sum("gross_value"),
    "orders": Count("split_group", distinct=True),   # cart-level: split orders counted once
    "units": Sum("units"),
    "retailers": Count("retailer_id", distinct=True),
    "distributors": Count("distributor_id", distinct=True),
}


def agg_orders(qs):
    r = qs.aggregate(**ORDER_AGG)
    return {k: (float(v) if v is not None else 0.0) for k, v in r.items()}


def new_retailers_in(qs, start, end):
    """Distinct retailers in qs whose first-ever qualifying order date is within [start, end]."""
    return qs.filter(retailer__first_order_date__gte=start, retailer__first_order_date__lte=end).values(
        "retailer_id").distinct().count()


def monthly_orders(qs, start, end):
    """{month_start: {sales, orders, units, retailers, distributors, new}}"""
    rows = qs.filter(placed_date__gte=start, placed_date__lte=end).annotate(m=TruncMonth("placed_date")).values(
        "m").annotate(**ORDER_AGG)
    out = {}
    for r in rows:
        out[as_date(r["m"])] = {k: float(r[k] or 0) for k in ORDER_AGG}
    new_rows = (qs.filter(placed_date__gte=start, placed_date__lte=end)
                .annotate(m=TruncMonth("placed_date"), fm=TruncMonth("retailer__first_order_date"))
                .filter(m=F("fm")).values("m").annotate(n=Count("retailer_id", distinct=True)))
    for r in new_rows:
        out.setdefault(as_date(r["m"]), {k: 0.0 for k in ORDER_AGG})["new"] = float(r["n"])
    for v in out.values():
        v.setdefault("new", 0.0)
    return out


def spark(monthly, months, fn):
    return [num(fn(monthly.get(m, {})) or 0) for m in months]


def spark_months(end):
    last = month_start(end)
    return [add_months(last, -i) for i in range(11, -1, -1)]


# ----------------------------------------------------------------------------- targets
def target_scope(filters):
    if filters.distributors:
        return "distributor", filters.distributors
    if filters.asms:
        return "asm", filters.asms
    if filters.states:
        return "state", filters.states
    if filters.regions:
        return "region", filters.regions
    sc = filters.scope
    if sc.all:
        return "overall", None
    for t, ids in (("distributor", sc.distributors), ("asm", sc.asms), ("state", sc.states),
                   ("region", sc.regions)):
        if ids:
            return t, ids
    return None, None


def target_values(scope_type, ids, months, metric="sales", as_of=None):
    """{(scope_id, month): value} using the latest effective version per key."""
    if not scope_type or not months:
        return {}
    as_of = as_of or dt.date.today()
    qs = Target.objects.filter(scope_type=scope_type, metric=metric, month__in=months)
    if ids is not None:
        qs = qs.filter(scope_id__in=ids)
    best = {}
    for t in qs.values("scope_id", "month", "value", "effective_from", "version"):
        key = (t["scope_id"], t["month"])
        rank = (t["effective_from"] <= as_of, t["effective_from"], t["version"])
        if key not in best or rank > best[key][0]:
            best[key] = (rank, t["value"])
    return {k: v[1] for k, v in best.items()}


def target_by_month(filters, months, metric="sales"):
    st, ids = target_scope(filters)
    vals = target_values(st, ids, months, metric, filters.today)
    out = defaultdict(Decimal)
    for (_, m), v in vals.items():
        out[m] += v
    return dict(out)


def target_block(filters, base_qs):
    """Target vs achievement over the months spanned by the period (None if no target)."""
    p = filters.period
    months = months_between(p.start, p.end)
    tmap = target_by_month(filters, months)
    if not tmap:
        return None, {}
    total = float(sum(tmap.values()))
    range_start, range_end = months[0], month_end(months[-1])
    eff_end = min(p.end, filters.today)
    achieved = float(base_qs.filter(placed_date__gte=range_start, placed_date__lte=eff_end)
                     .aggregate(s=Sum("gross_value"))["s"] or 0)
    days_total = (range_end - range_start).days + 1
    days_elapsed = max(0, min((eff_end - range_start).days + 1, days_total))
    remaining = days_total - days_elapsed
    balance = max(total - achieved, 0.0)
    crr = achieved / days_elapsed if days_elapsed else 0.0
    return {
        "target": num(total),
        "achieved": num(achieved),
        "achievement_pct": share(achieved, total),
        "balance": num(balance),
        "days_elapsed": days_elapsed,
        "days_total": days_total,
        "current_run_rate": num(crr),
        "required_run_rate": num(balance / remaining) if remaining > 0 else 0.0,
        "projected": num(crr * days_total),
    }, tmap


def daily_target_rate(tmap):
    """{month: per-day target}"""
    out = {}
    for m, v in tmap.items():
        out[m] = float(v) / ((month_end(m) - m).days + 1)
    return out


__all__ = ["Q"]
