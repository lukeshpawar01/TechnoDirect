"""Monthly ASM sales targets from the "Technodirect Order Tracking" workbook (one tab per month, TD Target in lakhs).

    python manage.py import_asm_targets "C:/.../Technodirect Order Tracking (2).xlsx" [--dry-run]

How the sheet is read:
  * Tab name -> month: "May", "June", "July", "Aug", "Sept" = 2025 (they precede "Oct 25"); "Oct 25" ... "Sept 26".
    Tabs laid out per distributor (Distributor / Order Value / ASM / Total Target) are distributor trackers and
    belong to import_asm_tracker, not here. NB: the tab named "Oct 26" holds April 2026 data.
  * Target = the "TD Target" column, in lakhs. Text such as "15L", "110 orders 30L", "2.5Cr" is parsed; a
    target given only in orders ("130 orders") or 0 is skipped.
  * A row is a person (ASM), a distributor ("Zealous", "Kanchan", "Sandeep") or a territory with no ASM
    ("Mumbai"); ROW_RULES below says which, per month where it changed. Rows nobody can be mapped to
    ("Ranjeeth") still count in the month total but not under a person.
  * Writes ASM targets, distributor targets (ASM-less rows), region totals and the overall (the sheet's
    Total row; none when the tab has no Total). Months that already have a distributor-level tracker
    (e.g. Apr-26, Nov-26) keep it: only ASMs with no target there are added.
Only months from Jan 2026 (SINCE) are loaded, plus months asked for by name (--month 2025-10: October 2025
was added on request, 19 Nov 2026).
Re-runnable: unchanged values stay, a changed value becomes a new target version.
"""
import datetime as dt
import re
from collections import Counter, defaultdict
from decimal import Decimal

from warehouse.models import Asm, Distributor, Target

# Oct-26 and Nov-26 tabs are deliberately absent: those months come from the Order Tracking Sheet10 trackers
# (import_asm_tracker --targets-only), which are the approved distributor-level targets.
TAB_MONTH = {
    "may": "2025-05", "june": "2025-06", "july": "2025-07", "aug": "2025-08", "sept": "2025-09",
    "oct 25": "2025-10", "nov 25": "2025-11", "dec 25": "2025-12", "jan 26": "2026-01", "feb 26": "2026-02",
    "mar 26": "2026-03", "april 26": "2026-04", "may 26": "2026-05", "june 26": "2026-06", "july 26": "2026-07",
    "aug 26": "2026-08", "sept 26": "2026-09",
}
# sheet name (lower-case) -> dashboard ASM name
ASM_ALIASES = {
    "mohd aamer": "Mohd Aameer", "mohd aameer": "Mohd Aameer", "mohd jafar": "Jafar", "gururaj": "Gururaj",
    "gondi gururaj": "Gururaj", "imran": "Imran & Anil", "imran ulla khan": "Imran & Anil", "ranjith": "Ranjith",
    "s ranjith": "Ranjith", "vishal": "Vishal", "vishal batra": "Vishal", "supriya": "Supriya",
    "supriya kumar singh": "Supriya", "ajoy": "Ajoy", "ajoy ghughu": "Ajoy", "gaurav": "Gaurav",
    "gaurav sharma": "Gaurav", "dhanjit": "Danjith", "dhanjit chetry": "Danjith", "shankar": "Shankar",
    "shankar yadav": "Shankar", "ankush": "Ankush", "vineet": "Vineeth", "vineet pandey": "Vineeth",
    "rohit": "Rohit", "rohit pandey": "Rohit", "sateesh (pune)": "Sateesh", "satish wankhedkar": "Sateesh",
    "kunal": "Kunal", "sunny": "Sunny", "sunny gaikwad": "Sunny", "suresh": "Suresh", "jp": "JP",
    "yatendra": "Yatendra", "zealous": "Zealous",
    # AP (Virat Sports Wear): Imran and Anil worked together Jan-Sep 2026 (one joint ASM); Anil alone from Oct 2026
    "imran & anil": "Imran & Anil", "anil": "Anil",
}
# rows that are not a person: (name, months or None) -> ("distributor", source_id, asm to add to) / ("asm", name)
ROW_RULES = [
    ("kanchan", None, ("distributor", "td:14", None)),
    ("sandeep", None, ("asm", "Gaurav")),  # Sandeep Sports is in Gaurav's territory: part of his ASM target
    ("mumbai", {"2026-04"}, ("asm", "Rohit")),                # Apr-26 tracker: Ajay Hosiery = Rohit
    ("mumbai", {"2026-05"}, ("distributor", "td:37", None)),  # Ajay Hosiery between Rohit and Suresh
    ("mumbai", {"2026-06"}, ("asm", "Suresh")),               # Suresh joined 1 Jun 26
    ("ranjeeth", None, ("unassigned", None, None)),
    # 2025: Imran worked alone (Virat Sports Wear) - his own ASM, not the joint "Imran & Anil" of 2026
    ("imran", {"2025-10", "2025-11", "2025-12"}, ("asm", "Imran")),
]
NOTE = "ASM targets workbook ({tab}, TD Target in lakhs)"


def lakhs(value):
    """TD Target cell -> rupees (Decimal) or None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value)) * 100000 if value else None
    text = str(value).replace(",", "")
    m = re.findall(r"([\d.]+)\s*(cr|l|k)\b", text.lower())
    if not m:
        return None  # e.g. "130 orders"
    num, unit = m[-1]
    return Decimal(num) * {"cr": 10000000, "l": 100000, "k": 1000}[unit]


def rule_for(name, month):
    for key, months, rule in ROW_RULES:
        if name == key and (months is None or month in months):
            return rule
    return None


def read_workbook(path):
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    out = {}
    for ws in wb.worksheets:
        month = TAB_MONTH.get(ws.title.strip().lower())
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        head = next((r for r in rows if r and any(str(c or "").strip().lower() == "td target" for c in r)), None)
        if not month or head is None:
            continue  # beat-plan link tabs, distributor trackers
        i_name = next(i for i, c in enumerate(head) if str(c or "").strip().lower() == "name")
        i_tgt = next(i for i, c in enumerate(head) if str(c or "").strip().lower() == "td target")
        i_ach = next((i for i, c in enumerate(head) if str(c or "").strip().lower().startswith(("td achieved", "acheived", "achieved"))), None)
        entries, total = [], None
        for r in rows[rows.index(head) + 1:]:
            name = str(r[i_name] or "").strip() if i_name < len(r) else ""
            if not name or name.lower() == "name":
                if entries:
                    break  # a repeated block below the first (e.g. June 2025)
                continue
            if name.lower() == "total":
                total = lakhs(r[i_tgt])
                continue
            ach = r[i_ach] if i_ach is not None and i_ach < len(r) else None
            entries.append({"name": name, "target": lakhs(r[i_tgt]), "raw": r[i_tgt],
                            "achieved_l": ach if isinstance(ach, (int, float)) else None})
        out[ws.title.strip()] = {"month": dt.date.fromisoformat(month + "-01"), "rows": entries, "total": total}
    return out


SINCE = dt.date(2026, 1, 1)  # ASM targets are managed from Jan 2026 (earlier months are not tracked)


def import_asm_targets(path, dry_run=False, put_target=None, since=SINCE, months=None):
    """months: only these months ("YYYY-MM"), even before SINCE (e.g. Oct 2025, loaded on request)."""
    from masters.management.commands.import_asm_tracker import Command

    put = put_target or Command.put_target
    asms = {a.name: a for a in Asm.objects.select_related("region")}
    report, written = [], Counter()
    for tab, sheet in read_workbook(path).items():
        month, key = sheet["month"], sheet["month"].isoformat()[:7]
        if months is not None:
            if key not in months:
                continue
        elif month < since:
            continue
        has_dist_tracker = Target.objects.filter(month=month, scope_type="distributor").exclude(
            notes__startswith="ASM Beat Plan").exclude(notes__startswith="ASM targets workbook").exists()
        existing_asm = set(Target.objects.filter(month=month, scope_type="asm").values_list("scope_id", flat=True))
        by_asm, by_dist, by_region = defaultdict(Decimal), {}, defaultdict(Decimal)
        unassigned, skipped = Decimal(0), []
        for e in sheet["rows"]:
            name, v = e["name"].lower().strip(), e["target"]
            if v is None:
                if e["raw"] not in (None, 0, 0.0, ""):
                    skipped.append(f"{e['name']} ({e['raw']})")
                continue
            rule = rule_for(name, key)
            if rule and rule[0] == "unassigned":
                unassigned += v
                continue
            if rule and rule[0] == "distributor":
                d = Distributor.objects.get(source_id=rule[1])
                by_dist[d.id] = by_dist.get(d.id, Decimal(0)) + v
                if rule[2]:
                    by_asm[asms[rule[2]].id] += v
                if d.region_id:
                    by_region[d.region_id] += v
                continue
            asm_name = rule[1] if rule else ASM_ALIASES.get(name)
            a = asms.get(asm_name) if asm_name else None
            if a is None:
                skipped.append(f"{e['name']} (no ASM match)")
                unassigned += v
                continue
            by_asm[a.id] += v
            if a.region_id:
                by_region[a.region_id] += v
        notes = NOTE.format(tab=tab)
        line = Counter()
        if not dry_run:
            for aid, v in by_asm.items():
                if has_dist_tracker and aid in existing_asm:
                    continue  # the distributor-level tracker for this month already set it
                line[put(month, "asm", aid, v, notes)] += 1
            if not has_dist_tracker:
                for did, v in by_dist.items():
                    line[put(month, "distributor", did, v, notes)] += 1
                for rid, v in by_region.items():
                    line[put(month, "region", rid, v, notes)] += 1
                if sheet["total"]:
                    line[put(month, "overall", None, sheet["total"], notes)] += 1
        written.update(line)
        report.append({
            "tab": tab, "month": key, "asm_targets": len(by_asm), "sum_l": float(sum(by_asm.values()) / 100000),
            "total_l": float(sheet["total"] / 100000) if sheet["total"] else None,
            "unassigned_l": float(unassigned / 100000), "skipped": skipped,
            "kept_distributor_tracker": has_dist_tracker, "written": dict(line),
        })
    return {"months": report, "written": dict(written)}


def reconcile(path):
    """Sheet 'achieved' (lakhs) vs dashboard sales per ASM-month: checks the ASM attribution."""
    from django.db.models import Sum
    from django.db.models.functions import TruncMonth

    from warehouse.models import Order

    actual = defaultdict(float)
    for r in Order.objects.filter(is_qualifying=True, asm__isnull=False).annotate(m=TruncMonth("placed_date")).values(
            "m", "asm__name").annotate(s=Sum("gross_value")):
        actual[(r["m"].isoformat()[:7] if hasattr(r["m"], "isoformat") else str(r["m"])[:7], r["asm__name"])] += \
            float(r["s"] or 0) / 100000
    rows = []
    for tab, sheet in read_workbook(path).items():
        if sheet["month"] < SINCE:
            continue
        key = sheet["month"].isoformat()[:7]
        for e in sheet["rows"]:
            name = e["name"].lower().strip()
            rule = rule_for(name, key)
            if rule and rule[0] == "asm" and any(ASM_ALIASES.get(x["name"].lower().strip()) == rule[1]
                                                  for x in sheet["rows"]):
                continue  # folded into an ASM that has its own row (e.g. "Sandeep" -> Gaurav): not comparable
            asm_name = rule[1] if rule and rule[0] == "asm" else (None if rule else ASM_ALIASES.get(name))
            if not asm_name or e["achieved_l"] is None:
                continue
            rows.append((key, e["name"], asm_name, e["achieved_l"], round(actual.get((key, asm_name), 0.0), 2)))
    return rows
