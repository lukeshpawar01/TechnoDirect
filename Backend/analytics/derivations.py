"""Derived tables: retailer aggregates, RetailerMonth status, data-quality issues.

Run after every refresh (ingestion.tasks.refresh_all_inline) and by seed_demo_data.
"""
import datetime as dt
import logging
import re
from collections import defaultdict

from django.db import transaction
from django.db.models import Count, Max, Min, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from ingestion.upsert import chunked
from warehouse.models import (
    DataQualityIssue,
    InventorySnapshot,
    Order,
    Payment,
    PendingOrderJob,
    Pincode,
    Retailer,
    RetailerMonth,
)

from .filters import add_months, month_start, today_ist

log = logging.getLogger(__name__)
PINCODE_RE = re.compile(r"^[1-9][0-9]{5}$")


# ----------------------------------------------------------------------------- classification
def classify_months(active_months, through):
    """Classify a retailer's months.

    active_months: iterable of month-start dates with >=1 qualifying order.
    through: last month to evaluate (month start, usually current month).
    Returns [(month, status, is_active)] where status in new|retained|reactivated|lost.
      new         = first-ever active month
      retained    = active this month and previous month
      reactivated = active this month, not previous month, not new
      lost        = active previous month, not this month (is_active False)
    """
    active = sorted(set(active_months))
    if not active:
        return []
    act = set(active)
    out = []
    cur = active[0]
    first = active[0]
    while cur <= through:
        prev = add_months(cur, -1)
        if cur in act:
            if cur == first:
                out.append((cur, "new", True))
            elif prev in act:
                out.append((cur, "retained", True))
            else:
                out.append((cur, "reactivated", True))
        elif prev in act:
            out.append((cur, "lost", False))
        cur = add_months(cur, 1)
    return out


# ----------------------------------------------------------------------------- aggregates
def refresh_retailer_aggregates():
    agg = {
        r["retailer_id"]: r
        for r in Order.objects.filter(is_qualifying=True, retailer_id__isnull=False)
        .values("retailer_id")
        .annotate(first=Min("placed_date"), last=Max("placed_date"), n=Count("split_group", distinct=True),
                  s=Sum("gross_value"))
    }
    objs = []
    for r in Retailer.objects.only("id", "first_order_date", "last_order_date", "orders_count", "total_sales"):
        a = agg.get(r.id)
        new = (a["first"], a["last"], a["n"], a["s"] or 0) if a else (None, None, 0, 0)
        if (r.first_order_date, r.last_order_date, r.orders_count, r.total_sales) != new:
            r.first_order_date, r.last_order_date, r.orders_count, r.total_sales = new
            objs.append(r)
    Retailer.objects.bulk_update(objs, ["first_order_date", "last_order_date", "orders_count", "total_sales"],
                                 batch_size=1000)
    return len(objs)


def rebuild_retailer_months(through=None):
    through = month_start(through or today_ist())
    rows = (
        Order.objects.filter(is_qualifying=True, retailer_id__isnull=False)
        .annotate(m=TruncMonth("placed_date"))
        .values("retailer_id", "m")
        .annotate(sales=Sum("gross_value"), orders=Count("split_group", distinct=True), units=Sum("units"))
    )
    per = defaultdict(dict)
    for r in rows:
        m = r["m"]
        if isinstance(m, dt.datetime):
            m = m.date()
        per[r["retailer_id"]][m] = r
    terr = {
        rid: (rg, st, asm, dist)
        for rid, rg, st, asm, dist in Retailer.objects.values_list("id", "region_id", "state_id", "asm_id",
                                                                   "distributor_id")
    }
    objs = []
    for rid, months in per.items():
        t = terr.get(rid, (None, None, None, None))
        for m, status, is_active in classify_months(months.keys(), through):
            r = months.get(m)
            objs.append(RetailerMonth(
                retailer_id=rid, month=m, status=status, is_active=is_active,
                sales=(r["sales"] or 0) if r else 0, orders=(r["orders"] or 0) if r else 0,
                units=(r["units"] or 0) if r else 0,
                region_id=t[0], state_id=t[1], asm_id=t[2], distributor_id=t[3],
            ))
    with transaction.atomic():
        RetailerMonth.objects.all().delete()
        RetailerMonth.objects.bulk_create(objs, batch_size=2000)
    return len(objs)


# ----------------------------------------------------------------------------- data quality
DQ_LABELS = {
    "missing_pincode_mapping": ("Retailer pincode not in pincode master", "medium"),
    "invalid_pincode": ("Invalid / missing retailer pincode", "medium"),
    "duplicate_retailer_phone": ("Duplicate retailers (same phone)", "low"),
    "duplicate_retailer_gst": ("Duplicate retailers (same GSTIN)", "low"),
    "order_without_distributor": ("Order not mapped to a distributor", "high"),
    "payu_success_no_order": ("PayU success with no Medusa order", "high"),
    "paid_order_no_payu": ("Medusa paid order with no PayU transaction", "medium"),
    "stale_feed": ("Data feed stale / failed", "high"),
    "paid_order_not_created": ("Payment succeeded but order not created (pending-order job)", "high"),
    "stock_above_ck": ("App stock higher than distributor billing stock (CK)", "medium"),
}


def _issue(code, object_type="", object_id="", details=None, severity=None):
    label, sev = DQ_LABELS[code]
    return DataQualityIssue(code=code, label=label, severity=severity or sev, object_type=object_type,
                            object_id=str(object_id), details=details or {})


def payu_success_no_order_qs():
    cutoff = timezone.now() - dt.timedelta(minutes=30)
    return Payment.objects.filter(status="success", split_group="", added_on__lt=cutoff)


def paid_order_no_payu_qs():
    cutoff = timezone.now() - dt.timedelta(minutes=30)
    return Order.objects.filter(
        medusa_payment_status__in=["captured", "partially_refunded", "refunded"],
        payment_status_source="medusa", placed_at__lt=cutoff,
    ).exclude(status="cancelled")


def run_data_quality_checks():
    issues = []
    pins = set(Pincode.objects.values_list("pincode", flat=True))
    for rid, pin in Retailer.objects.values_list("id", "pincode"):
        pin = (pin or "").strip()
        if not PINCODE_RE.match(pin):
            issues.append(_issue("invalid_pincode", "retailer", rid, {"pincode": pin}))
        elif pin not in pins:
            issues.append(_issue("missing_pincode_mapping", "retailer", rid, {"pincode": pin}))

    for field, code in (("phone", "duplicate_retailer_phone"), ("gstin", "duplicate_retailer_gst")):
        dups = (Retailer.objects.exclude(**{field: ""}).values(field).annotate(n=Count("id")).filter(n__gt=1))
        for d in dups:
            ids = list(Retailer.objects.filter(**{field: d[field]}).values_list("id", flat=True)[:20])
            issues.append(_issue(code, "retailer", ids[0], {field: d[field], "retailer_ids": ids, "count": d["n"]}))

    for oid, disp in Order.objects.filter(distributor__isnull=True).values_list("id", "display_id")[:5000]:
        issues.append(_issue("order_without_distributor", "order", oid, {"display_id": disp}))

    if Payment.objects.exists():  # only meaningful once PayU data flows
        for p in payu_success_no_order_qs().values("id", "source_id", "txnid", "amount", "added_on")[:5000]:
            issues.append(_issue("payu_success_no_order", "payment", p["id"], {
                "payu_txn_id": p["source_id"], "txnid": p["txnid"], "amount": float(p["amount"]),
                "added_on": timezone.localtime(p["added_on"]).isoformat(timespec="seconds")}))
        for o in paid_order_no_payu_qs().values("id", "display_id", "gross_value", "placed_at")[:5000]:
            issues.append(_issue("paid_order_no_payu", "order", o["id"], {
                "display_id": o["display_id"], "value": float(o["gross_value"]),
                "placed_at": timezone.localtime(o["placed_at"]).isoformat(timespec="seconds")}))

    # Medusa ts_pending_order_job: paid, but the order was never created and no refund started
    cutoff = timezone.now() - dt.timedelta(minutes=30)
    stuck = (PendingOrderJob.objects.filter(order_source_id="", refund_initiated_at__isnull=True,
                                            job_created_at__lt=cutoff)
             .exclude(status__in=["completed", "success", "done", "refunded", "cancelled", "canceled"]))
    for j in stuck.values("id", "source_id", "cart_id", "status", "attempt", "error", "amount",
                          "job_created_at")[:5000]:
        issues.append(_issue("paid_order_not_created", "pending_order_job", j["id"], {
            "job_id": j["source_id"], "cart_id": j["cart_id"], "status": j["status"], "attempt": j["attempt"],
            "error": j["error"], "amount": float(j["amount"]) if j["amount"] is not None else None,
            "created_at": timezone.localtime(j["job_created_at"]).isoformat(timespec="seconds")}))

    # App stock vs Channel Konnect stock (only for distributors that have both feeds)
    ck = {(d, s): q for d, s, q in InventorySnapshot.objects.filter(source="ck", is_latest=True)
          .values_list("distributor_id", "sku", "quantity")}
    if ck:
        for d, s, q in InventorySnapshot.objects.filter(source="td", is_latest=True).values_list(
                "distributor_id", "sku", "quantity"):
            if (d, s) in ck and q > ck[(d, s)]:
                issues.append(_issue("stock_above_ck", "inventory", f"{d}:{s}", {
                    "distributor_id": d, "sku": s, "app_qty": q, "ck_qty": ck[(d, s)]}))

    from .envelope import freshness
    from ingestion.connectors import CONNECTORS

    for f in freshness(list(CONNECTORS)):
        if f["status"] != "ok" and f.get("detail") != "not_configured":
            issues.append(_issue("stale_feed", "source", f["source"], f,
                                 severity="high" if f["status"] == "failed" else "medium"))

    with transaction.atomic():
        DataQualityIssue.objects.filter(resolved_at__isnull=True).delete()
        for chunk in chunked(issues, 2000):
            DataQualityIssue.objects.bulk_create(chunk)
    counts = defaultdict(int)
    for i in issues:
        counts[i.code] += 1
    return dict(counts)


def run_all_derivations():
    from .cache import bump_cache_version

    from ingestion.payments_link import reconcile_payments

    details = {
        "payments_reconciled": reconcile_payments(),
        "retailers_updated": refresh_retailer_aggregates(),
        "retailer_months": rebuild_retailer_months(),
        "dq_issues": run_data_quality_checks(),
    }
    bump_cache_version()
    return details
