"""TD P&L, quarter on quarter - the formulas of TD_P&L_QoQ_Rev.xlsx (sheet 'P&L QoQ'), line by line.

    Gross Revenue                     input                                   (row 4)
    Less: Returns / Refunds / Canc.   input                                   (row 5)
    Net Revenue                       Gross - Returns                         (row 6)
    Less: Product Cost / COGS         Net x COGS %   (sheet: 70%)            (row 7)
    Gross Profit                      Net - COGS                              (row 8)
    Gross Margin %                    Gross Profit / Net                      (row 9)
    Less: Payment Gateway             Gross x PG %   (sheet: 1%)             (row 10)
    Less: Loyalty Cost                Gross x Loyalty %  (sheet: 0.5% / 2)    (row 11)
    CM 1                              Gross Profit - (PG + Loyalty)           (row 12)
    CM %                              CM 1 / Net                              (row 13)
    Less: Technology / Platform       input                                   (row 14)
    Less: Manpower & operating cost   input                                   (row 15)
    CM 2                              CM 1 - (Technology + Manpower)          (row 16)
    Misc Exp                          input                                   (row 17)
    Operating Profit / EBITDA         CM 2 - Misc                             (row 18)
    Operating Margin %                EBITDA / Gross Revenue  (note: on Gross, CM % is on Net - as in the sheet)

QoQ growth = (this quarter - previous quarter) / previous quarter, as in the sheet's growth columns, with two fixes:
  * margin rows show the change in percentage points (30.0% -> 28.7% = -1.3 pp); the sheet divided percentages by
    percentages, which is not meaningful;
  * Loyalty Cost growth is calculated (the sheet had a hard-coded 0 in D11).

Checks against the data, per quarter (they never change the P&L, they show where the entered / assumed figures differ):
  gross revenue  - order value incl. points of paid orders placed in the quarter (TD data)
  returns        - customer refunds in the finance tracker for orders placed in the quarter
  payment gateway- actual PayU deduction rate: (PayU amount - PayU settlement) / PayU amount, settled orders without a
                   refund (finance tracker)
  loyalty        - loyalty points actually redeemed on the quarter's orders (TD data)
"""
import datetime as dt
from decimal import Decimal

from django.db.models import Count, F, Q, Sum
from django.utils.timezone import localdate  # India date (TIME_ZONE), not the server clock

D0 = Decimal(0)
HUNDRED = Decimal(100)

# key, label, kind (input | calc | assumption | subtotal | total | margin), formula shown in the dashboard
LINES = [
    ("gross_revenue", "Gross Revenue", "input", "Entered"),
    ("returns", "Less: Returns / Refunds / Cancellations", "input", "Entered"),
    ("net_revenue", "Net Revenue", "subtotal", "Gross Revenue - Returns"),
    ("cogs", "Less: Product Cost / COGS", "assumption", "{cogs_pct}% of Net Revenue"),
    ("gross_profit", "Gross Profit", "subtotal", "Net Revenue - COGS"),
    ("gross_margin", "Gross Margin %", "margin", "Gross Profit / Net Revenue"),
    ("payment_gateway", "Less: Payment Gateway", "assumption", "{pg_pct}% of Gross Revenue"),
    ("loyalty", "Less: Loyalty Cost", "assumption", "{loyalty_pct}% of Gross Revenue"),
    ("cm1", "CM 1", "subtotal", "Gross Profit - Payment Gateway - Loyalty"),
    ("cm1_pct", "CM %", "margin", "CM 1 / Net Revenue"),
    ("tech", "Less: Technology / Platform Cost", "input", "Entered"),
    ("manpower", "Less: Manpower & Operating Cost", "input", "Entered"),
    ("cm2", "CM 2", "subtotal", "CM 1 - Technology - Manpower"),
    ("misc", "Misc Exp", "input", "Entered"),
    ("ebitda", "Operating Profit / EBITDA", "total", "CM 2 - Misc"),
    ("op_margin", "Operating Margin %", "margin", "EBITDA / Gross Revenue"),
]
MARGINS = {k for k, _l, kind, _f in LINES if kind == "margin"}
INPUT_FIELDS = ["gross_revenue", "returns", "cogs_pct", "pg_pct", "loyalty_pct", "tech_platform_cost",
                "manpower_operating_cost", "misc_expense", "notes"]
CARRY_FORWARD = ["cogs_pct", "pg_pct", "loyalty_pct", "tech_platform_cost", "manpower_operating_cost", "misc_expense"]


# ----------------------------------------------------------------------------- quarters
def is_quarter_start(d):
    return d.day == 1 and d.month in (1, 4, 7, 10)


def quarter_of(d):
    return dt.date(d.year, ((d.month - 1) // 3) * 3 + 1, 1)


def next_quarter(start):
    return dt.date(start.year + (start.month == 10), (start.month % 12) + 3 if start.month != 10 else 1, 1)


def quarter_end(start):
    return next_quarter(start) - dt.timedelta(days=1)


def quarter_label(start):
    """'Q2 (FY 25-26)' - the sheet's labels. FY starts 1 April."""
    fy = start.year if start.month >= 4 else start.year - 1
    q = {4: 1, 7: 2, 10: 3, 1: 4}[start.month]
    return f"Q{q} (FY {fy % 100:02d}-{(fy + 1) % 100:02d})"


# ----------------------------------------------------------------------------- the sheet's formulas
def _sub(a, *bs):
    if a is None or any(b is None for b in bs):
        return None
    return a - sum(bs, D0)


def _ratio(a, b):
    if a is None or b in (None, D0):
        return None
    return a / b


def compute(q):
    """{line key: Decimal | None} for one PnlQuarter (None = an input it needs is not entered yet)."""
    g, r = q.gross_revenue, q.returns
    pct = lambda p: Decimal(p) / HUNDRED  # noqa: E731
    v = {"gross_revenue": g, "returns": r}
    v["net_revenue"] = _sub(g, r)
    v["cogs"] = v["net_revenue"] * pct(q.cogs_pct) if v["net_revenue"] is not None else None
    v["gross_profit"] = _sub(v["net_revenue"], v["cogs"])
    v["gross_margin"] = _ratio(v["gross_profit"], v["net_revenue"])
    v["payment_gateway"] = g * pct(q.pg_pct) if g is not None else None
    v["loyalty"] = g * pct(q.loyalty_pct) if g is not None else None
    v["cm1"] = _sub(v["gross_profit"], v["payment_gateway"], v["loyalty"])
    v["cm1_pct"] = _ratio(v["cm1"], v["net_revenue"])
    v["tech"], v["manpower"], v["misc"] = q.tech_platform_cost, q.manpower_operating_cost, q.misc_expense
    v["cm2"] = _sub(v["cm1"], v["tech"], v["manpower"])
    v["ebitda"] = _sub(v["cm2"], v["misc"])
    v["op_margin"] = _ratio(v["ebitda"], g)
    return v


def growth(cur, prev):
    """{line key: fraction (value lines) or percentage points as a fraction (margin lines) | None}."""
    out = {}
    for key, *_ in LINES:
        a, b = cur.get(key), (prev or {}).get(key)
        if a is None or b is None:
            out[key] = None
        elif key in MARGINS:
            out[key] = a - b
        else:
            out[key] = (a - b) / b if b else None
    return out


# ----------------------------------------------------------------------------- checks against the data
def data_checks(q, values):
    """Entered / assumed figures next to what the data says. ebitda_effect = EBITDA with the actual cost - EBITDA in
    the P&L (negative: the P&L overstates profit)."""
    from masters.models import PnlDataCheck
    from warehouse.models import DistributorSettlement

    start, end = q.quarter_start, quarter_end(q.quarter_start)
    dc = PnlDataCheck.objects.filter(quarter_start=start).first()
    tr = DistributorSettlement.objects.filter(order_date__gte=start, order_date__lte=end)
    t = tr.aggregate(n=Count("id"), refunds=Sum("customer_refund"))
    settled = tr.filter(pg_settlement__gt=0, payu_value__gt=0).filter(Q(customer_refund__isnull=True) | Q(customer_refund=0))
    s = settled.aggregate(base=Sum("payu_value"), fee=Sum(F("payu_value") - F("pg_settlement")))
    g = values.get("gross_revenue")
    out = {"data_orders": dc.orders if dc else 0,
           "tracker_orders": t["n"] or 0,
           "tracker_coverage": (round((t["n"] or 0) / dc.orders, 4) if dc and dc.orders else None),
           "cancelled_value": float(dc.cancelled_value) if dc else None}
    rows = []

    def row(key, label, entered, data, basis, ebitda_effect=None):
        rows.append({"key": key, "label": label, "entered": _f(entered), "data": _f(data),
                     "diff": _f(entered - data) if entered is not None and data is not None else None,
                     "diff_pct": (float((entered - data) / data) if entered is not None and data else None),
                     "ebitda_effect": _f(ebitda_effect), "basis": basis})

    row("gross_revenue", "Gross Revenue", g, dc.order_value if dc else None,
        "Order value incl. points of paid orders placed in the quarter (TD data)")
    row("returns", "Returns / refunds", values.get("returns"), t["refunds"] if t["n"] else None,
        "Customer refunds in the finance tracker for the quarter's orders")
    pg_rate = (s["fee"] / s["base"]) if s["base"] else None
    pg_actual = (g * pg_rate) if g is not None and pg_rate is not None else None
    row("payment_gateway", "Payment gateway", values.get("payment_gateway"), pg_actual,
        (f"Actual PayU deduction {float(pg_rate) * 100:.2f}% (PayU amount - settlement, settled orders without "
         f"a refund) x Gross Revenue" if pg_rate is not None else "No PayU settlements in the finance tracker"),
        ebitda_effect=(values["payment_gateway"] - pg_actual) if pg_actual is not None and values.get("payment_gateway") is not None else None)
    loy_actual = dc.points_redeemed if dc else None
    row("loyalty", "Loyalty cost", values.get("loyalty"), loy_actual,
        "Loyalty points redeemed on the quarter's orders (TD data)",
        ebitda_effect=(values["loyalty"] - loy_actual) if loy_actual is not None and values.get("loyalty") is not None else None)
    out["rows"] = rows
    out["pg_actual_rate"] = float(pg_rate) if pg_rate is not None else None
    return out


def _f(v):
    return None if v is None else float(v)


# ----------------------------------------------------------------------------- the statement
def statement(today=None):
    from masters.models import PnlQuarter

    today = today or localdate()
    quarters = list(PnlQuarter.objects.all())
    by_start = {q.quarter_start: q for q in quarters}
    computed = {q.quarter_start: compute(q) for q in quarters}
    out = []
    for q in quarters:
        prev_start = quarter_of(q.quarter_start - dt.timedelta(days=1))
        vals = computed[q.quarter_start]
        g = growth(vals, computed.get(prev_start)) if prev_start in by_start else {k: None for k, *_ in LINES}
        missing = [f for f in ("gross_revenue", "returns", "tech_platform_cost", "manpower_operating_cost",
                               "misc_expense") if getattr(q, f) is None]
        out.append({
            "start": q.quarter_start.isoformat(), "end": quarter_end(q.quarter_start).isoformat(),
            "label": quarter_label(q.quarter_start),
            "status": "complete" if quarter_end(q.quarter_start) < today else "in_progress",
            "previous": quarter_label(prev_start) if prev_start in by_start else None,
            "inputs": {f: (_f(getattr(q, f)) if f != "notes" else q.notes) for f in INPUT_FIELDS},
            "values": {k: _f(v) for k, v in vals.items()},
            "growth": {k: _f(v) for k, v in g.items()},
            "missing": missing,
            "checks": data_checks(q, vals),
            "updated_by": q.updated_by, "updated_at": q.updated_at.isoformat() if q.updated_at else None,
        })
    nxt = next_quarter(quarters[-1].quarter_start) if quarters else quarter_of(today)
    return {
        "lines": [{"key": k, "label": label, "kind": kind, "formula": f} for k, label, kind, f in LINES],
        "quarters": out,
        "next_quarter": ({"start": nxt.isoformat(), "label": quarter_label(nxt)} if nxt <= today else None),
    }


def export_rows(data):
    """The statement as the sheet lays it out: one row per line, value and QoQ growth per quarter."""
    rows = []
    for line in data["lines"]:
        r = {"P&L Particular": line["label"]}
        for q in data["quarters"]:
            v = q["values"].get(line["key"])
            r[q["label"]] = round(v, 4 if line["kind"] == "margin" else 2) if v is not None else None
            gr = q["growth"].get(line["key"])
            r[f"{q['label']} QoQ" + (" (pp)" if line["kind"] == "margin" else "")] = (
                round(gr * 100, 2) if gr is not None else None)
        rows.append(r)
    return rows


# ----------------------------------------------------------------------------- data totals (at every import)
def rebuild_data_checks(order_rows):
    """Per-quarter totals from the TD orders (dicts of strings, as the importer reads them)."""
    from collections import defaultdict

    from ingestion.normalize import to_date, to_dec
    from masters.models import PnlDataCheck

    from warehouse.models import Distributor

    # company-internal accounts (Distributor.is_internal) are not revenue
    internal = {sid.split(":", 1)[1] for sid in Distributor.objects.filter(
        is_internal=True, source_id__startswith="td:").values_list("source_id", flat=True)}
    agg = defaultdict(lambda: {"orders": 0, "order_value": D0, "line_value": D0, "cancelled_value": D0,
                               "points_redeemed": D0})
    for o in order_rows:
        if (o.get("distributor_id") or "").strip() in internal:
            continue
        day = to_date(o.get("order_date"))
        if not day:
            continue
        paid = bool((o.get("mode") or "").strip()) or to_dec(o.get("payu_amount")) > 0
        if not paid:
            continue
        a = agg[quarter_of(day)]
        total = to_dec(o.get("total_amount"))
        a["orders"] += 1
        a["order_value"] += total
        a["line_value"] += to_dec(o.get("line_total"))
        a["points_redeemed"] += to_dec(o.get("points_redeemed"))
        if (o.get("ts_order_status") or "").strip().lower() in ("cancelled", "canceled"):
            a["cancelled_value"] += total
    for start, a in agg.items():
        PnlDataCheck.objects.update_or_create(quarter_start=start, defaults=a)
    PnlDataCheck.objects.exclude(quarter_start__in=list(agg)).delete()
    return len(agg)
