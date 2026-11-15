"""Growth journey & retailer value (the board-review analyses of TD_DataDeck slides 28-44, 56, 59-61).

Everything runs from launch to the end of the selected period, inside the user's scope and filters.
Sales are qualifying order value (paid, not cancelled), order counts are cart-level (split orders once).
"""
import calendar
import datetime as dt
import math
from collections import defaultdict

from django.db.models import Count, F, Max, Min, Sum
from django.db.models.functions import TruncMonth

from warehouse.models import OrderLine, Retailer

from ..filters import add_months, fy_label, fy_quarter_label, fy_start, month_start, quarter_start
from ..metrics import as_date, delta_pct, launch_month, median, mkey, num, pct, ratio, share
from .base import AnalyticsView

CUM_MILESTONES_CR = [1, 5, 10, 20, 30, 50, 75, 100, 150, 200, 300, 500]
MONTH_MILESTONES_CR = [0.5, 1, 2, 2.5, 3, 4, 5, 7.5, 10]
SPEND_BUCKETS = [("< ₹10K", 0, 10_000), ("₹10–25K", 10_000, 25_000), ("₹25–50K", 25_000, 50_000),
                 ("₹50K–1L", 50_000, 100_000), ("₹1–2L", 100_000, 200_000), ("₹2–5L", 200_000, 500_000),
                 ("₹5–10L", 500_000, 1_000_000), ("₹10L+", 1_000_000, None)]


def _month_end(m):
    return m.replace(day=calendar.monthrange(m.year, m.month)[1])


def _year_back(d):
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year - 1, day=28)


def _cr(v):
    return f"₹{v:g} Cr"


def _factors(a):
    """Sales = active retailers x orders per retailer x AOV; AOV = units per order x realisation per unit."""
    s, o, r, u = a["sales"], a["orders"], a["retailers"], a["units"]
    return {
        "sales": s, "active_retailers": r, "orders_per_retailer": ratio(o, r), "aov": ratio(s, o),
        "units_per_order": ratio(u, o), "realisation_per_unit": ratio(s, u),
    }


def _log_shares(prev, cur, keys, total_key):
    """Each factor's share of the change in the product, by log contribution (sums to 100%)."""
    try:
        total = math.log(cur[total_key] / prev[total_key])
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if not total:
        return None
    out = {}
    for k in keys:
        try:
            out[k] = round(math.log(cur[k] / prev[k]) / total * 100, 1)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    return out


class GrowthView(AnalyticsView):
    permission_code = "view_retention"
    sources = ["medusa", "payu"]
    export_key = "monthly"

    def compute(self, f, request, **kw):
        p = f.period
        end = p.end
        last_m = month_start(end)
        base = f.orders(end=end)
        first_seen = base.aggregate(d=Min("placed_date"))["d"]
        first_m = min(launch_month(), month_start(first_seen)) if first_seen else min(launch_month(), last_m)
        first_m = min(first_m, last_m)

        # ---------------------------------------------------------------- monthly series
        agg = {as_date(r["m"]): r for r in base.filter(placed_date__gte=first_m).annotate(
            m=TruncMonth("placed_date")).values("m").annotate(
            sales=Sum("gross_value"), orders=Count("split_group", distinct=True), units=Sum("units"),
            retailers=Count("retailer_id", distinct=True), distributors=Count("distributor_id", distinct=True))}
        new_by_m = {as_date(r["m"]): r["n"] for r in base.filter(retailer__first_order_date__isnull=False).annotate(
            m=TruncMonth("retailer__first_order_date")).values("m").annotate(n=Count("retailer_id", distinct=True))}
        # repeat (retailer's first order was in an earlier month) vs new sales per month
        new_sales_m = {as_date(r["m"]): float(r["s"] or 0) for r in base.annotate(
            m=TruncMonth("placed_date"), fm=TruncMonth("retailer__first_order_date")).filter(m=F("fm")).values(
            "m").annotate(s=Sum("gross_value"))}
        # basket breadth: distinct articles per order and per month
        per_order = defaultdict(list)
        styles_m = {}
        lines = OrderLine.objects.filter(order__in=base.filter(placed_date__gte=first_m)).exclude(style="")
        if f.has_line_filters():
            lines = lines.filter(f.lines_q())
        for r in lines.annotate(m=TruncMonth("order__placed_date")).values("m", "order_id").annotate(
                k=Count("style", distinct=True)):
            per_order[as_date(r["m"])].append(r["k"])
        for r in lines.annotate(m=TruncMonth("order__placed_date")).values("m").annotate(k=Count("style", distinct=True)):
            styles_m[as_date(r["m"])] = r["k"]

        months, m = [], first_m
        while m <= last_m:
            months.append(m)
            m = add_months(m, 1)
        partial_last = end < _month_end(last_m)

        monthly, cum_s, cum_r, cum_o = [], 0.0, 0, 0
        z = {"sales": 0, "orders": 0, "units": 0, "retailers": 0, "distributors": 0}
        for m in months:
            a = agg.get(m, z)
            s, o, u, r = float(a["sales"] or 0), a["orders"] or 0, a["units"] or 0, a["retailers"] or 0
            prev = agg.get(add_months(m, -1))
            ly = agg.get(add_months(m, -12))
            cum_s += s
            cum_o += o
            cum_r += new_by_m.get(m, 0)
            po = per_order.get(m, [])
            new_s = new_sales_m.get(m, 0.0)
            monthly.append({
                "month": mkey(m), "is_partial": partial_last and m == last_m,
                "sales": num(s), "orders": o, "units": u, "active_retailers": r, "distributors": a["distributors"] or 0,
                "new_retailers": new_by_m.get(m, 0),
                "aov": ratio(s, o), "units_per_order": ratio(u, o), "realisation_per_unit": ratio(s, u),
                "sales_per_retailer": ratio(s, r), "orders_per_retailer": ratio(o, r),
                "mom_pct": delta_pct(s, float(prev["sales"] or 0)) if prev and prev["sales"] else None,
                "prev_year_sales": num(ly["sales"]) if ly else None,
                "yoy_pct": delta_pct(s, float(ly["sales"] or 0)) if ly and ly["sales"] else None,
                "cum_sales": num(cum_s), "cum_orders": cum_o, "cum_retailers": cum_r,
                "active_pct_of_base": pct(r, cum_r),
                "new_sales": num(new_s), "repeat_sales": num(s - new_s), "repeat_share": pct(s - new_s, s),
                "articles_per_order": round(sum(po) / len(po), 2) if po else None,
                "articles_sold": styles_m.get(m, 0),
            })

        # ---------------------------------------------------------------- quarters & financial years
        def rollup(key_fn, label_fn, span_end_fn):
            groups = defaultdict(lambda: {"sales": 0.0, "orders": 0})
            for mm in months:
                a = agg.get(mm)
                if a:
                    g = groups[key_fn(mm)]
                    g["sales"] += float(a["sales"] or 0)
                    g["orders"] += a["orders"] or 0
            ret = defaultdict(set)
            for rid, d in base.filter(placed_date__gte=first_m).values_list("retailer_id", "placed_date").distinct():
                ret[key_fn(d)].add(rid)
            out, prev = [], None
            for k in sorted(set(groups) | set(ret)):
                g = groups[k]
                out.append({
                    "label": label_fn(k), "start": k.isoformat(), "sales": num(g["sales"]), "orders": g["orders"],
                    "aov": ratio(g["sales"], g["orders"]), "active_retailers": len(ret.get(k, ())),
                    "growth_pct": delta_pct(g["sales"], prev) if prev else None,
                    "is_partial": end < span_end_fn(k),
                })
                prev = g["sales"]
            return out

        quarters = rollup(quarter_start, fy_quarter_label, lambda q: _month_end(add_months(q, 2)))
        fys = rollup(fy_start, fy_label, lambda y: dt.date(y.year + 1, 3, 31))

        # ---------------------------------------------------------------- milestones
        milestones, cum, crossed, month_hit = [], 0.0, set(), set()
        record = max(monthly, key=lambda r: r["sales"]) if monthly else None
        for row in monthly:
            cum = row["cum_sales"]
            for t in CUM_MILESTONES_CR:
                if t not in crossed and cum >= t * 1e7:
                    crossed.add(t)
                    milestones.append({"month": row["month"], "kind": "cumulative", "label": f"{_cr(t)} cumulative"})
            for t in MONTH_MILESTONES_CR:
                if t not in month_hit and row["sales"] >= t * 1e7:
                    month_hit.add(t)
                    milestones.append({"month": row["month"], "kind": "month",
                                       "label": f"First {_cr(t)} month ({row['orders']} orders)"})
        if record and record["sales"]:
            milestones.append({"month": record["month"], "kind": "record",
                               "label": f"Record month: ₹{record['sales'] / 1e7:.2f} Cr"})

        # ---------------------------------------------------------------- growth decomposition (vs same period LY)
        def period_agg(s, e):
            r = base.filter(placed_date__gte=s, placed_date__lte=e).aggregate(
                sales=Sum("gross_value"), orders=Count("split_group", distinct=True), units=Sum("units"),
                retailers=Count("retailer_id", distinct=True))
            return {k: float(v or 0) for k, v in r.items()}

        ly_s, ly_e = _year_back(p.start), _year_back(end)
        cur_a, ly_a = period_agg(p.start, end), period_agg(ly_s, ly_e)
        cf, lf = _factors(cur_a), _factors(ly_a)
        keys = ["active_retailers", "orders_per_retailer", "aov"]
        shares = _log_shares(lf, cf, keys, "sales")
        aov_shares = _log_shares(lf, cf, ["units_per_order", "realisation_per_unit"], "aov")
        labels = {"active_retailers": "Active retailers", "orders_per_retailer": "Orders per active retailer",
                  "aov": "Average order value", "units_per_order": "Units per order",
                  "realisation_per_unit": "Realisation per unit"}
        change = cur_a["sales"] - ly_a["sales"]

        def frow(k, sh, base_change):
            return {"key": k, "label": labels[k], "prev": lf[k], "cur": cf[k], "change_pct": delta_pct(cf[k], lf[k]),
                    "share_pct": sh.get(k) if sh else None,
                    "contribution": num(base_change * sh[k] / 100) if sh else None}

        decomposition = {
            "period": {"start": p.start.isoformat(), "end": end.isoformat()},
            "compare": {"start": ly_s.isoformat(), "end": ly_e.isoformat()},
            "prev_sales": num(ly_a["sales"]), "cur_sales": num(cur_a["sales"]),
            "change": num(change), "change_pct": delta_pct(cur_a["sales"], ly_a["sales"]),
            "factors": [frow(k, shares, change) for k in keys],
            "aov_factors": [frow(k, aov_shares, (cf["aov"] or 0) - (lf["aov"] or 0)) for k in
                            ["units_per_order", "realisation_per_unit"]],
            "available": shares is not None,
        }

        # ---------------------------------------------------------------- like-for-like bridge (6 months vs same 6 LY)
        w_start = add_months(last_m, -5)
        pw_start, pw_end = _year_back(w_start), _year_back(end)

        def per_retailer(s, e):
            return {r: float(v or 0) for r, v in base.filter(placed_date__gte=s, placed_date__lte=e).values(
                "retailer_id").annotate(v=Sum("gross_value")).values_list("retailer_id", "v")}

        cw, pw = per_retailer(w_start, end), per_retailer(pw_start, pw_end)
        both = cw.keys() & pw.keys()
        lfl_prev, lfl_cur = sum(pw[r] for r in both), sum(cw[r] for r in both)
        new_ids, lapsed_ids = cw.keys() - pw.keys(), pw.keys() - cw.keys()
        bridge = {
            "window": {"start": w_start.isoformat(), "end": end.isoformat()},
            "prev_window": {"start": pw_start.isoformat(), "end": pw_end.isoformat()},
            "prev_total": num(sum(pw.values())), "cur_total": num(sum(cw.values())),
            "like_for_like": {"retailers": len(both), "prev": num(lfl_prev), "cur": num(lfl_cur),
                              "change": num(lfl_cur - lfl_prev), "change_pct": delta_pct(lfl_cur, lfl_prev)},
            "new": {"retailers": len(new_ids), "sales": num(sum(cw[r] for r in new_ids))},
            "lapsed": {"retailers": len(lapsed_ids), "sales": num(sum(pw[r] for r in lapsed_ids))},
        }

        # ---------------------------------------------------------------- retailer value
        pairs = defaultdict(set)
        for rid, mm in base.annotate(mm=TruncMonth("placed_date")).values_list("retailer_id", "mm").distinct():
            pairs[rid].add(as_date(mm))
        y_start = add_months(last_m, -11)
        spend = sorted(((rid, float(v or 0)) for rid, v in base.filter(placed_date__gte=y_start).values(
            "retailer_id").annotate(v=Sum("gross_value")).values_list("retailer_id", "v")), key=lambda x: -x[1])
        vals = [v for _, v in spend]
        tot12 = sum(vals)
        nq = math.ceil(len(vals) / 4) if vals else 0
        hist = [{"bucket": lbl, "retailers": sum(1 for v in vals if v >= lo and (hi is None or v < hi))}
                for lbl, lo, hi in SPEND_BUCKETS]
        act12 = [sum(1 for mm in pairs[rid] if y_start <= mm <= last_m) for rid, _ in spend]
        months_dist = [{"months": k, "retailers": sum(1 for a in act12 if a == k)} for k in range(1, 13)]

        life = list(base.values("retailer_id").annotate(
            n=Count("split_group", distinct=True), s=Sum("gross_value"), last=Max("placed_date")))
        life_tot = sum(float(r["s"] or 0) for r in life)
        multi = [r for r in life if r["n"] >= 2]
        top = sorted(life, key=lambda r: -float(r["s"] or 0))[:15]
        names = dict(Retailer.objects.filter(id__in=[r["retailer_id"] for r in top]).values_list("id", "name"))

        def aov_of(qs):
            a = qs.aggregate(s=Sum("gross_value"), n=Count("split_group", distinct=True))
            return ratio(float(a["s"] or 0), a["n"]), a["n"]

        cur_q = base.filter(placed_date__gte=p.start)
        first_aov, first_n = aov_of(cur_q.filter(placed_date=F("retailer__first_order_date")))
        rep_aov, rep_n = aov_of(cur_q.exclude(placed_date=F("retailer__first_order_date")))

        retailer_value = {
            "window": {"start": y_start.isoformat(), "end": end.isoformat()},
            "transacting": len(vals), "avg_spend": ratio(tot12, len(vals)), "median_spend": median(vals),
            "top_quartile": {"retailers": nq, "avg_spend": ratio(sum(vals[:nq]), nq),
                             "share": share(sum(vals[:nq]), tot12)},
            "histogram": hist, "months_active": months_dist,
            "avg_months_active": round(sum(act12) / len(act12), 1) if act12 else None,
            "single_month": sum(1 for a in act12 if a == 1),
            "lifetime": {"acquired": len(life), "repeat_retailers": len(multi), "repeat_pct": pct(len(multi), len(life)),
                         "repeat_sales_share": share(sum(float(r["s"] or 0) for r in multi), life_tot),
                         "avg_orders": ratio(sum(r["n"] for r in life), len(life)),
                         "one_order": len(life) - len(multi),
                         "one_order_sales": num(sum(float(r["s"] or 0) for r in life if r["n"] < 2))},
            "first_vs_repeat_aov": {"first_aov": first_aov, "first_orders": first_n,
                                    "repeat_aov": rep_aov, "repeat_orders": rep_n},
            "top_retailers": [{"id": r["retailer_id"], "name": names.get(r["retailer_id"], "—"), "orders": r["n"],
                               "sales": num(r["s"]), "months_active": len(pairs[r["retailer_id"]]),
                               "last_order": r["last"].isoformat() if r["last"] else None} for r in top],
        }

        lm = monthly[-1] if monthly else None
        headline = {
            "since": first_m.isoformat(), "cum_sales": num(cum_s), "cum_orders": cum_o,
            "retailers": len(life), "distributors": base.values("distributor_id").distinct().count(),
            "last_month": lm["month"] if lm else None, "last_month_sales": lm["sales"] if lm else None,
            "repeat_share_last_month": lm["repeat_share"] if lm else None,
            "record_month": record["month"] if record else None,
        }
        return {"headline": headline, "monthly": monthly, "quarters": quarters, "fy": fys,
                "milestones": milestones, "decomposition": decomposition, "bridge": bridge,
                "retailer_value": retailer_value}
