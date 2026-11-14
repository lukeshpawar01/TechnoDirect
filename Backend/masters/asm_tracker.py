"""ASM performance tracker: read (screen / Excel export) and write (on-screen edit / Excel upload).

The team keeps the tracker in Excel. Every write path goes through the same importer as
`manage.py import_asm_tracker`, so editing on screen, uploading the Excel and the command line behave the same:
ASMs are created by name, each distributor gets its ASM and region, and the month's SALES targets are set per
distributor, per ASM and per region (sums) and overall. A save/upload is the full picture for that month:
a distributor whose target is blank loses its own target (it is covered by its ASM's target).
"""
import datetime as dt
import io
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum

from accounts.scope import DISTRIBUTOR_DIMS, get_scope
from analytics.cache import bump_cache_version
from analytics.derivations import attribute_orders_to_distributor_asm
from analytics.filters import month_end, month_start, today_ist
from analytics.metrics import pct, target_values
from warehouse.models import Asm, Distributor, Order, Region, Target

COLUMNS = ["Distributor", "Region", "ASM", "Order Value", "No of Orders", "Share %", "Total Target",
           "Target Remained", "Acheived %", "ASM Target", "ASM Order Value", "ASM Acheived %"]


def parse_month(value):
    if not value:
        return month_start(today_ist())
    try:
        return dt.date.fromisoformat(str(value)[:7] + "-01")
    except ValueError:
        raise ValueError("month must be YYYY-MM") from None


def tracker(month, user):
    """Rows per distributor (within the user's data scope) + per-ASM summary for `month`."""
    dists = Distributor.objects.select_related("asm", "region")
    sq = get_scope(user).q(DISTRIBUTOR_DIMS)
    if sq is not None:
        dists = dists.filter(sq)
    dists = list(dists.order_by("name"))
    ids = [d.id for d in dists]
    end = min(month_end(month), today_ist()) if month <= today_ist() else month_end(month)
    agg = {r["distributor_id"]: r for r in Order.objects.filter(
        is_qualifying=True, distributor_id__in=ids, placed_date__gte=month, placed_date__lte=end,
    ).values("distributor_id").annotate(v=Sum("gross_value"), n=Count("split_group", distinct=True))}
    total_sales = float(sum(float(r["v"] or 0) for r in agg.values()))
    dist_t = target_values("distributor", ids, [month])
    asm_ids = sorted({d.asm_id for d in dists if d.asm_id})
    asm_t = target_values("asm", asm_ids, [month])

    asm_sales = defaultdict(float)
    for d in dists:
        if d.asm_id:
            asm_sales[d.asm_id] += float((agg.get(d.id) or {}).get("v") or 0)

    rows = []
    for d in dists:
        a = agg.get(d.id) or {}
        sales = float(a.get("v") or 0)
        target = dist_t.get((d.id, month))
        at = asm_t.get((d.asm_id, month)) if d.asm_id else None
        rows.append({
            "distributor_id": d.id, "distributor": d.name, "region": d.region.name if d.region_id else "",
            "asm_id": d.asm_id, "asm": d.asm.name if d.asm_id else "",
            "sales": round(sales, 2), "orders": a.get("n") or 0, "share": pct(sales, total_sales),
            "target": float(target) if target is not None else None,
            "remaining": max(float(target) - sales, 0) if target is not None else None,
            "achieved_pct": pct(sales, float(target)) if target else None,
            "asm_target": float(at) if at is not None else None,
            "asm_sales": round(asm_sales.get(d.asm_id, 0.0), 2) if d.asm_id else None,
            "asm_achieved_pct": pct(asm_sales.get(d.asm_id, 0.0), float(at)) if at else None,
        })

    summary = []
    for aid in asm_ids:
        mine = [r for r in rows if r["asm_id"] == aid]
        t = asm_t.get((aid, month))
        s = asm_sales.get(aid, 0.0)
        summary.append({
            "asm_id": aid, "asm": mine[0]["asm"], "region": mine[0]["region"], "distributors": len(mine),
            "sales": round(s, 2), "orders": sum(r["orders"] for r in mine),
            "target": float(t) if t is not None else None,
            "remaining": max(float(t) - s, 0) if t is not None else None,
            "achieved_pct": pct(s, float(t)) if t else None,
        })
    summary.sort(key=lambda r: -(r["target"] or 0))
    overall = target_values("overall", None, [month]).get((None, month))
    return {
        "month": month.isoformat()[:7], "as_of": end.isoformat(),
        "rows": rows, "asm_summary": summary,
        "totals": {"sales": round(total_sales, 2), "orders": sum(r["orders"] for r in rows),
                   "target": float(overall) if overall is not None else None,
                   "achieved_pct": pct(total_sales, float(overall)) if overall else None},
        "regions": list(Region.objects.order_by("name").values_list("name", flat=True)),
        "asms": list(Asm.objects.filter(is_active=True).order_by("name").values_list("name", flat=True)),
    }


def to_xlsx(data):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    navy = PatternFill("solid", fgColor="1E2A5E")
    head = Font(bold=True, color="FFFFFF")
    wb = Workbook()
    ws = wb.active
    ws.title = f"Tracker {data['month']}"
    ws.append(COLUMNS)
    for r in data["rows"]:
        ws.append([r["distributor"], r["region"], r["asm"] or "", r["sales"], r["orders"],
                   (r["share"] or 0) / 100, r["target"], r["remaining"],
                   (r["achieved_pct"] / 100) if r["achieved_pct"] is not None else None,
                   r["asm_target"], r["asm_sales"],
                   (r["asm_achieved_pct"] / 100) if r["asm_achieved_pct"] is not None else None])
    t = data["totals"]
    ws.append(["Total", "", "", t["sales"], t["orders"], 1, t["target"],
               max((t["target"] or 0) - t["sales"], 0) if t["target"] else None,
               (t["achieved_pct"] / 100) if t["achieved_pct"] is not None else None, None, None, None])
    for c in ws[1]:
        c.font, c.fill, c.alignment = head, navy, Alignment(horizontal="center", vertical="center", wrap_text=True)
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    money_cols, pct_cols = ("D", "G", "H", "J", "K"), ("F", "I", "L")
    for row in ws.iter_rows(min_row=2):
        for c in row:
            if c.column_letter in money_cols:
                c.number_format = '"₹"#,##,##0'
            elif c.column_letter in pct_cols:
                c.number_format = "0.0%"
    widths = {"A": 32, "B": 10, "C": 16, "D": 15, "E": 10, "F": 9, "G": 15, "H": 15, "I": 11, "J": 15, "K": 16, "L": 13}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"

    s2 = wb.create_sheet("ASM summary")
    s2.append(["ASM", "Region", "Distributors", "Order Value", "Orders", "Target", "Target Remained", "Acheived %"])
    for r in data["asm_summary"]:
        s2.append([r["asm"], r["region"], r["distributors"], r["sales"], r["orders"], r["target"], r["remaining"],
                   (r["achieved_pct"] / 100) if r["achieved_pct"] is not None else None])
    for c in s2[1]:
        c.font, c.fill = head, navy
    for row in s2.iter_rows(min_row=2):
        for c in row:
            if c.column_letter in ("D", "F", "G"):
                c.number_format = '"₹"#,##,##0'
            elif c.column_letter == "H":
                c.number_format = "0.0%"
    for col, w in {"A": 20, "B": 10, "C": 12, "D": 15, "E": 9, "F": 15, "G": 16, "H": 11}.items():
        s2.column_dimensions[col].width = w

    s3 = wb.create_sheet("How to update")
    for line in [
        f"ASM tracker for {data['month']} (actuals as of {data['as_of']}).",
        "To update: change Region, ASM or Total Target on the first sheet, save, and use 'Upload tracker' on the",
        "Territory page (pick the same month). Order Value / Orders / Acheived % are calculated by the dashboard",
        "and are ignored on upload. A new ASM name creates the ASM. 'Vacant' or blank ASM = no ASM.",
        "Blank Total Target = the distributor has no own target (it is covered by its ASM's target).",
        "The ASM / region / overall targets are the sums of the distributor targets.",
    ]:
        s3.append([line])
    s3.column_dimensions["A"].width = 110
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def rows_from_file(f):
    """Read Distributor / Region / ASM / Total Target from an uploaded .xlsx or .csv (tracker layout)."""
    name = (getattr(f, "name", "") or "").lower()
    if name.endswith(".csv"):
        import csv

        text = f.read().decode("utf-8-sig", errors="replace")
        raw = list(csv.reader(io.StringIO(text)))
    else:
        from openpyxl import load_workbook

        try:
            wb = load_workbook(f, read_only=True, data_only=True)
        except Exception:  # noqa: BLE001
            raise ValueError("Not a valid .xlsx or .csv file.") from None
        raw = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    if not raw:
        raise ValueError("The file is empty.")
    header = [_cell(h).lower() for h in raw[0]]

    def col(*names):
        for n in names:
            if n in header:
                return header.index(n)
        return None

    ci = {"Distributor": col("distributor"), "Region": col("region"), "ASM": col("asm"),
          "Total Target": col("total target", "target")}
    missing = [k for k in ("Distributor", "ASM", "Total Target") if ci[k] is None]
    if missing:
        raise ValueError(f"Missing column(s): {', '.join(missing)}. Use the exported tracker as the template.")
    rows, total = [], None
    for values in raw[1:]:
        r = {k: (_cell(values[i]) if i is not None and i < len(values) else "") for k, i in ci.items()}
        if not r["Distributor"]:
            continue
        if r["Distributor"].lower() == "total":
            total = r
            continue
        rows.append(r)
    if not rows:
        raise ValueError("No distributor rows found.")
    return rows, total


def sync_state_targets(month):
    """State SALES target for `month` = sum of the (latest) distributor targets of distributors based in it.
    Keeps Territory → by State and the State filter in line with the ASM tracker."""
    from masters.management.commands.import_asm_tracker import Command

    dist = target_values("distributor", None, [month])
    home = dict(Distributor.objects.filter(id__in=[d for d, _ in dist], state__isnull=False)
                .values_list("id", "state_id"))
    by_state = defaultdict(Decimal)
    for (did, _), v in dist.items():
        if did in home and v:
            by_state[home[did]] += Decimal(v)
    for sid, v in by_state.items():
        Command.put_target(month, "state", sid, v, "sum of distributor targets (ASM tracker)")
    Target.objects.filter(month=month, metric="sales", scope_type="state").exclude(scope_id__in=list(by_state)).delete()
    return len(by_state)


def apply_rows(rows, month, label, total_row=None):
    """Write tracker rows (dicts with Distributor / Region / ASM / Total Target) for `month`."""
    from masters.management.commands.import_asm_tracker import Command, money

    cmd = Command()
    matched = cmd.match_distributors([r["Distributor"] for r in rows], create=True)
    with transaction.atomic():
        result = cmd.apply(rows, matched, month, total_row or {"Total Target": ""}, label)
        # snapshot semantics: targets that are no longer in the sheet are removed for this month
        dist_with = {matched[r["Distributor"]][0].id for r in rows if money(r.get("Total Target"))}
        dist_all = {matched[r["Distributor"]][0].id for r in rows}
        asm_with = set(Distributor.objects.filter(id__in=dist_with, asm__isnull=False).values_list("asm_id", flat=True))
        region_with = set(Distributor.objects.filter(id__in=dist_with, region__isnull=False)
                          .values_list("region_id", flat=True))
        base = Target.objects.filter(month=month, metric="sales")
        removed = base.filter(scope_type="distributor", scope_id__in=dist_all - dist_with).delete()[0]
        removed += base.filter(scope_type="asm").exclude(scope_id__in=asm_with).delete()[0]
        removed += base.filter(scope_type="region").exclude(scope_id__in=region_with).delete()[0]
        result["targets_removed"] = removed
        result["state_targets"] = sync_state_targets(month)
    # Only what an ASM / target change affects: credit orders to the distributor's ASM and clear the cache.
    # Retailer totals and data-quality checks don't depend on ASMs or targets; the scheduled refresh rebuilds them.
    attribute_orders_to_distributor_asm()
    bump_cache_version()
    return {k: (v if not isinstance(v, Decimal) else float(v)) for k, v in result.items()}
