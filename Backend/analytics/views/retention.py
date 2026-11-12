from collections import defaultdict

from django.db.models import Count, Max, Min, Q, Sum

from accounts.scope import RETAILER_MONTH_DIMS
from warehouse.models import RetailerMonth

from ..filters import add_months, fy_quarter_label, month_start, quarter_start
from ..metrics import launch_month, mkey, num, pct, ratio, share, spark_months
from .base import AnalyticsView

BANDS = [("1", 1, 1), ("2", 2, 2), ("3-5", 3, 5), ("6-10", 6, 10), ("11-20", 11, 20), ("21+", 21, None)]
PARETO_N = [10, 25, 50, 100, 250, 500, 1000]


class RetentionView(AnalyticsView):
    permission_code = "view_retention"
    sources = ["medusa", "payu"]
    export_key = "movement"

    def compute(self, f, request, **kw):
        p = f.period
        end_m = month_start(p.end)
        first_m = min(launch_month(), end_m)
        rm = RetailerMonth.objects.filter(f.dims_q(RETAILER_MONTH_DIMS), month__gte=first_m, month__lte=end_m)
        seg = f.segment_retailers()
        if seg is not None:
            rm = rm.filter(retailer_id__in=seg)

        counts = defaultdict(lambda: defaultdict(int))
        sales = defaultdict(lambda: defaultdict(float))
        orders_m = defaultdict(int)
        for r in rm.values("month", "status").annotate(n=Count("id"), s=Sum("sales"), o=Sum("orders")):
            counts[r["month"]][r["status"]] += r["n"]
            sales[r["month"]][r["status"]] += float(r["s"] or 0)
            orders_m[r["month"]] += r["o"] or 0

        months = []
        m = first_m
        while m <= end_m:
            months.append(m)
            m = add_months(m, 1)
        movement, prev_active = [], 0
        for m in months:
            c = counts[m]
            active = c["new"] + c["retained"] + c["reactivated"]
            movement.append({
                "month": mkey(m), "active": active, "retained": c["retained"], "reactivated": c["reactivated"],
                "new": c["new"], "lost": c["lost"], "net": active - prev_active,
                "mom_retention": pct(c["retained"], prev_active),
            })
            prev_active = active

        active_pairs = list(rm.filter(is_active=True).values_list("retailer_id", "month"))
        by_q = defaultdict(set)
        by_r = defaultdict(set)
        for rid, mo in active_pairs:
            by_q[quarter_start(mo)].add(rid)
            by_r[rid].add(mo)
        quarterly = []
        for q in sorted(by_q):
            prev = by_q.get(add_months(q, -3))
            if prev:
                quarterly.append({"quarter": fy_quarter_label(q), "rate": share(len(by_q[q] & prev), len(prev))})

        cohorts_map = defaultdict(set)
        for rid, ms in by_r.items():
            cohorts_map[min(ms)].add(rid)
        cohorts = []
        for c in sorted(cohorts_map):
            members = cohorts_map[c]
            values, k = [], 0
            mm = c
            while mm <= end_m:
                values.append(share(sum(1 for r in members if mm in by_r[r]), len(members), 1))
                k += 1
                mm = add_months(c, k)
            cohorts.append({"cohort": mkey(c), "size": len(members), "values": values})

        contribution = [{"month": mkey(m), "new_sales": num(sales[m]["new"]),
                         "repeat_sales": num(sales[m]["retained"]),
                         "reactivated_sales": num(sales[m]["reactivated"])} for m in months]

        life = list(f.orders(end=p.end).values("retailer_id").annotate(
            n=Count("split_group", distinct=True), s=Sum("gross_value"), first=Min("placed_date"),
            last=Max("placed_date")))
        bands = []
        for label, lo, hi in BANDS:
            sel = [r for r in life if r["n"] >= lo and (hi is None or r["n"] <= hi)]
            bands.append({"band": label, "retailers": len(sel), "sales": num(sum(float(r["s"] or 0) for r in sel))})
        gaps = [(r["last"] - r["first"]).days / (r["n"] - 1) for r in life if r["n"] >= 2]

        per_ret = sorted((float(r["s"] or 0) for r in f.orders(start=p.start, end=p.end).values(
            "retailer_id").annotate(s=Sum("gross_value"))), reverse=True)
        tot = sum(per_ret)
        pareto = [{"top_n": n, "share": share(sum(per_ret[:n]), tot)} for n in PARETO_N if n <= max(len(per_ret), 10)]

        m12 = spark_months(p.end)
        opar = [{"month": mkey(m), "value": ratio(orders_m.get(m, 0),
                                                  counts[m]["new"] + counts[m]["retained"] + counts[m]["reactivated"])}
                for m in m12]
        return {
            "movement": movement, "quarterly_retention": quarterly, "cohorts": cohorts,
            "contribution": contribution, "order_bands": bands, "pareto": pareto,
            "avg_days_between_orders": round(sum(gaps) / len(gaps), 1) if gaps else None,
            "orders_per_active_retailer": opar,
        }


__all__ = ["Q"]
