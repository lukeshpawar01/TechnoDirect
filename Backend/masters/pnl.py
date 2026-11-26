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

Everything is calculated from the entered figures and the % assumptions only. The edit form offers two figures
from the data to fill in ("Use data"): gross revenue (order value incl. points of paid orders placed in the quarter,
TD data) and returns (customer refunds in the finance tracker for the quarter's orders).
"""
import datetime as dt
from decimal import Decimal

from django.db.models import Count, Sum
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


# ----------------------------------------------------------------------------- data figures for the edit form
def data_checks(q, values):
    """What the data says for the two entered revenue lines, offered as "Use data" in the edit form.
    The P&L itself is calculated only from the entered figures and the % assumptions (payment gateway and loyalty
    are % of Gross Revenue). The actual-PayU / loyalty comparison was removed on 2026-11-26 (user request: no PayU
    settlement data for now - PayU API not connected)."""
    from masters.models import PnlDataCheck
    from warehouse.models import DistributorSettlement

    start, end = q.quarter_start, quarter_end(q.quarter_start)
    dc = PnlDataCheck.objects.filter(quarter_start=start).first()
    t = DistributorSettlement.objects.filter(order_date__gte=start, order_date__lte=end).aggregate(
        n=Count("id"), refunds=Sum("customer_refund"))
    rows = [
        {"key": "gross_revenue", "data": _f(dc.order_value) if dc else None},
        {"key": "returns", "data": _f(t["refunds"]) if t["n"] else None},
    ]
    return {"rows": rows}


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


# ----------------------------------------------------------------------------- monthly P&L
MONTH_FIELDS = ["gross_revenue", "returns", "cogs_pct", "pg_pct", "loyalty_pct", "tech_platform_cost",
                "manpower_operating_cost", "misc_expense"]
MONTH_COSTS = ["tech_platform_cost", "manpower_operating_cost", "misc_expense"]
PCT_DEFAULTS = {"cogs_pct": Decimal(70), "pg_pct": Decimal(1), "loyalty_pct": Decimal("0.25")}
MAX_MONTHS = 12


def month_start(d):
    return d.replace(day=1)


def add_months(m, n):
    y, mo = divmod(m.month - 1 + n, 12)
    return dt.date(m.year + y, mo + 1, 1)


def month_end(m):
    return add_months(m, 1) - dt.timedelta(days=1)


def month_label(m):
    return m.strftime("%b %Y")


class _Inputs:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def month_inputs(m, today, quarters, data, refunds, tracker_from, override):
    """The month's inputs and where each comes from.
    Defaults: gross = TD order value incl. points of paid orders (TD data); returns = finance tracker refunds for the
    month's orders (or the quarter's returns in proportion to revenue before the tracker starts); % = the month's
    quarter (else the latest quarter before it, else the sheet's); costs = the quarter's / 3. A month in progress
    counts costs only for the days so far, so its EBITDA is month to date like its revenue."""
    q = quarters.get(quarter_of(m))
    if q is None:
        before = [k for k in quarters if k <= m]
        q = quarters[max(before)] if before else (quarters[max(quarters)] if quarters else None)
    days_total = (month_end(m) - m).days + 1
    partial = month_end(m) >= today >= m
    elapsed = (today - m).days + 1 if partial else days_total
    share = Decimal(elapsed) / Decimal(days_total)
    vals, src = {}, {}

    d = data.get(m)
    vals["gross_revenue"], src["gross_revenue"] = (d.order_value, "TD orders") if d else (None, "no data")
    if tracker_from and m >= month_start(tracker_from):
        vals["returns"], src["returns"] = refunds.get(m, D0), "finance tracker"
    elif q is not None and q.returns is not None and q.gross_revenue and vals["gross_revenue"] is not None:
        vals["returns"] = q.returns * vals["gross_revenue"] / q.gross_revenue
        src["returns"] = "quarter's returns, by revenue"
    else:
        vals["returns"] = D0 if vals["gross_revenue"] is not None else None
        src["returns"] = "none recorded"
    for f in PCT_DEFAULTS:
        vals[f] = getattr(q, f) if q is not None else PCT_DEFAULTS[f]
        src[f] = quarter_label(q.quarter_start) if q is not None else "sheet default"
    for f in MONTH_COSTS:
        qv = getattr(q, f) if q is not None else None
        vals[f] = (qv / 3 * share) if qv is not None else None
        if qv is None:
            src[f] = "not entered"
        else:
            src[f] = f"{quarter_label(q.quarter_start)} / 3" + (f" x {elapsed}/{days_total} days" if partial else "")
    if override is not None:
        for f in MONTH_FIELDS:
            v = getattr(override, f)
            if v is not None:
                vals[f], src[f] = v, "entered"
    return vals, src, partial


def monthly_statement(start, end, today=None):
    """The P&L for each month start..end (inclusive), with growth on the month before."""
    from warehouse.models import DistributorSettlement

    from masters.models import PnlMonth, PnlMonthData, PnlQuarter

    today = today or localdate()
    first = add_months(start, -1)
    quarters = {q.quarter_start: q for q in PnlQuarter.objects.all()}
    data = {r.month: r for r in PnlMonthData.objects.filter(month__gte=first, month__lte=end)}
    overrides = {r.month: r for r in PnlMonth.objects.filter(month__gte=first, month__lte=end)}
    tracker_from = DistributorSettlement.objects.order_by("order_date").values_list("order_date", flat=True).first()
    refunds = {}
    for day, v in DistributorSettlement.objects.filter(order_date__gte=first, order_date__lte=month_end(end)).values_list(
            "order_date", "customer_refund"):
        refunds[month_start(day)] = refunds.get(month_start(day), D0) + (v or D0)

    months, m = [], first
    while m <= end:
        months.append(m)
        m = add_months(m, 1)
    computed = {}
    for m in months:
        vals, src, partial = month_inputs(m, today, quarters, data, refunds, tracker_from, overrides.get(m))
        computed[m] = (compute(_Inputs(**vals)), vals, src, partial)
    out = []
    for m in months[1:]:
        values, vals, src, partial = computed[m]
        prev = computed.get(add_months(m, -1))
        o = overrides.get(m)
        missing = [f for f in ("gross_revenue", "tech_platform_cost", "manpower_operating_cost", "misc_expense")
                   if vals.get(f) is None]
        tracked = bool(tracker_from and m >= month_start(tracker_from))
        out.append({
            "start": m.isoformat(), "end": month_end(m).isoformat(), "label": month_label(m),
            "status": "in_progress" if partial else ("future" if m > today else "complete"),
            "previous": month_label(add_months(m, -1)),
            "inputs": {**{f: _f(vals[f]) for f in MONTH_FIELDS}, "notes": o.notes if o else ""},
            "entered": {f: (_f(getattr(o, f)) if o else None) for f in MONTH_FIELDS},
            "sources": src,
            "values": {k: _f(v) for k, v in values.items()},
            "growth": ({k: _f(v) for k, v in growth(values, prev[0]).items()} if prev
                       else {k: None for k, *_ in LINES}),
            "missing": missing,
            "data": {"gross_revenue": _f(data[m].order_value) if m in data else None,
                     "returns": _f(refunds.get(m, D0)) if tracked else None},
            "updated_by": o.updated_by if o else "",
            "updated_at": o.updated_at.isoformat() if o and o.updated_at else None,
        })
    first_data = PnlMonthData.objects.order_by("month").values_list("month", flat=True).first()
    return {"lines": [{"key": k, "label": label, "kind": kind, "formula": f} for k, label, kind, f in LINES],
            "months": out,
            "range": {"from": start.isoformat()[:7], "to": end.isoformat()[:7],
                      "earliest": first_data.isoformat()[:7] if first_data else None,
                      "latest": month_start(today).isoformat()[:7], "max_months": MAX_MONTHS}}


def monthly_export_rows(data):
    rows = []
    for line in data["lines"]:
        r = {"P&L Particular": line["label"]}
        for q in data["months"]:
            v = q["values"].get(line["key"])
            r[q["label"]] = round(v, 4 if line["kind"] == "margin" else 2) if v is not None else None
            gr = q["growth"].get(line["key"])
            r[f"{q['label']} MoM" + (" (pp)" if line["kind"] == "margin" else "")] = (
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
    def blank():
        return {"orders": 0, "order_value": D0, "line_value": D0, "cancelled_value": D0, "points_redeemed": D0}

    agg, magg = defaultdict(blank), defaultdict(blank)
    for o in order_rows:
        if (o.get("distributor_id") or "").strip() in internal:
            continue
        day = to_date(o.get("order_date"))
        if not day:
            continue
        paid = bool((o.get("mode") or "").strip()) or to_dec(o.get("payu_amount")) > 0
        if not paid:
            continue
        total = to_dec(o.get("total_amount"))
        for a in (agg[quarter_of(day)], magg[day.replace(day=1)]):  # the quarter and the month
            a["orders"] += 1
            a["order_value"] += total
            a["line_value"] += to_dec(o.get("line_total"))
            a["points_redeemed"] += to_dec(o.get("points_redeemed"))
            if (o.get("ts_order_status") or "").strip().lower() in ("cancelled", "canceled"):
                a["cancelled_value"] += total
    for start, a in agg.items():
        PnlDataCheck.objects.update_or_create(quarter_start=start, defaults=a)
    PnlDataCheck.objects.exclude(quarter_start__in=list(agg)).delete()
    from masters.models import PnlMonthData

    for start, a in magg.items():
        PnlMonthData.objects.update_or_create(month=start, defaults=a)
    PnlMonthData.objects.exclude(month__in=list(magg)).delete()
    return len(agg)
