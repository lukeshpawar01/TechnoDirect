"""Order flow & delays (Orders & Fulfilment page).

Answers three questions a fulfilment analyst asks every morning:
  1. Flow   - how many orders came in, went out and arrived each day?
  2. Speed  - how many days do orders take from placed -> shipped (dispatch) and shipped -> delivered (transit)?
  3. Where  - which orders get delayed: by distributor, state, ASM, weekday placed, order size, cart type, payment
              mode or platform; ranked by how many late orders each group causes, not just its late rate.

The TD export records ship / delivery as calendar dates (no time of day), so lead times are whole days:
`0` = shipped the day it was placed. An order is late when it took longer than the SLA *or* is still waiting past
the SLA - counting only finished orders would hide exactly the orders that are stuck. Orders still "open" in the TD
data but placed before the open window (ORDER_OPEN_WINDOW_DAYS) are stale statuses, not waiting orders.

"Today" is the data date (the latest day with orders in the TD export), not the clock: the export lags a day or two
and measuring from the clock would make every recent order look late.
"""
import datetime as dt
from collections import defaultdict

from django.conf import settings
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from warehouse.models import Order

from ..metrics import median, pct
from .base import AnalyticsView

DIMENSIONS = {
    "distributor": "Distributor",
    "state": "State",
    "asm": "ASM",
    "weekday": "Day placed",
    "size": "Order size (units)",
    "cart": "Cart type",
    "payment_mode": "Payment mode",
    "platform": "Platform",
}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SIZE_BANDS = [("lt20", "Under 20 units", 0, 20), ("20_49", "20–49 units", 20, 50), ("50_99", "50–99 units", 50, 100),
              ("100p", "100+ units", 100, None)]
# lead-time buckets in days: (key, label, lo, hi) - hi exclusive, None = open-ended
LEAD_BUCKETS = [("0", "Same day", 0, 1), ("1", "1 day", 1, 2), ("2", "2 days", 2, 3), ("3", "3 days", 3, 4),
                ("4_6", "4–6 days", 4, 7), ("7p", "7+ days", 7, None)]
# a group needs this many orders before it can be called a hotspot (a 1-of-1 late rate is noise)
MIN_GROUP_ORDERS = 10


def dispatch_sla_days():
    return max(1, round(settings.ORDER_DISPATCH_SLA_HOURS / 24))


def transit_sla_days():
    return settings.ORDER_TRANSIT_SLA_DAYS


def data_date(today=None):
    """The latest day with orders in the data (capped at today)."""
    from ..filters import today_ist

    today = today or today_ist()
    last = Order.objects.aggregate(m=Max("placed_date"))["m"]
    return min(last, today) if last else today


def _d(ts):
    return timezone.localtime(ts).date() if ts else None


def _size_key(units):
    for key, _, lo, hi in SIZE_BANDS:
        if units >= lo and (hi is None or units < hi):
            return key
    return SIZE_BANDS[-1][0]


def bucket_key(days):
    for key, _, lo, hi in LEAD_BUCKETS:
        if days >= lo and (hi is None or days < hi):
            return key
    return LEAD_BUCKETS[-1][0]


class LeadRow:
    """One non-cancelled order placed in the period, with its stage durations in days."""

    __slots__ = ("id", "placed", "shipped", "delivered", "dispatch_days", "transit_days", "waiting_dispatch",
                 "waiting_transit", "late_dispatch", "late_transit", "keys")

    def __init__(self, r, as_of, window_start, d_sla, t_sla):
        self.id = r["id"]
        self.placed = r["placed_date"]
        self.shipped = _d(r["shipped_at"])
        self.delivered = _d(r["delivered_at"])
        if self.shipped and self.shipped < self.placed:
            self.shipped = self.placed
        if self.delivered and self.shipped and self.delivered < self.shipped:
            self.delivered = self.shipped
        self.dispatch_days = (self.shipped - self.placed).days if self.shipped else None
        self.transit_days = (self.delivered - self.shipped).days if self.delivered and self.shipped else None
        # still waiting = not done yet and placed recently enough that the open status is believable
        live = self.placed >= window_start
        self.waiting_dispatch = (as_of - self.placed).days if not self.shipped and live else None
        self.waiting_transit = (as_of - self.shipped).days if self.shipped and not self.delivered and live else None
        self.late_dispatch = (self.dispatch_days is not None and self.dispatch_days > d_sla) or (
            self.waiting_dispatch is not None and self.waiting_dispatch > d_sla)
        self.late_transit = (self.transit_days is not None and self.transit_days > t_sla) or (
            self.waiting_transit is not None and self.waiting_transit > t_sla)
        units = r["units"] or 0
        self.keys = {
            "distributor": r["distributor_id"], "state": r["state_id"], "asm": r["asm_id"],
            "weekday": WEEKDAYS[self.placed.weekday()], "size": _size_key(units),
            "cart": "split" if r["is_split"] else "single",
            "payment_mode": r["payment_mode"] or "Unknown", "platform": r["platform"] or "Unknown",
        }


def lead_rows(f, as_of=None):
    """Non-cancelled orders placed in the selected period (all other page filters apply) as LeadRows."""
    as_of = as_of or data_date()
    window_start = as_of - dt.timedelta(days=settings.ORDER_OPEN_WINDOW_DAYS)
    d_sla, t_sla = dispatch_sla_days(), transit_sla_days()
    qs = f.orders(start=f.period.start, end=f.period.end, qualifying=False).exclude(status="cancelled")
    fields = ("id", "placed_date", "shipped_at", "delivered_at", "units", "is_split", "payment_mode", "platform",
              "distributor_id", "state_id", "asm_id")
    return [LeadRow(r, as_of, window_start, d_sla, t_sla) for r in qs.values(*fields)]


def _labels(dim, keys):
    from warehouse.models import Asm, Distributor, State

    ids = [k for k in keys if k is not None]
    if dim == "distributor":
        m = dict(Distributor.objects.filter(id__in=ids).values_list("id", "name"))
    elif dim == "state":
        m = dict(State.objects.filter(id__in=ids).values_list("id", "name"))
    elif dim == "asm":
        m = dict(Asm.objects.filter(id__in=ids).values_list("id", "name"))
    elif dim == "size":
        m = {k: lbl for k, lbl, _, _ in SIZE_BANDS}
    elif dim == "cart":
        m = {"split": "Split cart", "single": "Single cart"}
    elif dim == "weekday":
        m = dict(zip(WEEKDAYS, ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]))
    else:
        m = {}
    return {k: (m.get(k) or ("Not mapped" if k is None else str(k))) for k in keys}


def group_stats(rows, dim):
    groups = defaultdict(list)
    for r in rows:
        groups[r.keys[dim]].append(r)
    labels = _labels(dim, groups.keys())
    total_late_d = sum(r.late_dispatch for r in rows)
    total_late_t = sum(r.late_transit for r in rows)
    out = []
    for key, rs in groups.items():
        disp = [r.dispatch_days for r in rs if r.dispatch_days is not None]
        tran = [r.transit_days for r in rs if r.transit_days is not None]
        late_d = sum(r.late_dispatch for r in rs)
        late_t = sum(r.late_transit for r in rs)
        shipped_or_waiting = len(disp) + sum(r.waiting_dispatch is not None for r in rs)
        in_transit_base = len(tran) + sum(r.waiting_transit is not None for r in rs)
        late_any = sum(r.late_dispatch or r.late_transit for r in rs)
        out.append({
            "key": "none" if key is None else str(key),
            "label": labels[key],
            "orders": len(rs),
            "median_dispatch_days": median(disp),
            "late_dispatch": late_d,
            "late_dispatch_pct": pct(late_d, shipped_or_waiting),
            "median_transit_days": median(tran),
            "late_transit": late_t,
            "late_transit_pct": pct(late_t, in_transit_base),
            "late_orders": late_any,
            "late_pct": pct(late_any, len(rs)),
            # share of all the period's late dispatches / transits this group accounts for
            "late_dispatch_share": pct(late_d, total_late_d),
            "late_transit_share": pct(late_t, total_late_t),
        })
    # worst first: most late orders caused, then late rate
    out.sort(key=lambda g: (-g["late_orders"], -(g["late_pct"] or 0), g["label"]))
    return out


def _distribution(values, waiting, sla):
    counts = defaultdict(int)
    for v in values:
        counts[bucket_key(v)] += 1
    done = len(values)
    return {
        "buckets": [{"key": k, "label": lbl, "orders": counts[k], "late": lo >= sla + 1}
                    for k, lbl, lo, _ in LEAD_BUCKETS],
        "done": done,
        "median_days": median(values),
        "within_sla_pct": pct(sum(v <= sla for v in values), done),
        "waiting": len(waiting),
        "waiting_late": sum(w > sla for w in waiting),
    }


def _insights(rows, d_sla, t_sla, overall):
    """Plain-language findings, worst first. Each carries the drill params that list its orders."""
    out = []
    n = len(rows)
    if not n:
        return out
    base_d = overall["dispatch"]
    base_t = overall["transit"]
    # same base as each group's rate: orders shipped or still (believably) waiting
    late_d_rate = pct(sum(r.late_dispatch for r in rows), base_d["done"] + base_d["waiting"]) or 0
    late_t_rate = pct(sum(r.late_transit for r in rows), base_t["done"] + base_t["waiting"]) or 0

    stuck = [r for r in rows if r.waiting_dispatch is not None and r.waiting_dispatch > d_sla]
    if stuck:
        out.append({"tone": "bad", "text": f"{len(stuck)} orders are still not shipped {d_sla}+ days after being placed "
                                           f"(oldest waiting {max(r.waiting_dispatch for r in stuck)} days).",
                    "params": {"delay": "dispatch", "waiting": "1"}, "title": "Not shipped, past the dispatch SLA"})
    stuck_t = [r for r in rows if r.waiting_transit is not None and r.waiting_transit > t_sla]
    if stuck_t:
        out.append({"tone": "bad", "text": f"{len(stuck_t)} shipped orders are still not delivered after {t_sla}+ days "
                                           f"in transit.",
                    "params": {"delay": "transit", "waiting": "1"}, "title": "In transit, past the transit SLA"})

    seen = set()  # (stage, late count, orders): a one-distributor state repeats its distributor's finding

    for dim, stage, rate_base in (("distributor", "dispatch", late_d_rate), ("state", "transit", late_t_rate),
                                  ("distributor", "transit", late_t_rate), ("state", "dispatch", late_d_rate)):
        groups = [g for g in group_stats(rows, dim) if g["orders"] >= MIN_GROUP_ORDERS and g["key"] != "none"]
        groups.sort(key=lambda g: -g[f"late_{stage}"])
        for g in groups[:1]:
            rate = g[f"late_{stage}_pct"] or 0
            if g[f"late_{stage}"] < 3 or rate < max(2 * rate_base, rate_base + 10):
                continue
            sig = (stage, g[f"late_{stage}"], g["orders"])
            if sig in seen:
                continue
            seen.add(sig)
            med = g[f"median_{stage}_days"]
            what = "ship late" if stage == "dispatch" else "arrive late"
            sla = d_sla if stage == "dispatch" else t_sla
            out.append({
                "tone": "bad",
                "text": f"{g['label']}: {rate:.0f}% of orders {what} (more than {sla} days) vs {rate_base:.0f}% overall"
                        f" - {g[f'late_{stage}']} of {g['orders']} orders, median {_days(med)}; "
                        f"{(g[f'late_{stage}_share'] or 0):.0f}% of all late {'dispatches' if stage == 'dispatch' else 'deliveries'}.",
                "params": {"delay": stage, "group_by": dim, "group": g["key"]},
                "title": f"{g['label']} · late {stage}",
            })

    # structural patterns: weekday, split carts, order size
    phrase = {
        "weekday": lambda g: f"Orders placed on {g['label']}",
        "cart": lambda g: "Split-cart orders" if g["key"] == "split" else "Single-cart orders",
        "size": lambda g: "Orders under 20 units" if g["key"] == "lt20" else f"Orders of {g['label']}",
    }
    for dim in ("weekday", "cart", "size"):
        groups = [g for g in group_stats(rows, dim) if g["orders"] >= 3 * MIN_GROUP_ORDERS]
        if len(groups) < 2:
            continue
        worst = max(groups, key=lambda g: g["late_dispatch_pct"] or 0)
        best = min(groups, key=lambda g: g["late_dispatch_pct"] or 0)
        wr, br = worst["late_dispatch_pct"] or 0, best["late_dispatch_pct"] or 0
        if worst["late_dispatch"] >= 5 and wr >= max(2 * br, br + 8):
            out.append({
                "tone": "warn",
                "text": f"{phrase[dim](worst)} ship late {wr:.0f}% of the time vs {br:.0f}% for "
                        f"{phrase[dim](best)[0].lower() + phrase[dim](best)[1:]}.",
                "params": {"delay": "dispatch", "group_by": dim, "group": worst["key"]},
                "title": f"{worst['label']} · late dispatch",
            })

    if base_d["within_sla_pct"] is not None and not out:
        out.append({"tone": "good", "text": f"{base_d['within_sla_pct']:.0f}% of orders shipped within {d_sla} days and "
                                            f"{(base_t['within_sla_pct'] or 0):.0f}% arrived within {t_sla} days of "
                                            f"shipping - no group stands out.", "params": None, "title": ""})
    return out[:6]


def _days(v):
    if v is None:
        return "–"
    v = round(v, 1)
    return f"{v:g} day" + ("" if v == 1 else "s")


def daily_flow(f, as_of):
    """Orders received / shipped / delivered per day of the period (weekly beyond ~6 weeks)."""
    p = f.period
    end = min(p.end, as_of) if p.start <= as_of else p.end
    days = (end - p.start).days + 1
    weekly = days > 45
    # shipped / delivered are counted on the day they happen, so look back for orders placed before the period
    look_back = p.start - dt.timedelta(days=60)
    qs = f.orders(start=look_back, end=end, qualifying=False).exclude(status="cancelled")
    rec, shp, dlv = defaultdict(int), defaultdict(int), defaultdict(int)

    def slot(d):
        return d - dt.timedelta(days=d.weekday()) if weekly else d

    for placed, shipped, delivered in qs.values_list("placed_date", "shipped_at", "delivered_at"):
        if p.start <= placed <= end:
            rec[slot(placed)] += 1
        sd, dd = _d(shipped), _d(delivered)
        if sd and p.start <= sd <= end:
            shp[slot(sd)] += 1
        if dd and p.start <= dd <= end:
            dlv[slot(dd)] += 1
    slots, d = [], slot(p.start)
    while d <= end:
        slots.append(d)
        d += dt.timedelta(days=7 if weekly else 1)
    return {
        "granularity": "week" if weekly else "day",
        "points": [{"date": s.isoformat(), "received": rec[s], "shipped": shp[s], "delivered": dlv[s]} for s in slots],
    }


class FulfilmentFlowView(AnalyticsView):
    """GET /api/orders/flow/?group_by=distributor|state|asm|weekday|size|cart|payment_mode|platform"""

    permission_code = "view_orders"
    sources = ["supabase"]
    export_key = "hotspots.rows"

    def compute(self, f, request, **kw):
        dim = request.query_params.get("group_by") or "distributor"
        if dim not in DIMENSIONS:
            raise ValidationError({"group_by": f"must be one of {list(DIMENSIONS)}"})
        as_of = data_date()
        d_sla, t_sla = dispatch_sla_days(), transit_sla_days()
        rows = lead_rows(f, as_of)
        dispatch = _distribution([r.dispatch_days for r in rows if r.dispatch_days is not None],
                                 [r.waiting_dispatch for r in rows if r.waiting_dispatch is not None], d_sla)
        transit = _distribution([r.transit_days for r in rows if r.transit_days is not None],
                                [r.waiting_transit for r in rows if r.waiting_transit is not None], t_sla)
        e2e = [(r.delivered - r.placed).days for r in rows if r.delivered]
        overall = {"dispatch": dispatch, "transit": transit}
        flow = daily_flow(f, as_of)
        day = next((x for x in flow["points"] if x["date"] == as_of.isoformat()), None)
        prev = next((x for x in flow["points"] if x["date"] == (as_of - dt.timedelta(days=1)).isoformat()), None)
        return {
            "as_of": as_of.isoformat(),
            "sla": {"dispatch_days": d_sla, "transit_days": t_sla},
            "flow": flow,
            "latest_day": {"date": as_of.isoformat(), "today": day, "previous": prev} if flow["granularity"] == "day" else None,
            "orders": len(rows),
            "dispatch": dispatch,
            "transit": transit,
            "end_to_end_median_days": median(e2e),
            "late_orders": sum(r.late_dispatch or r.late_transit for r in rows),
            "insights": _insights(rows, d_sla, t_sla, overall),
            "hotspots": {"group_by": dim, "label": DIMENSIONS[dim], "min_orders": MIN_GROUP_ORDERS,
                         "rows": group_stats(rows, dim)},
            "dimensions": [{"key": k, "label": v} for k, v in DIMENSIONS.items()],
        }

    def cache_extra(self, request, **kwargs):
        return f"{super().cache_extra(request, **kwargs)}|v1"


def drill_flow(f, q):
    """Orders behind a number in the Order flow & delays section. Returns an Order queryset or None.

    flow_day=YYYY-MM-DD & flow_event=received|shipped|delivered [& flow_week=1]
    lead=dispatch|transit & lead_bucket=<LEAD_BUCKETS key>   finished orders that took that many days
    delay=dispatch|transit [& waiting=1] [& group_by=<dim> & group=<key>]   late orders (optionally one group /
                                                                           only those still waiting)
    group_by=<dim> & group=<key>                              all of that group's orders in the period
    """
    day, lead, delay = q.get("flow_day"), q.get("lead"), q.get("delay")
    dim, group = q.get("group_by"), q.get("group")
    if day:
        try:
            d0 = dt.date.fromisoformat(day)
        except ValueError:
            raise ValidationError({"flow_day": "must be YYYY-MM-DD"}) from None
        d1 = d0 + dt.timedelta(days=6 if q.get("flow_week") in ("1", "true") else 0)
        event = q.get("flow_event") or "received"
        qs = f.orders(qualifying=False).exclude(status="cancelled")
        if event == "received":
            return qs.filter(placed_date__gte=d0, placed_date__lte=d1)
        if event not in ("shipped", "delivered"):
            raise ValidationError({"flow_event": "must be received, shipped or delivered"})
        field = f"{event}_at"
        lo = timezone.make_aware(dt.datetime.combine(d0, dt.time.min))
        hi = timezone.make_aware(dt.datetime.combine(d1 + dt.timedelta(days=1), dt.time.min))
        return qs.filter(**{f"{field}__gte": lo, f"{field}__lt": hi})
    if not (lead or delay or (dim and group is not None)):
        return None
    if dim and dim not in DIMENSIONS:
        raise ValidationError({"group_by": f"must be one of {list(DIMENSIONS)}"})
    rows = lead_rows(f)
    if dim and group is not None:
        want = None if group == "none" else group
        rows = [r for r in rows if (None if r.keys[dim] is None else str(r.keys[dim])) == want]
    if lead:
        if lead not in ("dispatch", "transit"):
            raise ValidationError({"lead": "must be dispatch or transit"})
        b = q.get("lead_bucket")
        if b not in [k for k, *_ in LEAD_BUCKETS]:
            raise ValidationError({"lead_bucket": f"must be one of {[k for k, *_ in LEAD_BUCKETS]}"})
        attr = f"{lead}_days"
        rows = [r for r in rows if getattr(r, attr) is not None and bucket_key(getattr(r, attr)) == b]
    if delay:
        if delay not in ("dispatch", "transit", "any"):
            raise ValidationError({"delay": "must be dispatch, transit or any"})
        if delay == "any":
            rows = [r for r in rows if r.late_dispatch or r.late_transit]
        else:
            rows = [r for r in rows if getattr(r, f"late_{delay}")]
        if q.get("waiting") in ("1", "true"):
            rows = [r for r in rows if getattr(r, f"waiting_{delay if delay != 'any' else 'dispatch'}") is not None]
    return Order.objects.filter(id__in=[r.id for r in rows])
