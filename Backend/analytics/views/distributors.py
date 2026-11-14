import datetime as dt
from collections import defaultdict

from django.db.models import Count, F, Max, Q, Sum
from django.utils import timezone
from django.db.models.functions import TruncMonth
from django.http import Http404
from rest_framework.exceptions import ValidationError

from accounts.scope import ASM_DIMS, DISTRIBUTOR_DIMS, REGION_DIMS, RETAILER_DIMS, STATE_DIMS
from warehouse.models import Asm, Distributor, InventorySnapshot, OrderLine, Region, Retailer, State, primary_inventory

from ..filters import add_months, month_start, months_between
from ..metrics import (
    as_date,
    delta_pct,
    median,
    mkey,
    num,
    pct,
    ratio,
    share,
    spark_months,
    target_values,
)
from .base import AnalyticsView


def _iso(v):
    if not v:
        return None
    if isinstance(v, dt.datetime):
        return timezone.localtime(v).isoformat(timespec="seconds")
    return v.isoformat()


def scoped_distributors(f):
    return Distributor.objects.filter(f.dims_q(DISTRIBUTOR_DIMS, retailer_field=None))


def dispatch_stats(qs, group_field):
    """{group: (dispatch_pct, median_dispatch_days)} for non-cancelled orders in qs."""
    rows = qs.exclude(status="cancelled").values_list(group_field, "placed_at", "shipped_at")
    tot, shipped, durations = defaultdict(int), defaultdict(int), defaultdict(list)
    for g, placed, ship in rows:
        tot[g] += 1
        if ship:
            shipped[g] += 1
            durations[g].append((ship - placed).total_seconds() / 86400)
    return {g: (pct(shipped[g], tot[g]), median(durations[g])) for g in tot}


class DistributorsView(AnalyticsView):
    permission_code = "view_distributors"
    sources = ["medusa", "payu", "channel_konnect"]
    export_key = "rows"

    def cache_extra(self, request, **kwargs):
        return super().cache_extra(request, **kwargs) + f"|sync={request.query_params.get('stock_sync', '')}"

    def compute(self, f, request, **kw):
        p = f.period
        dists = list(scoped_distributors(f).select_related("state", "region", "asm"))
        ids = [d.id for d in dists]
        base = f.orders()
        cur_qs = base.filter(placed_date__gte=p.start, placed_date__lte=p.end)
        cur = {r["distributor_id"]: r for r in cur_qs.values("distributor_id").annotate(
            sales=Sum("gross_value"), orders=Count("id"), retailers=Count("retailer_id", distinct=True),
            new=Count("retailer_id", distinct=True, filter=Q(retailer__first_order_date__gte=p.start,
                                                              retailer__first_order_date__lte=p.end)))}
        cmp = {}
        if p.cmp_start:
            cmp = dict(base.filter(placed_date__gte=p.cmp_start, placed_date__lte=p.cmp_end)
                       .values("distributor_id").annotate(s=Sum("gross_value")).values_list("distributor_id", "s"))
        l3_start = add_months(month_start(p.end), -2)
        l3m = dict(base.filter(placed_date__gte=l3_start, placed_date__lte=p.end).values("distributor_id")
                   .annotate(s=Sum("gross_value")).values_list("distributor_id", "s"))
        months12 = spark_months(p.end)
        sp = defaultdict(dict)
        for r in base.filter(placed_date__gte=months12[0], placed_date__lte=p.end).annotate(
                m=TruncMonth("placed_date")).values("distributor_id", "m").annotate(s=Sum("gross_value")):
            sp[r["distributor_id"]][as_date(r["m"])] = float(r["s"] or 0)
        mapped = dict(Retailer.objects.filter(distributor_id__in=ids).values("distributor_id")
                      .annotate(n=Count("id")).values_list("distributor_id", "n"))
        disp = dispatch_stats(f.orders(start=p.start, end=p.end, qualifying=False), "distributor_id")
        tv = target_values("distributor", ids, months_between(p.start, p.end), "sales", f.today)
        targets = defaultdict(float)
        for (sid, _), v in tv.items():
            targets[sid] += float(v)
        stock = dict(primary_inventory().filter(distributor_id__in=ids).values("distributor_id")
                     .annotate(m=Max("synced_at")).values_list("distributor_id", "m"))
        total = sum(float(r["sales"] or 0) for r in cur.values())
        rows = []
        for d in dists:
            c = cur.get(d.id, {})
            sales = float(c.get("sales") or 0)
            orders, act, new = c.get("orders", 0), c.get("retailers", 0), c.get("new", 0)
            t = targets.get(d.id)
            dp = disp.get(d.id, (None, None))
            rows.append({
                "id": d.id, "code": d.code, "name": d.name, "state": d.state.name if d.state_id else None,
                "region": d.region.name if d.region_id else None, "asm": d.asm.name if d.asm_id else None,
                "sales": num(sales), "share": share(sales, total), "orders": orders, "aov": ratio(sales, orders),
                "retailers": mapped.get(d.id, 0), "active_retailers": act, "new_retailers": new,
                "repeat_pct": pct(act - new, act), "orders_per_retailer": ratio(orders, act),
                "dispatch_pct": dp[0], "median_dispatch_days": dp[1],
                "l3m_sales": num(l3m.get(d.id)),
                "growth_pct": delta_pct(sales, float(cmp.get(d.id) or 0)) if p.cmp_start else None,
                "target": num(t) if t else None, "achievement_pct": share(sales, t) if t else None,
                "last_stock_sync": _iso(stock.get(d.id)),
                "spark": [num(sp[d.id].get(m, 0)) for m in months12],
            })
        rows.sort(key=lambda r: -r["sales"])
        sync = request.query_params.get("stock_sync")
        if sync in ("fresh", "stale", "never"):
            cutoff = timezone.now() - dt.timedelta(hours=24)

            def bucket(r):
                at = stock.get(r["id"])
                return "never" if not at else ("fresh" if at >= cutoff else "stale")

            rows = [r for r in rows if bucket(r) == sync]
        return {"rows": rows}


class DistributorDetailView(AnalyticsView):
    permission_code = "view_distributors"
    sources = ["medusa", "payu", "channel_konnect"]
    export_key = "retailers"

    def compute(self, f, request, pk=None):
        d = scoped_distributors(f).select_related("state", "region", "asm").filter(pk=pk).first()
        if d is None:
            raise Http404
        from .overview import kpi

        p = f.period
        base = f.orders().filter(distributor_id=d.id)
        cur_qs = base.filter(placed_date__gte=p.start, placed_date__lte=p.end)

        def agg(qs, s, e):
            a = qs.aggregate(sales=Sum("gross_value"), orders=Count("id"), units=Sum("units"),
                             retailers=Count("retailer_id", distinct=True),
                             new=Count("retailer_id", distinct=True, filter=Q(
                                 retailer__first_order_date__gte=s, retailer__first_order_date__lte=e)))
            a = {k: float(v or 0) for k, v in a.items()}
            a["aov"] = ratio(a["sales"], a["orders"])
            return a

        a = agg(cur_qs, p.start, p.end)
        c = agg(base.filter(placed_date__gte=p.cmp_start, placed_date__lte=p.cmp_end), p.cmp_start,
                p.cmp_end) if p.cmp_start else None
        all_q = f.orders(qualifying=False).filter(distributor_id=d.id)
        disp = dispatch_stats(all_q.filter(placed_date__gte=p.start, placed_date__lte=p.end),
                              "distributor_id").get(d.id, (None, None))
        disp_c = dispatch_stats(all_q.filter(placed_date__gte=p.cmp_start, placed_date__lte=p.cmp_end),
                                "distributor_id").get(d.id, (None, None)) if p.cmp_start else (None, None)
        tv = target_values("distributor", [d.id], months_between(p.start, p.end), "sales", f.today)
        tgt = float(sum(tv.values())) if tv else None
        last_sync = primary_inventory().filter(distributor=d).aggregate(m=Max("synced_at"))["m"]

        months = spark_months(p.end)
        mrows = {as_date(r["m"]): r for r in base.filter(placed_date__gte=months[0], placed_date__lte=p.end)
                 .annotate(m=TruncMonth("placed_date")).values("m").annotate(
                     sales=Sum("gross_value"), orders=Count("id"), units=Sum("units"),
                     retailers=Count("retailer_id", distinct=True))}
        mdisp = defaultdict(lambda: [0, 0])
        for pd, ship in all_q.filter(placed_date__gte=months[0], placed_date__lte=p.end).exclude(
                status="cancelled").values_list("placed_date", "shipped_at"):
            mdisp[pd.replace(day=1)][0] += 1
            mdisp[pd.replace(day=1)][1] += 1 if ship else 0
        mt = target_values("distributor", [d.id], months, "sales", f.today)
        mnew = {as_date(r["m"]): r["n"] for r in base.filter(placed_date__gte=months[0], placed_date__lte=p.end)
                .annotate(m=TruncMonth("placed_date"), fm=TruncMonth("retailer__first_order_date"))
                .filter(m=F("fm")).values("m").annotate(n=Count("retailer_id", distinct=True))}

        def sp(fn):
            return [num(fn(mrows.get(m, {}), m) or 0) for m in months]

        kpis = {
            "sales": kpi(a["sales"], c and c["sales"], sp(lambda r, m: r.get("sales"))),
            "orders": kpi(a["orders"], c and c["orders"], sp(lambda r, m: r.get("orders"))),
            "aov": kpi(a["aov"], c and c["aov"], sp(lambda r, m: ratio(r.get("sales"), r.get("orders")))),
            "units": kpi(a["units"], c and c["units"], sp(lambda r, m: r.get("units"))),
            "active_retailers": kpi(a["retailers"], c and c["retailers"], sp(lambda r, m: r.get("retailers"))),
            "new_retailers": kpi(a["new"], c and c["new"], sp(lambda r, m: mnew.get(m, 0))),
            "dispatch_pct": kpi(disp[0] or 0, disp_c[0] if c else None,
                                sp(lambda r, m: pct(mdisp[m][1], mdisp[m][0]))),
            "achievement_pct": kpi(share(a["sales"], tgt) if tgt else 0, None,
                                   sp(lambda r, m: share(r.get("sales"), mt.get((d.id, m))) if mt.get((d.id, m)) else 0)),
        }
        if c is None:
            for k in kpis:
                kpis[k]["compare"] = kpis[k]["delta_pct"] = None
        target = {"target": num(tgt), "achieved": num(a["sales"]), "achievement_pct": share(a["sales"], tgt),
                  "balance": num(max(tgt - a["sales"], 0))} if tgt else None
        monthly = [{"month": mkey(m), "sales": num(mrows.get(m, {}).get("sales")),
                    "orders": mrows.get(m, {}).get("orders", 0),
                    "active_retailers": mrows.get(m, {}).get("retailers", 0)} for m in months]
        lines = OrderLine.objects.filter(order__in=cur_qs).filter(f.lines_q())
        top_articles = [{"style": r["style"], "name": r["product__name"], "sales": num(r["s"]), "units": r["u"]}
                        for r in lines.values("style", "product__name").annotate(
                            s=Sum("total"), u=Sum("quantity")).order_by("-s")[:20]]
        rets = cur_qs.values("retailer_id", "retailer__name").annotate(
            s=Sum("gross_value"), n=Count("id"), last=Max("placed_date")).order_by("-s")[:50]
        retailers = [{"id": r["retailer_id"], "name": r["retailer__name"], "sales": num(r["s"]), "orders": r["n"],
                      "last_order_date": _iso(r["last"])} for r in rets]
        profile = {
            "id": d.id, "code": d.code, "name": d.name, "state": d.state.name if d.state_id else None,
            "region": d.region.name if d.region_id else None, "asm": d.asm.name if d.asm_id else None,
            "city": d.city, "gstin": d.gstin, "is_active": d.is_active, "onboarded_on": _iso(d.onboarded_on),
            "last_stock_sync": _iso(last_sync),
            "mapped_retailers": Retailer.objects.filter(distributor=d).count(),
            "median_dispatch_days": disp[1],
        }
        return {"profile": profile, "kpis": kpis, "target": target, "monthly": monthly,
                "top_articles": top_articles, "retailers": retailers}


GROUPS = {
    "region": (Region, REGION_DIMS, "region_id"),
    "state": (State, STATE_DIMS, "state_id"),
    "asm": (Asm, ASM_DIMS, "asm_id"),
}


class TerritoryView(AnalyticsView):
    permission_code = "view_territory"
    export_key = "rows"

    def compute(self, f, request, **kw):
        group_by = request.query_params.get("group_by", "state")
        if group_by not in GROUPS:
            raise ValidationError({"group_by": "must be region, state or asm"})
        model, _, gfield = GROUPS[group_by]
        p = f.period
        base = f.orders()
        cur_qs = base.filter(placed_date__gte=p.start, placed_date__lte=p.end)
        cur = {r[gfield]: r for r in cur_qs.values(gfield).annotate(
            sales=Sum("gross_value"), orders=Count("split_group", distinct=True),
            retailers=Count("retailer_id", distinct=True),
            new=Count("retailer_id", distinct=True, filter=Q(retailer__first_order_date__gte=p.start,
                                                              retailer__first_order_date__lte=p.end)))}
        cmp = {}
        if p.cmp_start:
            cmp = dict(base.filter(placed_date__gte=p.cmp_start, placed_date__lte=p.cmp_end).values(gfield)
                       .annotate(s=Sum("gross_value")).values_list(gfield, "s"))
        rb = Retailer.objects.filter(f.dims_q(RETAILER_DIMS, retailer_field="id"))
        kyc = {r[gfield]: r for r in rb.values(gfield).annotate(
            kyc=Count("id", filter=Q(kyc_status="approved")),
            ever=Count("id", filter=Q(first_order_date__isnull=False)))}
        dist_counts = dict(Distributor.objects.filter(f.dims_q(DISTRIBUTOR_DIMS, retailer_field=None),
                                                      is_active=True)
                           .values(gfield).annotate(n=Count("id")).values_list(gfield, "n"))
        group_ids = set(cur) | set(kyc) | set(dist_counts)
        group_ids.discard(None)
        names = dict(model.objects.filter(id__in=group_ids).values_list("id", "name"))
        tv = target_values(group_by, list(group_ids), months_between(p.start, p.end), "sales", f.today)
        targets = defaultdict(float)
        for (sid, _), v in tv.items():
            targets[sid] += float(v)
        rows = []
        for gid in group_ids | ({None} if None in cur else set()):
            c, k = cur.get(gid, {}), kyc.get(gid, {})
            sales = float(c.get("sales") or 0)
            t = targets.get(gid)
            rows.append({
                "id": gid, "name": names.get(gid, "Unmapped"), "sales": num(sales),
                "target": num(t) if t else None, "achievement_pct": share(sales, t) if t else None,
                "orders": c.get("orders", 0), "active_retailers": c.get("retailers", 0),
                "new_retailers": c.get("new", 0), "kyc_base": k.get("kyc", 0),
                "adoption_pct": pct(k.get("ever", 0), k.get("kyc", 0)),
                "distributors": dist_counts.get(gid, 0),
                "growth_pct": delta_pct(sales, float(cmp.get(gid) or 0)) if p.cmp_start else None,
            })
        rows.sort(key=lambda r: -r["sales"])
        months12 = spark_months(p.end)
        monthly = [{"month": mkey(r["m"]), "group": names.get(r[gfield], "Unmapped"), "group_id": r[gfield],
                    "sales": num(r["s"])}
                   for r in base.filter(placed_date__gte=months12[0], placed_date__lte=p.end)
                   .annotate(m=TruncMonth("placed_date")).values("m", gfield).annotate(s=Sum("gross_value"))
                   .order_by("m", gfield)]
        return {"group_by": group_by, "rows": rows, "monthly_by_group": monthly}
