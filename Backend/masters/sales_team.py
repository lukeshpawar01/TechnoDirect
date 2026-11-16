"""Sales hierarchy from the HR "Master ASM Tracker" (RSM -> ASM -> senior / field sales executives).

    python manage.py import_sales_team "data/import/sales_team/Master ASM Tracker - ASM_RSM_FSE complete details.csv"

How people are matched (re-runnable; prints every match so it can be checked):
  * Role = the second "Designation" column: Regional Sales Manager -> RSM, Area Sales Manager -> ASM,
    anything else -> field staff.
  * Dashboard ASMs carry short names from the monthly tracker ("Danjith", "Sateesh", "JP"); each is matched to
    the HR person with the same / near-same name tokens ("Dhanjit Chetry", "Satish Wankhedkar", "Jayaprakash T R").
  * "Reporting Manager" is free text ("Prabhakar reddy", "Amitendu Chatterjee", "Samarpan"); it is matched to an
    RSM (for ASMs) or to an ASM / RSM (for field staff) the same way.
  * An ASM with no HR match or no RSM (e.g. a distributor-managed "ASM") reports to the RSM heading its region.
Only names, employee ids, roles, base city, region and joining dates are stored - no phone, email or address.
"""
import csv
import datetime as dt
import re
from difflib import SequenceMatcher

from django.db import transaction

from warehouse.models import Asm, FieldStaff, Region, Rsm

# short names used on the trackers that no spelling rule can resolve
ALIASES = {"jp": "jayaprakash"}
DATE_FORMATS = ("%d %B %Y", "%d %b %Y", "%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d/%m/%Y")


def clean(value):
    return re.sub(r"\s+", " ", (value or "").replace("\n", " ")).strip()


def tokens(name):
    return [t for t in re.findall(r"[a-z]+", clean(name).lower()) if len(t) > 1]


def tok_eq(a, b):
    if a == b:
        return True
    if min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)):
        return True
    return min(len(a), len(b)) >= 4 and SequenceMatcher(None, a, b).ratio() >= 0.7


def name_score(short, full):
    """Share of `short`'s tokens found in `full` (0..1)."""
    st = [ALIASES.get(t, t) for t in tokens(short)]
    ft = tokens(full)
    if not st or not ft:
        return 0.0
    return sum(1 for t in st if any(tok_eq(t, f) for f in ft)) / len(st)


def best_match(short, people, minimum=0.5):
    scored = sorted(((name_score(short, p["name"]), i) for i, p in enumerate(people)), reverse=True)
    if not scored or scored[0][0] < minimum:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None  # ambiguous
    return people[scored[0][1]]


def parse_date(value):
    value = clean(value)
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def nice(name):
    name = clean(name).strip(" .")
    return " ".join(w.capitalize() if (w.isupper() or w.islower()) and len(w) > 1 else w for w in name.split(" "))


def read_people(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    head = [clean(h).lower() for h in rows[0]]
    col = lambda name, nth=0: [i for i, h in enumerate(head) if h == name][nth]  # noqa: E731
    i_id, i_name, i_doj = col("emp id"), col("name"), col("doj")
    i_role = col("designation", 1) if head.count("designation") > 1 else col("designation")
    i_title, i_mgr, i_city, i_reg, i_status = col("designation"), col("reporting manager"), col("city"), \
        col("region"), col("current status")
    people = []
    for r in rows[1:]:
        if len(r) <= i_status or not clean(r[i_id]):
            continue
        role_txt = clean(r[i_role]).lower()
        role = "rsm" if "regional sales manager" in role_txt else "asm" if "area sales manager" in role_txt else "field"
        people.append({
            "emp_id": clean(r[i_id]), "name": clean(r[i_name]), "title": clean(r[i_title]), "role": role,
            "manager": clean(r[i_mgr]), "city": clean(r[i_city]), "region": clean(r[i_reg]),
            "joined_on": parse_date(r[i_doj]), "active": clean(r[i_status]).lower() in ("active", ""),
        })
    return people


@transaction.atomic
def import_sales_team(path, dry_run=False):
    people = read_people(path)
    rsms_p = [p for p in people if p["role"] == "rsm"]
    asms_p = [p for p in people if p["role"] == "asm"]
    regions = {r.name.lower(): r for r in Region.objects.all()}
    log = []

    # RSMs
    rsm_by_emp = {}
    for p in rsms_p:
        obj = Rsm.objects.filter(emp_id=p["emp_id"]).first() or Rsm(code=f"RSM-{p['emp_id']}"[:32], emp_id=p["emp_id"])
        obj.name, obj.joined_on, obj.is_active = nice(p["name"])[:120], p["joined_on"], p["active"]
        obj.region = regions.get(p["region"].lower())
        if not dry_run:
            obj.save()
        rsm_by_emp[p["emp_id"]] = obj
        log.append(f"RSM  {obj.name:<30} {p['region']}")
    region_rsm = {}
    for p in rsms_p:
        region_rsm.setdefault(p["region"].lower(), rsm_by_emp[p["emp_id"]])

    def rsm_for(person):
        """RSM a person reports to: their manager if that is an RSM, else the RSM of their region."""
        m = best_match(person["manager"], rsms_p)
        if m and m["emp_id"] != person["emp_id"]:
            return rsm_by_emp[m["emp_id"]], "reports to"
        return region_rsm.get(person["region"].lower()), "region"

    # dashboard ASMs <- HR ASMs
    matched_hr = {}
    for a in Asm.objects.select_related("region").order_by("name"):
        p = best_match(a.name, asms_p)
        if p:
            rsm, how = rsm_for(p)
            a.full_name, a.emp_id, a.joined_on = nice(p["name"])[:120], p["emp_id"], p["joined_on"]
            matched_hr[p["emp_id"]] = a
        else:
            rsm, how = region_rsm.get(a.region.name.lower()) if a.region_id else None, "region (not in HR master)"
        a.rsm = rsm
        if not dry_run:
            a.save(update_fields=["full_name", "emp_id", "joined_on", "rsm", "updated_at"])
        log.append(f"ASM  {a.name:<14} = {a.full_name or '-':<28} -> RSM {rsm.name if rsm else '-'} [{how}]")
    unmatched = [p["name"] for p in asms_p if p["emp_id"] not in matched_hr]

    # field staff -> ASM (or straight to an RSM)
    staff = 0
    leaders = asms_p + rsms_p
    for p in people:
        if p["role"] != "field":
            continue
        m = best_match(p["manager"], leaders)
        asm = matched_hr.get(m["emp_id"]) if m and m["role"] == "asm" else None
        rsm = asm.rsm if asm else (rsm_by_emp.get(m["emp_id"]) if m and m["role"] == "rsm"
                                   else region_rsm.get(p["region"].lower()))
        if not dry_run:
            FieldStaff.objects.update_or_create(emp_id=p["emp_id"], defaults={
                "name": nice(p["name"])[:120], "designation": p["title"][:64], "asm": asm, "rsm": rsm,
                "region": regions.get(p["region"].lower()), "base_city": p["city"][:100],
                "joined_on": p["joined_on"], "is_active": p["active"]})
        staff += 1
        log.append(f"FSE  {nice(p['name']):<30} -> {asm.name if asm else '(no ASM)':<14} / "
                   f"{rsm.name if rsm else '-'}  [manager: {p['manager']}]")
    return {"log": log, "rsms": len(rsms_p), "asms_matched": len(matched_hr), "field_staff": staff,
            "hr_asms_without_territory": unmatched}
