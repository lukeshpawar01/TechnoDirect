"""GET /api/inventory/fullset-impact/ - what full sets do to sales (Inventory page, "Full sets vs sales").

Method (user, 2026-11-27): take every distributor's stock on a past snapshot (default: the latest one at least
`lookback` days old, ?lookback=7|10|14, default 10), classify each style it carries in all five core sizes as
  full   - S, M, L, XL and 2XL all in stock (XXL = 2XL), the same full set as the stock matrix
  broken - 1-2 core sizes at zero, badly - 3-4 at zero, out - none in stock
and measure what it sold of that style from the next day to today. Comparing stock BEFORE with sales AFTER avoids
the trap of today's stock (a style that sold well has sizes missing because it sold).

Lost sales on a broken set = the sales its missing sizes would have made: the combo's own sales scaled up by TD's
size curve (share of units per size in the same window): sold / (1 - share of missing sizes) - sold, capped at
sold x 1 (a broken set could at most have doubled). Combos that sold nothing count as no loss (conservative). Follows the page filters (territory, Category I/II/III, article);
removed distributors are left out.
"""
import datetime as dt
from collections import defaultdict

from django.db.models import Max
from rest_framework.exceptions import ValidationError

from accounts.scope import INVENTORY_DIMS
from warehouse.models import Distributor, OrderLine, primary_inventory

from ..metrics import num, pct
from ..styles import expand
from .base import AnalyticsView

CORE = ("S", "M", "L", "XL", "2XL")
GROUPS = (("full", "Full set (S–2XL all in stock)"), ("broken", "Broken: 1–2 core sizes missing"),
          ("badly", "Badly broken: 3–4 missing"), ("out", "Out: no core size in stock"))
LOOKBACKS = (7, 10, 14)
HAVE_FLOOR = 0.5


def _core(size):
    u = (size or "").strip().upper()
    return "2XL" if u == "XXL" else u


class FullSetImpactView(AnalyticsView):
    permission_code = "view_inventory"
    sources = ["supabase"]
    export_key = "distributors"

    def cache_extra(self, request, **kwargs):
        return f"{super().cache_extra(request, **kwargs)}|lb={request.query_params.get('lookback', '')}"

    def compute(self, f, request, **kw):
        raw = request.query_params.get("lookback") or "10"
        if not raw.isdigit() or int(raw) not in LOOKBACKS:
            raise ValidationError({"lookback": f"must be one of {LOOKBACKS}"})
        lookback = int(raw)
        today = f.today
        inv = primary_inventory().filter(f.dims_q(INVENTORY_DIMS, retailer_field=None))
        if f.articles:
            inv = inv.filter(style__in=expand(f.articles))
        if f.categories:
            inv = inv.filter(product__category_l1__in=f.categories)
        for lvl, vals in ((1, f.cat_l1), (2, f.cat_l2), (3, f.cat_l3)):
            if vals:
                inv = inv.filter(**{f"product__category_l{lvl}__in": vals})
        hidden = set(Distributor.objects.filter(removed=True).values_list("id", flat=True))
        inv = inv.exclude(distributor_id__in=hidden)

        snap = inv.filter(snapshot_date__lte=today - dt.timedelta(days=lookback)).aggregate(d=Max("snapshot_date"))["d"]
        if snap is None:  # not enough history yet: the earliest snapshot
            snap = inv.order_by("snapshot_date").values_list("snapshot_date", flat=True).first()
        if snap is None or snap >= today:
            return {"available": False, "reason": "Not enough stock history yet (needs a snapshot before today)."}
        start, days = snap + dt.timedelta(days=1), (today - snap).days

        stock = defaultdict(lambda: defaultdict(int))  # (did, style) -> core size -> qty
        for did, style, size, q in inv.filter(snapshot_date=snap).values_list("distributor_id", "style", "size", "quantity"):
            stock[(did, style)][_core(size)] += max(q or 0, 0)

        lines = OrderLine.objects.filter(order__in=f.orders(start=start, end=today)).filter(f.lines_q())
        sold, value = defaultdict(int), defaultdict(float)
        size_units = defaultdict(int)
        for did, style, size, q, t in lines.values_list("order__distributor_id", "style", "size", "quantity", "total"):
            sold[(did, style)] += q or 0
            value[(did, style)] += float(t or 0)
            if _core(size) in CORE:
                size_units[_core(size)] += q or 0
        curve_total = sum(size_units.values())
        curve = {z: (size_units[z] / curve_total if curve_total else 0.2) for z in CORE}

        groups = defaultdict(lambda: {"combos": 0, "sold": 0, "units": 0, "value": 0.0})
        missing_count = defaultdict(int)
        per_d = defaultdict(lambda: {"styles": 0, "full": 0, "units": 0, "lost_units": 0.0, "lost_value": 0.0})
        lost_rows = []
        for key, sizes in stock.items():
            if not all(z in sizes for z in CORE):
                continue  # not offered in all five core sizes there (kids, free size...)
            miss = [z for z in CORE if sizes[z] <= 0]
            g = "full" if not miss else "broken" if len(miss) <= 2 else "badly" if len(miss) < 5 else "out"
            u, v = sold.get(key, 0), value.get(key, 0.0)
            G = groups[g]
            G["combos"] += 1
            G["sold"] += 1 if u else 0
            G["units"] += u
            G["value"] += v
            d = per_d[key[0]]
            d["styles"] += 1
            d["full"] += g == "full"
            d["units"] += u
            if g in ("broken", "badly"):
                for z in miss:
                    missing_count[z] += 1
                # the sizes still in stock carry `have` of demand; scaling up is capped at 2x (have floor 0.5): with
                # most sizes gone, its sales came from restocks or other sizes and the scale-up would be fiction
                have = max(1 - sum(curve[z] for z in miss), HAVE_FLOOR)
                if u:
                    extra = u / have - u
                    d["lost_units"] += extra
                    d["lost_value"] += extra * v / u
                    lost_rows.append((key, miss, u, extra * v / u))

        names = dict(Distributor.objects.filter(id__in=list(per_d)).values_list("id", "name"))
        out_groups = []
        for k, label in GROUPS:
            G = groups.get(k) or {"combos": 0, "sold": 0, "units": 0, "value": 0.0}
            n = G["combos"]
            out_groups.append({"key": k, "label": label, "combos": n, "sold_pct": pct(G["sold"], n),
                               "units_per_combo": round(G["units"] / n, 2) if n else None,
                               "value_per_combo": num(G["value"] / n) if n else None,
                               "units": G["units"], "value": num(G["value"])})
        gmap = {g["key"]: g for g in out_groups}
        full_u, broken_u = gmap["full"]["units_per_combo"], gmap["broken"]["units_per_combo"]
        lost_value = sum(d["lost_value"] for d in per_d.values())
        lost_units = sum(d["lost_units"] for d in per_d.values())
        dists = sorted(({
            "id": did, "name": names.get(did, "?"), "styles": d["styles"],
            "full_pct": pct(d["full"], d["styles"]), "units": d["units"],
            "units_per_style": round(d["units"] / d["styles"], 2) if d["styles"] else None,
            "lost_value": num(d["lost_value"]), "lost_value_month": num(d["lost_value"] / days * 30),
        } for did, d in per_d.items()), key=lambda r: (-r["lost_value"], -r["units"]))
        lost_rows.sort(key=lambda r: -r[3])
        return {
            "available": True, "snapshot_date": snap.isoformat(), "from": start.isoformat(), "to": today.isoformat(),
            "days": days, "lookback": lookback, "groups": out_groups,
            "full_vs_broken": round(full_u / broken_u, 1) if full_u and broken_u else None,
            "size_curve": [{"size": z, "sales_share_pct": round(curve[z] * 100, 1), "broken_sets_missing": missing_count[z]}
                           for z in CORE],
            "lost": {"units": round(lost_units), "value": num(lost_value), "value_month": num(lost_value / days * 30)},
            "distributors": dists,
            "top_lost": [{"style": k[1], "distributor": names.get(k[0], "?"), "missing": m, "sold": u,
                          "lost_value": num(v)} for k, m, u, v in lost_rows[:15]],
        }
