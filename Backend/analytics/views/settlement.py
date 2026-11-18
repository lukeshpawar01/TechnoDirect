"""Distributor settlement endpoints: summary, per-distributor statement and the order list (see analytics/settlement.py)."""
from django.db.models import Q
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from accounts.permissions import HasPerm

from .. import settlement as st
from ..export import ExportListMixin
from ..filters import parse_filters
from .base import AnalyticsView


class SettlementSummaryView(AnalyticsView):
    permission_code = "view_settlements"
    sources = ["settlement"]
    export_key = "payouts"

    def compute(self, f, request, **kw):
        return st.summary(f)


class SettlementDistributorsView(AnalyticsView):
    permission_code = "view_settlements"
    sources = ["settlement"]
    export_key = "rows"

    def compute(self, f, request, **kw):
        return st.by_distributor(f)


class SettlementDistributorDetailView(AnalyticsView):
    permission_code = "view_settlements"
    sources = ["settlement"]
    export_key = "open_orders"

    def compute(self, f, request, pk=None, **kw):
        return st.distributor_statement(f, pk)


ORDERING = {"order_date": "order_date", "payable": "payable", "order_value": "order_value",
            "settled_on": "settled_on", "delivered_date": "delivered_date", "distributor": "distributor__name",
            "order_ref": "order_ref", "customer_refund": "customer_refund"}


class SettlementOrderListView(ExportListMixin, generics.ListAPIView):
    """Order-level settlement rows with status, payout date and amounts."""

    permission_classes = [IsAuthenticated, HasPerm("view_settlements")]
    export_filename = "distributor_settlements"

    def get_queryset(self):
        f = parse_filters(self.request)
        self._today = f.today
        q = self.request.query_params
        qs = st.base_qs(f)
        if q.get("search"):
            s = q["search"].strip().lstrip("#")
            qs = qs.filter(Q(order_ref__icontains=s) | Q(customer__icontains=s) | Q(transaction_id__icontains=s))
        view = q.get("view") or ""
        if view == "due":
            qs = qs.filter(fulfilment="delivered").exclude(settlement_status__in=["settled", "cancelled"]).exclude(
                payment_status="cancelled")
        elif view == "overdue":
            import datetime as dt

            qs = qs.filter(fulfilment="delivered", delivered_date__lt=f.today - dt.timedelta(days=st.SLA_DAYS)).exclude(
                settlement_status__in=["settled", "cancelled"]).exclude(payment_status="cancelled")
        elif view == "issues":
            qs = qs.exclude(issues=[])
        key = (q.get("ordering") or "-order_date").strip()
        field = ORDERING.get(key.lstrip("-"), "order_date")
        desc = key.startswith("-") if key.lstrip("-") in ORDERING else True
        if view == "split":
            qs = qs.filter(multi_distributor=True)
        return qs.select_related("distributor", "asm", "order").order_by(("-" if desc else "") + field, "order_ref")

    def get_serializer(self, *args, **kwargs):
        return _Rows(*args, today=getattr(self, "_today", None), **kwargs)


class _Rows:
    def __init__(self, instance, many=False, today=None, **kw):
        items = list(instance if many else [instance])
        groups = {r.order.split_group for r in items if r.multi_distributor and r.order_id}
        parts = st.cart_parts(groups)
        out = []
        for r in items:
            b, age = st.bucket({"settlement_status": r.settlement_status, "payment_status": r.payment_status,
                                "fulfilment": r.fulfilment, "delivered_date": r.delivered_date}, today)
            out.append({
                "id": r.id, "order_ref": r.order_ref, "order_id": r.order_id, "order_date": r.order_date,
                "delivered_date": r.delivered_date, "fulfilment": r.fulfilment, "customer": r.customer,
                "destination": r.destination,
                "distributor": r.distributor.name if r.distributor_id else r.sheet_distributor,
                "distributor_id": r.distributor_id, "asm": r.asm.name if r.asm_id else None,
                "order_value": float(r.order_value), "customer_refund": float(r.customer_refund),
                "loyalty_points": float(r.loyalty_points), "payable": float(r.payable),
                "payment_mode": r.payment_mode, "transaction_id": r.transaction_id,
                "payment_status": r.payment_status, "settlement_status": r.settlement_status,
                "settled_on": r.settled_on,
                "days_to_settle": (r.settled_on - r.delivered_date).days if r.settled_on and r.delivered_date else None,
                "state": b, "days_since_delivery": age, "overdue": b == "due" and age is not None and age > st.SLA_DAYS,
                "remark": r.remark, "issues": r.issues,
                "is_split": r.multi_distributor,
                "split_with": [{"order_ref": p["order_ref"], "order_id": p["order_id"], "distributor": p["distributor__name"],
                                "distributor_id": p["distributor_id"], "payable": float(p["payable"]),
                                "settlement_status": p["settlement_status"]}
                               for p in parts.get(r.order.split_group if r.order_id else None, [])
                               if p["order_ref"] != r.order_ref],
            })
        self.data = out if many else (out[0] if out else {})
