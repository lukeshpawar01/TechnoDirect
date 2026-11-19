"""Distributor settlement: import of the finance team's 'Technodirect Order Tracking - Tracker' sheet.

One row per app order:
- order and delivery dates, and the payment status (Approved / Not Approved / Cancelled);
- the settlement status (Settled / Not Settled / Cancelled; blank = not yet reviewed);
- the distributor payout date ("Distributor Settlement Date") and the amounts.

Amounts, as checked on 2026-11-18:
- Distributor Settlement = ORDER VALUE - Customer Refund. This holds exactly on 6,819 of 6,824 readable rows.
- Loyalty points are not deducted: TechnoSport carries them.
- Customer Settlement is what PayU paid TechnoSport after gateway charges, so the PG charge = PayU value - Customer
  Settlement.

Payee:
- The payee is the distributor named in the sheet. Each sheet name is mapped to the app distributor most of its
  orders belong to, ignoring the Techno Sportswear fallback, and the name is saved as an alias.
- About 50 orders were reassigned. They are paid to the sheet's distributor and flagged.

The import is a full rebuild in one transaction, because the sheet is the source of truth for settlement.
"""
import csv
import datetime as dt
import hashlib
import logging
import os
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

from django.db import transaction

log = logging.getLogger(__name__)

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
FULFILMENT = {"DELIVERED": "delivered", "IN TRANSIT": "in_transit", "NOT DISPATCHED": "not_dispatched",
              "CANCELLED": "cancelled"}
PAYMENT = {"approved": "approved", "not approved": "not_approved", "cancelled": "cancelled"}
SETTLEMENT = {"settled": "settled", "not settled": "not_settled", "cancelled": "cancelled"}
FALLBACK_DISTRIBUTOR = "techno sportswear"  # app orders without a real distributor sit on the company


def _month(tok):
    return MONTHS.get(tok[:3]) if len(tok) >= 3 else None


def parse_date(raw):
    """Latest date in a free-text cell. It handles these forms:
    - "Sunday, February 01, 2026"
    - "18 Sept 2026"
    - "Oct 8,2026"
    - "23-July-2026" and "15Jun-2026"
    - "May 30.2026"
    - "4/24/2026"
    - ranges such as "june 12,2026 - june 13,2026", where the latest date wins.
    """
    s = (raw or "").strip().lower()
    if not s or not re.search(r"\d{4}", s):
        return None
    found = []
    for m, d, y in re.findall(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", s):
        found.append((int(y), int(m), int(d)))
    s2 = re.sub(r"\b\d{1,2}/\d{1,2}/\d{4}\b", " ", s)
    s2 = re.sub(r"([a-z])(\d)|(\d)([a-z])", lambda x: f"{x[1] or x[3]} {x[2] or x[4]}", s2)  # 15Jun -> 15 Jun
    s2 = re.sub(r"[-_.,/]", " ", s2)
    toks = s2.split()
    for i, t in enumerate(toks):
        if not re.fullmatch(r"\d{4}", t):
            continue
        y = int(t)
        a, b = (toks[i - 2] if i >= 2 else ""), (toks[i - 1] if i >= 1 else "")
        if b.isdigit() and _month(a):  # Feb 01 2026
            found.append((y, _month(a), int(b)))
        elif a.isdigit() and _month(b):  # 18 Sept 2026
            found.append((y, _month(b), int(a)))
    out = []
    for y, m, d in found:
        try:
            out.append(dt.date(y, m, d))
        except ValueError:
            pass
    return max(out) if out else None


def parse_money(raw, multi=False):
    """Rupee amount. multi=True sums cells like '₹150 & ₹4769' or '310, 132'. Returns None when unreadable."""
    s = (raw or "").replace("₹", "").strip()
    if not s:
        return Decimal(0)
    parts = re.split(r"\s*&\s*|,\s+", s) if multi else [s]
    total = Decimal(0)
    for p in parts:
        p = p.replace(",", "").strip()
        neg = p.startswith("(") or p.startswith("-")
        p = p.strip("()-").strip().rstrip(".")  # "₹1,915." (trailing dot)
        if not re.fullmatch(r"\d+(\.\d+)?", p):
            return None
        try:
            v = Decimal(p)
        except InvalidOperation:
            return None
        total += -v if neg else v
    return total


def file_signature(path):
    st = os.stat(path)
    return hashlib.sha1(f"{os.path.basename(path)}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()


def normalize_rows(rows):
    # headers carry stray spaces (" Distributor") and a typo ("Distributor Settlememnt")
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in rows]


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return normalize_rows(list(csv.DictReader(fh)))


def _payees(rows, orders):
    """Sheet distributor name -> Distributor (alias, then majority of its app orders)."""
    from ingestion.normalize import norm
    from warehouse.models import Distributor

    index = {}
    for d in Distributor.objects.all():
        for x in [d.name, d.code, *(d.aliases or [])]:
            if x:
                index.setdefault(norm(x), d)
    votes = defaultdict(Counter)
    for r in rows:
        o = orders.get(r["order id"].lstrip("#"))
        if o and o.distributor_id and FALLBACK_DISTRIBUTOR not in o.distributor.name.lower():
            votes[r["distributor"]][o.distributor_id] += 1
    by_id = {d.id: d for d in Distributor.objects.all()}
    out, aliased, unknown = {}, [], []
    for name in {r["distributor"] for r in rows if r["distributor"]}:
        d = index.get(norm(name))
        if d is None and votes[name]:
            d = by_id[votes[name].most_common(1)[0][0]]
            if name not in (d.aliases or []):
                d.aliases = [*(d.aliases or []), name]
                d.save(update_fields=["aliases"])
                aliased.append(f"{name} -> {d.name}")
        if d is None:
            unknown.append(name)
        out[name] = d
    return out, aliased, unknown


def import_file(path):
    """Full rebuild of DistributorSettlement from the tracker CSV. Returns a reconciliation report."""
    return import_rows(read_rows(path))


def import_rows(rows):
    """Full rebuild of DistributorSettlement from the tracker rows (normalised headers): the live Google Sheet or the
    CSV export. Returns a reconciliation report."""
    from analytics.cache import bump_cache_version
    from warehouse.models import DistributorSettlement, Order

    rows = [r for r in rows if r.get("order id")]
    refs = [r["order id"].lstrip("#") for r in rows]
    orders = {}
    for o in Order.objects.filter(display_id__in=refs).select_related("distributor"):
        orders.setdefault(o.display_id, o)
    payees, aliased, unknown = _payees(rows, orders)

    objs, seen, issues = [], set(), Counter()
    for r in rows:
        ref = r["order id"].lstrip("#")
        if ref in seen:
            issues["duplicate order id (later row skipped)"] += 1
            continue
        seen.add(ref)
        o = orders.get(ref)
        d = payees.get(r["distributor"])
        notes = []
        order_date = parse_date(r["order date"]) or (o.placed_date if o else None)
        if order_date is None:
            issues["no order date (row skipped)"] += 1
            continue
        ov = parse_money(r["order value"]) or Decimal(0)
        refund = parse_money(r["customer refund"], multi=True)
        if refund is None:
            notes.append("refund unreadable")
            refund = Decimal(0)
        raw_pay = r.get("distributor settlememnt", r.get("distributor settlement", ""))
        payable = parse_money(raw_pay)
        cancelled = r["status"].upper() == "CANCELLED" or r["settlement status"].lower() == "cancelled"
        derived = False
        if payable is None or not raw_pay:
            if payable is None:
                notes.append("payable unreadable: order value - refund used")
            derived, payable = True, (Decimal(0) if cancelled else ov - refund)
        elif abs(payable - (ov - refund)) >= 1:
            notes.append("payable differs from order value - refund")
        pay = PAYMENT.get(r["payment status"].lower(), "pending")
        st = SETTLEMENT.get(r["settlement status"].lower(), "pending")
        settled_on = parse_date(r["distributor settlement date"])
        if r["distributor settlement date"] and settled_on is None and r["distributor settlement date"] != ".":
            notes.append("payout date unreadable")
        if st == "settled" and not settled_on:
            notes.append("settled without a payout date")
        if st != "settled" and settled_on:
            notes.append(f"{st.replace('_', ' ')} but has a payout date")
        if o and d and o.distributor_id and o.distributor_id != d.id and FALLBACK_DISTRIBUTOR not in o.distributor.name.lower():
            notes.append(f"reassigned: app order is on {o.distributor.name}")
        if o is None:
            notes.append("order not found in app data")
        pg = parse_money(r["customer settlement"]) if r["customer settlement"] else None
        for n in notes:
            issues[re.sub(r": app order is on .*", "", n)] += 1
        objs.append(DistributorSettlement(
            order_ref=ref, order=o, sheet_distributor=r["distributor"][:200], distributor=d,
            region_id=(d.region_id if d else None) or (o.region_id if o else None),
            state_id=(o.state_id if o else None) or (d.state_id if d else None),
            asm_id=(d.asm_id if d else None) or (o.asm_id if o else None),
            customer=r["customer name"][:200],
            destination=", ".join(x for x in (r["destination place"].title(), r["destination state"]) if x)[:200],
            order_date=order_date, dispatch_date=parse_date(r["dispatch date"]),
            delivered_date=parse_date(r["delivered date"]),
            fulfilment=FULFILMENT.get(r["status"].upper(), r["status"].lower()[:16]),
            multi_distributor=r["multi distributor order"].lower() == "yes",
            courier_charge=parse_money(r["multi dist.courier amt"]) or 0,
            order_value=ov, payu_value=parse_money(r["check value from payu"]) or 0,
            customer_refund=refund, refund_date=parse_date(r["refund date"]),
            pg_settlement=pg, pg_settlement_date=parse_date(r["settlement date"]),
            loyalty_points=parse_money(r["loyalty points"]) or 0,
            payable=payable, payable_derived=derived,
            payment_mode=r["payment mode"].upper()[:16], transaction_id=r["transaction id"][:64],
            payment_status=pay, settlement_status=st, settled_on=settled_on,
            remark=r["remark"][:255], issues=notes,
        ))
    with transaction.atomic():
        DistributorSettlement.objects.all().delete()
        DistributorSettlement.objects.bulk_create(objs, batch_size=1000)
    from masters.splits import mark_split_carts

    split = mark_split_carts()  # the tracker's "Multi Distributor Order" flags decide split carts
    bump_cache_version()
    status = Counter(o.settlement_status for o in objs)
    return {
        "rows": len(objs), "file_rows": len(rows),
        "orders_matched": sum(1 for o in objs if o.order_id), "distributors": len({o.distributor_id for o in objs}),
        "aliases_added": aliased, "unknown_distributors": unknown,
        "settlement_status": dict(status), "issues": dict(issues), "split_carts": split,
        "order_value": float(sum(o.order_value for o in objs)), "payable": float(sum(o.payable for o in objs)),
        "settled": float(sum(o.payable for o in objs if o.settlement_status == "settled")),
        "order_dates": [min(o.order_date for o in objs).isoformat(), max(o.order_date for o in objs).isoformat()]
        if objs else None,
    }


def refresh_if_changed(path=None, triggered_by="schedule", force=False):
    """Scheduled refresh step: re-import when the tracker file changed. Returns a step dict for refresh_all."""
    from django.conf import settings
    from django.utils import timezone

    from ingestion.models import SyncRun, SyncWatermark

    from ingestion import gsheets

    url = getattr(settings, "SETTLEMENT_SHEET_URL", "")
    if not path and url and gsheets.configured():
        # the live Google Sheet
        try:
            rows = normalize_rows(gsheets.read_table(url, getattr(settings, "SETTLEMENT_SHEET_TAB", "")))
        except Exception as exc:  # noqa: BLE001 - the previous import stays on the dashboard
            run = SyncRun.objects.create(source="settlement", status="failed", triggered_by=triggered_by,
                                         error=f"Google Sheet: {exc}"[:4000], finished_at=timezone.now())
            return {"source": "settlement", "status": "failed", "rows": 0, "run_id": run.pk}
        sig, via = "gs:" + gsheets.signature(rows), "google_sheet"

        def load():
            return import_rows(rows)
    elif path:
        # an explicit file (manage.py import_... --file): a one-off import
        sig, via = file_signature(path), "file"

        def load():
            return import_file(path)
    else:
        # only the live Google Sheet - set SETTLEMENT_SHEET_URL and GOOGLE_SERVICE_ACCOUNT_JSON
        return {"source": "settlement", "status": "not_configured", "rows": 0, "run_id": None}
    wm = SyncWatermark.objects.filter(key="settlement:file").first()
    if not force and wm and wm.cursor == sig:
        return {"source": "settlement", "status": "skipped", "rows": 0, "run_id": None}
    run = SyncRun.objects.create(source="settlement", status="running", triggered_by=triggered_by)
    try:
        rep = load()
        run.status, run.rows = "success", rep["rows"]
        run.details = {k: rep[k] for k in ("rows", "orders_matched", "settlement_status", "issues", "unknown_distributors")}
        run.details["via"] = via
        SyncWatermark.put("settlement:file", timezone.now(), cursor=sig)
    except Exception as exc:  # noqa: BLE001
        log.exception("Settlement import failed")
        run.status, run.error = "failed", str(exc)[:4000]
    run.finished_at = timezone.now()
    run.save()
    return {"source": "settlement", "status": run.status, "rows": run.rows, "run_id": run.pk}


def sync_settlement_asms():
    """Settlement rows follow their payee distributor's current ASM (handovers included). Returns rows changed."""
    from django.db.models import F, OuterRef, Subquery

    from warehouse.models import Distributor, DistributorSettlement

    stale = (DistributorSettlement.objects.filter(distributor__isnull=False).exclude(asm_id=F("distributor__asm_id"))
             .exclude(asm__isnull=True, distributor__asm__isnull=True))
    return stale.update(asm_id=Subquery(Distributor.objects.filter(id=OuterRef("distributor_id")).values("asm_id")[:1]))
