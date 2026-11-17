"""Retailer segments over time (Retailers page, "Segment trends").

Buckets follow a grain (day / week / month / FY quarter) and end at the selected period's end; the last bucket may be
running (partial). For every bucket:

Lifecycle (flows within the bucket; same rules as the monthly Retention movement, generalised to any grain)
    active       >= 1 valid order in the bucket
    new          first-ever valid order falls in the bucket
    retained     active in this bucket and in the previous one
    reactivated  active, not active in the previous bucket, and not new
    lost         active in the previous bucket, not in this one
Lifecycle (state as of the bucket end)
    one_time / repeat         1 / 2+ valid orders up to the bucket end
    inactive_30 / 60 / 90     last order 30-59 / 60-89 / 90+ days before the bucket end
    never_ordered             signed up by the bucket end, no valid order by then
RFM (state as of the bucket end): analytics.rfm.compute(as_of=bucket end) - same rules as the RFM panel.

Valid order = qualifying (paid, not cancelled) with value > 0, as in RFM. Region / ASM / distributor filters choose the
retailers counted; RFM ranking stays global.
"""
import datetime as dt
from collections import defaultdict

from django.utils import timezone

from . import rfm
from .filters import add_months

GRAINS = ("day", "week", "month", "quarter")
DEFAULT_COUNT = {"day": 30, "week": 13, "month": 12, "quarter": 8}
FLOW_KEYS = ["new", "retained", "reactivated", "lost", "active"]
STATE_KEYS = ["one_time", "repeat", "inactive_30", "inactive_60", "inactive_90", "never_ordered"]


def default_grain(preset, start, end):
    """Grain that fits the selected period."""
    if preset in ("today", "yesterday"):
        return "day"
    if preset in ("wtd", "last_week", "last_7d", "last_30d"):
        return "week"
    if preset in ("q1", "q2", "q3", "q4", "qtd"):
        return "quarter"
    if preset == "custom":
        n = (end - start).days + 1
        return "day" if n <= 14 else "week" if n <= 92 else "month"
    return "month"


def bucket_start(d, grain):
    if grain == "day":
        return d
    if grain == "week":
        return d - dt.timedelta(days=d.weekday())  # Monday
    if grain == "month":
        return d.replace(day=1)
    q = 10 if d.month >= 10 else 7 if d.month >= 7 else 4 if d.month >= 4 else 1  # FY quarters: Apr, Jul, Oct, Jan
    return dt.date(d.year, q, 1)


def step(d, grain, k):
    if grain == "day":
        return d + dt.timedelta(days=k)
    if grain == "week":
        return d + dt.timedelta(weeks=k)
    return add_months(d, k * (1 if grain == "month" else 3))


def buckets(end, grain, count):
    """[(start, end_inclusive, partial)] oldest first; the last bucket ends at `end`."""
    first = bucket_start(end, grain)
    out = []
    for k in range(count - 1, -1, -1):
        s = step(first, grain, -k)
        e = step(s, grain, 1) - dt.timedelta(days=1)
        out.append((s, min(e, end), e > end))
    return out


def label(s, grain):
    if grain == "day":
        return s.strftime("%d %b")
    if grain == "week":
        return "Wk " + s.strftime("%d %b")
    if grain == "month":
        return s.strftime("%b-%y")
    fy = s.year if s.month >= 4 else s.year - 1
    q = {4: 1, 7: 2, 10: 3, 1: 4}[s.month]
    return f"Q{q} FY{str(fy + 1)[-2:]}"


def _signups_by(retailer_ids, ends):
    """{bucket end: retailers in scope signed up by then} - one pass over the table for all bucket ends."""
    from django.db.models import Count, Q

    from warehouse.models import Retailer

    qs = Retailer.objects.filter(id__in=retailer_ids) if retailer_ids is not None else Retailer.objects.all()
    aggs = {"none": Count("id", filter=Q(signed_up_at__isnull=True))}
    for i, e in enumerate(ends):
        cut = timezone.make_aware(dt.datetime.combine(e + dt.timedelta(days=1), dt.time.min))
        aggs[f"b{i}"] = Count("id", filter=Q(signed_up_at__lt=cut))
    r = qs.aggregate(**aggs)
    return {e: r[f"b{i}"] + r["none"] for i, e in enumerate(ends)}


def lifecycle(orders, bks, grain, scope=None, signup_scope=None):
    """{key: [count per bucket]} for FLOW_KEYS + STATE_KEYS."""
    first_day = {}
    days = defaultdict(list)
    for rid, d, _, v in orders:
        if scope is not None and rid not in scope:
            continue
        days[rid].append(d)
    for rid, ds in days.items():
        ds.sort()
        first_day[rid] = ds[0]
    # previous bucket of the first one is needed for retained / reactivated / lost
    prev0 = step(bks[0][0], grain, -1)
    allb = [(prev0, bks[0][0] - dt.timedelta(days=1), False)] + list(bks)
    active = []
    for s, e, _ in allb:
        active.append({rid for rid, ds in days.items() if any(s <= x <= e for x in ds)})
    signed = _signups_by(signup_scope, [e for _, e, _ in bks])
    out = {k: [] for k in FLOW_KEYS + STATE_KEYS}
    for i, (s, e, _) in enumerate(bks, start=1):
        cur, prev = active[i], active[i - 1]
        new = {r for r in cur if s <= first_day[r] <= e}
        out["active"].append(len(cur))
        out["new"].append(len(new))
        out["retained"].append(len(cur & prev))
        out["reactivated"].append(len(cur - prev - new))
        out["lost"].append(len(prev - cur))
        n_orders = {r: sum(1 for x in ds if x <= e) for r, ds in days.items() if first_day[r] <= e}
        out["one_time"].append(sum(1 for n in n_orders.values() if n == 1))
        out["repeat"].append(sum(1 for n in n_orders.values() if n >= 2))
        gaps = [(e - max(x for x in days[r] if x <= e)).days for r in n_orders]
        out["inactive_30"].append(sum(1 for g in gaps if 30 <= g < 60))
        out["inactive_60"].append(sum(1 for g in gaps if 60 <= g < 90))
        out["inactive_90"].append(sum(1 for g in gaps if g >= 90))
        out["never_ordered"].append(max(signed[e] - len(n_orders), 0))
    return out


def rfm_series(orders, bks, scope=None):
    """{segment: [count per bucket]} from an RFM snapshot at each bucket end (prospects left out)."""
    out = {k: [] for k in rfm.SEGMENTS if k != "prospect"}
    for _, e, _ in bks:
        rows = rfm.compute(as_of=e, orders=orders)["rows"]
        cnt = defaultdict(int)
        for rid, r in rows.items():
            if scope is None or rid in scope:
                cnt[r["segment"]] += 1
        for k in out:
            out[k].append(cnt.get(k, 0))
    return out


def trend(f, grain=None, count=None, kind="rfm"):
    """Payload for /retailers/segment-trend/."""
    from .views.funnel import retailer_base

    orders = rfm.load_orders()
    latest = max((o[1] for o in orders), default=f.today)
    # never past the last day with data: a day whose orders have not arrived yet would read as everyone "lost"
    end = min(f.period.end, f.today, latest)
    grain = grain if grain in GRAINS else default_grain(f.period.preset, f.period.start, f.period.end)
    try:
        count = max(2, min(int(count or DEFAULT_COUNT[grain]), 60))
    except ValueError:
        count = DEFAULT_COUNT[grain]
    bks = buckets(end, grain, count)
    scope = set(retailer_base(f).filter(orders_count__gt=0).values_list("id", flat=True))
    signup_scope = retailer_base(f).values("id")

    # same buckets one year earlier, for the "same period last year" comparison of the latest bucket
    # same buckets one year earlier (for the chart's last-year line and the latest bucket's comparison);
    # weeks / days shift by 52 weeks / 364 days so weekdays line up
    if grain in ("month", "quarter"):
        ly_end = add_months(end, -12)
    else:
        ly_end = end - dt.timedelta(days=364)
    ly = buckets(ly_end, grain, count)
    if kind == "lifecycle":
        series = lifecycle(orders, bks, grain, scope, signup_scope)
        ly_series = lifecycle(orders, ly, grain, scope, signup_scope)
    else:
        kind = "rfm"
        series = rfm_series(orders, bks, scope)
        ly_series = rfm_series(orders, ly, scope)
    first_data = min((o[1] for o in orders), default=end)
    ly_has_data = [e >= first_data for _, e, _ in ly]
    # a running bucket (e.g. 1-17 Nov) is compared like-for-like: the previous bucket cut at the same day offset
    prev_series = None
    if bks[-1][2] and kind == "lifecycle":
        offset = (end - bks[-1][0]).days
        prev_start = bks[-2][0]
        lfl = buckets(min(prev_start + dt.timedelta(days=offset), bks[-2][1]), grain, 2)
        prev_series = lifecycle(orders, lfl, grain, scope, signup_scope)
    rows = []
    for k, vals in series.items():
        now = vals[-1]
        prev = prev_series[k][-1] if prev_series else (vals[-2] if len(vals) > 1 else None)
        last_year = ly_series[k][-1] if ly_series.get(k) and ly_has_data[-1] else None
        rows.append({"key": k, "now": now, "prev": prev, "last_year": last_year})
    return {
        "kind": kind, "grain": grain, "as_of": end.isoformat(), "data_until": latest.isoformat(),
        "buckets": [{"start": s.isoformat(), "end": e.isoformat(), "label": label(s, grain), "partial": p}
                    for s, e, p in bks],
        "series": series,
        # null where the year-ago bucket predates the data
        "last_year": {k: [v if ok else None for v, ok in zip(vals, ly_has_data)] for k, vals in ly_series.items()},
        "compare": {"now_label": label(bks[-1][0], grain), "prev_label": label(bks[-2][0], grain),
                    "like_for_like": bool(prev_series), "running": bks[-1][2],
                    # day / week labels carry no year: add it, or "vs 17 Nov" reads like a future date
                    "last_year_label": label(ly[-1][0], grain) + (ly[-1][0].strftime(" %y") if grain in ("day", "week") else ""),
                    "rows": rows},
    }
