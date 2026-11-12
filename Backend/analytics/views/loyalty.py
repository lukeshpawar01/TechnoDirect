from django.db.models import Count, Max, Min, Q, Sum
from django.db.models.functions import TruncMonth

from accounts.scope import ORDER_DIMS
from warehouse.models import LoyaltyEvent

from ..metrics import mkey, pct
from .base import AnalyticsView

EVENT_LABELS = dict(LoyaltyEvent.EVENT_TYPES)


def _totals(qs):
    a = qs.aggregate(
        issued=Sum("points", filter=Q(points__gt=0)), redeemed=Sum("points", filter=Q(points__lt=0)),
        events=Count("id"), members=Count("retailer_id", distinct=True),
        earners=Count("retailer_id", distinct=True, filter=Q(event_type="earned")),
        redeemers=Count("retailer_id", distinct=True, filter=Q(event_type="redeemed")),
        new_members=Count("id", filter=Q(event_type="new_customer")),
    )
    issued, redeemed = a["issued"] or 0, abs(a["redeemed"] or 0)
    return {"points_issued": issued, "points_redeemed": redeemed, "net_points": issued - redeemed,
            "redemption_rate": pct(redeemed, issued), "events": a["events"], "members": a["members"],
            "earning_retailers": a["earners"], "redeeming_retailers": a["redeemers"],
            "new_members": a["new_members"]}


class LoyaltyView(AnalyticsView):
    """Loyalty points: issued / redeemed in the period, lifetime balances, monthly trend, top members."""

    permission_code = "view_loyalty"
    sources = []
    export_key = "top_members"

    def compute(self, f, request, **kw):
        p = f.period
        base = LoyaltyEvent.objects.filter(f.dims_q(ORDER_DIMS))
        seg = f.segment_retailers()
        if seg is not None:
            base = base.filter(retailer_id__in=seg)
        period = base.filter(event_date__gte=p.start, event_date__lte=p.end)
        prev = base.filter(event_date__gte=p.cmp_start, event_date__lte=p.cmp_end) if p.cmp_start else None

        monthly = [{
            "month": mkey(r["m"]), "issued": r["issued"] or 0, "redeemed": abs(r["redeemed"] or 0),
            "earners": r["earners"], "new_members": r["new_members"],
        } for r in base.annotate(m=TruncMonth("event_date")).values("m").annotate(
            issued=Sum("points", filter=Q(points__gt=0)), redeemed=Sum("points", filter=Q(points__lt=0)),
            earners=Count("retailer_id", distinct=True, filter=Q(event_type="earned")),
            new_members=Count("id", filter=Q(event_type="new_customer")),
        ).order_by("m")]

        by_event = [{"event": EVENT_LABELS.get(r["event_type"], r["event_type"]), "events": r["n"],
                     "points": abs(r["s"] or 0)}
                    for r in period.values("event_type").annotate(n=Count("id"), s=Sum("points")).order_by("-n")]

        by_state = [{"state": r["state__name"] or "Unmapped", "members": r["members"],
                     "issued": r["issued"] or 0, "redeemed": abs(r["redeemed"] or 0)}
                    for r in period.values("state__name").annotate(
                        members=Count("retailer_id", distinct=True),
                        issued=Sum("points", filter=Q(points__gt=0)),
                        redeemed=Sum("points", filter=Q(points__lt=0))).order_by("-issued")]

        members = (base.filter(retailer_id__isnull=False).values(
            "retailer_id", "retailer__name", "retailer__owner_name", "state__name", "distributor__name")
            .annotate(earned=Sum("points", filter=Q(points__gt=0)), redeemed=Sum("points", filter=Q(points__lt=0)),
                      events=Count("id"), last_event=Max("event_date"),
                      orders=Count("order_display_id", distinct=True, filter=~Q(order_display_id="")))
            .order_by("-earned")[:100])
        top = []
        for r in members:
            earned, redeemed = r["earned"] or 0, abs(r["redeemed"] or 0)
            top.append({"retailer_id": r["retailer_id"], "retailer": r["retailer__name"],
                        "owner": r["retailer__owner_name"], "state": r["state__name"],
                        "distributor": r["distributor__name"], "earned": earned, "redeemed": redeemed,
                        "balance": earned - redeemed, "orders": r["orders"], "events": r["events"],
                        "last_event": r["last_event"].isoformat() if r["last_event"] else None})

        dates = base.aggregate(first=Min("event_date"), last=Max("event_date"))
        return {
            "period": _totals(period),
            "previous": _totals(prev) if prev is not None else None,
            "lifetime": _totals(base),
            "data_range": {"first": dates["first"].isoformat() if dates["first"] else None,
                           "last": dates["last"].isoformat() if dates["last"] else None},
            "monthly": monthly,
            "by_event": by_event,
            "by_state": by_state,
            "top_members": top,
        }

