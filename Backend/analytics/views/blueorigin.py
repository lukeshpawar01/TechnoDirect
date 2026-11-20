"""BlueOrigin (offline) endpoints: summary, hierarchy roll-up and the retailer list (see analytics/blueorigin.py)."""
from django.db.models import DecimalField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from accounts.permissions import HasPerm
from warehouse.models import BoRetailerMonth, BoRetailerQuarter

from .. import blueorigin as bo
from ..export import ExportListMixin
from ..filters import fy_quarter_label, parse_filters
from ..metrics import num
from .base import AnalyticsView


# The BlueOrigin page shows distributor-sheet data only: app (TechnoDirect) comparisons are left out of the
# payloads and exports. App retailers still get their tier on the Retailers pages.
APP_KEYS = {"on_app", "on_app_pct", "app_buyers", "app_buyers_pct", "app_sales", "app", "td_retailer_id",
            "td_retailer", "app_orders"}


def bo_only(x):
    if isinstance(x, dict):
        return {k: bo_only(v) for k, v in x.items() if k not in APP_KEYS}
    if isinstance(x, list):
        return [bo_only(v) for v in x]
    return x


class BoSummaryView(AnalyticsView):
    permission_code = "view_blueorigin"
    export_key = "by_tier"

    def compute(self, f, request, **kw):
        return bo_only(bo.summary(f))


class BoHierarchyView(AnalyticsView):
    permission_code = "view_blueorigin"
    export_key = "rows"

    def compute(self, f, request, **kw):
        return bo_only(bo.hierarchy(f, request.query_params.get("group_by") or "asm"))


ORDERING = {"purchase": "purchase", "name": "name", "tier": "tier_rank", "distributor": "distributor__name",
            "bo_id": "bo_id"}
TIER_RANK = {t: i for i, t in enumerate(bo.TIERS)}


class BoRetailerListView(ExportListMixin, generics.ListAPIView):
    """BO retailers with purchase in the window and the tier at the window's tier quarter."""

    permission_classes = [IsAuthenticated, HasPerm("view_blueorigin")]
    export_filename = "blueorigin_retailers"

    def get_queryset(self):
        from django.db.models import Case, IntegerField, When

        f = parse_filters(self.request)
        w = bo.window(f)
        self._w = w
        q = self.request.query_params
        qs = bo.retailers_qs(f, w)
        if w is None:
            return qs.none()
        if q.get("search"):
            s = q["search"].strip()
            qs = qs.filter(Q(name__icontains=s) | Q(bo_id__icontains=s) | Q(phone__icontains=s))
        month_sum = (BoRetailerMonth.objects.filter(bo_retailer=OuterRef("pk"), month__gte=w["start"],
                                                    month__lte=w["end"]).values("bo_retailer")
                     .annotate(s=Sum("value")).values("s")[:1])
        tier_now = BoRetailerQuarter.objects.filter(bo_retailer=OuterRef("pk"), quarter=w["tier_quarter"]).values("tier")[:1]
        qs = qs.annotate(
            purchase=Coalesce(Subquery(month_sum, output_field=DecimalField()), Value(0, output_field=DecimalField())),
            tier_now=Coalesce(Subquery(tier_now), Value("Untiered")),
        ).annotate(tier_rank=Case(*[When(tier_now=t, then=Value(i)) for t, i in TIER_RANK.items()],
                                  default=Value(9), output_field=IntegerField()))
        if q.get("active") in ("1", "true"):
            qs = qs.filter(purchase__gt=0)
        key = (q.get("ordering") or "-purchase").strip()
        field = ORDERING.get(key.lstrip("-"), "purchase")
        desc = key.startswith("-") if key.lstrip("-") in ORDERING else True
        return qs.select_related("distributor", "asm__rsm", "state").order_by(
            ("-" if desc else "") + field, "bo_id")

    def get_serializer(self, *args, **kwargs):
        return _Rows(*args, request=self.request, **kwargs)


class _Rows:
    def __init__(self, instance, many=False, request=None, **kw):
        from .funnel import mask_phone

        items = list(instance if many else [instance])
        can = request.user.has_code("view_pii")
        hist = {}
        for bid, q, t in BoRetailerQuarter.objects.filter(bo_retailer_id__in=[i.id for i in items]).order_by(
                "quarter").values_list("bo_retailer_id", "quarter", "tier"):
            hist.setdefault(bid, []).append({"quarter": fy_quarter_label(q), "tier": t})
        out = []
        for r in items:
            out.append({
                "id": r.id, "bo_id": r.bo_id, "retailer": r.name, "phone": mask_phone(r.phone, can),
                "district": r.district or None, "state": r.state.name if r.state_id else None,
                "distributor": r.distributor.name if r.distributor_id else None,
                "offline_only_distributor": bool(r.distributor_id and r.distributor.bo_only),
                "asm": r.asm.name if r.asm_id else None,
                "rsm": r.asm.rsm.name if r.asm_id and r.asm.rsm_id else None,
                "tier": r.tier_now, "tier_history": hist.get(r.id, [])[-4:],
                "purchase": num(r.purchase),
            })
        self.data = out if many else (out[0] if out else {})


class BoPotentialView(AnalyticsView):
    """TD actual vs expected by BlueOrigin tier (a TD view: app sales are the point here, so not passed through
    bo_only). Visible with the Executive Overview permission."""

    permission_code = "view_overview"
    export_key = "rows"

    def compute(self, f, request, **kw):
        return bo.potential(f, request.query_params.get("group_by") or "asm")
