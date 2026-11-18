"""BlueOrigin (offline) data: the quarterly distributor sheets FY??_qtr?.csv (Dropbox "Power BI" folder).

Each sheet row is one retailer in one quarter, already deduped by BlueOrigin (Retailer_ID, e.g. TIR-00615):
month values for the quarter, Last 3 Months, the sheet tier ("New Tier"; blank = Untiered), deliverables.

Mapping to the TechnoDirect hierarchy
    distributor  name / code / alias match; a distributor unknown to TechnoDirect is created as bo_only
                 (state from Dist-state.xlsx, no ASM until one is assigned)
    state        the sheet's State, else the pincode's state, else the distributor's state
    region       the state's region
    ASM          the distributor's ASM today (same rule as app retailers); RSM follows from the ASM
TechnoDirect retailers are matched by phone (last 10 digits): they get `tier` (the best tier among their BO records in
the latest quarter) and `warm_match` (= known offline, which drives the Funnel's warm / cold split).

The import is a full rebuild (the sheets are the source of truth) inside one transaction.
"""
import csv
import datetime as dt
import glob
import hashlib
import logging
import os
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

from django.db import transaction

log = logging.getLogger(__name__)

FILE_GLOB = "FY??_qtr?.csv"
TIERS = ["Platinum", "Gold", "Silver", "Green", "Yellow", "Untiered"]
TIER_RANK = {t: i for i, t in enumerate(TIERS)}  # lower = better
BENEFITS = {"Catalog": "catalog", "GMB": "gmb", "Product video": "product_video", "Hyperlocal Ads": "hyperlocal_ads",
            "Shop Board": "shop_board", "SIS Unit": "sis_unit", "Carry Bags": "carry_bags",
            "Influencer": "influencer", "Certificate": "certificate"}
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
           "nov": 11, "dec": 12}
_MONTH_COL = re.compile(r"^(Jan|Feb|Mar|Apr|May|June?|July?|Aug|Sept?|Oct|Nov|Dec)_(\d{2})$", re.I)
# spellings seen in the sheets / Dist-state.xlsx that the state-name table does not know
STATE_ALIASES = {"up": "UP", "uk": "UK", "telengana": "TS", "maharastra": "MH", "maharstara": "MH", "andhara": "AP",
                 "delhi ncr": "DL", "bihar(patna)": "BR", "bihar (bhagalpur)": "BR", "tripura/mizoram": "TR",
                 "chattisgarh": "CG", "mp": "MP", "jammu": "JK", "orissa": "OD"}


# ----------------------------------------------------------------------------- parsing helpers
def phone10(raw):
    """Last 10 digits of a mobile number, or '' for junk (too short, not 6-9 led, 1111111111, 0123456789...)."""
    s = str(raw or "").strip()
    if re.fullmatch(r"\d+\.0+", s):  # numbers saved as floats by a spreadsheet: 9876543210.0
        s = s.split(".")[0]
    d = re.sub(r"\D", "", s)[-10:]
    if len(d) != 10 or d[0] not in "6789" or len(set(d)) < 4:
        return ""
    return d


def money(raw):
    try:
        return Decimal(str(raw).replace(",", "").strip() or "0").quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def quarter_of_file(path):
    """'FY27_qtr2.csv' -> (date(2026, 7, 1), 'Q2 FY27'). FY27 = Apr 2026 - Mar 2027."""
    m = re.search(r"FY(\d{2})_qtr([1-4])", os.path.basename(path), re.I)
    if not m:
        return None, None
    fy, q = int(m.group(1)), int(m.group(2))
    start_month = {1: 4, 2: 7, 3: 10, 4: 1}[q]
    year = 2000 + fy - (0 if q == 4 else 1)
    return dt.date(year, start_month, 1), f"Q{q} FY{fy:02d}"


def month_of_column(col):
    m = _MONTH_COL.match(col.strip())
    if not m:
        return None
    return dt.date(2000 + int(m.group(2)), _MONTHS[m.group(1)[:3].lower()], 1)


def clean_tier(raw):
    t = (raw or "").strip().title()
    return t if t in TIER_RANK else "Untiered"


def source_files(folder):
    return sorted(glob.glob(os.path.join(folder, FILE_GLOB)), key=lambda p: quarter_of_file(p)[0] or dt.date.min)


def files_signature(folder):
    h = hashlib.sha1()
    for p in source_files(folder):
        st = os.stat(p)
        h.update(f"{os.path.basename(p)}|{st.st_size}|{int(st.st_mtime)}".encode())
    return h.hexdigest()


# ----------------------------------------------------------------------------- reference data
class Geo:
    def __init__(self):
        from warehouse import geo
        from warehouse.models import State

        self.geo = geo
        self.by_code = {s.code: s for s in State.objects.all()}

    def state(self, name="", pincode=""):
        key = re.sub(r"\s+", " ", (name or "").strip().lower())
        code = STATE_ALIASES.get(key) or self.geo.state_code_for_name(key) if key else None
        if not code and pincode:
            pin = re.sub(r"\D", "", str(pincode))[:6]
            code = self.geo.state_code_for_pincode(pin)
        return self.by_code.get(code) if code else None


class Distributors:
    """BlueOrigin distributor names -> TechnoDirect distributors (creates bo_only ones for unknown names)."""

    def __init__(self, folder, geo):
        from ingestion.csv_import import norm
        from warehouse.models import Distributor

        self.norm, self.geo = norm, geo
        self.index = {}
        for d in Distributor.objects.all():
            for x in [d.name, d.code, *(d.aliases or [])]:
                if x:
                    self.index.setdefault(norm(x), d)
        self.home_state = self._dist_states(folder)
        self.created = []

    def _dist_states(self, folder):
        path = os.path.join(folder, "Dist-state.xlsx")
        out = {}
        if not os.path.exists(path):
            return out
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for row in list(wb.worksheets[0].iter_rows(values_only=True))[1:]:
            if row and row[0]:
                out[self.norm(str(row[0]))] = self.geo.state(str(row[1] or ""))
        wb.close()
        return out

    def resolve(self, name, row_states):
        """Distributor for a sheet name; row_states = Counter of states seen on its rows (fallback home state)."""
        from ingestion.csv_import import nice_name
        from warehouse.models import Distributor

        n = self.norm(name)
        if not n:
            return None
        d = self.index.get(n)
        if d:
            return d
        st = self.home_state.get(n) or (row_states.most_common(1)[0][0] if row_states else None)
        base = re.sub(r"[^A-Z0-9]", "", name.upper())[:10] or "BO"
        code, i = base, 1
        while Distributor.objects.filter(code=code).exists():
            i += 1
            code = f"{base[:8]}{i:02d}"
        d = Distributor.objects.create(
            code=code, name=nice_name(name)[:200], source_id=f"bo:{n}"[:64], state=st,
            region=st.region if st else None, bo_only=True, is_active=True, aliases=[name])
        self.index[n] = d
        self.created.append(d.name)
        return d


# ----------------------------------------------------------------------------- import
def read_files(folder):
    """[(quarter_start, label, path, rows)] - raises with the file name when a file cannot be read."""
    out = []
    for p in source_files(folder):
        q, label = quarter_of_file(p)
        try:
            with open(p, encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
        except OSError as exc:  # e.g. a Dropbox online-only file that could not be downloaded
            raise RuntimeError(f"Cannot read {os.path.basename(p)}: {exc}") from exc
        out.append((q, label, p, rows))
    return out


def import_folder(folder):
    """Full rebuild of the BlueOrigin tables from the folder. Returns a reconciliation report."""
    from analytics.cache import bump_cache_version
    from warehouse.models import BoRetailer, BoRetailerMonth, BoRetailerQuarter

    files = read_files(folder)
    if not files:
        raise RuntimeError(f"No {FILE_GLOB} files in {folder}")
    geo = Geo()
    report = {"folder": folder, "files": [], "tiers": {}, "month_totals": {}}

    # pass 1: states seen per distributor (home state for distributors unknown to TechnoDirect)
    dist_states = defaultdict(Counter)
    for _, _, _, rows in files:
        for r in rows:
            st = geo.state(r.get("State", ""), r.get("Pincode", ""))
            if st:
                dist_states[r.get("Distributor", "").strip()][st] += 1

    with transaction.atomic():
        dists = Distributors(folder, geo)
        dist_of = {name: dists.resolve(name, cnt) for name, cnt in dist_states.items()}
        master, quarters, months = {}, [], defaultdict(Decimal)
        for q, label, path, rows in files:
            mcols = [(c, month_of_column(c)) for c in (rows[0].keys() if rows else []) if month_of_column(c)]
            tiers = Counter()
            for r in rows:
                bo_id = (r.get("Retailer_ID") or "").strip()
                dname = (r.get("Distributor") or "").strip()
                if not bo_id:
                    continue
                d = dist_of.get(dname) or dists.resolve(dname, Counter())
                st = geo.state(r.get("State", ""), r.get("Pincode", "")) or (d.state if d else None)
                tier = clean_tier(r.get("New Tier"))
                tiers[tier] += 1
                vals = {m: money(r.get(c)) for c, m in mcols}
                purchase = money(r.get("Last 3 Months")) if (r.get("Last 3 Months") or "").strip() else sum(
                    vals.values(), Decimal("0"))
                for m, v in vals.items():
                    months[(bo_id, m)] += v
                quarters.append({"bo_id": bo_id, "quarter": q, "label": label, "purchase": purchase, "tier": tier,
                                 "old_tier": (r.get("Old Tier") or "").strip().title()[:16],
                                 "deliverables": (r.get("Deliverables") or "").strip().lower()[:16],
                                 "benefits": {k: (r.get(c) or "").strip().lower() for c, k in BENEFITS.items()
                                              if (r.get(c) or "").strip()},
                                 "d": d, "st": st})
                # the latest quarter's row describes the retailer
                master[bo_id] = {"name": (r.get("Retailer Name") or bo_id).strip()[:200], "d": d, "st": st,
                                 "district": (r.get("District") or r.get("City") or "").strip()[:100],
                                 "pincode": re.sub(r"\D", "", str(r.get("Pincode") or ""))[:6],
                                 "phone": phone10(r.get("Phone") or r.get("Phone_Raw")),
                                 "phone_alt": phone10(r.get("Phone_Alt")), "tier": tier, "tier_quarter": q,
                                 "first": master.get(bo_id, {}).get("first") or q, "last": q}
            report["files"].append({"file": os.path.basename(path), "quarter": label, "rows": len(rows),
                                    "months": [m.isoformat()[:7] for _, m in mcols]})
            report["tiers"][label] = dict(tiers)

        BoRetailerMonth.objects.all().delete()
        BoRetailerQuarter.objects.all().delete()
        BoRetailer.objects.all().delete()

        def geo_ids(d, st):
            return {"distributor_id": d.id if d else None, "state_id": st.id if st else None,
                    "region_id": (st.region_id if st else None) or (d.region_id if d else None),
                    "asm_id": d.asm_id if d else None}

        BoRetailer.objects.bulk_create([
            BoRetailer(bo_id=k, name=m["name"], district=m["district"], pincode=m["pincode"], phone=m["phone"],
                       phone_alt=m["phone_alt"], tier=m["tier"], tier_quarter=m["tier_quarter"],
                       first_quarter=m["first"], last_quarter=m["last"], **geo_ids(m["d"], m["st"]))
            for k, m in master.items()], batch_size=2000)
        ids = dict(BoRetailer.objects.values_list("bo_id", "id"))
        BoRetailerQuarter.objects.bulk_create([
            BoRetailerQuarter(bo_retailer_id=ids[x["bo_id"]], quarter=x["quarter"], label=x["label"],
                              purchase=x["purchase"], tier=x["tier"], old_tier=x["old_tier"],
                              deliverables=x["deliverables"], benefits=x["benefits"], **geo_ids(x["d"], x["st"]))
            for x in quarters], batch_size=2000)
        mrows = []
        for (bo_id, m), v in months.items():
            report["month_totals"][m.isoformat()[:7]] = report["month_totals"].get(m.isoformat()[:7], 0) + float(v)
            if v:
                mm = master[bo_id]
                mrows.append(BoRetailerMonth(bo_retailer_id=ids[bo_id], month=m, value=v, **geo_ids(mm["d"], mm["st"])))
        BoRetailerMonth.objects.bulk_create(mrows, batch_size=2000)
        report.update(retailers=len(master), quarter_rows=len(quarters), month_rows=len(mrows),
                      distributors_created=dists.created,
                      distributors_matched=sorted({d.name for d in dist_of.values() if d and not d.bo_only}))
        report["td_match"] = tag_td_retailers()
    bump_cache_version()
    return report


# ----------------------------------------------------------------------------- TechnoDirect link
def tag_td_retailers():
    """Phone-match BO retailers to app retailers; set Retailer.tier / warm_match and BoRetailer.td_retailer."""
    from django.db.models import Max

    from warehouse.models import BoRetailer, BoRetailerQuarter, Retailer

    latest = BoRetailerQuarter.objects.aggregate(q=Max("quarter"))["q"]
    td_by_phone = defaultdict(list)
    for rid, ph, orders in Retailer.objects.exclude(phone="").values_list("id", "phone", "orders_count"):
        p = phone10(ph)
        if p:
            td_by_phone[p].append((orders or 0, -rid))
    latest_tier = dict(BoRetailerQuarter.objects.filter(quarter=latest).values_list("bo_retailer_id", "tier"))
    link, warm, best = {}, set(), {}
    for bid, ph, alt in BoRetailer.objects.values_list("id", "phone", "phone_alt"):
        cands = td_by_phone.get(ph, []) + td_by_phone.get(alt, [])
        if not cands:
            continue
        rid = -max(cands)[1]  # the app account with most orders (oldest on ties) represents the shop
        link[bid] = rid
        warm.update(-c[1] for c in cands)
        t = latest_tier.get(bid)  # not in the latest quarter's sheet = no current tier
        if t and TIER_RANK[t] < TIER_RANK.get(best.get(rid, "Untiered"), 99):
            best[rid] = t
        best.setdefault(rid, t or "Untiered")  # known offline but not in the latest sheet

    def chunks(xs, n=800):
        xs = list(xs)
        for i in range(0, len(xs), n):
            yield xs[i:i + n]

    with transaction.atomic():
        BoRetailer.objects.exclude(td_retailer=None).update(td_retailer=None)
        by_rid = defaultdict(list)
        for bid, rid in link.items():
            by_rid[rid].append(bid)
        for part in chunks(by_rid.items(), 500):
            for rid, bids in part:
                BoRetailer.objects.filter(id__in=bids).update(td_retailer_id=rid)
        Retailer.objects.exclude(warm_match=False, tier="").update(warm_match=False, tier="")
        for part in chunks(warm):
            Retailer.objects.filter(id__in=part).update(warm_match=True)
        by_tier = defaultdict(list)
        for rid, t in best.items():
            by_tier[t].append(rid)
        for t, rids in by_tier.items():
            for part in chunks(rids):
                Retailer.objects.filter(id__in=part).update(tier=t)
    buyers = Retailer.objects.filter(orders_count__gt=0)
    return {"bo_linked": len(link), "td_warm": len(warm),
            "td_buyers_matched": buyers.filter(warm_match=True).count(), "td_buyers": buyers.count(),
            "td_never_ordered_matched": Retailer.objects.filter(orders_count=0, warm_match=True).count(),
            "latest_quarter": latest.isoformat() if latest else None}


def sync_bo_asms():
    """BO rows follow their distributor's ASM today (handovers included). Returns rows changed."""
    from django.db.models import F, OuterRef, Subquery

    from warehouse.models import BoRetailer, BoRetailerMonth, BoRetailerQuarter, Distributor

    n = 0
    for model in (BoRetailer, BoRetailerQuarter, BoRetailerMonth):
        stale = (model.objects.filter(distributor__isnull=False).exclude(asm_id=F("distributor__asm_id"))
                 .exclude(asm__isnull=True, distributor__asm__isnull=True))
        n += stale.update(asm_id=Subquery(Distributor.objects.filter(id=OuterRef("distributor_id")).values("asm_id")[:1]))
    return n


def refresh_if_changed(folder=None, triggered_by="schedule"):
    """Scheduled refresh step: re-import when the sheet files changed. Returns a step dict for refresh_all."""
    from django.conf import settings
    from django.utils import timezone

    from ingestion.models import SyncRun, SyncWatermark

    from masters import dropbox_bo

    via = "folder"
    if not folder and dropbox_bo.configured():
        via = "dropbox"
        # live from Dropbox: refresh the local mirror first (only changed files are downloaded)
        try:
            folder = dropbox_bo.mirror()["folder"]
        except Exception as exc:  # noqa: BLE001 - the previous import stays on the dashboard
            log.warning("BlueOrigin Dropbox download failed: %s", exc)
            run = SyncRun.objects.create(source="blueorigin", status="failed", triggered_by=triggered_by,
                                         error=str(exc)[:4000], finished_at=timezone.now())
            return {"source": "blueorigin", "status": "failed", "rows": 0, "run_id": run.pk}
    folder = folder or getattr(settings, "BLUEORIGIN_DIR", "")
    if not folder or not os.path.isdir(folder):
        return {"source": "blueorigin", "status": "not_configured", "rows": 0, "run_id": None}
    sig = files_signature(folder)
    wm = SyncWatermark.objects.filter(key="blueorigin:files").first()
    if wm and wm.cursor == sig:
        return {"source": "blueorigin", "status": "skipped", "rows": 0, "run_id": None}
    run = SyncRun.objects.create(source="blueorigin", status="running", triggered_by=triggered_by)
    try:
        rep = import_folder(folder)
        run.status, run.rows = "success", rep["quarter_rows"]
        run.details = {k: rep[k] for k in ("retailers", "quarter_rows", "month_rows", "distributors_created",
                                           "td_match", "tiers")}
        run.details["via"] = via
        SyncWatermark.put("blueorigin:files", timezone.now(), cursor=sig)
    except Exception as exc:  # noqa: BLE001
        log.exception("BlueOrigin import failed")
        run.status, run.error = "failed", str(exc)[:4000]
    run.finished_at = timezone.now()
    run.save()
    return {"source": "blueorigin", "status": run.status, "rows": run.rows, "run_id": run.pk}
