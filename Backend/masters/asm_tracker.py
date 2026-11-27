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
from warehouse.models import Asm, Distributor, Order, Region, Rsm, State, Target
from analytics.metrics import order_count

COLUMNS = ["Distributor", "Region", "ASM", "Total Target", "Order Value", "No of Orders", "Share %",
           "Target Remained", "Acheived %"]


def parse_month(value):
    if not value:
        return month_start(today_ist())
    try:
        return dt.date.fromisoformat(str(value)[:7] + "-01")
    except ValueError:
        raise ValueError("month must be YYYY-MM") from None


FIRST_MONTH = dt.date(2025, 10, 1)  # ASM targets & performance: Oct 2025 (added on request) and from Jan 2026


def asm_in_charge(dists, day):
    """{distributor_id: Asm | None} on `day` from the handover history (current ASM when there is none)."""
    from django.db.models import Q

    from warehouse.models import AsmAssignment

    out = {d.id: d.asm for d in dists}
    for a in AsmAssignment.objects.filter(distributor_id__in=list(out), start__lte=day).filter(
            Q(end__isnull=True) | Q(end__gte=day)).select_related("asm"):
        out[a.distributor_id] = a.asm
    return out


def tracker(month, user):
    """The monthly ASM tracker in the layout of the team's sheet (Nov 26): one row per distributor (within the
    user's data scope) with the ASM in charge that month, + a per-ASM summary."""
    dists = Distributor.objects.select_related("asm", "region").filter(bo_only=False, is_internal=False, removed=False)  # app distributors only
    sq = get_scope(user).q(DISTRIBUTOR_DIMS)
    if sq is not None:
        dists = dists.filter(sq)
    dists = list(dists.order_by("name"))
    ids = [d.id for d in dists]
    end = min(month_end(month), today_ist()) if month <= today_ist() else month_end(month)
    in_charge = asm_in_charge(dists, end)
    month_orders = Order.objects.filter(is_qualifying=True, placed_date__gte=month, placed_date__lte=end)
    agg = {r["distributor_id"]: r for r in month_orders.filter(distributor_id__in=ids).values(
        "distributor_id").annotate(v=Sum("gross_value"), n=order_count())}
    total_sales = float(sum(float(r["v"] or 0) for r in agg.values()))
    dist_t = target_values("distributor", ids, [month])
    asm_t = {aid: v for (aid, _), v in target_values("asm", None, [month]).items()}

    rows = []
    for d in dists:
        a, asm = agg.get(d.id) or {}, in_charge.get(d.id)
        sales = float(a.get("v") or 0)
        target = dist_t.get((d.id, month))
        rows.append({
            "distributor_id": d.id, "distributor": d.name, "region": d.region.name if d.region_id else "",
            "asm_id": asm.id if asm else None, "asm": asm.name if asm else "",
            "sales": round(sales, 2), "orders": a.get("n") or 0, "share": pct(sales, total_sales),
            "target": float(target) if target is not None else None,
            "remaining": max(float(target) - sales, 0) if target is not None else None,
            "achieved_pct": pct(sales, float(target)) if target else None,
        })
    rows.sort(key=lambda r: (-(r["target"] or 0), -r["sales"], r["distributor"]))
    # person-by-person split of each distributor's target (months written by the live incentive sheet)
    from warehouse.models import TargetSplit

    splits = defaultdict(list)
    for s in TargetSplit.objects.filter(month=month, distributor_id__in=ids):
        splits[s.distributor_id].append({"person": s.person, "role": s.role, "value": float(s.value)})
    for r in rows:
        r["split"] = splits.get(r["distributor_id"], [])
    from .target_sheet import sheet_managed

    # ASM summary: sales credited to the ASM in the month (handover-aware); target = the ASM's target
    asm_sales = {r["asm_id"]: r for r in month_orders.filter(asm__isnull=False).values("asm_id").annotate(
        v=Sum("gross_value"), n=order_count())}
    asm_ids = sorted({r["asm_id"] for r in rows if r["asm_id"]} | set(asm_t))
    asms = {a.id: a for a in Asm.objects.filter(id__in=asm_ids).select_related("region")}
    summary = []
    for aid in asm_ids:
        a = asms.get(aid)
        if a is None:
            continue
        mine = [r for r in rows if r["asm_id"] == aid]
        t = asm_t.get(aid)
        s = float((asm_sales.get(aid) or {}).get("v") or 0)
        summary.append({
            "asm_id": aid, "asm": a.name, "region": a.region.name if a.region_id else "",
            "distributors": len(mine), "sales": round(s, 2), "orders": (asm_sales.get(aid) or {}).get("n") or 0,
            "target": float(t) if t is not None else None,
            "remaining": max(float(t) - s, 0) if t is not None else None,
            "achieved_pct": pct(s, float(t)) if t else None,
            # 'distributors' = sum of its distributors' targets (edit those); 'asm' = set for the ASM as a whole
            "target_from": "distributors" if any(r["target"] for r in mine) else "asm",
        })
    summary.sort(key=lambda r: (-(r["target"] or 0), -r["sales"]))
    overall = target_values("overall", None, [month]).get((None, month))

    # TD Target Forecaster: suggestion for this month (made on the 27th of the month before) + its accuracy
    from .target_forecast import latest_for, wape

    fc = latest_for(month)
    forecast = None
    if fc:
        for r in rows:
            r["suggested"] = fc["distributor"].get(r["distributor_id"])
        for a in summary:
            a["suggested"] = fc["asm"].get(a["asm_id"])
        set_t = {a["asm_id"]: a["target"] for a in summary if a["target"]}
        acc = wape({k: fc["asm"].get(k, 0.0) for k in set_t}, set_t) if set_t else None
        forecast = {"as_of": fc["as_of"], "model": fc["model"], "params": fc["params"], "overall": fc["overall"],
                    "asm": {asms[k].name: v for k, v in fc["asm"].items() if k in asms} |
                           {a.name: fc["asm"][a.id] for a in Asm.objects.filter(id__in=list(fc["asm"])).exclude(id__in=list(asms))},
                    "wape_vs_set": round(acc * 100, 1) if acc is not None else None}
    return {
        "month": month.isoformat()[:7], "as_of": end.isoformat(), "first_month": FIRST_MONTH.isoformat()[:7],
        "rows": rows, "asm_summary": summary, "forecast": forecast,
        # targets of this month come from the live incentive sheet: edit them there, not in the tracker
        "managed_by_sheet": sheet_managed(month),
        "totals": {"sales": round(total_sales, 2), "orders": sum(r["orders"] for r in rows),
                   "target": float(overall) if overall is not None else None,
                   "remaining": max(float(overall) - total_sales, 0) if overall is not None else None,
                   "achieved_pct": pct(total_sales, float(overall)) if overall else None},
        "regions": list(Region.objects.order_by("name").values_list("name", flat=True)),
        "asms": list(Asm.objects.filter(is_active=True).order_by("name").values_list("name", flat=True)),
        # for the Add ASM / Add distributor forms
        "states": [{"id": i, "name": n, "region": r} for i, n, r in
                   State.objects.order_by("name").values_list("id", "name", "region__name")],
        "rsms": [{"id": i, "name": n, "region": r} for i, n, r in
                 Rsm.objects.filter(is_active=True).order_by("name").values_list("id", "name", "region__name")],
    }


def create_asm(data):
    """New ASM from the tracker editor: {name, full_name, region, rsm_id, joined_on}. Raises ValueError."""
    import re

    name = " ".join(str(data.get("name") or "").split())[:120]
    if not name:
        raise ValueError("Enter the ASM's name as used on the target sheets (e.g. Gururaj).")
    if Asm.objects.filter(name__iexact=name).exists():
        raise ValueError(f"An ASM called {name} already exists.")
    region = Region.objects.filter(name__iexact=str(data.get("region") or "")).first()
    if region is None:
        raise ValueError("Choose the ASM's region.")
    rsm = Rsm.objects.filter(id=data.get("rsm_id")).first() if data.get("rsm_id") else         Rsm.objects.filter(region=region, is_active=True).order_by("id").first()
    joined = None
    if data.get("joined_on"):
        try:
            joined = dt.date.fromisoformat(str(data["joined_on"])[:10])
        except ValueError:
            raise ValueError("Joining date must be a date.") from None
    base = "ASM-" + (re.sub(r"[^A-Z0-9]+", "", name.upper())[:20] or "NEW")
    code, i = base, 1
    while Asm.objects.filter(code=code).exists():
        i += 1
        code = f"{base}{i}"
    return Asm.objects.create(code=code, name=name, full_name=" ".join(str(data.get("full_name") or "").split())[:120],
                              region=region, rsm=rsm, joined_on=joined, is_active=True)


def create_distributor(data):
    """New distributor from the tracker editor: {name, state_id, city, asm}. Raises ValueError.

    Matched later by name when the distributor appears in the data export (it then gets its export id)."""
    import re

    from ingestion.normalize import nice_name, norm

    raw = " ".join(str(data.get("name") or "").split())
    if not raw:
        raise ValueError("Enter the distributor's name.")
    n = norm(raw)
    for d in Distributor.objects.all():
        if n in {norm(x) for x in [d.name, d.code, *(d.aliases or [])]}:
            raise ValueError(f"{raw} already exists as {d.name}.")
    state = State.objects.select_related("region").filter(id=data.get("state_id")).first()
    if state is None:
        raise ValueError("Choose the distributor's state.")
    asm = None
    if str(data.get("asm") or "").strip():
        asm = Asm.objects.filter(name__iexact=str(data["asm"]).strip()).first()
        if asm is None:
            raise ValueError(f"No ASM called {data['asm']}. Add the ASM first.")
    base = re.sub(r"[^A-Z0-9]", "", raw.upper())[:10] or "DIST"
    code, i = base, 1
    while Distributor.objects.filter(code=code).exists():
        i += 1
        code = f"{base[:8]}{i:02d}"
    return Distributor.objects.create(code=code, name=nice_name(raw)[:200], source_id=f"name:{n}"[:64],
                                      state=state, region=state.region, asm=asm,
                                      city=" ".join(str(data.get("city") or "").split()).title()[:100],
                                      onboarded_on=today_ist(), is_active=True)


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
        ws.append([r["distributor"], r["region"], r["asm"] or "", r["target"], r["sales"], r["orders"],
                   (r["share"] or 0) / 100, r["remaining"],
                   (r["achieved_pct"] / 100) if r["achieved_pct"] is not None else None])
    t = data["totals"]
    ws.append(["Total", "", "", t["target"], t["sales"], t["orders"], 1, t["remaining"],
               (t["achieved_pct"] / 100) if t["achieved_pct"] is not None else None])
    for c in ws[1]:
        c.font, c.fill, c.alignment = head, navy, Alignment(horizontal="center", vertical="center", wrap_text=True)
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    money_cols, pct_cols = ("D", "E", "H"), ("G", "I")
    for row in ws.iter_rows(min_row=2):
        for c in row:
            if c.column_letter in money_cols:
                c.number_format = '"₹"#,##,##0'
            elif c.column_letter in pct_cols:
                c.number_format = "0.0%"
    widths = {"A": 32, "B": 10, "C": 16, "D": 15, "E": 15, "F": 11, "G": 9, "H": 15, "I": 11}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"

    s2 = wb.create_sheet("ASM summary")
    s2.append(["ASM", "Region", "Distributors", "Order Value", "Orders", "Target", "Target Remained", "Acheived %",
               "Target set by"])
    for r in data["asm_summary"]:
        s2.append([r["asm"], r["region"], r["distributors"], r["sales"], r["orders"], r["target"], r["remaining"],
                   (r["achieved_pct"] / 100) if r["achieved_pct"] is not None else None,
                   "distributor targets" if r["target_from"] == "distributors" else "ASM target"])
    for c in s2[1]:
        c.font, c.fill = head, navy
    for row in s2.iter_rows(min_row=2):
        for c in row:
            if c.column_letter in ("D", "F", "G"):
                c.number_format = '"₹"#,##,##0'
            elif c.column_letter == "H":
                c.number_format = "0.0%"
    for col, w in {"A": 20, "B": 10, "C": 12, "D": 15, "E": 9, "F": 15, "G": 16, "H": 11, "I": 18}.items():
        s2.column_dimensions[col].width = w

    s3 = wb.create_sheet("How to update")
    for line in [
        f"ASM tracker for {data['month']} (actuals as of {data['as_of']}).",
        "To update: change Region, ASM or Total Target on the first sheet, save, and use 'Upload tracker' on the",
        "Region & ASM Performance page (pick the same month). Order Value / Orders / Acheived % are calculated by the dashboard",
        "and are ignored on upload. A new ASM name creates the ASM. 'Vacant' or blank ASM = no ASM.",
        "Blank Total Target = the distributor has no own target (it is covered by its ASM's target).",
        "An ASM's target is the sum of its distributors' targets; an ASM with no distributor targets keeps the ASM",
        "target set on the dashboard (Edit ASM & targets) or in the monthly ASM targets workbook.",
        "Region and company targets are the sums of the ASM targets and the targets of distributors with no ASM.",
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


def recompute_rollups(month, label):
    """Company and region targets for `month` = ASM targets + targets of distributors with no ASM target."""
    from masters.management.commands.import_asm_tracker import Command

    asm_t = {aid: v for (aid, _), v in target_values("asm", None, [month]).items() if v}
    dist_t = {did: v for (did, _), v in target_values("distributor", None, [month]).items() if v}
    dists = {d.id: d for d in Distributor.objects.filter(id__in=list(dist_t))}
    in_charge = asm_in_charge(list(dists.values()), month_end(month))
    covered = {did for did in dist_t if in_charge.get(did) and in_charge[did].id in asm_t}
    asm_with_dists = {in_charge[did].id for did in covered}
    overall = sum(asm_t.values(), Decimal(0)) + sum((v for did, v in dist_t.items() if did not in covered), Decimal(0))
    region = defaultdict(Decimal)
    for did, v in dist_t.items():
        if dists[did].region_id:
            region[dists[did].region_id] += v
    for a in Asm.objects.filter(id__in=[a for a in asm_t if a not in asm_with_dists]):
        if a.region_id:
            region[a.region_id] += asm_t[a.id]
    notes = f"ASM tracker: {label}"[:255]
    Target.objects.filter(month=month, metric="sales", scope_type="region").exclude(scope_id__in=list(region)).delete()
    for rid, v in region.items():
        Command.put_target(month, "region", rid, v, notes)
    if overall:
        Command.put_target(month, "overall", None, overall, notes)
    return float(overall)


def apply_rows(rows, month, label, total_row=None, asm_targets=None):
    """Write tracker rows (dicts with Distributor / Region / ASM / Total Target) for `month`.

    asm_targets: [{asm, target}] for ASMs whose target is set for the ASM as a whole (no distributor targets);
    target None removes it. An ASM with distributor targets always gets their sum."""
    from masters.management.commands.import_asm_tracker import Command, money

    cmd = Command()
    matched = cmd.match_distributors([r["Distributor"] for r in rows], create=True)
    # A row whose ASM / region the user did not touch keeps today's mapping (the page may have been loaded before
    # a handover was recorded); its target counts for the ASM in charge in that month.
    in_charge = asm_in_charge([matched[r["Distributor"]][0] for r in rows if matched[r["Distributor"]][0]],
                              month_end(month))
    for r in rows:
        d = matched[r["Distributor"]][0]
        if "ASM Original" in r and r["ASM"].strip().lower() == r["ASM Original"].strip().lower():
            r["_asm_unchanged"] = True
            a = in_charge.get(d.id) if d else None
            r["ASM"] = a.name if a else ""
        if "Region Original" in r and r["Region"].strip().lower() == r["Region Original"].strip().lower():
            r["_region_unchanged"] = True
            r["Region"] = d.region.name if d and d.region_id else ""
    with transaction.atomic():
        result = cmd.apply(rows, matched, month, total_row or {"Total Target": ""}, label)
        # snapshot semantics: targets that are no longer in the sheet are removed for this month
        dist_with = {matched[r["Distributor"]][0].id for r in rows if money(r.get("Total Target"))}
        dist_all = {matched[r["Distributor"]][0].id for r in rows}
        asm_with = set(Distributor.objects.filter(id__in=dist_with, asm__isnull=False).values_list("asm_id", flat=True))
        base = Target.objects.filter(month=month, metric="sales")
        removed = base.filter(scope_type="distributor", scope_id__in=dist_all - dist_with).delete()[0]
        # ASM-level targets (ASMs with no distributor targets, e.g. from the monthly ASM workbook) are kept;
        # only an ASM whose distributor targets were all cleared loses its summed target
        had_dist_sum = set(base.filter(scope_type="asm", notes__startswith="ASM tracker").values_list("scope_id", flat=True))
        removed += base.filter(scope_type="asm", scope_id__in=had_dist_sum - asm_with).delete()[0]
        asm_by_name = {a.name.lower(): a for a in Asm.objects.all()}
        for item in asm_targets or []:
            a = asm_by_name.get(str(item.get("asm") or "").strip().lower())
            if a is None or a.id in asm_with:
                continue  # unknown, or set by its distributors' targets
            v = item.get("target")
            if v in (None, ""):
                removed += base.filter(scope_type="asm", scope_id=a.id).delete()[0]
            else:
                cmd.put_target(month, "asm", a.id, Decimal(str(v)), f"ASM-level target: {label}"[:255])
        result["overall_target"] = f"{recompute_rollups(month, label):,.0f}"
        result["targets_removed"] = removed
        result["state_targets"] = sync_state_targets(month)
    # Only what an ASM / target change affects: credit orders to the distributor's ASM and clear the cache.
    # Retailer totals and data-quality checks don't depend on ASMs or targets; the scheduled refresh rebuilds them.
    attribute_orders_to_distributor_asm()
    bump_cache_version()
    return {k: (v if not isinstance(v, Decimal) else float(v)) for k, v in result.items()}
