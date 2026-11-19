import datetime as dt
from collections import defaultdict

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.utils import timezone
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasPerm
from accounts.scope import CRM_DIMS, LINE_DIMS
from warehouse.models import CrmTicket, Order, Payment, Retailer

from ..export import ExportListMixin
from ..filters import add_months, parse_filters
from ..metrics import as_date, median, mkey, num, pct, spark_months
from ..envelope import envelope
from .base import AnalyticsView
from .funnel import resolve_ordering
from .overview import OPEN_STATUSES, open_orders, open_sla_breaches, stale_open_orders

# the last bucket ends at the open window (ORDER_OPEN_WINDOW_DAYS): older "open" orders are stale TD statuses
AGE_BUCKETS = [("0-1d", 0, 24), ("1-2d", 24, 48), ("2-4d", 48, 96), ("4-7d", 96, 168), ("7d+", 168, None)]


def day_bounds(start, end):
    s = timezone.make_aware(dt.datetime.combine(start, dt.time.min))
    e = timezone.make_aware(dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min))
    return s, e


def payments_qs(f, start, end):
    s, e = day_bounds(start, end)
    qs = Payment.objects.filter(added_on__gte=s, added_on__lt=e)
    return qs.filter(f.dims_q(LINE_DIMS, retailer_field="order__retailer_id"))


def hours(a, b):
    return round((b - a).total_seconds() / 3600, 1) if a and b else None


class OrdersSummaryView(AnalyticsView):
    permission_code = "view_orders"
    sources = ["supabase", "payu", "google_sheets"]
    export_key = "status_counts"

    def compute(self, f, request, **kw):
        p = f.period
        allq = f.orders(start=p.start, end=p.end, qualifying=False)
        # the status chart is the order-status selector, so it always shows every status (other filters still apply)
        status_counts = [{"status": r["status"], "count": r["n"], "value": num(r["v"])}
                         for r in f.orders(start=p.start, end=p.end, qualifying=False, statuses=False).values("status").annotate(n=Count("id"), v=Sum("gross_value")).order_by("status")]
        # headline counts respect the selected statuses
        picked = set(f.order_status)
        in_scope = [r for r in status_counts if not picked or r["status"] in picked]
        total_n = sum(r["count"] for r in in_scope)
        cancelled = sum(r["count"] for r in in_scope if r["status"] == "cancelled")

        now = timezone.now()
        ageing_counts = defaultdict(int)
        for st, placed in open_orders(f).values_list("status", "placed_at"):
            age_h = (now - placed).total_seconds() / 3600
            for label, lo, hi in AGE_BUCKETS:
                if age_h >= lo and (hi is None or age_h < hi):
                    ageing_counts[(label, st)] += 1
                    break
        ageing = [{"bucket": label, "status": st, "count": ageing_counts.get((label, st), 0)}
                  for label, _, _ in AGE_BUCKETS for st in OPEN_STATUSES]

        months12 = spark_months(p.end)
        tat_rows = f.orders(start=months12[0], end=p.end, qualifying=False).exclude(status="cancelled").values_list(
            "placed_date", "placed_at", "shipped_at", "delivered_at")
        disp_all, deliv_all = [], []
        disp_m, deliv_m = defaultdict(list), defaultdict(list)
        placed_n, shipped_n = defaultdict(int), defaultdict(int)
        for pd, placed, shipped, delivered in tat_rows:
            m = pd.replace(day=1)
            placed_n[m] += 1
            shipped_n[m] += 1 if shipped else 0
            dh, vh = hours(placed, shipped), hours(placed, delivered)
            if dh is not None:
                disp_m[m].append(dh)
                if p.start <= pd <= p.end:
                    disp_all.append(dh)
            if vh is not None:
                deliv_m[m].append(vh)
                if p.start <= pd <= p.end:
                    deliv_all.append(vh)
        tat = {
            "order_to_dispatch_median_h": median(disp_all),
            "order_to_delivery_median_h": median(deliv_all),
            "trend": [{"month": mkey(m), "dispatch_h": median(disp_m.get(m, [])),
                       "delivery_h": median(deliv_m.get(m, [])),
                       "dispatch_pct": pct(shipped_n[m], placed_n[m])} for m in months12],
        }

        pq = payments_qs(f, p.start, p.end)
        pa = pq.aggregate(
            success=Count("id", filter=Q(status="success")),
            failed=Count("id", filter=Q(status__in=["failure", "userCancelled"])),
            pending=Count("id", filter=Q(status="pending")),
            failed_value=Sum("amount", filter=Q(status__in=["failure", "userCancelled"])),
            paid_no_order=Count("id", filter=Q(status="success", split_group="")),
        )
        mode_mix = [{"mode": r["mode"] or "UNKNOWN", "count": r["n"], "value": num(r["v"])}
                    for r in pq.filter(status="success").values("mode").annotate(
                        n=Count("id"), v=Sum("amount")).order_by("-v")]
        payment = {"success": pa["success"], "failed": pa["failed"], "pending": pa["pending"],
                   "failed_value": num(pa["failed_value"]), "paid_no_order": pa["paid_no_order"],
                   "mode_mix": mode_mix}
        # null when PayU is not configured and no PayU data has ever been loaded
        from ingestion.connectors import PayUConnector

        if not PayUConnector().is_configured() and not Payment.objects.exists():
            payment = None

        # Payment mode / ordering platform straight from the orders (no gateway or settlement data needed)
        paid = f.orders(start=p.start, end=p.end)
        paid_total = float(paid.aggregate(v=Sum("gross_value"))["v"] or 0)

        def mix(field):
            return [{"key": r[field] or "Unknown", "orders": r["n"], "value": num(r["v"]),
                     "share": pct(float(r["v"] or 0), paid_total)}
                    for r in paid.values(field).annotate(n=Count("id"), v=Sum("gross_value")).order_by("-v")]

        carts = allq.values("split_group").annotate(n=Count("id"))
        split_carts = sum(1 for c in carts if c["n"] > 1)

        crm_qs = CrmTicket.objects.filter(f.dims_q(CRM_DIMS))
        open_t = crm_qs.exclude(status="closed")
        from ingestion.connectors.google_sheets import GoogleSheetsConnector

        lo, hi = day_bounds(p.start, p.end)
        in_period = crm_qs.filter(opened_at__gte=lo, opened_at__lt=hi)
        refunds = [t.get("refund_amount") for t in in_period.values_list("raw", flat=True)]
        crm = {
            # CRM cards are shown only once the CRM sheet is connected or tickets exist
            "connected": GoogleSheetsConnector().is_configured() or CrmTicket.objects.exists(),
            "open": open_t.count(),
            "opened_in_period": in_period.count(),
            "closed_in_period": in_period.filter(status="closed").count(),
            "refund_in_period": round(sum(float(x) for x in refunds if x), 2),
            # every issue raised in the period, by type, open and closed (the CRM sheet is mostly closed issues)
            "by_type": [{"type": r["ticket_type"], "count": r["n"], "open": r["o"]} for r in
                        in_period.values("ticket_type").annotate(n=Count("id"), o=Count("id", filter=~Q(status="closed")))
                        .order_by("-n")],
        }
        return {
            "status_counts": status_counts, "ageing": ageing, "tat": tat,
            "open_window_days": settings.ORDER_OPEN_WINDOW_DAYS,
            # older orders the TD export still shows as placed / confirmed / shipped (status never updated)
            "stale_open": stale_open_orders(f).count(),
            "cancellation_rate": pct(cancelled, total_n) or 0.0,
            "payment": payment,
            "order_payment_modes": mix("payment_mode"),
            "order_platforms": mix("platform"),
            "split_orders": {"split_carts": split_carts, "total_carts": len(carts)},
            "sla_breaches": open_sla_breaches(f).count(),
            "crm": crm,
        }


ORDER_ORDER_FIELDS = {
    "placed_at": "placed_at", "value": "gross_value", "status": "status", "payment_status": "payment_status",
    "payment_mode": "payment_mode", "units": "units", "display_id": "id", "id": "id",
    "retailer": "retailer__name", "distributor": "distributor__name", "state": "state__name",
    "is_split": "is_split", "awb": "awb",
}


def order_row(o):
    return {
        "id": o.id, "display_id": o.display_id, "placed_at": timezone.localtime(o.placed_at).isoformat(),
        "retailer": o.retailer.name if o.retailer_id else None, "retailer_id": o.retailer_id,
        "distributor": o.distributor.name if o.distributor_id else None, "distributor_id": o.distributor_id,
        "state": o.state.name if o.state_id else None,
        "status": o.status, "payment_status": o.payment_status, "payment_mode": o.payment_mode or None,
        "payu_txn_id": o.payu_txn_id or None, "value": num(o.gross_value), "units": o.units,
        "awb": o.awb or None, "dispatch_hours": hours(o.placed_at, o.shipped_at), "is_split": o.is_split,
        # calendar days (the TD export has dates only): placed -> shipped, shipped -> delivered
        "shipped_on": timezone.localtime(o.shipped_at).date().isoformat() if o.shipped_at else None,
        "delivered_on": timezone.localtime(o.delivered_at).date().isoformat() if o.delivered_at else None,
        "dispatch_days": max(0, (timezone.localtime(o.shipped_at).date() - o.placed_date).days) if o.shipped_at else None,
        "transit_days": max(0, (timezone.localtime(o.delivered_at).date() - timezone.localtime(o.shipped_at).date()).days)
        if o.shipped_at and o.delivered_at else None,
    }


class _OrderRows:
    def __init__(self, instance, many=False, **kw):
        items = instance if many else [instance]
        self.data = [order_row(o) for o in items]
        if not many:
            self.data = self.data[0]


def drill_orders(f, q):
    """Orders behind one mark of an Orders-page chart (same basis as OrdersSummaryView).

    age_bucket=0-1d|1-2d|2-4d|4-7d|7d+  open orders by time since placed (any period; placed within the open
                                          window, like the ageing heatmap)
    month=YYYY-MM                         orders placed that month, cancelled excluded (TAT trend)
    paid=1                                paid, non-cancelled orders only (payment mode / platform mix)
    mode=<payment mode | Unknown>         payment mode as shown in the mix (Unknown = blank)
    Returns None when no drill parameter is given."""
    bucket, month = q.get("age_bucket"), q.get("month")
    if bucket:
        b = next((x for x in AGE_BUCKETS if x[0] == bucket), None)
        if b is None:
            raise ValidationError({"age_bucket": f"must be one of {[x[0] for x in AGE_BUCKETS]}"})
        now = timezone.now()
        qs = open_orders(f, use_filter_statuses=True).filter(placed_at__lte=now - dt.timedelta(hours=b[1]))
        if b[2] is not None:
            qs = qs.filter(placed_at__gt=now - dt.timedelta(hours=b[2]))
        return qs
    if month:
        try:
            m0 = dt.date.fromisoformat(month + "-01")
        except ValueError:
            raise ValidationError({"month": "must be YYYY-MM"}) from None
        return f.orders(start=m0, end=add_months(m0, 1) - dt.timedelta(days=1), qualifying=False).exclude(
            status="cancelled")
    if q.get("paid") in ("1", "true") or q.get("mode"):
        qs = f.orders(start=f.period.start, end=f.period.end)
        mode = q.get("mode")
        if mode:
            qs = qs.filter(payment_mode="" if mode.lower() == "unknown" else mode)
        return qs
    return None


def drill_any(f, q):
    """The orders behind a chart mark: Orders-page charts first, then the Order flow & delays section."""
    drill = drill_orders(f, q)
    if drill is None:
        from .fulfilment import drill_flow

        drill = drill_flow(f, q)
    return drill


class OrderListView(ExportListMixin, generics.ListAPIView):
    permission_classes = [IsAuthenticated, HasPerm("view_orders")]
    export_filename = "orders"

    def get_queryset(self):
        f = parse_filters(self.request)
        q = self.request.query_params
        drill = drill_any(f, q)
        qs = (drill if drill is not None else f.orders(start=f.period.start, end=f.period.end, qualifying=False)
              ).select_related("retailer", "distributor", "state")
        if q.get("sla_breached") in ("1", "true"):
            qs = open_sla_breaches(f, use_filter_statuses=True).select_related("retailer", "distributor", "state")
        if q.get("search"):
            s = q["search"].strip()
            qs = qs.filter(Q(display_id__icontains=s) | Q(awb__icontains=s) | Q(retailer__name__icontains=s) |
                           Q(payu_txn_id=s) | Q(payment_ref=s))
        return qs.order_by(*resolve_ordering(q.get("ordering"), ORDER_ORDER_FIELDS, "-placed_at"), "-id")

    def get_serializer(self, *args, **kwargs):
        return _OrderRows(*args, **kwargs)


class OrderRetailersView(ExportListMixin, generics.ListAPIView):
    """Retailers behind a set of orders (same parameters as /orders/): one row per retailer."""

    permission_classes = [IsAuthenticated, HasPerm("view_orders")]
    export_filename = "retailers"

    def get_queryset(self):
        from django.db.models import Max

        f = parse_filters(self.request)
        q = self.request.query_params
        drill = drill_any(f, q)
        qs = drill if drill is not None else f.orders(start=f.period.start, end=f.period.end, qualifying=False)
        if q.get("sla_breached") in ("1", "true"):
            qs = open_sla_breaches(f, use_filter_statuses=True)
        if q.get("search"):
            s = q["search"].strip()
            qs = qs.filter(Q(retailer__name__icontains=s) | Q(retailer__phone__icontains=s))
        rows = (qs.filter(retailer__isnull=False).values("retailer_id")
                .annotate(orders=Count("id"), value=Sum("gross_value"), last_order=Max("placed_at")))
        order = {"orders": "orders", "value": "value", "last_order": "last_order"}
        key = (q.get("ordering") or "-value").strip()
        field = order.get(key.lstrip("-"), "value")
        return rows.order_by(("-" if key.startswith("-") or key.lstrip("-") not in order else "") + field,
                             "retailer_id")

    def get_serializer(self, *args, **kwargs):
        return _RetailerRows(*args, request=self.request, **kwargs)


class _RetailerRows:
    def __init__(self, instance, many=False, request=None, **kw):
        from .. import rfm
        from .funnel import mask_phone

        items = list(instance if many else [instance])
        rs = {r.id: r for r in Retailer.objects.filter(id__in=[i["retailer_id"] for i in items]).select_related(
            "state", "distributor", "asm")}
        can = request.user.has_code("view_pii")
        f = parse_filters(request)
        seg = rfm.snapshot(rfm.as_of_for(f))["rows"]
        out = []
        for i in items:
            r = rs.get(i["retailer_id"])
            if r is None:
                continue
            key = (seg.get(r.id) or {}).get("segment", "prospect")
            out.append({
                "id": r.id, "retailer": r.name, "phone": mask_phone(r.phone, can), "city": r.city or None,
                "state": r.state.name if r.state_id else None,
                "distributor": r.distributor.name if r.distributor_id else None,
                "asm": r.asm.name if r.asm_id else None, "rfm_segment": key, "rfm_label": rfm.label(seg.get(r.id)),
                "orders": i["orders"], "value": num(i["value"]),
                "last_order": timezone.localtime(i["last_order"]).isoformat() if i["last_order"] else None,
            })
        self.data = out if many else (out[0] if out else {})


class OrderDetailView(APIView):
    permission_classes = [IsAuthenticated, HasPerm("view_orders")]

    def get(self, request, pk):
        f = parse_filters(request)
        o = (Order.objects.filter(f.dims_q()).select_related("retailer", "distributor", "state")
             .filter(pk=pk).first())
        if o is None:
            raise Http404
        data = order_row(o)
        data.update({
            "split_group": o.split_group, "payment_ref": o.payment_ref or None,
            "payment_status_source": o.payment_status_source, "courier": o.courier or None,
            "siblings": list(Order.objects.filter(split_group=o.split_group).exclude(pk=o.pk).values(
                "id", "display_id", "distributor__name")) if o.is_split else [],
        })
        data["lines"] = [{
            "style": l.style, "name": l.product.name if l.product_id else None, "sku": l.sku, "size": l.size,
            "quantity": l.quantity, "unit_price": num(l.unit_price), "total": num(l.total),
        } for l in o.lines.select_related("product").order_by("style", "size")]
        pays = list((Payment.objects.filter(Q(order=o) | Q(split_group=o.split_group)) if o.split_group
                     else Payment.objects.filter(order=o)).distinct().order_by("added_on"))
        data["payments"] = [{
            "txn_id": p.source_id, "amount": num(p.amount), "status": p.status, "mode": p.mode or None,
            "at": timezone.localtime(p.added_on).isoformat(),
            "merchant_txnid": p.txnid, "bank": p.bank or None, "error_message": p.error_message or None,
        } for p in pays]
        dist = o.distributor.name if o.distributor_id else None
        tl = [
            (o.placed_at, "received", "Order placed" + (" (split cart)" if o.is_split else ""),
             o.retailer.name if o.retailer_id else None),
            (o.confirmed_at, "confirmed", "Confirmed by distributor", dist),
            (o.shipped_at, "shipped", f"Shipped via {o.courier} (AWB {o.awb})" if o.awb else "Shipped", dist),
            (o.delivered_at, "delivered", "Delivered", o.courier or None),
            (o.cancelled_at, "cancelled", "Order cancelled", None),
        ]
        tl += [(p.added_on, f"payment_{p.status}",
                f"PayU {p.status} ₹{num(p.amount):,.0f} via {p.mode or 'NA'}"
                + (f" – {p.error_message}" if p.error_message else ""), "PayU") for p in pays]
        data["timeline"] = [{"at": timezone.localtime(at).isoformat(), "status": st, "note": note, "actor": actor}
                            for at, st, note, actor in sorted((x for x in tl if x[0]), key=lambda x: x[0])]
        return envelope(data, f, ["supabase", "payu"])


__all__ = ["as_date"]
