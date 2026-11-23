"""ASM & executive incentive tracker - the team's sheet "TD_ASM_Executive_Incentive_Tracker", computed from data.

Targets per person per distributor come from the live sheet (TargetSplit, masters/target_sheet.py). Achievement
(user's definitions, 20 Nov 2026):

  KPI (weight, sheet "KPI Criteria")   counted for the month
  TD target (50%)                      qualifying TD sales of the distributor
  New Retailer (20%)                   BlueOrigin CONVERSIONS: retailers who bought offline in BlueOrigin before the
                                       month and placed their first-ever TD order in the month
  BO G/P/S (20%)                       of those, the ones with BO tier Gold / Platinum / Silver
  KYC Conversion (10%)                 any retailer whose first-ever TD order is in the month and whose KYC was done
                                       BEFORE the month (converting the existing KYC base)

Credit
  * BO conversions (New, G/P/S) belong to the retailer's BlueOrigin distributor (the offline relationship), and
    only when that distributor is in the incentive sheet; otherwise they count for no one (user, 2026-11-23).
  * KYC conversions belong to the distributor of the retailer's first TD order.
  * Orders carry no ASM/executive, so on a distributor with several people each KPI is split by their target for
    THAT KPI (TD sales by TD target).
Payout (TD_Incentive_Policy.docx, 23 Nov 2026 - replaces the sheet's overall score and 75/90/100/150 slabs):
  * each KPI on its own: achievement % (as shown, 1 decimal) -> payout factor  <70% 0 | 70-<90% 0.90 | 90%+ 1.00
    (the policy's top slab is "90% to below 100%" and its example pays 1.00 at 100%, so 100%+ stays 1.00)
  * a KPI without a target pays 0
  * payout % of the eligible incentive = sum of weight x factor, e.g. 50%x0.9 + 20%x1 + 20%x0.9 + 10%x1 = 93%
    (KPI payable = KPI eligible amount (weight x total eligible) x factor; the total is the sum)
"""
import datetime as dt
from collections import defaultdict

from django.db.models import Min, Sum

KPIS = [("td", "TD target", 0.50), ("new", "New retailers (BO to TD)", 0.20), ("gps", "BO Gold/Platinum/Silver", 0.20),
        ("kyc", "KYC conversion", 0.10)]
GPS_TIERS = ("Platinum", "Gold", "Silver")
ELIGIBLE_DEFAULT = 5000.0  # ₹ eligible incentive per person (TD_Incentive_Policy example), unless the row sets its own
FACTORS = [(90, 1.0), (70, 0.9)]  # KPI achievement % >= x -> payout factor (TD_Incentive_Policy)
TARGET_FIELD = {"td": "value", "new": "new_retailer_target", "gps": "bo_gps_target", "kyc": "kyc_target"}
VACANT = ("vacant", "-", "na", "n/a")


def payout_factor(achievement):
    """A KPI's payout factor from its achievement % (None = no target -> 0)."""
    if achievement is None:
        return 0.0
    for floor, f in FACTORS:
        if achievement >= floor:
            return f
    return 0.0


def score(row):
    """Fill {k}_factor and {k}_payable (% of the eligible incentive) per KPI and payout_pct (their sum) from the
    row's {k}_pct values (already rounded as shown)."""
    total = 0.0
    for k, _, w in KPIS:
        f = payout_factor(row.get(f"{k}_pct"))
        row[f"{k}_factor"] = f
        row[f"{k}_payable"] = round(w * f * 100, 1)
        total += w * f * 100
    row["payout_pct"] = round(total, 1)
    return row


def tier_before(bo_ids, month):
    """{bo_retailer_id: tier} in the last BlueOrigin quarter that ENDED before `month` (missing from it = Untiered).

    Not the latest tier: BO values include app orders, so a quarter that contains the conversion month would rate the
    retailer partly on the very TD orders being rewarded (and an old period must use the tier it had then)."""
    from django.db.models import Max

    from analytics.filters import add_months
    from warehouse.models import BoRetailerQuarter

    q = BoRetailerQuarter.objects.filter(quarter__lte=add_months(month, -3)).aggregate(q=Max("quarter"))["q"]
    if q is None:
        return {}
    return dict(BoRetailerQuarter.objects.filter(quarter=q, bo_retailer_id__in=list(bo_ids))
                .values_list("bo_retailer_id", "tier"))


def _bo_links(td_ids, month):
    """{td_retailer_id: (distributor_id, asm_id, tier before the month)} for TD retailers that bought offline in
    BlueOrigin before `month`."""
    from warehouse.models import BoRetailer, BoRetailerMonth

    before = {b for b in BoRetailerMonth.objects.filter(bo_retailer__td_retailer_id__in=td_ids, month__lt=month,
                                                        value__gt=0).values_list("bo_retailer_id", flat=True)}
    out = {}
    # one TD retailer can match several BO rows (same phone): the one with the most offline purchase wins
    rows = (BoRetailer.objects.filter(id__in=before).annotate(p=Sum("months__value"))
            .values("id", "td_retailer_id", "distributor_id", "asm_id", "p").order_by("-p"))
    rows = list(rows)
    tiers = tier_before({r["id"] for r in rows}, month)
    for r in rows:
        out.setdefault(r["td_retailer_id"], (r["distributor_id"], r["asm_id"], tiers.get(r["id"]) or "Untiered"))
    return out


def month_retailers(month):
    """Retailers whose first-ever TD order is in `month`: {retailer_id: {...}} with their KPI flags and credit."""
    from analytics.filters import month_end
    from warehouse.models import Order, Retailer

    end = month_end(month)
    firsts = (Order.objects.filter(is_qualifying=True).values("retailer_id")
              .annotate(first=Min("placed_at")).filter(first__date__gte=month, first__date__lte=end))
    ids = [r["retailer_id"] for r in firsts]
    first_order = {}
    for o in (Order.objects.filter(is_qualifying=True, retailer_id__in=ids).order_by("placed_at")
              .values("retailer_id", "distributor_id", "display_id", "placed_date", "gross_value")):
        first_order.setdefault(o["retailer_id"], o)
    bo = _bo_links(ids, month)
    out = {}
    for r in Retailer.objects.filter(id__in=ids).values("id", "name", "phone", "city", "tier", "kyc_status",
                                                         "kyc_approved_at", "signed_up_at", "state__name"):
        fo = first_order.get(r["id"])
        if fo is None:
            continue
        kyc_at = r["kyc_approved_at"] or r["signed_up_at"]  # no approval date in TD data: sign-up date (2026-11-15)
        kyc_day = kyc_at.date() if isinstance(kyc_at, dt.datetime) else kyc_at
        bo_dist, bo_asm, bo_tier = bo.get(r["id"], (None, None, None))
        is_bo = r["id"] in bo
        if is_bo:
            r["tier"] = bo_tier  # the tier it had before converting, from the same BO record that gets the credit
        out[r["id"]] = {
            **r, "distributor_id": fo["distributor_id"], "first_order": fo["display_id"],
            "first_order_date": fo["placed_date"], "first_order_value": float(fo["gross_value"] or 0),
            "kyc_on": kyc_day, "bo_existing": is_bo, "bo_distributor_id": bo_dist, "bo_asm_id": bo_asm,
            "new": is_bo,
            "gps": is_bo and (r["tier"] or "") in GPS_TIERS,
            "kyc": r["kyc_status"] == "approved" and kyc_day is not None and kyc_day < month,
        }
    return out


def _credit(rets, by_dist, sheet_asms):
    """{retailer_id: {kpi: ("dist", distributor_id) | ("asm", asm_id) | None}} - where each counted KPI is credited."""
    out = {}
    for rid, r in rets.items():
        c = {}
        for k in ("new", "gps", "kyc"):
            if not r[k]:
                continue
            if k == "kyc":
                c[k] = ("dist", r["distributor_id"]) if r["distributor_id"] in by_dist else None
            elif r["bo_distributor_id"] in by_dist:
                c[k] = ("dist", r["bo_distributor_id"])
            else:
                # only the incentive sheet's distributors count: a BlueOrigin distributor that is not in the sheet
                # (e.g. Noble, offline only) gives no credit to anyone - not even its BlueOrigin ASM (user, 2026-11-23)
                c[k] = None
        out[rid] = c
    return out


def _sheet(month, user):
    """The sheet's people in the user's scope: (by_dist {distributor_id: [TargetSplit]}, allowed distributor ids)."""
    from accounts.scope import DISTRIBUTOR_DIMS, get_scope
    from warehouse.models import Distributor, TargetSplit

    splits = list(TargetSplit.objects.filter(month=month).select_related("distributor__region", "asm", "field_staff"))
    dists = Distributor.objects.filter(id__in={s.distributor_id for s in splits})
    sq = get_scope(user).q(DISTRIBUTOR_DIMS) if user is not None else None
    if sq is not None:
        dists = dists.filter(sq)
    allowed = set(dists.values_list("id", flat=True))
    by_dist = defaultdict(list)
    for s in splits:
        if s.distributor_id in allowed and s.person.strip().lower() not in VACANT:
            by_dist[s.distributor_id].append(s)
    return by_dist, allowed


def tracker(month, user=None):
    """{month, as_of, people: [...], totals} - one row per person, with per-distributor detail."""
    from django.utils.timezone import localdate

    from analytics.filters import month_end
    from warehouse.models import Order

    by_dist, allowed = _sheet(month, user)
    sheet_asms = {s.asm_id for rs in by_dist.values() for s in rs if s.role == "asm" and s.asm_id}
    end = min(month_end(month), localdate())
    sales = {r["distributor_id"]: float(r["v"] or 0) for r in Order.objects.filter(
        is_qualifying=True, placed_date__gte=month, placed_date__lte=end, distributor_id__in=allowed
    ).values("distributor_id").annotate(v=Sum("gross_value"))}
    rets = month_retailers(month)
    credit = _credit(rets, by_dist, sheet_asms)
    dist_counts = defaultdict(lambda: {"new": 0, "gps": 0, "kyc": 0})
    asm_counts = defaultdict(lambda: {"new": 0, "gps": 0, "kyc": 0})
    for rid, c in credit.items():
        for k, where in c.items():
            if where is None:
                continue
            (dist_counts if where[0] == "dist" else asm_counts)[where[1]][k] += 1

    people = {}
    for did, rows in by_dist.items():
        actual = {"td": sales.get(did, 0.0), **dist_counts[did]}
        tot = {k: sum(float(getattr(r, f) or 0) for r in rows) for k, f in TARGET_FIELD.items()}
        for r in rows:
            key = (r.role, r.asm_id or r.field_staff_id or r.person.strip().lower())
            p = people.setdefault(key, {
                "person": r.person, "role": r.role, "asm_id": r.asm_id if r.role == "asm" else None,
                "region": r.distributor.region.name if r.distributor.region_id else "",
                "base_incentive": None, "distributors": [], "via_bo_asm": {"new": 0, "gps": 0},
                **{f"{k}_target": 0.0 for k, _, _ in KPIS}, **{f"{k}_actual": 0.0 for k, _, _ in KPIS}})
            if r.base_incentive is not None:
                p["base_incentive"] = (p["base_incentive"] or 0) + float(r.base_incentive)
            row = {"distributor_id": did, "distributor": r.distributor.name,
                   "shared": len(rows) > 1, "shared_with": [o.person for o in rows if o is not r]}
            for k, _, _ in KPIS:
                t = float(getattr(r, TARGET_FIELD[k]) or 0)
                share = t / tot[k] if tot[k] else 0.0
                a = actual[k] * share
                p[f"{k}_target"] += t
                p[f"{k}_actual"] += a
                row[f"{k}_target"], row[f"{k}_actual"], row[f"{k}_share_pct"] = t, round(a, 2), round(share * 100, 1)
            p["distributors"].append(row)
    # BO conversions whose BlueOrigin distributor is not in the sheet: to their BlueOrigin ASM (once per ASM)
    for p in people.values():
        extra = asm_counts.get(p["asm_id"]) if p["asm_id"] else None
        if extra:
            for k in ("new", "gps"):
                p[f"{k}_actual"] += extra[k]
                p["via_bo_asm"][k] = extra[k]
    out = []
    for p in people.values():
        for k, _, w in KPIS:
            t, a = p[f"{k}_target"], p[f"{k}_actual"]
            pc = a / t * 100 if t else None
            p[f"{k}_pct"] = round(pc, 1) if pc is not None else None
            p[f"{k}_actual"] = round(a, 2) if k == "td" else round(a, 1)
        score(p)
        p["incentive"] = round(p["base_incentive"] * p["payout_pct"] / 100, 2) if p["base_incentive"] else None
        out.append(p)
    out.sort(key=lambda p: (p["region"], -p["td_target"], p["person"]))
    credited = [c for c in credit.values()]
    totals = {k: sum(1 for c in credited if c.get(k)) for k in ("new", "gps", "kyc")}
    uncredited = {k: sum(1 for c in credited if k in c and c[k] is None) for k in ("new", "gps", "kyc")}
    return {"month": month.isoformat()[:7], "as_of": end.isoformat(), "people": out, "totals": totals,
            "uncredited": uncredited, "weights": {k: w for k, _, w in KPIS},
            "factors": [{"from": f, "factor": x} for f, x in FACTORS]}


def retailer_list(month, user=None, kpi=None, tiers=None, distributor_ids=None, asm_id=None, can_see_phone=False):
    """The retailers behind the counts, with who they are credited to. kpi: new / gps / kyc; tiers: BO tiers
    ('None' = not in BlueOrigin); distributor_ids / asm_id: one person's retailers (credited through their
    distributors, or through their BlueOrigin ASM)."""
    from analytics.views.funnel import mask_phone
    from warehouse.models import Asm, Distributor

    by_dist, allowed = _sheet(month, user)
    sheet_asms = {s.asm_id for rs in by_dist.values() for s in rs if s.role == "asm" and s.asm_id}
    rets = month_retailers(month)
    credit = _credit(rets, by_dist, sheet_asms)
    names = dict(Distributor.objects.values_list("id", "name"))
    asm_names = dict(Asm.objects.values_list("id", "name"))
    pick = set(distributor_ids or [])
    asm_people = defaultdict(set)
    for rs in by_dist.values():
        for s in rs:
            if s.role == "asm" and s.asm_id:
                asm_people[s.asm_id].add(s.person)
    rows = []
    for rid, r in rets.items():
        kpis = [k for k in ("new", "gps", "kyc") if r[k]] if kpi not in ("new", "gps", "kyc") else ([kpi] if r[kpi] else [])
        if not kpis:
            continue
        tier = r["tier"] or "None"
        if tiers and tier not in tiers:
            continue
        where = credit[rid].get(kpis[0])
        if where is None and user is not None and r["distributor_id"] not in allowed and r["bo_distributor_id"] not in allowed:
            continue  # outside the user's scope
        if pick or asm_id:
            mine = where is not None and ((where[0] == "dist" and where[1] in pick) or (where[0] == "asm" and where[1] == asm_id))
            if not mine:
                continue
        if where is None:
            to = "No one in the sheet"
        elif where[0] == "dist":
            to = ", ".join(s.person for s in by_dist[where[1]]) + f" ({names.get(where[1])})"
        else:
            to = ", ".join(sorted(asm_people[where[1]])) + " (BlueOrigin ASM)"
        rows.append({
            "retailer_id": r["id"], "retailer": r["name"], "phone": mask_phone(r["phone"], can_see_phone),
            "city": r["city"], "state": r["state__name"],
            "td_distributor": names.get(r["distributor_id"]),
            "bo_distributor": names.get(r["bo_distributor_id"]) if r["bo_existing"] else None,
            "bo_asm": asm_names.get(r["bo_asm_id"]) if r["bo_existing"] else None,
            "tier": r["tier"] or "Not in BlueOrigin", "first_order": r["first_order"],
            "first_order_date": r["first_order_date"].isoformat(), "first_order_value": r["first_order_value"],
            "kyc_on": r["kyc_on"].isoformat() if r["kyc_on"] else None,
            "counts_for": [lbl for k, lbl in (("new", "New (BO to TD)"), ("gps", "BO G/P/S"), ("kyc", "KYC conversion"))
                           if r[k]],
            "credited_to": to})
    rows.sort(key=lambda x: (x["credited_to"], x["first_order_date"]))
    return rows


def sheet_month(month):
    """The month to show: `month` when the incentive sheet has rows for it, else the latest month it has (or None)."""
    from django.db.models import Max

    from warehouse.models import TargetSplit

    if TargetSplit.objects.filter(month=month).exists():
        return month
    return TargetSplit.objects.aggregate(m=Max("month"))["m"]


def sheet_table(month, user=None):
    """The team's sheet "TD_ASM_Executive_Incentive_Tracker", row for row (sheet order), with every Actual / Achieved
    column computed from data. One row per person per distributor, vacant lines included. Base incentive and the
    incentive amount are left out (decided outside the dashboard, 2026-11-23). Within a distributor each KPI is split
    by the row's target for that KPI; a row's payout factors and payout % use only its own KPIs, as the sheet does."""
    from django.utils.timezone import localdate

    from accounts.scope import DISTRIBUTOR_DIMS, get_scope
    from analytics.filters import month_end
    from warehouse.models import Distributor, Order, TargetSplit

    shown = sheet_month(month)
    if shown is None:
        return {"requested": month.isoformat()[:7], "month": None, "rows": []}
    splits = list(TargetSplit.objects.filter(month=shown).select_related(
        "distributor__region", "distributor__state", "asm").order_by("id"))  # created in sheet order
    dists = Distributor.objects.filter(id__in={s.distributor_id for s in splits})
    sq = get_scope(user).q(DISTRIBUTOR_DIMS) if user is not None else None
    if sq is not None:
        dists = dists.filter(sq)
    allowed = set(dists.values_list("id", flat=True))
    splits = [s for s in splits if s.distributor_id in allowed]
    end = min(month_end(shown), localdate())
    sales = {r["distributor_id"]: float(r["v"] or 0) for r in Order.objects.filter(
        is_qualifying=True, placed_date__gte=shown, placed_date__lte=end, distributor_id__in=allowed
    ).values("distributor_id").annotate(v=Sum("gross_value"))}
    named = defaultdict(list)
    for s in splits:
        if s.person.strip().lower() not in VACANT:
            named[s.distributor_id].append(s)
    sheet_asms = {s.asm_id for rs in named.values() for s in rs if s.role == "asm" and s.asm_id}
    credit = _credit(month_retailers(shown), named, sheet_asms)
    dist_counts = defaultdict(lambda: {"new": 0, "gps": 0, "kyc": 0})
    asm_counts = defaultdict(lambda: {"new": 0, "gps": 0, "kyc": 0})
    for c in credit.values():
        for k, where in c.items():
            if where is not None:
                (dist_counts if where[0] == "dist" else asm_counts)[where[1]][k] += 1
    by_dist = defaultdict(list)
    for s in splits:
        by_dist[s.distributor_id].append(s)
    asm_given = set()  # BO conversions credited via the BlueOrigin ASM go on that ASM's first row only
    rows = []
    for s in splits:
        rs = by_dist[s.distributor_id]
        vacant = s.person.strip().lower() in VACANT
        row = {"id": s.id, "month": shown.strftime("%b %Y"), "region": s.distributor.region.name if s.distributor.region_id else "",
               "state": s.distributor.state.name if s.distributor.state_id else "", "distributor_id": s.distributor_id,
               "distributor": s.distributor.name, "role": "Executive" if s.role == "executive" else "ASM",
               "employee": s.person, "vacant": vacant, "asm_id": s.asm_id if s.role == "asm" else None,
               "shared_with": [o.person for o in rs if o is not s]}
        for k, _, w in KPIS:
            t = float(getattr(s, TARGET_FIELD[k]) or 0)
            pool = rs if k == "td" else [o for o in rs if o.person.strip().lower() not in VACANT]
            tot = sum(float(getattr(o, TARGET_FIELD[k]) or 0) for o in pool)
            share = t / tot if (tot and (k == "td" or not vacant)) else 0.0
            base = sales.get(s.distributor_id, 0.0) if k == "td" else dist_counts[s.distributor_id][k]
            a = base * share
            if k in ("new", "gps") and row["asm_id"] and row["asm_id"] not in asm_given and asm_counts.get(row["asm_id"]):
                a += asm_counts[row["asm_id"]][k]
                row[f"{k}_via_bo_asm"] = asm_counts[row["asm_id"]][k]
            pc = a / t * 100 if t else None
            row[f"{k}_target"] = t if t else None
            row[f"{k}_actual"] = round(a, 2) if k == "td" else round(a, 1)
            row[f"{k}_pct"] = round(pc, 1) if pc is not None else None
        if row["asm_id"] and asm_counts.get(row["asm_id"]):
            asm_given.add(row["asm_id"])
        score(row)
        # payment (TD_Incentive_Policy): KPI payable = eligible amount x KPI weight x payout factor; total = their sum
        eligible = None if vacant else (float(s.base_incentive) if s.base_incentive else ELIGIBLE_DEFAULT)
        row["eligible"] = eligible
        for k, _, w in KPIS:
            row[f"{k}_amount"] = round(eligible * w * row[f"{k}_factor"], 2) if eligible else None
        row["payment"] = round(sum(row[f"{k}_amount"] for k, _, _ in KPIS), 2) if eligible else None
        rows.append(row)
    return {"requested": month.isoformat()[:7], "month": shown.isoformat()[:7], "as_of": end.isoformat(),
            "fallback": shown != month, "rows": rows,
            "weights": {k: w for k, _, w in KPIS}, "factors": [{"from": f, "factor": x} for f, x in FACTORS]}
