"""Best sellers by area (Products page): each region's / state's top 10 styles and top 10 categories in the period.

GET /api/products/best-sellers/  (the page's usual filters: period, region, category, style ...)

Styles are folded to their base code (all colours: 'OR99 Black' -> OR99), categories are Category III
(trackpants, t-shirts, jackets ...). Each item carries its share of the area's sales and its national rank, so a
style that ranks far higher in one area than nationally shows up as that area's local favourite.
"""
from collections import defaultdict

from ..metrics import num, share
from ..styles import base_style, catalog
from .base import AnalyticsView
from .products import line_qs

TOP_N = 10


def _cat(l3, l2):
    return (l3 or l2 or "Unclassified").strip().title()


class BestSellersByAreaView(AnalyticsView):
    permission_code = "view_products"

    def compute(self, f, request, **kw):
        p = f.period
        names = {code: c.get("name") for code, c in catalog().items()}
        rows = line_qs(f, p.start, p.end).values_list(
            "order__region__name", "order__state__name", "style", "product__category_l3", "product__category_l2",
            "total", "quantity", "order__retailer_id")

        # (level, area) -> (dim, key) -> [sales, units, {retailers}]
        agg = defaultdict(lambda: defaultdict(lambda: [0.0, 0, set()]))
        nat = {"style": defaultdict(float), "category": defaultdict(float)}
        style_cat = defaultdict(lambda: defaultdict(float))  # style -> category -> sales (its main category)
        cat_style = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))  # (level, area) -> cat -> style
        region_of_state = {}
        for region, state, style, l3, l2, total, qty, rid in rows:
            region, state = region or "Unmapped", state or "Unmapped"
            region_of_state.setdefault(state, region)
            code, cat, v, q = base_style(style) or "–", _cat(l3, l2), float(total or 0), qty or 0
            nat["style"][code] += v
            nat["category"][cat] += v
            style_cat[code][cat] += v
            for level, area in (("region", region), ("state", state)):
                for dim, key in (("style", code), ("category", cat)):
                    a = agg[(level, area)][(dim, key)]
                    a[0] += v
                    a[1] += q
                    if rid:
                        a[2].add(rid)
                cat_style[(level, area)][cat][code] += v

        rank = {dim: {k: i + 1 for i, (k, _) in enumerate(sorted(vals.items(), key=lambda x: -x[1]))}
                for dim, vals in nat.items()}
        main_cat = {code: max(c.items(), key=lambda x: x[1])[0] for code, c in style_cat.items()}

        out = {"region": {"style": [], "category": []}, "state": {"style": [], "category": []}}
        for (level, area), items in agg.items():
            for dim in ("style", "category"):
                mine = [(k, a) for (d, k), a in items.items() if d == dim]
                total = sum(a[0] for _, a in mine)
                if total <= 0:
                    continue
                top = []
                for k, a in sorted(mine, key=lambda x: -x[1][0])[:TOP_N]:
                    row = {"key": k, "sales": num(a[0]), "units": a[1], "retailers": len(a[2]),
                           "share": share(a[0], total), "national_rank": rank[dim].get(k)}
                    if dim == "style":
                        row.update(name=names.get(k) or k, category=main_cat.get(k))
                    else:
                        styles = cat_style[(level, area)][k]
                        lead = max(styles.items(), key=lambda x: x[1])[0] if styles else None
                        row.update(name=k, top_style=lead, top_style_name=names.get(lead) if lead else None,
                                   styles=sum(1 for v in styles.values() if v > 0))
                    top.append(row)
                entry = {"area": area, "sales": num(total), "items": sum(1 for _, a in mine if a[0] > 0), "top": top}
                if level == "state":
                    entry["region"] = region_of_state.get(area)
                out[level][dim].append(entry)
        for level in out.values():
            for dim in level:
                level[dim].sort(key=lambda e: -e["sales"])
        return {**out, "national": {dim: len(v) for dim, v in nat.items()}, "top_n": TOP_N}
