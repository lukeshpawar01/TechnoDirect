"""Inventory page, the Power BI "Inventory" tab (TD_Analytics.pbix) rebuilt on live stock:

  GET /api/inventory/matrix/    "Current Stock with Each Distributor": Style -> Size rows x distributor columns, stock
                                units; and "Full Sets with Each Distributor" (style x distributor)
  GET /api/inventory/run-rate/  "Stockwise Run Rate" + "Quantity sold in last 30, 60, 90 Days" per style

Both are paginated by style (?page, ?page_size, ?q= style or name search, ?ordering=) and follow the page filters
(territory, Category I/II/III, article, size). Stock = the latest sync per distributor (latest_inventory).

Full set (user, 2026-11-27): one piece in each core size S, M, L, XL, 2XL (XXL counts as 2XL); a distributor's full
sets of a style = the smallest stock across those five sizes. Styles that don't come in all five (kids, free size)
have no full sets (null).
"""
import datetime as dt
from collections import defaultdict

from django.db.models import Min, Q, Sum
from rest_framework.exceptions import ValidationError

from warehouse.models import Distributor, OrderLine

from ..metrics import num
from .base import AnalyticsView
from .products import latest_inventory

CORE = ("S", "M", "L", "XL", "2XL")
SIZE_ORDER = ["XS", "S", "M", "L", "XL", "2XL", "XXL", "3XL", "4XL", "5XL",
              "2-3Y", "3-4Y", "5-6Y", "7-8Y", "9-10Y", "11-12Y", "12Y", "13-14Y", "FREE SIZE"]
PAGE_MAX = 100


def size_key(s):
    u = (s or "").upper()
    return (SIZE_ORDER.index(u) if u in SIZE_ORDER else 99, u)


def _core(size):
    u = (size or "").strip().upper()
    return "2XL" if u == "XXL" else u


def _page(request):
    try:
        page = max(int(request.query_params.get("page") or 1), 1)
        size = min(max(int(request.query_params.get("page_size") or 25), 1), PAGE_MAX)
    except ValueError:
        raise ValidationError({"page": "must be a number"}) from None
    return page, size


def _search(qs, request, style_field="style", name_field="product__name"):
    q = (request.query_params.get("q") or "").strip()
    return qs.filter(Q(**{f"{style_field}__icontains": q}) | Q(**{f"{name_field}__icontains": q})) if q else qs


class _Paged(AnalyticsView):
    permission_code = "view_inventory"
    sources = ["channel_konnect", "supabase"]

    def cache_extra(self, request, **kwargs):
        p = request.query_params
        return (f"{super().cache_extra(request, **kwargs)}|{p.get('page', '')}|{p.get('page_size', '')}|"
                f"{p.get('q', '')}|{p.get('ordering', '')}|{bool(p.get('export'))}")


class InventoryMatrixView(_Paged):
    export_key = "rows"
    ORDERINGS = ("-stock", "stock", "style", "-style", "-full_sets")

    def compute(self, f, request, **kw):
        ordering = request.query_params.get("ordering") or "-stock"
        if ordering not in self.ORDERINGS:
            raise ValidationError({"ordering": f"must be one of {self.ORDERINGS}"})
        page, size = _page(request)
        inv = _search(latest_inventory(f), request)

        cells = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))  # style -> size -> did -> qty
        meta, snap = {}, None
        for style, sz, did, qty in inv.values_list("style", "size", "distributor_id").annotate(
                q=Sum("quantity")).values_list("style", "size", "distributor_id", "q"):
            cells[style][sz or "-"][did] += max(qty or 0, 0)
        for style, name, l3 in inv.values_list("style", "product__name", "product__category_l3").distinct():
            meta.setdefault(style, (name, l3))
        snap = inv.aggregate(d=Min("snapshot_date"))["d"]

        dist_total = defaultdict(int)
        styles = []
        for style, sizes in cells.items():
            by_dist = defaultdict(int)
            for per in sizes.values():
                for did, q in per.items():
                    by_dist[did] += q
                    dist_total[did] += q
            core = {_core(s) for s in sizes}
            full = None
            if all(c in core for c in CORE):
                full = {}
                dids = set().union(*(sizes[s].keys() for s in sizes))
                for did in dids:
                    have = defaultdict(int)
                    for s, per in sizes.items():
                        if _core(s) in CORE:
                            have[_core(s)] += per.get(did, 0)
                    n = min(have[c] for c in CORE)
                    if n:
                        full[did] = n
            name, l3 = meta.get(style, (None, None))
            styles.append({
                "style": style, "name": name, "category": (l3 or "").replace("-", " ").title() or None,
                "stock": sum(by_dist.values()), "by_dist": {d: q for d, q in by_dist.items() if q},
                "full_sets": full, "full_total": sum(full.values()) if full is not None else None,
                "sizes": [{"size": s, "stock": sum(per.values()), "by_dist": {d: q for d, q in per.items() if q}}
                          for s, per in sorted(sizes.items(), key=lambda kv: size_key(kv[0]))],
            })

        key = ordering.lstrip("-")
        if key == "style":
            styles.sort(key=lambda r: r["style"], reverse=ordering.startswith("-"))
        elif key == "full_sets":
            styles.sort(key=lambda r: -(r["full_total"] or 0))
        else:
            styles.sort(key=lambda r: r["stock"], reverse=ordering.startswith("-"))

        names = dict(Distributor.objects.filter(id__in=list(dist_total)).values_list("id", "name"))
        dists = sorted(({"id": d, "name": names.get(d, "?"), "stock": q} for d, q in dist_total.items()),
                       key=lambda x: -x["stock"])
        chunk = styles[(page - 1) * size: page * size]
        # flat rows for the CSV/XLSX export: one per style x size, a column per distributor
        rows = [{"style": s["style"], "size": z["size"], "total": z["stock"],
                 **{d["name"]: z["by_dist"].get(d["id"], 0) for d in dists}}
                for s in styles for z in s["sizes"]] if request.query_params.get("export") else []
        return {
            "distributors": dists, "grand_total": sum(dist_total.values()), "count": len(styles),
            "page": page, "page_size": size, "styles": chunk,
            "full_sets_total": sum(s["full_total"] or 0 for s in styles),
            "full_sets_by_dist": {d: sum((s["full_sets"] or {}).get(d, 0) for s in styles) for d in dist_total},
            "snapshot_date": snap.isoformat() if snap else None, "core_sizes": list(CORE), "rows": rows,
        }


class InventoryRunRateView(_Paged):
    """Per style: stock now, units sold in the last 30/60/90 days and their value, and the run rate since the style's
    first sale (Power BI "Stockwise Run Rate"): Units DRR = units sold / active days (first sale -> today),
    Units MRR = DRR x 30. Days of stock = stock / the last 30 days' daily rate (today's pace)."""

    export_key = "styles"
    SORTABLE = ("style", "stock", "sold_30", "sold_60", "sold_90", "sales_90", "qty_sold", "active_days", "drr", "mrr",
                "days_of_stock")

    def compute(self, f, request, **kw):
        ordering = request.query_params.get("ordering") or "-sold_30"
        if ordering.lstrip("-") not in self.SORTABLE:
            raise ValidationError({"ordering": f"must be one of {self.SORTABLE} (prefix - for descending)"})
        page, size = _page(request)
        today = f.today
        inv = _search(latest_inventory(f), request)
        stock = defaultdict(int)  # negative stock rows count as 0, as in the matrix
        for style, q in inv.values_list("style", "quantity"):
            stock[style] += max(q or 0, 0)
        meta = {}
        for style, name, l3 in inv.values_list("style", "product__name", "product__category_l3").distinct():
            meta.setdefault(style, (name, l3))

        lines = _search(OrderLine.objects.filter(order__in=f.orders()).filter(f.lines_q()), request)
        sold = defaultdict(lambda: {"all": 0, "first": None, "30": 0, "60": 0, "90": 0, "value_90": 0.0})
        for style, placed, q, total in lines.values_list("style", "order__placed_date", "quantity", "total"):
            s = sold[style]
            q = q or 0
            s["all"] += q
            if placed and (s["first"] is None or placed < s["first"]):
                s["first"] = placed
            age = (today - placed).days if placed else 9999
            for w in (30, 60, 90):
                if 0 <= age < w:
                    s[str(w)] += q
            if 0 <= age < 90:
                s["value_90"] += float(total or 0)
        for style, name, l3 in OrderLine.objects.filter(style__in=[s for s in sold if s not in meta]).values_list(
                "style", "product__name", "product__category_l3").distinct():
            meta.setdefault(style, (name, l3))

        out = []
        for style in set(stock) | {s for s, v in sold.items() if v["90"]}:
            v = sold.get(style) or {"all": 0, "first": None, "30": 0, "60": 0, "90": 0, "value_90": 0.0}
            st = max(stock.get(style) or 0, 0)
            active = (today - v["first"]).days + 1 if v["first"] else None
            drr = v["all"] / active if active else None
            name, l3 = meta.get(style, (None, None))
            out.append({
                "style": style, "name": name, "category": (l3 or "").replace("-", " ").title() or None,
                "stock": st, "sold_30": v["30"], "sold_60": v["60"], "sold_90": v["90"], "sales_90": num(v["value_90"]),
                "qty_sold": v["all"], "active_days": active,
                "drr": round(drr, 2) if drr is not None else None, "mrr": round(drr * 30, 1) if drr is not None else None,
                # cover at today's pace (last 30 days), not the lifetime rate
                "days_of_stock": round(st / (v["30"] / 30)) if v["30"] else None,
            })
        key, desc = ordering.lstrip("-"), ordering.startswith("-")
        if key == "style":
            out.sort(key=lambda r: r["style"], reverse=desc)
        else:  # styles with no value (never sold) always last
            have = sorted((r for r in out if r[key] is not None), key=lambda r: r[key], reverse=desc)
            out = have + [r for r in out if r[key] is None]
        totals = {k: sum(r[k] or 0 for r in out) for k in ("stock", "sold_30", "sold_60", "sold_90", "sales_90")}
        return {"count": len(out), "page": page, "page_size": size, "totals": totals,
                "rows": out[(page - 1) * size: page * size],
                "styles": out if request.query_params.get("export") else []}
