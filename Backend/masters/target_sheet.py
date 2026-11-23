"""Monthly sales targets, person by person, read LIVE from the team's Google Sheet
"TD_ASM_Executive_Incentive_Tracker" (tab "Monthly Tracker"; TARGETS_SHEET_URL / TARGETS_SHEET_TAB).

Sheet layout (header row has "Employee Name" and "TD Target (₹)"): one row per person per distributor;
Month / Region / State / Distributor are written once per block and left blank below (filled down here).
Only the months that appear in the sheet are changed (a month label without a year, e.g. "Oct", is the
latest such month up to today). For each month in the sheet:

  * distributor target = sum of its rows (ASM + executives), e.g. Heera = Gururaj 80 L + Srinivas 30 L
  * ASM target: a distributor with one ASM (or none) -> its whole target to the ASM in charge that month in
    the dashboard (the person its sales are credited to); a distributor with several ASM rows (Virat, Oct 26:
    Imran 30 L + Anil 10 L) -> each ASM their own line, the executives' amounts shared in the same ratio
  * state / region / company totals = sums of the distributor targets
  * the person-by-person split is kept in TargetSplit (shown on the ASM tracker)
The sheet is the full picture for its months: targets of that month no longer in it are removed.
Anything that cannot be matched (a distributor name) fails the run and leaves the targets as they were.
Re-imported only when the sheet changed (content hash); each run is a SyncRun "targets_sheet".
"""
import datetime as dt
import logging
import re
from collections import defaultdict
from decimal import Decimal

from django.db import transaction

from . import name_match

log = logging.getLogger(__name__)
SOURCE = "targets_sheet"
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"], start=1)}


class TargetSheetError(ValueError):
    pass


def resolve_month(label, today):
    """'Oct' / 'Oct 26' / 'October 2026' / '2026-10' -> date(2026, 10, 1); no year = latest such month <= today."""
    s = (label or "").strip().lower()
    m = re.match(r"^(\d{4})-(\d{1,2})$", s)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), 1)
    m = re.match(r"^([a-z]{3})[a-z]*[\s\-']*(\d{2}|\d{4})?$", s)
    if not m or m.group(1) not in MONTHS:
        return None
    mon = MONTHS[m.group(1)]
    if m.group(2):
        y = int(m.group(2))
        return dt.date(y + 2000 if y < 100 else y, mon, 1)
    y = today.year if mon <= today.month else today.year - 1
    return dt.date(y, mon, 1)


def money(raw):
    s = re.sub(r"[^\d.]", "", str(raw or ""))
    return Decimal(s) if s and s != "." else Decimal(0)


def parse(values, today):
    """Sheet cells -> [{month, region, state, distributor, role, person, target}] (target > 0 only)."""
    hi = next((i for i, r in enumerate(values[:15])
               if any("employee" in (c or "").lower() for c in r) and any("td target" in (c or "").lower() for c in r)), None)
    if hi is None:
        raise TargetSheetError("Header row not found (needs 'Employee Name' and 'TD Target' columns)")
    head = [(c or "").strip().lower() for c in values[hi]]

    def col(*names):
        for n in names:
            for i, h in enumerate(head):
                if h.startswith(n):
                    return i
        return None

    ci = {"month": col("month"), "region": col("region"), "state": col("state"), "distributor": col("distributor"),
          "role": col("role"), "person": col("employee"), "target": col("td target"),
          # incentive KPIs (optional columns)
          "nr": col("new retailer target"), "gps": col("bo g/p/s target", "bo gps target"),
          "kyc": col("kyc conversion target"), "base": col("base incentive")}
    missing = [k for k in ("month", "distributor", "role", "person", "target") if ci[k] is None]
    if missing:
        raise TargetSheetError(f"Missing column(s): {', '.join(missing)}")
    rows, last = [], {}
    for r in values[hi + 1:]:
        cell = {k: (r[i].strip() if i is not None and i < len(r) else "") for k, i in ci.items()}
        for k in ("month", "region", "state", "distributor"):  # written once per block
            if cell[k]:
                last[k] = cell[k]
            else:
                cell[k] = last.get(k, "")
        t = money(cell["target"])
        if not cell["person"] or t <= 0:
            continue
        m = resolve_month(cell["month"], today)
        if m is None:
            raise TargetSheetError(f"Month '{cell['month']}' not understood (row for {cell['person']})")
        rows.append({"month": m, "region": cell["region"], "state": cell["state"], "distributor": cell["distributor"],
                     "role": "executive" if cell["role"].lower().startswith("exec") else "asm",
                     "person": cell["person"], "target": t, "nr": count(cell["nr"]), "gps": count(cell["gps"]),
                     "kyc": count(cell["kyc"]), "base": money(cell["base"]) or None})
    return rows


def count(raw):
    """A KPI target cell -> int, or None when blank (no target for that KPI)."""
    s = re.sub(r"[^\d]", "", str(raw or ""))
    return int(s) if s else None


def plan(rows):
    """Match names and work out every target to write. Returns {month: {...}}; raises on unmatched distributors."""
    from warehouse.models import Asm, Distributor, FieldStaff

    from .asm_tracker import asm_in_charge
    from analytics.filters import month_end

    dists = list(Distributor.objects.select_related("region", "state"))
    asms = list(Asm.objects.all())
    staff = list(FieldStaff.objects.all())
    unmatched = sorted({r["distributor"] for r in rows
                        if not r.get("dist") and not name_match.distributor(r["distributor"], dists)})
    if unmatched:
        raise TargetSheetError("Distributor(s) not found in the dashboard: " + ", ".join(unmatched)
                               + " - add them (or an alias) first")
    out = {}
    for month in sorted({r["month"] for r in rows}):
        mrows = [r for r in rows if r["month"] == month]
        by_dist = defaultdict(list)
        for r in mrows:
            r["dist"] = r.get("dist") or name_match.distributor(r["distributor"], dists)  # editor: already chosen
            vacant = r["person"].strip().lower() in ("vacant", "-", "na", "n/a")
            r["asm"] = None if vacant or r["role"] != "asm" else name_match.person(r["person"], asms)
            r["staff"] = None if vacant or r["role"] != "executive" else name_match.person(r["person"], staff)
            by_dist[r["dist"].id].append(r)
        in_charge = asm_in_charge([rs[0]["dist"] for rs in by_dist.values()], month_end(month))
        dist_total, asm_total, notes = {}, defaultdict(Decimal), []
        for did, rs in by_dist.items():
            total = sum((r["target"] for r in rs), Decimal(0))
            dist_total[did] = total
            asm_rows = [r for r in rs if r["role"] == "asm" and r["asm"] is not None]
            if len({r["asm"].id for r in asm_rows}) >= 2:
                # several ASMs on one distributor: each their own line + a share of the executives' amounts
                own = sum((r["target"] for r in asm_rows), Decimal(0))
                for r in asm_rows:
                    asm_total[r["asm"].id] += (total * r["target"] / own).quantize(Decimal("0.01"))
            else:
                a = in_charge.get(did)
                if a is not None:
                    asm_total[a.id] += total
                named = [r for r in rs if r["role"] == "asm" and r["person"].strip().lower() != "vacant"]
                if named and (a is None or not any(r["asm"] and r["asm"].id == a.id for r in named)):
                    notes.append(f"{rs[0]['dist'].name}: sheet says {named[0]['person']}, the dashboard credits "
                                 f"{a.name if a else 'no ASM'} - target follows the dashboard")
        out[month] = {"rows": mrows, "distributors": dist_total, "asms": dict(asm_total), "notes": notes,
                      "total": sum(dist_total.values(), Decimal(0))}
    return out


def apply(planned, label="Google Sheet: Monthly Tracker"):
    """Write the planned targets (only the months in the sheet)."""
    from analytics.cache import bump_cache_version
    from masters.management.commands.import_asm_tracker import Command
    from warehouse.models import Distributor, Target, TargetSplit

    from .asm_tracker import sync_state_targets

    put = Command.put_target
    report = {}
    with transaction.atomic():
        for month, p in planned.items():
            base = Target.objects.filter(month=month, metric="sales")
            for did, v in p["distributors"].items():
                put(month, "distributor", did, v, label)
            removed = base.filter(scope_type="distributor").exclude(scope_id__in=list(p["distributors"])).delete()[0]
            for aid, v in p["asms"].items():
                put(month, "asm", aid, v, label)
            removed += base.filter(scope_type="asm").exclude(scope_id__in=list(p["asms"])).delete()[0]
            region = defaultdict(Decimal)
            for d in Distributor.objects.filter(id__in=list(p["distributors"]), region__isnull=False):
                region[d.region_id] += p["distributors"][d.id]
            for rid, v in region.items():
                put(month, "region", rid, v, label)
            removed += base.filter(scope_type="region").exclude(scope_id__in=list(region)).delete()[0]
            put(month, "overall", None, p["total"], label)
            states = sync_state_targets(month)
            TargetSplit.objects.filter(month=month).delete()
            TargetSplit.objects.bulk_create([
                TargetSplit(month=month, distributor=r["dist"], role=r["role"], person=r["person"][:120],
                            asm=r["asm"], field_staff=r["staff"], value=r["target"], source=label[:64],
                            new_retailer_target=r.get("nr"), bo_gps_target=r.get("gps"), kyc_target=r.get("kyc"),
                            base_incentive=r.get("base"))
                for r in p["rows"]])
            report[month.isoformat()[:7]] = {
                "total": float(p["total"]), "distributors": len(p["distributors"]), "asms": len(p["asms"]),
                "states": states, "people": len(p["rows"]), "removed": removed, "notes": p["notes"]}
    from analytics.derivations import attribute_orders_to_distributor_asm

    attribute_orders_to_distributor_asm()
    bump_cache_version()
    return report


SHEET_MSG = ("{m} targets come from the incentive sheet (TD_ASM_Executive_Incentive_Tracker). Change them with "
             "'Edit incentive sheet' on Region & ASM Performance (or in the live sheet, for a month not yet edited here).")


def sheet_managed(month):
    """True when `month`'s targets were written by the live sheet (then the tracker editor must not overwrite them)."""
    from django.db.models import Q

    from warehouse.models import TargetSplit

    return TargetSplit.objects.filter(month=month).filter(
        Q(source__startswith="Google Sheet") | Q(source__startswith=EDIT_PREFIX)).exists()


def refresh_if_changed(triggered_by="schedule", force=False):
    """Scheduled refresh step: re-read the live sheet and apply it when it changed."""
    from django.conf import settings
    from django.utils import timezone

    from ingestion import gsheets
    from ingestion.models import SyncRun, SyncWatermark

    url = getattr(settings, "TARGETS_SHEET_URL", "")
    if not url or not gsheets.configured():
        return {"source": SOURCE, "status": "not_configured", "rows": 0, "run_id": None}
    try:
        values = gsheets.read_values(url, getattr(settings, "TARGETS_SHEET_TAB", ""))
    except Exception as exc:  # noqa: BLE001 - the previous targets stay
        run = SyncRun.objects.create(source=SOURCE, status="failed", triggered_by=triggered_by,
                                     error=f"Google Sheet: {exc}"[:4000], finished_at=timezone.now())
        return {"source": SOURCE, "status": "failed", "rows": 0, "run_id": run.pk}
    sig = "gs:" + gsheets.signature(values)
    wm = SyncWatermark.objects.filter(key="targets_sheet").first()
    if not force and wm and wm.cursor == sig:
        return {"source": SOURCE, "status": "skipped", "rows": 0, "run_id": None}
    run = SyncRun.objects.create(source=SOURCE, status="running", triggered_by=triggered_by)
    try:
        rows = parse(values, timezone.localdate())
        mine = edited_months()  # months saved in the dashboard belong to the dashboard now
        skipped = sorted({r["month"].isoformat()[:7] for r in rows if r["month"] in mine})
        rows = [r for r in rows if r["month"] not in mine]
        report = apply(plan(rows)) if rows else {}
        if skipped:
            report["kept_dashboard_edits"] = skipped
        run.status, run.rows = "success", len(rows)
        run.details = {"via": "google_sheet", "months": report}
        SyncWatermark.put("targets_sheet", timezone.now(), cursor=sig)
    except Exception as exc:  # noqa: BLE001
        log.exception("Targets sheet import failed")
        run.status, run.error = "failed", str(exc)[:4000]
    run.finished_at = timezone.now()
    run.save()
    return {"source": SOURCE, "status": run.status, "rows": run.rows, "run_id": run.pk}


def executive_performance(month, user):
    """Executives' targets (incentive sheet) vs sales for `month`.

    Orders carry no executive, so an executive's sales come from their distributor(s):
      * alone on a distributor (no ASM line there)  -> the distributor's sales, exactly
      * sharing it with an ASM / others             -> the distributor's sales x their share of its target
                                                       ("allocated"; the user's choice, 19 Nov 2026)
    Within the user's data scope; sales up to today for the running month."""
    from django.db.models import Sum

    from accounts.scope import DISTRIBUTOR_DIMS, get_scope
    from analytics.filters import month_end, today_ist
    from analytics.metrics import pct
    from warehouse.models import Distributor, Order, TargetSplit

    splits = list(TargetSplit.objects.filter(month=month).select_related("distributor__region", "field_staff"))
    dists = Distributor.objects.filter(id__in={s.distributor_id for s in splits})
    sq = get_scope(user).q(DISTRIBUTOR_DIMS)
    if sq is not None:
        dists = dists.filter(sq)
    allowed = set(dists.values_list("id", flat=True))
    end = min(month_end(month), today_ist())
    sales = {r["distributor_id"]: float(r["v"] or 0) for r in Order.objects.filter(
        is_qualifying=True, placed_date__gte=month, placed_date__lte=end, distributor_id__in=allowed
    ).values("distributor_id").annotate(v=Sum("gross_value"))}
    by_dist = {}
    for s in splits:
        by_dist.setdefault(s.distributor_id, []).append(s)
    people = {}
    for did, rows in by_dist.items():
        if did not in allowed:
            continue
        total = sum(float(r.value) for r in rows) or 1.0
        others = [f"{r.person} ({'ASM' if r.role == 'asm' else 'Exec'})" for r in rows]
        for r in rows:
            if r.role != "executive":
                continue
            share = float(r.value) / total
            exact = len(rows) == 1
            key = r.field_staff_id or r.person.lower()
            p = people.setdefault(key, {
                "person": r.person, "hr_name": r.field_staff.name if r.field_staff_id else None,
                "region": r.distributor.region.name if r.distributor.region_id else "",
                "target": 0.0, "sales": 0.0, "distributors": []})
            s_amt = sales.get(did, 0.0) * share
            p["target"] += float(r.value)
            p["sales"] += s_amt
            p["distributors"].append({
                "distributor_id": did, "distributor": r.distributor.name, "target": float(r.value),
                "distributor_sales": round(sales.get(did, 0.0), 2), "share_pct": round(share * 100, 1),
                "sales": round(s_amt, 2), "exact": exact,
                "shared_with": [o for o in others if not o.startswith(f"{r.person} (")]})
    out = []
    for p in people.values():
        exact = [d["exact"] for d in p["distributors"]]
        p.update(sales=round(p["sales"], 2), target=round(p["target"], 2),
                 achieved_pct=pct(p["sales"], p["target"]) if p["target"] else None,
                 basis="exact" if all(exact) else "allocated" if not any(exact) else "mixed")
        out.append(p)
    out.sort(key=lambda p: (-p["target"], p["person"]))
    return {"month": month.isoformat()[:7], "as_of": end.isoformat(), "executives": out}


# ----------------------------------------------------------------------------- editing the sheet in the dashboard
EDIT_PREFIX = "Dashboard edit"  # TargetSplit.source of a month saved from the dashboard's incentive editor
EDIT_COLUMNS = ("role", "person", "td_target", "new_target", "gps_target", "kyc_target")


def edited_months():
    """Months saved from the dashboard: from then on the dashboard owns them and the live sheet no longer
    overwrites them (the sheet keeps the months it alone has)."""
    from warehouse.models import TargetSplit

    return set(TargetSplit.objects.filter(source__startswith=EDIT_PREFIX).values_list("month", flat=True).distinct())


def _split_rows(month):
    from warehouse.models import TargetSplit

    return [{"region": s.distributor.region.name if s.distributor.region_id else "",
             "state": s.distributor.state.name if s.distributor.state_id else "",
             "distributor_id": s.distributor_id, "distributor": s.distributor.name,
             "role": s.role, "person": s.person, "td_target": float(s.value),
             "new_target": s.new_retailer_target, "gps_target": s.bo_gps_target, "kyc_target": s.kyc_target,
             "eligible": float(s.base_incentive) if s.base_incentive is not None else None}
            for s in TargetSplit.objects.filter(month=month).select_related(
                "distributor__region", "distributor__state").order_by("id")]


def editor(month):
    """What the editor opens with: the month's rows in sheet order, or - for a month with none yet - a copy of the
    latest earlier month (targets kept, so only the changes need typing). Plus the pick lists."""
    from django.db.models import Q

    from warehouse.models import Asm, Distributor, FieldStaff, TargetSplit

    rows, copied_from = _split_rows(month), None
    source = TargetSplit.objects.filter(month=month).values_list("source", flat=True).first()
    if not rows:
        prev = TargetSplit.objects.filter(month__lt=month).order_by("-month").values_list("month", flat=True).first()
        if prev:
            rows, copied_from = _split_rows(prev), prev.isoformat()[:7]
    return {
        "month": month.isoformat()[:7], "rows": rows, "copied_from": copied_from,
        "owner": None if source is None else ("dashboard" if source.startswith(EDIT_PREFIX) else "sheet"),
        "source": source,
        "distributors": [{"id": d.id, "name": d.name, "region": d.region.name if d.region_id else "",
                          "state": d.state.name if d.state_id else ""}
                         for d in Distributor.objects.filter(Q(bo_only=False) | Q(id__in=[r["distributor_id"] for r in rows]))
                         .select_related("region", "state").order_by("name")],
        "people": {"asm": sorted(Asm.objects.values_list("name", flat=True)),
                   "executive": sorted(FieldStaff.objects.values_list("name", flat=True))},
    }


def save_month(month, rows, who):
    """Replace `month`'s incentive sheet with `rows` (the editor's grid, in order) through the same importer as the
    live sheet: distributor / ASM / region / state / overall targets and the person-by-person KPI targets."""
    from warehouse.models import Distributor

    if not rows:
        raise TargetSheetError("Add at least one row")
    dists = Distributor.objects.select_related("region", "state").in_bulk(
        [r.get("distributor_id") for r in rows if str(r.get("distributor_id") or "").isdigit()])
    parsed, seen = [], set()
    for i, r in enumerate(rows, start=1):
        d = dists.get(int(r["distributor_id"])) if str(r.get("distributor_id") or "").isdigit() else None
        if d is None:
            raise TargetSheetError(f"Row {i}: choose a distributor")
        person = str(r.get("person") or "").strip()[:120]
        if not person:
            raise TargetSheetError(f"Row {i} ({d.name}): enter the employee name, or 'Vacant'")
        role = "executive" if str(r.get("role") or "").lower().startswith("exec") else "asm"
        key = (d.id, role, person.lower())
        if key in seen and person.lower() not in ("vacant", "-", "na", "n/a"):
            raise TargetSheetError(f"Row {i}: {person} is already on {d.name} as {role}")
        seen.add(key)
        t = money(r.get("td_target"))
        if t <= 0:
            raise TargetSheetError(f"Row {i} ({d.name}, {person}): the TD target must be more than 0")
        kpi = {}
        base = None
        if str(r.get("eligible") or "").strip():
            base = money(r.get("eligible"))
            if not re.fullmatch(r"[\d,.\s₹]+", str(r.get("eligible")).strip()):
                raise TargetSheetError(f"Row {i} ({d.name}, {person}): the eligible incentive must be an amount in ₹")
            base = base or None
        for k, f in (("nr", "new_target"), ("gps", "gps_target"), ("kyc", "kyc_target")):
            v = r.get(f)
            if v in (None, ""):
                kpi[k] = None
                continue
            try:
                kpi[k] = int(float(v))
            except (TypeError, ValueError):
                raise TargetSheetError(f"Row {i} ({d.name}, {person}): {f.replace('_', ' ')} must be a whole number") from None
            if kpi[k] < 0:
                raise TargetSheetError(f"Row {i} ({d.name}, {person}): {f.replace('_', ' ')} must be 0 or more")
        parsed.append({"month": month, "region": d.region.name if d.region_id else "",
                       "state": d.state.name if d.state_id else "", "distributor": d.name, "role": role,
                       "person": person, "target": t, "base": base, "dist": d, **kpi})
    return apply(plan(parsed), f"{EDIT_PREFIX} by {who}")
