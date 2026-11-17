import datetime as dt
from collections import defaultdict

from django.db.models import Count, F, Max, Q, Sum
from django.utils import timezone
from django.db.models.functions import TruncMonth
from django.http import Http404
from rest_framework.exceptions import ValidationError

from accounts.scope import ASM_DIMS, DISTRIBUTOR_DIMS, REGION_DIMS, RETAILER_DIMS, STATE_DIMS
from warehouse.models import (Asm, Distributor, FieldStaff, InventorySnapshot, OrderLine, Region, Retailer, Rsm, State,
                              primary_inventory)

from ..filters import add_months, month_start, months_between
from ..rsm import region_rsm_map, with_rsm
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


L3M_MIN_BASE = 50_000  # growth on a smaller base is noise


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
        # previous 3 months, for "growth L3M vs P3M" (deck slide 50/51)
        p3m = dict(base.filter(placed_date__gte=add_months(l3_start, -3), placed_date__lt=l3_start)
                   .values("distributor_id").annotate(s=Sum("gross_value")).values_list("distributor_id", "s"))
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
        tsales = targeted_sales(cur_qs, "distributor_id", tv)
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
                "l3m_sales": num(l3m.get(d.id)), "p3m_sales": num(p3m.get(d.id)),
                "l3m_growth_pct": delta_pct(float(l3m.get(d.id) or 0), float(p3m[d.id]))
                if float(p3m.get(d.id) or 0) >= L3M_MIN_BASE else None,
                "sales_per_retailer": ratio(sales, act),
                "growth_pct": delta_pct(sales, float(cmp.get(d.id) or 0)) if p.cmp_start else None,
                "prev_sales": num(cmp.get(d.id)) if p.cmp_start else None,
                "target": num(t) if t else None,
                "achievement_pct": share(tsales.get(d.id, 0.0), t) if t else None,
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
        line_total = float(lines.aggregate(s=Sum("total"))["s"] or 0)
        top_articles = [{"style": r["style"], "name": r["product__name"],
                         "category": r["product__category_l3"] or r["product__category_l2"] or None,
                         "sales": num(r["s"]), "units": r["u"], "share": share(r["s"], line_total)}
                        for r in lines.values("style", "product__name", "product__category_l2", "product__category_l3")
                        .annotate(s=Sum("total"), u=Sum("quantity")).order_by("-s")[:20]]
        rets = cur_qs.values("retailer_id", "retailer__name", "retailer__state__name").annotate(
            s=Sum("gross_value"), n=Count("id"), last=Max("placed_date")).order_by("-s")[:50]
        from .. import rfm

        seg = rfm.snapshot(rfm.as_of_for(f))["rows"]
        retailers = []
        for r in rets:
            key = (seg.get(r["retailer_id"]) or {}).get("segment", "prospect")
            retailers.append({
                "id": r["retailer_id"], "name": r["retailer__name"], "state": r["retailer__state__name"],
                "segment": key, "rfm_label": rfm.SEGMENTS[key][0], "sales": num(r["s"]), "orders": r["n"],
                "last_order_date": _iso(r["last"]),
                "days_since_last_order": (f.today - r["last"]).days if r["last"] else None})
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


GROWTH_MIN_BASE = 50_000  # growth % on a smaller comparison base is noise (e.g. +12,27,35,820% on a few rupees)


def growth_on_base(sales, prev):
    prev = float(prev or 0)
    return delta_pct(float(sales), prev) if prev >= GROWTH_MIN_BASE else None


def targeted_sales(qs, gfield, tv):
    """{group: sales in the months that group has a target} - achievement must not divide all months' sales
    by the few months that carry a target."""
    months = defaultdict(set)
    for (gid, m), v in tv.items():
        if v:
            months[gid].add(m)
    out = defaultdict(float)
    for r in qs.annotate(_m=TruncMonth("placed_date")).values(gfield, "_m").annotate(_s=Sum("gross_value")):
        if as_date(r["_m"]) in months.get(r[gfield], ()):
            out[r[gfield]] += float(r["_s"] or 0)
    return out


GROUPS = {
    "region": (Region, REGION_DIMS, "region_id"),
    "state": (State, STATE_DIMS, "state_id"),
    "asm": (Asm, ASM_DIMS, "asm_id"),
    "rsm": (Rsm, None, "rsm_key"),  # derived: ASM's RSM, else the region's RSM (analytics/rsm.py)
}


class TerritoryView(AnalyticsView):
    permission_code = "view_territory"
    export_key = "rows"

    def compute(self, f, request, **kw):
        group_by = request.query_params.get("group_by", "state")
        if group_by not in GROUPS:
            raise ValidationError({"group_by": "must be region, rsm, state or asm"})
        model, _, gfield = GROUPS[group_by]
        p = f.period
        prep = with_rsm if group_by == "rsm" else (lambda qs: qs)
        base = prep(f.orders())
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
        rb = prep(Retailer.objects.filter(f.dims_q(RETAILER_DIMS, retailer_field="id")))
        kyc = {r[gfield]: r for r in rb.values(gfield).annotate(
            kyc=Count("id", filter=Q(kyc_status="approved")),
            ever=Count("id", filter=Q(first_order_date__isnull=False)))}
        dist_counts = dict(prep(Distributor.objects.filter(f.dims_q(DISTRIBUTOR_DIMS, retailer_field=None),
                                                           is_active=True))
                           .values(gfield).annotate(n=Count("id")).values_list(gfield, "n"))
        group_ids = set(cur) | set(kyc) | set(dist_counts)
        group_ids.discard(None)
        names = dict(model.objects.filter(id__in=group_ids).values_list("id", "name"))
        tv = target_values(group_by, list(group_ids), months_between(p.start, p.end), "sales", f.today)
        targets = defaultdict(float)
        for (sid, _), v in tv.items():
            targets[sid] += float(v)
        tsales = targeted_sales(cur_qs, gfield, tv)
        rows = []
        for gid in group_ids | ({None} if None in cur else set()):
            c, k = cur.get(gid, {}), kyc.get(gid, {})
            sales = float(c.get("sales") or 0)
            t = targets.get(gid)
            rows.append({
                "id": gid, "name": names.get(gid, "Unmapped"), "sales": num(sales),
                "target": num(t) if t else None,
                "achievement_pct": share(tsales.get(gid, 0.0), t) if t else None,
                "orders": c.get("orders", 0), "active_retailers": c.get("retailers", 0),
                "new_retailers": c.get("new", 0), "kyc_base": k.get("kyc", 0),
                "adoption_pct": pct(k.get("ever", 0), k.get("kyc", 0)),
                "distributors": dist_counts.get(gid, 0),
                "sales_per_retailer": ratio(sales, c.get("retailers", 0)),
                "growth_pct": growth_on_base(sales, cmp.get(gid)) if p.cmp_start else None,
            })
        rows.sort(key=lambda r: -r["sales"])
        team = self.team(group_by, rows)
        months12 = spark_months(p.end)
        monthly = [{"month": mkey(r["m"]), "group": names.get(r[gfield], "Unmapped"), "group_id": r[gfield],
                    "sales": num(r["s"])}
                   for r in base.filter(placed_date__gte=months12[0], placed_date__lte=p.end)
                   .annotate(m=TruncMonth("placed_date")).values("m", gfield).annotate(s=Sum("gross_value"))
                   .order_by("m", gfield)]
        out = {"group_by": group_by, "rows": rows, "monthly_by_group": monthly}
        if group_by == "rsm":
            out["breakdown"] = self.rsm_breakdown(f, base, cur_qs, p)
        return out

    @staticmethod
    def team(group_by, rows):
        """Adds the people behind each row: RSM -> ASMs / field staff; ASM -> its RSM and field staff."""
        ids = [r["id"] for r in rows if r["id"]]
        if group_by == "rsm":
            asms = dict(Asm.objects.filter(rsm_id__in=ids, is_active=True).values("rsm_id").annotate(
                n=Count("id")).values_list("rsm_id", "n"))
            fse = dict(FieldStaff.objects.filter(rsm_id__in=ids, is_active=True).values("rsm_id").annotate(
                n=Count("id")).values_list("rsm_id", "n"))
            info = {r.id: r for r in Rsm.objects.filter(id__in=ids).select_related("region")}
            for r in rows:
                x = info.get(r["id"])
                r.update({"asms": asms.get(r["id"], 0), "field_staff": fse.get(r["id"], 0),
                          "region": x.region.name if x and x.region_id else None})
        elif group_by == "asm":
            fse = dict(FieldStaff.objects.filter(asm_id__in=ids, is_active=True).values("asm_id").annotate(
                n=Count("id")).values_list("asm_id", "n"))
            info = {a.id: a for a in Asm.objects.filter(id__in=ids).select_related("rsm")}
            for r in rows:
                a = info.get(r["id"])
                r.update({"field_staff": fse.get(r["id"], 0), "rsm_id": a.rsm_id if a else None,
                          "rsm": a.rsm.name if a and a.rsm_id else None,
                          "full_name": (a.full_name or None) if a else None})
        return None

    @staticmethod
    def rsm_breakdown(f, base, cur_qs, p):
        """RSM -> ASM rows for the team hierarchy table (ASM-less sales shown as 'Distributor-managed')."""
        cur = {(r["rsm_key"], r["asm_id"]): r for r in cur_qs.values("rsm_key", "asm_id").annotate(
            sales=Sum("gross_value"), orders=Count("split_group", distinct=True),
            retailers=Count("retailer_id", distinct=True))}
        cmp = {}
        if p.cmp_start:
            cmp = {(r["rsm_key"], r["asm_id"]): r["s"] for r in base.filter(
                placed_date__gte=p.cmp_start, placed_date__lte=p.cmp_end).values("rsm_key", "asm_id").annotate(
                s=Sum("gross_value"))}
        asms = {a.id: a for a in Asm.objects.filter(rsm__isnull=False, is_active=True)}
        if f.rsms:
            asms = {k: a for k, a in asms.items() if a.rsm_id in f.rsms}
        if f.asms:
            asms = {k: a for k, a in asms.items() if k in f.asms}
        # an ASM who joined after the period is not part of that period's team
        asms = {k: a for k, a in asms.items() if not a.joined_on or a.joined_on <= p.end}
        keys = set(cur) | {(a.rsm_id, a.id) for a in asms.values()}
        tv = target_values("asm", [k[1] for k in keys if k[1]], months_between(p.start, p.end), "sales", f.today)
        tgt = defaultdict(float)
        for (aid, _), v in tv.items():
            tgt[aid] += float(v)
        tsales = targeted_sales(cur_qs, "asm_id", tv)
        # ASM-less distributors' own targets belong to the "Distributor-managed" row of their region's RSM
        reg_rsm = region_rsm_map()
        no_asm = {d: reg_rsm.get(r) for d, r in Distributor.objects.filter(asm__isnull=True).values_list(
            "id", "region_id")}
        dm_tgt, dm_months = defaultdict(float), defaultdict(set)
        for (did, m), v in target_values("distributor", list(no_asm), months_between(p.start, p.end), "sales",
                                         f.today).items():
            if no_asm[did] and not f.asms and (not f.rsms or no_asm[did] in f.rsms):
                dm_tgt[no_asm[did]] += float(v)
                dm_months[no_asm[did]].add(m)
                keys.add((no_asm[did], None))
        dm_sales = defaultdict(float)
        for r in cur_qs.filter(asm__isnull=True).annotate(_m=TruncMonth("placed_date")).values(
                "rsm_key", "_m").annotate(_s=Sum("gross_value")):
            if as_date(r["_m"]) in dm_months.get(r["rsm_key"], ()):
                dm_sales[r["rsm_key"]] += float(r["_s"] or 0)
        fse = dict(FieldStaff.objects.filter(is_active=True, asm__isnull=False).values("asm_id").annotate(
            n=Count("id")).values_list("asm_id", "n"))
        out = []
        for rsm_id, asm_id in keys:
            if rsm_id is None:
                continue
            c = cur.get((rsm_id, asm_id), {})
            sales = float(c.get("sales") or 0)
            t = tgt.get(asm_id) if asm_id else dm_tgt.get(rsm_id)
            t_sales = tsales.get(asm_id, 0.0) if asm_id else dm_sales.get(rsm_id, 0.0)
            a = asms.get(asm_id) or (Asm.objects.filter(id=asm_id).first() if asm_id else None)
            out.append({
                "rsm_id": rsm_id, "asm_id": asm_id,
                "name": a.name if a else "Distributor-managed (no ASM)",
                "full_name": (a.full_name or None) if a else None,
                "is_active": a.is_active if a else True,
                "joined_on": a.joined_on if a else None,
                "sales": num(sales), "target": num(t) if t else None,
                "achievement_pct": share(t_sales, t) if t else None,
                "orders": c.get("orders", 0), "active_retailers": c.get("retailers", 0),
                "growth_pct": growth_on_base(sales, cmp.get((rsm_id, asm_id))) if p.cmp_start else None,
                "field_staff": fse.get(asm_id, 0) if asm_id else 0,
            })
        out.sort(key=lambda r: (r["rsm_id"], r["asm_id"] is None, -r["sales"]))
        return out


class DistributorInsightsView(AnalyticsView):
    """GET /distributors/insights/ — board-review views of the distributor network (deck slides 49, 52, 62, 63):
    top-5 monthly trend, top 3 articles per distributor, distributors transacting per month and
    retailers buying from more than one distributor."""

    permission_code = "view_distributors"
    sources = ["medusa", "payu"]
    export_key = "top_articles"

    def compute(self, f, request, **kw):
        p = f.period
        ids = set(scoped_distributors(f).values_list("id", flat=True))
        names = dict(Distributor.objects.filter(id__in=ids).values_list("id", "name"))
        base = f.orders(end=p.end).filter(distributor_id__in=ids)
        cur = base.filter(placed_date__gte=p.start)
        months12 = spark_months(p.end)

        # top 5 distributors of the period, monthly over 12 months; the rest folded into "Other"
        top5 = list(cur.values("distributor_id").annotate(s=Sum("gross_value")).order_by("-s")
                    .values_list("distributor_id", flat=True)[:5])
        series = defaultdict(lambda: defaultdict(float))
        transacting = {}
        for r in base.filter(placed_date__gte=months12[0]).annotate(m=TruncMonth("placed_date")).values(
                "m", "distributor_id").annotate(s=Sum("gross_value")):
            key = names.get(r["distributor_id"], "Unmapped") if r["distributor_id"] in top5 else "Other"
            series[key][as_date(r["m"])] += float(r["s"] or 0)
        for r in base.filter(placed_date__gte=months12[0]).annotate(m=TruncMonth("placed_date")).values("m").annotate(
                n=Count("distributor_id", distinct=True), rt=Count("retailer_id", distinct=True)):
            transacting[as_date(r["m"])] = r
        order = [names.get(d, "Unmapped") for d in top5] + (["Other"] if "Other" in series else [])
        trend = {"months": [mkey(m) for m in months12],
                 "series": [{"name": n, "data": [num(series[n].get(m, 0)) for m in months12]} for n in order]}

        # top 3 articles per distributor in the period
        per = defaultdict(list)
        lines = OrderLine.objects.filter(order__in=cur).exclude(style="")
        if f.has_line_filters():
            lines = lines.filter(f.lines_q())
        for r in lines.values("order__distributor_id", "style").annotate(s=Sum("total")).order_by(
                "order__distributor_id", "-s"):
            lst = per[r["order__distributor_id"]]
            if len(lst) < 3:
                lst.append({"style": r["style"], "sales": num(r["s"])})
        dsales = dict(cur.values("distributor_id").annotate(s=Sum("gross_value")).values_list("distributor_id", "s"))
        top_articles = sorted([{"id": d, "name": names.get(d, "Unmapped"), "sales": num(dsales.get(d)),
                                "articles": per[d]} for d in per], key=lambda r: -r["sales"])

        # retailers buying from 2+ distributors: ever, and per month
        life = list(base.values("retailer_id").annotate(d=Count("distributor_id", distinct=True),
                                                        n=Count("split_group", distinct=True)))
        multi = [r for r in life if r["d"] >= 2]
        single = [r for r in life if r["d"] < 2]
        per_m = defaultdict(lambda: [0, 0])
        for r in base.filter(placed_date__gte=months12[0]).annotate(m=TruncMonth("placed_date")).values(
                "m", "retailer_id").annotate(d=Count("distributor_id", distinct=True)):
            c = per_m[as_date(r["m"])]
            c[0] += 1
            c[1] += 1 if r["d"] >= 2 else 0
        multi_distributor = {
            "retailers": len(life), "multi": len(multi), "multi_pct": pct(len(multi), len(life)),
            "avg_orders_multi": ratio(sum(r["n"] for r in multi), len(multi)),
            "avg_orders_single": ratio(sum(r["n"] for r in single), len(single)),
            "monthly": [{"month": mkey(m), "active": per_m[m][0], "multi": per_m[m][1],
                         "multi_pct": pct(per_m[m][1], per_m[m][0])} for m in months12],
        }
        return {
            "trend": trend, "top_articles": top_articles, "multi_distributor": multi_distributor,
            "transacting_monthly": [{"month": mkey(m), "distributors": transacting.get(m, {}).get("n", 0),
                                     "retailers": transacting.get(m, {}).get("rt", 0)} for m in months12],
        }


class DistributorNetworkView(AnalyticsView):
    """GET /distributors/network/ — distributors grouped by state (state per the sales team's distributor list),
    with each one's sales and orders in the period."""

    permission_code = "view_distributors"
    export_key = "states"

    def compute(self, f, request, **kw):
        p = f.period
        dists = list(scoped_distributors(f).select_related("state", "region"))
        ids = [d.id for d in dists]
        cur = {r["distributor_id"]: r for r in f.orders(start=p.start, end=p.end).filter(distributor_id__in=ids)
               .values("distributor_id").annotate(s=Sum("gross_value"), n=Count("split_group", distinct=True))}
        ever = set(f.orders(end=p.end).filter(distributor_id__in=ids).values_list("distributor_id", flat=True)
                   .distinct())
        states = {}
        for d in dists:
            if d.id not in ever:
                continue  # never traded (test / dormant accounts)
            key = d.state_id
            b = states.setdefault(key, {"state": d.state.name if d.state_id else "Unmapped",
                                        "region": d.region.name if d.region_id else None,
                                        "sales": 0.0, "distributors": []})
            c = cur.get(d.id) or {}
            sales = float(c.get("s") or 0)
            b["sales"] += sales
            b["distributors"].append({"id": d.id, "name": d.name, "sales": num(sales), "orders": c.get("n") or 0})
        rows = []
        for b in states.values():
            b["distributors"].sort(key=lambda x: -x["sales"])
            b["selling"] = sum(1 for x in b["distributors"] if x["orders"])
            b["sales"] = num(b["sales"])
            rows.append(b)
        rows.sort(key=lambda r: (-r["sales"], r["state"]))
        return {
            "summary": {"states": len(rows), "distributors": sum(len(r["distributors"]) for r in rows),
                        "selling": sum(r["selling"] for r in rows)},
            "states": rows,
        }
