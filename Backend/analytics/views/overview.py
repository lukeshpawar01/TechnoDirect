import datetime as dt
from collections import defaultdict

from django.conf import settings
from django.db.models import Count, Max, Q, Sum
from django.utils import timezone

from accounts.scope import DISTRIBUTOR_DIMS
from warehouse.models import DataQualityIssue, Distributor, InventorySnapshot, State, primary_inventory

from ..filters import add_months, days_between, month_start
from ..metrics import (
    agg_orders,
    daily_target_rate,
    delta_pct,
    fmt_inr,
    launch_month,
    monthly_orders,
    mkey,
    new_retailers_in,
    num,
    ratio,
    share,
    spark,
    spark_months,
    target_block,
)
from .base import AnalyticsView

FUNNEL_STATUSES = ["received", "confirmed", "shipped", "delivered", "cancelled"]


def kpi(value, compare, spark_values):
    return {"value": num(value), "compare": num(compare) if compare is not None else None,
            "delta_pct": delta_pct(value, compare) if compare is not None else None, "spark": spark_values}


OPEN_STATUSES = ["received", "confirmed", "shipped"]


def open_window_start(f):
    return f.today - dt.timedelta(days=settings.ORDER_OPEN_WINDOW_DAYS - 1)


def open_orders(f, statuses=OPEN_STATUSES, use_filter_statuses=False):
    """Orders still open (not delivered / cancelled) and placed within ORDER_OPEN_WINDOW_DAYS. Older orders that
    still carry an open status are stale statuses in the TD export, not work in progress (see stale_open_orders)."""
    return f.orders(qualifying=False, statuses=use_filter_statuses).filter(
        status__in=statuses, placed_date__gte=open_window_start(f))


def stale_open_orders(f):
    """Orders placed before the open window that the TD export still shows as placed / confirmed / shipped."""
    return f.orders(qualifying=False, statuses=False).filter(status__in=OPEN_STATUSES,
                                                             placed_date__lt=open_window_start(f))


def open_sla_breaches(f, use_filter_statuses=False):
    """Not shipped yet and placed more than the dispatch SLA (in days) before the data date - the latest day in
    the TD export, not the clock: the export lags a day or two, and measuring from the clock made every order of
    those days look late. Same rule as the Order flow & delays section (fulfilment.py)."""
    from .fulfilment import data_date, dispatch_sla_days

    cutoff = data_date(f.today) - dt.timedelta(days=dispatch_sla_days())
    return open_orders(f, ["received", "confirmed"], use_filter_statuses).filter(placed_date__lt=cutoff)


def stale_stock_distributors(f):
    """Distributors whose stock was not updated within STOCK_SYNC_DAYS days (sheet date, see analytics/stocksync.py)."""
    from .. import stocksync

    ids = list(Distributor.objects.filter(f.dims_q(DISTRIBUTOR_DIMS, retailer_field=None), is_active=True,
                                          bo_only=False).values_list("id", flat=True))
    last = stocksync.last_sync(ids)
    return [d for d in ids if stocksync.bucket(last.get(d), f.today) != "fresh"]


class OverviewView(AnalyticsView):
    permission_code = "view_overview"
    export_key = "monthly"

    def compute(self, f, request, **kw):
        p = f.period
        base = f.orders()
        cur_qs = base.filter(placed_date__gte=p.start, placed_date__lte=p.end)
        cur = agg_orders(cur_qs)
        cur["new"] = new_retailers_in(cur_qs, p.start, p.end)
        cmp = None
        if p.cmp_start:
            cmp_qs = base.filter(placed_date__gte=p.cmp_start, placed_date__lte=p.cmp_end)
            cmp = agg_orders(cmp_qs)
            cmp["new"] = new_retailers_in(cmp_qs, p.cmp_start, p.cmp_end)

        months12 = spark_months(p.end)
        mon = monthly_orders(base, months12[0], p.end)

        def c(key, fn=None):
            if cmp is None:
                return None
            return fn(cmp) if fn else cmp[key]

        aov = lambda d: ratio(d.get("sales"), d.get("orders"))  # noqa: E731
        upo = lambda d: ratio(d.get("units"), d.get("orders"))  # noqa: E731
        rpu = lambda d: ratio(d.get("sales"), d.get("units"))  # noqa: E731
        rep = lambda d: (d.get("retailers", 0) - d.get("new", 0))  # noqa: E731
        kpis = {
            "sales": kpi(cur["sales"], c("sales"), spark(mon, months12, lambda d: d.get("sales"))),
            "orders": kpi(cur["orders"], c("orders"), spark(mon, months12, lambda d: d.get("orders"))),
            "aov": kpi(aov(cur), c("aov", aov), spark(mon, months12, aov)),
            "units_per_order": kpi(upo(cur), c("upo", upo), spark(mon, months12, upo)),
            "realisation_per_unit": kpi(rpu(cur), c("rpu", rpu), spark(mon, months12, rpu)),
            "active_retailers": kpi(cur["retailers"], c("retailers"), spark(mon, months12, lambda d: d.get("retailers"))),
            "new_retailers": kpi(cur["new"], c("new"), spark(mon, months12, lambda d: d.get("new"))),
            "repeat_retailers": kpi(rep(cur), c("rep", rep), spark(mon, months12, rep)),
            "active_distributors": kpi(cur["distributors"], c("distributors"),
                                       spark(mon, months12, lambda d: d.get("distributors"))),
        }

        # targets exist per territory (region / ASM / distributor), not per retailer tier or RFM segment: comparing a
        # tier's sales with the whole target would read as a false shortfall, so no target is shown then
        target_note = None
        if f.tiers or f.segment:
            target, tmap = None, {}
            target_note = "Targets are set per territory, not per tier or segment. Clear that filter to compare with target."
        else:
            target, tmap = target_block(f, base)

        # daily trend
        daily = {r["placed_date"]: r for r in cur_qs.values("placed_date").annotate(
            sales=Sum("gross_value"), orders=Count("split_group", distinct=True))}
        rates = daily_target_rate(tmap) if tmap else {}
        cum_s, cum_t, trend = 0.0, 0.0, []
        for d in days_between(p.start, p.end):
            r = daily.get(d)
            s = float(r["sales"]) if r else 0.0
            cum_s += s
            if rates:
                cum_t += rates.get(month_start(d), 0.0)
            trend.append({"date": d.isoformat(), "sales": num(s), "orders": int(r["orders"]) if r else 0,
                          "cum_sales": num(cum_s), "cum_target": num(cum_t) if rates else None})

        # monthly since launch (+ previous-year comparison)
        first = min(launch_month(), month_start(p.end))
        allm = monthly_orders(base, add_months(first, -12), p.end)
        monthly = []
        m = first
        while m <= month_start(p.end):
            d = allm.get(m, {})
            py = allm.get(add_months(m, -12))
            monthly.append({"month": mkey(m), "sales": num(d.get("sales")), "orders": int(d.get("orders", 0)),
                            "aov": aov(d), "active_retailers": int(d.get("retailers", 0)),
                            "prev_year_sales": num(py["sales"]) if py else None})
            m = add_months(m, 1)

        # order funnel (all orders, any payment state)
        allq = f.orders(start=p.start, end=p.end, qualifying=False)
        fa = allq.aggregate(
            received_c=Count("id"), received_v=Sum("gross_value"),
            confirmed_c=Count("id", filter=Q(status__in=["confirmed", "shipped", "delivered"])),
            confirmed_v=Sum("gross_value", filter=Q(status__in=["confirmed", "shipped", "delivered"])),
            shipped_c=Count("id", filter=Q(status__in=["shipped", "delivered"])),
            shipped_v=Sum("gross_value", filter=Q(status__in=["shipped", "delivered"])),
            delivered_c=Count("id", filter=Q(status="delivered")),
            delivered_v=Sum("gross_value", filter=Q(status="delivered")),
            cancelled_c=Count("id", filter=Q(status="cancelled")),
            cancelled_v=Sum("gross_value", filter=Q(status="cancelled")),
        )
        order_funnel = [{"status": s, "count": fa[f"{s}_c"] or 0, "value": num(fa[f"{s}_v"])}
                        for s in FUNNEL_STATUSES]

        # concentration & tops
        total = cur["sales"]
        by_dist = list(cur_qs.values("distributor_id").annotate(s=Sum("gross_value")).order_by("-s"))
        by_state = list(cur_qs.values("state_id").annotate(s=Sum("gross_value")).order_by("-s"))
        by_ret = list(cur_qs.values("retailer_id").annotate(s=Sum("gross_value")).order_by("-s")[:10])
        dnames = dict(Distributor.objects.values_list("id", "name"))
        snames = dict(State.objects.values_list("id", "name"))
        cmp_dist = {}
        if p.cmp_start:
            cmp_dist = {r["distributor_id"]: float(r["s"] or 0) for r in base.filter(
                placed_date__gte=p.cmp_start, placed_date__lte=p.cmp_end).values("distributor_id").annotate(
                s=Sum("gross_value"))}
        top_state = by_state[0] if by_state else None
        concentration = {
            "top3_distributor_share": share(sum(float(r["s"] or 0) for r in by_dist[:3]), total),
            "top_state": {"name": snames.get(top_state["state_id"], "Unmapped"),
                          "share": share(top_state["s"], total)} if top_state else None,
            "top10_retailer_share": share(sum(float(r["s"] or 0) for r in by_ret), total),
        } if total else None  # no sales in the period: the card shows its empty state, not "0.0% of sales"
        top_distributors = [{
            "id": r["distributor_id"], "name": dnames.get(r["distributor_id"], "Unmapped"),
            "sales": num(r["s"]), "share": share(r["s"], total),
            "growth_pct": delta_pct(r["s"], cmp_dist.get(r["distributor_id"])) if p.cmp_start else None,
        } for r in by_dist[:10]]
        top_states = [{"id": r["state_id"], "name": snames.get(r["state_id"], "Unmapped"), "sales": num(r["s"]),
                       "share": share(r["s"], total)} for r in by_state[:10]]

        return {
            "kpis": kpis, "target": target, "target_note": target_note, "daily_trend": trend, "monthly": monthly,
            "order_funnel": order_funnel, "concentration": concentration,
            "top_distributors": top_distributors, "top_states": top_states,
            "exceptions": self.exceptions(f, target),
        }

    def exceptions(self, f, target):
        out = []
        from ..stocksync import STOCK_SYNC_DAYS

        # "message" never repeats the count: the UI shows `count` in front of it (count None = no number shown)
        sla = open_sla_breaches(f).count()
        if sla:
            out.append({"code": "order_sla_breach", "severity": "high", "count": sla,
                        "message": f"orders not dispatched within {settings.ORDER_DISPATCH_SLA_HOURS}h "
                                   f"(placed in the last {settings.ORDER_OPEN_WINDOW_DAYS} days)",
                        "link": "/orders?order_status=received,confirmed&sla_breached=1"})
        stale = stale_stock_distributors(f)
        if stale:
            out.append({"code": "stock_sync_stale", "severity": "medium", "count": len(stale),
                        "message": f"distributors without a stock update in the last {STOCK_SYNC_DAYS} days",
                        "link": "/distributors?stock_sync=stale,never"})
        if target and target["days_total"] > target["days_elapsed"] > 0:
            req, curr = target["required_run_rate"], target["current_run_rate"]
            if req > curr:
                out.append({
                    "code": "target_run_rate_shortfall",
                    "severity": "high" if curr < 0.8 * req else "medium", "count": None,
                    "message": f"Run rate {fmt_inr(curr)}/day vs required {fmt_inr(req)}/day "
                               f"({target['achievement_pct']}% of {fmt_inr(target['target'])} achieved)",
                    "link": "/overview"})
        sev_rank = {"high": 0, "medium": 1, "low": 2}
        dq = defaultdict(lambda: [0, "low", ""])
        for code, label, sev, n in (DataQualityIssue.objects.filter(resolved_at__isnull=True)
                                    .values_list("code", "label", "severity").annotate(n=Count("id"))):
            e = dq[code]
            e[0] += n
            e[2] = label
            if sev_rank[sev] < sev_rank[e[1]]:
                e[1] = sev
        for code, (n, sev, label) in dq.items():
            out.append({"code": f"dq_{code}", "severity": sev, "count": n, "message": label,
                        "link": f"/data-health?issue={code}"})
        out.sort(key=lambda e: (sev_rank[e["severity"]], -(e["count"] or 0)))
        return out
