"""Source reconciliation: the dashboard against the sources it reads, so a figure never silently differs from the
sheet people check it against (like Oct-26 sales: ₹3.43 Cr on the dashboard, ₹3.50 Cr in the finance sheet).

Run after every refresh (run_data_quality_checks) and shown on Data Health. Each check returns rows; anything off
becomes a Data Health issue with the order / month / target it is about.

  tracker   finance "Order Tracking" sheet vs dashboard sales: per month (value, orders) and per order (only in
            the sheet, only in TD, value, distributor, cancelled status). Orders of the last 2 days are left out:
            the sheet lists them before the next TD import.
  supabase  TD's own data (Supabase orders table) vs what the dashboard imported, per month: orders and value.
  targets   one month's targets must add up the same at every level (overall = regions = states = ASMs =
            distributors) and equal the target sheet's total.
  sheets    names in the live sheets that matched no distributor (finance tracker, TechnoD Distributors).
"""
import datetime as dt
from collections import defaultdict

from django.db.models import Count, Sum

RECENT_DAYS = 2      # orders this new may be in the sheet before the next TD import
TOLERANCE = 1.0      # ₹ per order
MONTH_TOL = 1000.0   # ₹ per month (rounding in the sheet)


def _month(d):
    return d.replace(day=1)


def tracker(today):
    """Compared per CART, not per row: finance sometimes merges a split cart into one row, and TD and finance split
    a cart's amount between its distributors differently. A cart = TD orders sharing split_group."""
    from warehouse.models import DistributorSettlement, Order

    rows = list(DistributorSettlement.objects.values(
        "order_ref", "order_date", "order_value", "distributor_id", "distributor__name", "sheet_distributor",
        "fulfilment"))
    if not rows:
        return {"available": False}
    start = min(r["order_date"] for r in rows)
    orders = {o["display_id"]: o for o in Order.objects.filter(placed_date__gte=start).values(
        "id", "display_id", "split_group", "placed_date", "gross_value", "distributor_id", "distributor__name",
        "status", "is_qualifying")}
    recent = today - dt.timedelta(days=RECENT_DAYS)

    # month totals; sheet rows of the last days not imported yet are left out (they arrive with the next refresh)
    months = defaultdict(lambda: {"sheet": 0.0, "sheet_orders": 0, "dashboard": 0.0, "dashboard_orders": 0,
                                  "awaiting_import": 0})
    for r in rows:
        m = months[_month(r["order_date"])]
        if r["order_ref"] not in orders and r["order_date"] >= recent:
            m["awaiting_import"] += 1
            continue
        m["sheet"] += float(r["order_value"] or 0)
        m["sheet_orders"] += 1
    for o in orders.values():
        if o["is_qualifying"]:
            m = months[_month(o["placed_date"])]
            m["dashboard"] += float(o["gross_value"] or 0)
            m["dashboard_orders"] += 1
    month_rows = []
    for mm in sorted(months):
        v = months[mm]
        diff = v["dashboard"] - v["sheet"]
        month_rows.append({"month": mm.isoformat()[:7], **{k: round(x, 2) if isinstance(x, float) else x for k, x in v.items()},
                           "diff": round(diff, 2), "ok": abs(diff) <= MONTH_TOL})

    # carts
    cart_td, cart_sheet, cart_rows = defaultdict(float), defaultdict(float), defaultdict(list)
    for o in orders.values():
        if o["is_qualifying"]:
            cart_td[o["split_group"]] += float(o["gross_value"] or 0)
    only_sheet, dist_diff, status_diff = [], [], []
    for r in rows:
        o = orders.get(r["order_ref"])
        if o is None:
            if r["order_date"] < recent:
                only_sheet.append({"order": r["order_ref"], "date": r["order_date"].isoformat(),
                                   "value": float(r["order_value"] or 0), "distributor": r["sheet_distributor"]})
            continue
        cart_sheet[o["split_group"]] += float(r["order_value"] or 0)
        cart_rows[o["split_group"]].append(r["order_ref"])
        if r["distributor_id"] and o["distributor_id"] and r["distributor_id"] != o["distributor_id"]:
            dist_diff.append({"order": r["order_ref"], "date": r["order_date"].isoformat(),
                              "sheet": r["sheet_distributor"] or r["distributor__name"], "dashboard": o["distributor__name"]})
        if (r["fulfilment"] == "cancelled") != (o["status"] == "cancelled"):
            status_diff.append({"order": r["order_ref"], "date": r["order_date"].isoformat(),
                                "sheet": r["fulfilment"] or "–", "dashboard": o["status"]})
    by_group = defaultdict(list)
    for k, o in orders.items():
        by_group[o["split_group"]].append(o)
    value_diff, only_td = [], []
    for g, members in by_group.items():
        first = min(m["placed_date"] for m in members)
        if first >= recent or not any(m["is_qualifying"] for m in members):
            continue
        if g not in cart_sheet:  # no row of this cart in the sheet
            for m in members:
                if m["is_qualifying"]:
                    only_td.append({"order": m["display_id"], "date": m["placed_date"].isoformat(),
                                    "value": float(m["gross_value"] or 0), "distributor": m["distributor__name"],
                                    "status": m["status"]})
            continue
        d = cart_td[g] - cart_sheet[g]
        if abs(d) > TOLERANCE:
            value_diff.append({"order": " + ".join(sorted(m["display_id"] for m in members)), "date": first.isoformat(),
                               "sheet": round(cart_sheet[g], 2), "dashboard": round(cart_td[g], 2), "diff": round(d, 2),
                               "distributor": ", ".join(sorted({m["distributor__name"] or "?" for m in members})),
                               "split": len(members) > 1})
    # finance sometimes merges two TD orders of the same day into one row: a row short by exactly an order that is
    # missing from the sheet -> the pair is explained, not an error
    merged = []
    for v in list(value_diff):
        if v["diff"] >= 0:
            continue
        hit = next((o for o in only_td if o["date"] == v["date"] and abs(o["value"] + v["diff"]) <= TOLERANCE), None)
        if hit:
            only_td.remove(hit)
            value_diff.remove(v)
            merged.append({"sheet_row": v["order"], "merged_order": hit["order"], "date": v["date"], "value": v["sheet"]})
    value_diff.sort(key=lambda r: -abs(r["diff"]))
    return {"available": True, "merged_in_sheet": merged, "from": start.isoformat(), "months": month_rows, "only_sheet": only_sheet,
            "only_td": only_td, "value_diff": value_diff, "distributor_diff": dist_diff, "status_diff": status_diff}


def supabase(today):
    """Supabase orders per month vs the dashboard's import (all orders, before any dashboard rule)."""
    from django.conf import settings

    if "supabase" not in settings.DATABASES:
        return {"available": False}
    from ingestion.connectors.supabase import fetch
    from warehouse.models import Order

    from masters.exclusions import excluded_source_ids

    try:
        # the import takes total_amount, else the line total when TD has no order value: mirror it
        _c, rows = fetch("SELECT date_trunc('month', order_date)::date AS m, count(*), "
                         "sum(CASE WHEN coalesce(total_amount, 0) > 0 THEN total_amount ELSE line_total END) "
                         "FROM orders WHERE order_date IS NOT NULL GROUP BY 1 ORDER BY 1")
    except Exception as exc:  # noqa: BLE001 - no connection: shown, not raised
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"}
    local = {}
    for r in Order.objects.values("placed_date__year", "placed_date__month").annotate(n=Count("id"), v=Sum("gross_value")):
        local[dt.date(r["placed_date__year"], r["placed_date__month"], 1)] = (r["n"], float(r["v"] or 0))
    out = []
    removed = bool(excluded_source_ids())
    for m, n, v in rows:
        m = m if isinstance(m, dt.date) else dt.date.fromisoformat(str(m)[:10])
        ln, lv = local.get(m, (0, 0.0))
        sv = float(v or 0)
        out.append({"month": m.isoformat()[:7], "supabase_orders": n, "dashboard_orders": ln,
                    "supabase_value": round(sv, 2), "dashboard_value": round(lv, 2), "diff": round(lv - sv, 2),
                    "ok": ln == n and abs(lv - sv) <= MONTH_TOL or (m >= _month(today))})
    return {"available": True, "months": out, "note": "distributors removed from the dashboard have no orders" if removed else ""}


def targets():
    """For each month: the target at every level, which must agree, and the target sheet's total.
    Targets keep their history (a new version per edit): only the version in force counts, as everywhere else
    (metrics.target_values)."""
    from warehouse.models import Target, TargetSplit

    from .metrics import target_values

    months = sorted(set(Target.objects.filter(metric="sales").values_list("month", flat=True)))
    by = defaultdict(dict)
    for level in ("overall", "region", "state", "asm", "distributor"):
        vals = defaultdict(float)
        for (_sid, m), v in target_values(level, None, months).items():
            vals[m] += float(v or 0)
        for m, v in vals.items():
            by[m][level] = round(v, 2)
    sheet = {r["month"]: float(r["v"] or 0) for r in TargetSplit.objects.values("month").annotate(v=Sum("value"))}
    out = []
    for m in sorted(by):
        levels = by[m]
        # a level with targets for only a few scopes (e.g. 2 distributors) is partial, not a conflict
        full = {k: v for k, v in levels.items() if k in ("overall", "region")}
        vals = [v for v in full.values() if v]
        spread = (max(vals) - min(vals)) if vals else 0
        s = sheet.get(m)
        overall = levels.get("overall") or levels.get("region")
        ok = spread <= MONTH_TOL and (s is None or overall is None or abs(s - overall) <= MONTH_TOL)
        out.append({"month": m.isoformat()[:7], "levels": levels, "sheet": s, "ok": ok})
    return {"months": out}


def sheets():
    """Names the live sheets carry that matched nothing in the dashboard (from each sheet's last import)."""
    from ingestion.models import SyncRun

    out = {}
    for source, key in (("settlement", "unknown_distributors"), ("distributor_sync", "unmatched")):
        r = SyncRun.objects.filter(source=source, status="success").order_by("-id").first()
        out[source] = sorted((r.details or {}).get(key) or []) if r else []
    return out


def run(today=None):
    from django.utils.timezone import localdate

    today = today or localdate()
    return {"tracker": tracker(today), "supabase": supabase(today), "targets": targets(), "sheets": sheets()}


def issues(result):
    """[(code, object_type, object_id, details)] for Data Health."""
    out = []
    t = result.get("tracker") or {}
    for r in t.get("months", []):
        if not r["ok"]:
            out.append(("sales_vs_sheet_month", "month", r["month"], r))
    for code, key in (("order_only_in_sheet", "only_sheet"), ("order_missing_in_sheet", "only_td"),
                      ("order_value_vs_sheet", "value_diff"), ("order_distributor_vs_sheet", "distributor_diff"),
                      ("order_status_vs_sheet", "status_diff")):
        for r in t.get(key, []):
            out.append((code, "order", r["order"], r))
    for r in (result.get("supabase") or {}).get("months", []):
        if not r["ok"]:
            out.append(("import_vs_supabase", "month", r["month"], r))
    for r in (result.get("targets") or {}).get("months", []):
        if not r["ok"]:
            out.append(("targets_dont_add_up", "month", r["month"], r))
    for source, names in (result.get("sheets") or {}).items():
        for n in names:
            out.append(("sheet_distributor_unmatched", "sheet", f"{source}:{n}"[:64], {"sheet": source, "name": n}))
    return out


def apply_sheet_merges(result):
    """Orders finance merged into another order's row of the sheet (tracker["merged_in_sheet"]) count as part of that
    row, so the dashboard's order count equals the sheet's rows (user, 2026-11-27). Their value is unchanged."""
    from warehouse.models import Order

    pairs = {m["merged_order"].lstrip("#"): m["sheet_row"].lstrip("#")
             for m in (result.get("tracker") or {}).get("merged_in_sheet") or []}
    changed = Order.objects.exclude(merged_into="").exclude(display_id__in=list(pairs)).update(merged_into="")
    for oid, row in pairs.items():
        changed += Order.objects.filter(display_id=oid).exclude(merged_into=row).update(merged_into=row)
    if changed:
        from .cache import bump_cache_version

        bump_cache_version()
    return changed


def apply_sheet_cancellations():
    """TD does not update the status of older orders (memory: td-order-status-stale); the finance sheet records the
    cancellation. An order the sheet marks cancelled is cancelled on the dashboard too, unless TD says delivered.
    Runs after every import (the import resets the status from TD)."""
    from warehouse.models import DistributorSettlement, Order

    ids = list(DistributorSettlement.objects.filter(fulfilment="cancelled", order__isnull=False).exclude(
        order__status__in=("cancelled", "delivered")).values_list("order_id", flat=True))
    changed = 0
    for o in Order.objects.filter(id__in=ids):
        o.status = "cancelled"
        o.save(update_fields=["status", "is_qualifying", "updated_at"])  # save() recomputes is_qualifying
        changed += 1
    return changed


def store(result):
    """Keep the latest result for Data Health (a SyncRun of its own, like the other checks)."""
    import json

    from django.utils import timezone

    from ingestion.models import SyncRun

    now = timezone.now()
    SyncRun.objects.create(source="reconciliation", status="success", started_at=now, finished_at=now,
                           rows=len(issues(result)), details=json.loads(json.dumps(result, default=str)))
    SyncRun.objects.filter(source="reconciliation").exclude(
        id__in=SyncRun.objects.filter(source="reconciliation").order_by("-id").values("id")[:10]).delete()


def latest():
    from ingestion.models import SyncRun

    r = SyncRun.objects.filter(source="reconciliation").order_by("-id").first()
    return (r.details, r.finished_at) if r else (None, None)
