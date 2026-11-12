import datetime as dt
from collections import defaultdict

from django.db.models import Count, DecimalField, F, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.http import Http404
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from accounts.permissions import HasPerm
from accounts.scope import RETAILER_DIMS
from warehouse.models import Order, Retailer, RetailerMonth, State

from ..envelope import envelope
from ..export import ExportListMixin
from ..filters import add_months, month_start, parse_filters
from ..metrics import as_date, launch_month, mkey, num, pct, share
from .base import AnalyticsView


def retailer_base(f):
    return Retailer.objects.filter(f.dims_q(RETAILER_DIMS, retailer_field="id"))


def mask_phone(phone, can_see):
    if can_see or not phone:
        return phone
    p = str(phone)
    return p[:2] + "X" * max(len(p) - 4, 0) + p[-2:] if len(p) > 4 else "XXXX"


def retailer_segment(r, today):
    if not r.orders_count:
        return "never_ordered"
    days = (today - r.last_order_date).days if r.last_order_date else None
    if days is not None and days >= 90:
        return "inactive_90"
    if days is not None and days >= 60:
        return "inactive_60"
    if days is not None and days >= 30:
        return "inactive_30"
    if r.first_order_date and month_start(r.first_order_date) == month_start(today):
        return "new"
    return "one_time" if r.orders_count == 1 else "repeat"


class FunnelView(AnalyticsView):
    permission_code = "view_funnel"
    sources = ["medusa"]
    export_key = "by_state"

    def compute(self, f, request, **kw):
        p, t = f.period, f.today
        rb = retailer_base(f)
        cur_orders = f.orders(start=p.start, end=p.end)
        repeat = (f.orders(end=p.end).values("retailer_id").annotate(n=Count("split_group", distinct=True))
                  .filter(n__gte=2).count())
        agg = rb.aggregate(
            signed=Count("id", filter=Q(signed_up_at__isnull=True) | Q(signed_up_at__date__lte=p.end)),
            submitted=Count("id", filter=Q(kyc_status__in=["pending", "approved", "rejected"])),
            approved=Count("id", filter=Q(kyc_status="approved")),
            first=Count("id", filter=Q(first_order_date__lte=p.end)),
            pending=Count("id", filter=Q(kyc_status="pending")),
            rejected=Count("id", filter=Q(kyc_status="rejected")),
            never=Count("id", filter=Q(kyc_status="approved", orders_count=0)),
            never_warm=Count("id", filter=Q(kyc_status="approved", orders_count=0, warm_match=True)),
            never_flagged=Count("id", filter=Q(kyc_status="approved", orders_count=0) & (
                Q(distributor__isnull=True) | Q(state__isnull=True))),
            d30=Count("id", filter=Q(last_order_date__lte=t - dt.timedelta(days=30),
                                     last_order_date__gt=t - dt.timedelta(days=60))),
            d60=Count("id", filter=Q(last_order_date__lte=t - dt.timedelta(days=60),
                                     last_order_date__gt=t - dt.timedelta(days=90))),
            d90=Count("id", filter=Q(last_order_date__lte=t - dt.timedelta(days=90))),
        )
        active = cur_orders.values("retailer_id").distinct().count()
        stages = [
            {"key": "signed_up", "label": "Signed up", "count": agg["signed"]},
            {"key": "kyc_submitted", "label": "KYC submitted", "count": agg["submitted"]},
            {"key": "kyc_approved", "label": "KYC approved", "count": agg["approved"]},
            {"key": "first_order", "label": "Placed first order", "count": agg["first"]},
            {"key": "repeat_order", "label": "Placed repeat order", "count": repeat},
            {"key": "active_this_period", "label": f"Active ({p.label})", "count": active},
        ]

        # KYC approval month -> converted to first order
        kyc_rows = (rb.filter(kyc_status="approved", kyc_approved_at__isnull=False)
                    .annotate(m=TruncMonth("kyc_approved_at")).values("m")
                    .annotate(n=Count("id"), conv=Count("id", filter=Q(first_order_date__isnull=False)))
                    .order_by("m"))
        kyc_by_month = [{"month": mkey(r["m"]), "kyc_approved": r["n"], "converted": r["conv"],
                         "rate": share(r["conv"], r["n"])} for r in kyc_rows if as_date(r["m"]) <= p.end]

        acq = dict((as_date(r["m"]), r["n"]) for r in rb.filter(first_order_date__isnull=False).annotate(
            m=TruncMonth("first_order_date")).values("m").annotate(n=Count("id")))
        acquisition, cum = [], 0
        m = min(launch_month(), month_start(p.end))
        for k in sorted(k for k in acq if k < m):
            cum += acq[k]
        while m <= month_start(p.end):
            cum += acq.get(m, 0)
            acquisition.append({"month": mkey(m), "new_retailers": acq.get(m, 0), "cumulative": cum})
            m = add_months(m, 1)

        snames = dict(State.objects.values_list("id", "name"))
        st = {r["state_id"]: r for r in rb.values("state_id").annotate(
            kyc=Count("id", filter=Q(kyc_status="approved")),
            ever=Count("id", filter=Q(first_order_date__isnull=False, first_order_date__lte=p.end)))}
        act = dict(cur_orders.values("state_id").annotate(n=Count("retailer_id", distinct=True))
                   .values_list("state_id", "n"))
        by_state = sorted([{
            "state_id": sid, "state": snames.get(sid, "Unmapped"), "kyc_approved": r["kyc"],
            "ever_ordered": r["ever"], "active": act.get(sid, 0), "adoption_pct": pct(r["ever"], r["kyc"]),
        } for sid, r in st.items()], key=lambda x: -x["kyc_approved"])

        return {
            "stages": stages,
            "kyc_status": [{"status": "pending", "count": agg["pending"]},
                           {"status": "approved", "count": agg["approved"]},
                           {"status": "rejected", "count": agg["rejected"]}],
            "never_ordered": {"total": agg["never"], "warm": agg["never_warm"],
                              "cold": agg["never"] - agg["never_warm"], "flagged": agg["never_flagged"]},
            "inactivity": {"d30": agg["d30"], "d60": agg["d60"], "d90": agg["d90"]},
            "kyc_to_first_order_by_month": kyc_by_month,
            "acquisition_monthly": acquisition,
            "by_state": by_state,
        }


# ----------------------------------------------------------------------------- retailers list
# API field -> queryset expression (prefix with '-' for descending)
RETAILER_ORDER_FIELDS = {
    "sales": "period_sales", "orders": "period_orders", "name": "name", "last_order_date": "last_order_date",
    "first_order_date": "first_order_date", "lifetime_sales": "total_sales", "lifetime_orders": "orders_count",
    "state": "state__name", "distributor": "distributor__name", "asm": "asm__name", "kyc_status": "kyc_status",
    "warm_match": "warm_match", "id": "id",
    # more days since last order == older last_order_date
    "days_since_last_order": "-last_order_date",
}


def resolve_ordering(raw, mapping, default):
    """Translate `ordering=-a,b` (API field names) into ORM order_by args."""
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        desc = part.startswith("-")
        expr = mapping.get(part.lstrip("-"))
        if not expr:
            continue
        if desc:
            expr = expr[1:] if expr.startswith("-") else f"-{expr}"
        out.append(expr)
    out = out or [default]
    # nulls always last, whichever direction
    return [F(e[1:]).desc(nulls_last=True) if e.startswith("-") else F(e).asc(nulls_last=True) for e in out]


def retailer_row(r, can_pii, today):
    return {
        "id": r.id, "name": r.name, "phone": mask_phone(r.phone, can_pii),
        "state": r.state.name if r.state_id else None,
        "distributor": r.distributor.name if r.distributor_id else None,
        "asm": r.asm.name if r.asm_id else None,
        "kyc_status": r.kyc_status,
        "first_order_date": r.first_order_date, "last_order_date": r.last_order_date,
        "days_since_last_order": (today - r.last_order_date).days if r.last_order_date else None,
        "orders": getattr(r, "period_orders", None) or 0,
        "sales": num(getattr(r, "period_sales", 0)),
        "lifetime_orders": r.orders_count, "lifetime_sales": num(r.total_sales),
        "segment": retailer_segment(r, today),
        "warm_match": r.warm_match,
    }


class RetailerListView(ExportListMixin, generics.ListAPIView):
    """Rows: orders/sales are for the selected period; lifetime_* are all-time."""

    permission_classes = [IsAuthenticated, HasPerm("view_funnel")]
    export_filename = "retailers"

    def get_queryset(self):
        f = parse_filters(self.request)
        self.filters = f
        p = f.period
        qs = retailer_base(f).select_related("state", "distributor", "asm")
        seg = f.segment_retailers()
        if seg is not None:
            qs = qs.filter(id__in=seg)
        q = self.request.query_params
        if q.get("kyc_status"):
            qs = qs.filter(kyc_status__in=q["kyc_status"].split(","))
        if q.get("warm") in ("true", "1", "false", "0"):
            qs = qs.filter(warm_match=q["warm"] in ("true", "1"))
        if q.get("search"):
            s = q["search"].strip()
            qs = qs.filter(Q(name__icontains=s) | Q(phone__icontains=s) | Q(gstin__icontains=s) |
                           Q(owner_name__icontains=s))
        period_orders = Order.objects.filter(retailer_id=OuterRef("pk"), is_qualifying=True,
                                             placed_date__gte=p.start, placed_date__lte=p.end)
        qs = qs.annotate(
            period_sales=Coalesce(Subquery(period_orders.values("retailer_id").annotate(
                s=Sum("gross_value")).values("s")[:1]), Value(0), output_field=DecimalField()),
            period_orders=Coalesce(Subquery(period_orders.values("retailer_id").annotate(
                n=Count("split_group", distinct=True)).values("n")[:1]), Value(0), output_field=IntegerField()),
        )
        return qs.order_by(*resolve_ordering(q.get("ordering"), RETAILER_ORDER_FIELDS, "-period_sales"), "id")

    def get_serializer(self, *args, **kwargs):
        return _RowSerializer(*args, request=self.request, **kwargs)


class _RowSerializer:
    """Minimal serializer shim so ListAPIView pagination + export work with dict rows."""

    def __init__(self, instance, many=False, request=None, **kw):
        can = request.user.has_code("view_pii")
        today = parse_filters(request).today
        items = instance if many else [instance]
        self.data = [retailer_row(r, can, today) for r in items]
        if not many:
            self.data = self.data[0]


class RetailerDetailView(AnalyticsView):
    permission_code = "view_funnel"
    sources = ["medusa"]
    pii_sensitive = True
    export_key = "monthly"

    def compute(self, f, request, pk=None):
        r = retailer_base(f).select_related("state", "distributor", "asm", "region").filter(pk=pk).first()
        if r is None:
            raise Http404
        can = request.user.has_code("view_pii")
        profile = retailer_row(r, can, f.today)
        profile.update({
            "owner_name": r.owner_name, "email": r.email if can else None, "gstin": r.gstin,
            "pincode": r.pincode, "city": r.city, "region": r.region.name if r.region_id else None,
            "signed_up_at": r.signed_up_at, "kyc_approved_at": r.kyc_approved_at, "tier": r.tier,
            "orders": r.orders_count, "sales": num(r.total_sales),
            "first_order_date": r.first_order_date.isoformat() if r.first_order_date else None,
            "last_order_date": r.last_order_date.isoformat() if r.last_order_date else None,
        })
        for k in ("signed_up_at", "kyc_approved_at"):
            profile[k] = profile[k].isoformat() if profile[k] else None
        months = RetailerMonth.objects.filter(retailer=r).order_by("month")
        monthly = [{"month": mkey(m.month), "sales": num(m.sales), "orders": m.orders, "status": m.status}
                   for m in months]
        recent = Order.objects.filter(retailer=r).select_related("distributor").order_by("-placed_at")[:20]
        recent_orders = [{
            "id": o.id, "display_id": o.display_id, "placed_at": o.placed_at.isoformat(),
            "distributor": o.distributor.name if o.distributor_id else None, "status": o.status,
            "payment_status": o.payment_status, "value": num(o.gross_value), "units": o.units,
        } for o in recent]
        return {"profile": profile, "monthly": monthly, "recent_orders": recent_orders}


__all__ = ["defaultdict", "envelope"]
