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
  * BO conversions (New, G/P/S) belong to the retailer's BlueOrigin distributor (the offline relationship). When
    that distributor has no line in the sheet, they go to the retailer's BlueOrigin ASM if that ASM is in the sheet.
  * KYC conversions belong to the distributor of the retailer's first TD order.
  * Orders carry no ASM/executive, so on a distributor with several people each KPI is split by their target for
    THAT KPI (TD sales by TD target).
Overall score = TD% x 50% + New% x 20% + G/P/S% x 20% + KYC% x 10% (a KPI without a target counts 0).
Payout % (sheet "Payout Criteria"): <75% -> 0, 75-<90 -> 90, 90-<100 -> 100, 100-<150 -> 200, 150+ -> 300.
Incentive = base incentive x payout % (empty while the sheet has no base incentive).
"""
import datetime as dt
from collections import defaultdict

from django.db.models import Min, Sum

KPIS = [("td", "TD target", 0.50), ("new", "New retailers (BO to TD)", 0.20), ("gps", "BO Gold/Platinum/Silver", 0.20),
        ("kyc", "KYC conversion", 0.10)]
GPS_TIERS = ("Platinum", "Gold", "Silver")
SLABS = [(150, 300), (100, 200), (90, 100), (75, 90)]  # overall score >= x -> payout %
TARGET_FIELD = {"td": "value", "new": "new_retailer_target", "gps": "bo_gps_target", "kyc": "kyc_target"}
VACANT = ("vacant", "-", "na", "n/a")


def payout_pct(score):
    for floor, pay in SLABS:
        if score >= floor:
            return pay
    return 0


def _bo_links(td_ids, month):
    """{td_retailer_id: (distributor_id, asm_id)} for TD retailers that bought offline in BlueOrigin before `month`."""
    from warehouse.models import BoRetailer, BoRetailerMonth

    before = {b for b in BoRetailerMonth.objects.filter(bo_retailer__td_retailer_id__in=td_ids, month__lt=month,
                                                        value__gt=0).values_list("bo_retailer_id", flat=True)}
    out = {}
    # one TD retailer can match several BO rows (same phone): the one with the most offline purchase wins
    rows = (BoRetailer.objects.filter(id__in=before).annotate(p=Sum("months__value"))
            .values("td_retailer_id", "distributor_id", "asm_id", "p").order_by("-p"))
    for r in rows:
        out.setdefault(r["td_retailer_id"], (r["distributor_id"], r["asm_id"]))
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
        bo_dist, bo_asm = bo.get(r["id"], (None, None))
        is_bo = r["id"] in bo
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
            elif r["bo_asm_id"] in sheet_asms:
                c[k] = ("asm", r["bo_asm_id"])
            else:
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
        score = 0.0
        for k, _, w in KPIS:
            t, a = p[f"{k}_target"], p[f"{k}_actual"]
            pc = a / t * 100 if t else None
            p[f"{k}_pct"] = round(pc, 1) if pc is not None else None
            p[f"{k}_actual"] = round(a, 2) if k == "td" else round(a, 1)
            score += (pc or 0) * w
        p["score_pct"] = round(score, 1)
        p["payout_pct"] = payout_pct(score)
        p["incentive"] = round(p["base_incentive"] * p["payout_pct"] / 100, 2) if p["base_incentive"] else None
        out.append(p)
    out.sort(key=lambda p: (p["region"], -p["td_target"], p["person"]))
    credited = [c for c in credit.values()]
    totals = {k: sum(1 for c in credited if c.get(k)) for k in ("new", "gps", "kyc")}
    uncredited = {k: sum(1 for c in credited if k in c and c[k] is None) for k in ("new", "gps", "kyc")}
    return {"month": month.isoformat()[:7], "as_of": end.isoformat(), "people": out, "totals": totals,
            "uncredited": uncredited, "weights": {k: w for k, _, w in KPIS},
            "slabs": [{"from": f, "payout": p} for f, p in SLABS]}


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
