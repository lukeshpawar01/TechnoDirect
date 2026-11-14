"""Data tools the assistant can use. Each tool is an existing dashboard endpoint, called AS THE SIGNED-IN USER
through DRF (permission check + data-scope filtering + cache are exactly those of the dashboard page), so the
assistant can never see more than the user could see on screen.
"""
import json
import logging

from django.urls import resolve
from rest_framework.test import APIRequestFactory, force_authenticate

from ingestion.csv_import import norm
from masters.models import MetricDefinition
from warehouse.models import Asm, Distributor, Region, State

log = logging.getLogger(__name__)

COMMON_PARAMS = {"preset", "date_from", "date_to", "compare", "region", "state", "asm", "distributor", "category"}
PRESETS_HELP = ("today, yesterday, wtd (this week), last_week, mtd (month to date), prev_month, q1 (Apr-Jun), "
                "q2 (Jul-Sep), q3 (Oct-Dec), q4 (Jan-Mar), fytd (financial year to date, from 1 Apr), last_7d, "
                "last_30d, last_90d, last_12m, all_time, custom (needs date_from and date_to as YYYY-MM-DD)")

TOOLS = {
    "overview": {
        "label": "Executive Overview", "perm": "view_overview", "path": "/api/overview/",
        "about": "Headline KPIs for the period: sales, orders, average order value, units, active / new retailers, "
                 "target vs achievement with run rates and month-end projection, top distributors and states, "
                 "concentration and exceptions.",
        "extra": {"segment"},
    },
    "mom_trend": {
        "label": "Month-on-month trend", "perm": "view_overview", "path": "/api/trends/mom/",
        "about": "Monthly sales value, pieces, boxes, orders and average price per piece with month-on-month % "
                 "(the running month is compared like-for-like). Param months = 6, 12 or 24.",
        "extra": {"months", "cat_l2", "cat_l3"},
    },
    "funnel": {
        "label": "Retailer Funnel", "perm": "view_funnel", "path": "/api/funnel/",
        "about": "Retailer sign-up -> KYC -> first order funnel, KYC status mix, never-ordered retailers.",
        "extra": set(),
    },
    "distributors": {
        "label": "Distributors", "perm": "view_distributors", "path": "/api/distributors/",
        "about": "Scorecard per distributor: sales, share, orders, AOV, active / new retailers, repeat %, dispatch %, "
                 "target and achievement, ASM, stock-sync freshness.",
        "extra": {"stock_sync"},
    },
    "territory": {
        "label": "Territory", "perm": "view_territory", "path": "/api/territory/",
        "about": "Sales, target and achievement grouped by region, state or ASM (param group_by = region|state|asm).",
        "extra": {"group_by"},
    },
    "orders": {
        "label": "Orders & Fulfilment", "perm": "view_orders", "path": "/api/orders/summary/",
        "about": "Order status counts and values, ageing, dispatch / delivery turnaround, SLA breaches, payment "
                 "status and payment-mode mix.",
        "extra": {"payment_status", "payment_mode", "platform", "is_split"},
    },
    "products": {
        "label": "Products", "perm": "view_products", "path": "/api/products/",
        "about": "Sales by category, top and bottom articles (styles), sizes, new launches, realisation per unit.",
        "extra": {"cat_l2", "cat_l3"},
    },
    "inventory": {
        "label": "Inventory", "perm": "view_inventory", "path": "/api/inventory/",
        "about": "Current stock per distributor: out-of-stock and low-stock counts, stock cover, sync freshness.",
        "extra": {"cat_l2", "cat_l3", "size"},
    },
    "retention": {
        "label": "Retention & Growth", "perm": "view_retention", "path": "/api/retention/",
        "about": "Active / new / retained / reactivated / lost retailers by month, cohorts, repeat contribution, "
                 "order-frequency bands, Pareto concentration.",
        "extra": {"segment"},
    },
    "loyalty": {
        "label": "Loyalty Points", "perm": "view_loyalty", "path": "/api/loyalty/",
        "about": "Loyalty points issued and redeemed, redemption rate, members, monthly trend, top members.",
        "extra": {"event_type"},
    },
    "data_health": {
        "label": "Data Health", "perm": "view_data_health", "path": "/api/data-health/",
        "about": "Data source sync status, data-quality issues and reconciliation with the MIS.",
        "extra": set(),
    },
    "metric_definitions": {
        "label": "Metric Dictionary", "perm": None, "path": None,
        "about": "Official definitions and formulas of every dashboard metric (sales, AOV, active retailer, "
                 "retention, run rate, ...). Use it to explain what a metric means.",
        "extra": set(),
    },
}

DROP_KEYS = {"spark", "sparkline", "monthly_by_group", "daily", "cohorts", "issue_rows"}
MAX_LIST = 15
MAX_CHARS = 9000


def allowed_tools(user):
    return {k: t for k, t in TOOLS.items() if t["perm"] is None or user.has_code(t["perm"])}


def denied_tools(user):
    return {k: t for k, t in TOOLS.items() if t["perm"] and not user.has_code(t["perm"])}


def _round(v):
    if isinstance(v, float):
        return round(v, 2)
    return v


def compact(obj, max_list=MAX_LIST, depth=0):
    """Shrink an API payload for the model: drop sparklines, cut long lists, round floats."""
    if isinstance(obj, dict):
        return {k: compact(v, max_list, depth + 1) for k, v in obj.items() if k not in DROP_KEYS and v is not None}
    if isinstance(obj, list):
        out = [compact(v, max_list, depth + 1) for v in obj[:max_list]]
        if len(obj) > max_list:
            out.append({"_more_rows_not_shown": len(obj) - max_list})
        return out
    return _round(obj)


def _fit(data):
    """Largest list length that keeps the payload under MAX_CHARS; last resort is a truncated text preview."""
    s = ""
    for n in (MAX_LIST, 8, 5, 3):
        c = compact(data, n)
        s = json.dumps(c, ensure_ascii=False, default=str)
        if len(s) <= MAX_CHARS:
            return c
    return {"_note": "payload truncated", "preview": s[:MAX_CHARS]}


def _resolve_names(param, values):
    """The model may send names ("Karnataka", "Heera"); turn them into ids the API accepts."""
    model = {"region": Region, "state": State, "asm": Asm, "distributor": Distributor}.get(param)
    if model is None:
        return values
    out = []
    for v in values:
        v = str(v).strip()
        if not v:
            continue
        if v.isdigit():
            out.append(v)
            continue
        n = norm(v)
        hit = None
        for obj in model.objects.all():
            names = [obj.name, getattr(obj, "code", "")] + list(getattr(obj, "aliases", None) or [])
            if any(norm(x) == n for x in names if x):
                hit = obj
                break
        if hit is None:  # unique prefix ("Heera" -> "Heera Exports Inc")
            cands = [o for o in model.objects.all() if norm(o.name).startswith(n)]
            hit = cands[0] if len(cands) == 1 else None
        out.append(str(hit.id) if hit else "0")  # unknown name -> matches nothing rather than everything
    return out


def clean_params(tool, params):
    keep = COMMON_PARAMS | TOOLS[tool]["extra"]
    out = {}
    for k, v in (params or {}).items():
        if k not in keep or v in (None, "", []):
            continue
        vals = v if isinstance(v, list) else str(v).split(",")
        vals = _resolve_names(k, vals) if k in ("region", "state", "asm", "distributor") else vals
        if k == "category":
            vals = [str(x).strip().lower() for x in vals]
        out[k] = ",".join(str(x).strip() for x in vals if str(x).strip())
    return out


def run_tool(tool, params, user):
    """Execute a tool as `user`. Returns (data, meta, error)."""
    t = TOOLS[tool]
    if t["perm"] and not user.has_code(t["perm"]):
        return None, None, "not_authorised"
    if tool == "metric_definitions":
        rows = list(MetricDefinition.objects.values("code", "name", "definition", "formula", "source", "refresh"))
        return {"metrics": rows}, None, None
    factory = APIRequestFactory()
    req = factory.get(t["path"], params)
    force_authenticate(req, user=user)
    match = resolve(t["path"])
    try:
        resp = match.func(req, *match.args, **match.kwargs)
    except Exception as exc:  # noqa: BLE001
        log.exception("assistant tool %s failed", tool)
        return None, None, f"error: {exc.__class__.__name__}"
    if resp.status_code == 403:
        return None, None, "not_authorised"
    if resp.status_code >= 400:
        return None, None, f"error {resp.status_code}: {str(getattr(resp, 'data', ''))[:200]}"
    body = resp.data
    if isinstance(body, dict) and "data" in body:
        return _fit(body["data"]), body.get("meta"), None
    return _fit(body), None, None
