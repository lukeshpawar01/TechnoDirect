import datetime as dt
from collections import defaultdict

from django.db.models import Case, Count, DecimalField, F, IntegerField, Max, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce, TruncMonth
from django.http import Http404
from django.utils import timezone
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from accounts.permissions import HasPerm
from accounts.scope import RETAILER_DIMS
from warehouse.models import Order, Retailer, RetailerMonth, State

from ..envelope import envelope
from ..export import ExportListMixin
from ..filters import add_months, month_start, parse_filters
from .. import rfm
from ..metrics import as_date, launch_month, median, mkey, num, pct, share
from .base import AnalyticsView


def retailer_base(f):
    qs = Retailer.objects.filter(f.dims_q(RETAILER_DIMS, retailer_field="id"))
    if f.has_account is not None:
        qs = qs.filter(has_account=f.has_account)
    if f.kyc_statuses:  # "KYC status" module filter (Retailers, Funnel)
        qs = qs.filter(kyc_status__in=f.kyc_statuses)
    if f.kyc_verified is not None:  # "KYC Verified" module filter (Retailers, Funnel)
        qs = qs.filter(kyc_status="approved") if f.kyc_verified else qs.exclude(kyc_status="approved")
    return qs  # BlueOrigin tier: applied by dims_q


def _day0(d):
    return timezone.make_aware(dt.datetime.combine(d, dt.time.min))


def kyc_by(end):
    """Retailers whose KYC was approved by `end`. The TD data has no approval date, so the sign-up date stands in
    (user's choice, 2026-11-15): approved today and signed up on or before `end`."""
    return Q(kyc_status="approved", signed_up_at__lt=_day0(end + dt.timedelta(days=1)))


def never_by(end):
    """KYC-approved by `end` with no order up to `end` (the 'Never ordered' tile as on the period's last day)."""
    return kyc_by(end) & (Q(first_order_date__isnull=True) | Q(first_order_date__gt=end))


def inactive_ids(f, end, lo, hi=None):
    """Retailer ids whose last qualifying order up to `end` is `lo`..`hi`-1 days before `end` (hi None = no limit)."""
    last = f.orders(end=end).values("retailer_id").annotate(last=Max("placed_date"))
    last = last.filter(last__lte=end - dt.timedelta(days=lo))
    if hi is not None:
        last = last.filter(last__gt=end - dt.timedelta(days=hi))
    return last.values("retailer_id")


def mask_phone(phone, can_see):
    if can_see or not phone:
        return phone
    p = str(phone)
    return p[:2] + "X" * max(len(p) - 4, 0) + p[-2:] if len(p) > 4 else "XXXX"


def mask_email(email):
    """a****@domain.com for users without PII access."""
    if not email or "@" not in email:
        return None
    user, _, domain = email.partition("@")
    return f"{user[:1]}****@{domain}"


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
    sources = ["supabase"]
    export_key = "by_state"

    def compute(self, f, request, **kw):
        p, t = f.period, f.today
        rb = retailer_base(f)
        # IST day boundaries as aware datetimes: comparing the stored timestamp directly lets the database use it
        # as-is (a __date lookup converts every one of ~2 lakh rows to an IST date in Python on SQLite)
        day0 = lambda d: timezone.make_aware(dt.datetime.combine(d, dt.time.min))  # noqa: E731
        end_excl = day0(p.end + dt.timedelta(days=1))
        cur_orders = f.orders(start=p.start, end=p.end)
        repeat = (f.orders(end=p.end).values("retailer_id").annotate(n=Count("split_group", distinct=True))
                  .filter(n__gte=2).count())
        agg = rb.aggregate(
            signed=Count("id", filter=Q(signed_up_at__isnull=True) | Q(signed_up_at__lt=end_excl)),
            # KYC, never-ordered and inactivity tiles: the position at the END of the selected period
            # (Q2 -> as on 30 Sep; a period ending today -> today), not always today
            approved=Count("id", filter=kyc_by(p.end)),
            first=Count("id", filter=Q(first_order_date__lte=p.end)),
            pending=Count("id", filter=Q(kyc_status="pending", signed_up_at__lt=end_excl)),
            rejected=Count("id", filter=Q(kyc_status="rejected", signed_up_at__lt=end_excl)),
            never=Count("id", filter=never_by(p.end)),
            never_warm=Count("id", filter=never_by(p.end) & Q(warm_match=True)),
            never_flagged=Count("id", filter=never_by(p.end) & (Q(distributor__isnull=True) | Q(state__isnull=True))),
        )
        agg.update({k: rb.filter(id__in=inactive_ids(f, p.end, lo, hi)).count()
                    for k, lo, hi in (("d30", 30, 60), ("d60", 60, 90), ("d90", 90, None))})
        active = cur_orders.values("retailer_id").distinct().count()
        warm_ready = Retailer.objects.filter(warm_match=True).exists()
        stages = [
            {"key": "signed_up", "label": "Signed up", "count": agg["signed"]},
            # one KYC stage, "KYC approved", as on every other page: the TD export only has the approved flag,
            # so a separate "KYC submitted" stage always showed the same number
            {"key": "kyc_approved", "label": "KYC approved", "count": agg["approved"]},
            {"key": "first_order", "label": "Placed first order", "count": agg["first"]},
            {"key": "repeat_order", "label": "Placed repeat order", "count": repeat},
            {"key": "active_this_period", "label": f"Active ({p.label})", "count": active},
        ]

        # Sign-up cohorts (the source has no KYC approval date, only the customer's created date):
        # of the retailers who signed up in a month, how many are KYC-approved today, and how many of those
        # have placed a first order. Last 18 months up to the period end.
        last_m = month_start(p.end)
        first_m = add_months(last_m, -17)
        months = []
        m = first_m
        while m <= last_m:
            months.append(m)
            m = add_months(m, 1)
        # month bucket by IST month boundaries, evaluated in the database
        bucket = Case(*[When(signed_up_at__gte=day0(mm), signed_up_at__lt=day0(add_months(mm, 1)), then=Value(i))
                        for i, mm in enumerate(months)], default=Value(-1), output_field=IntegerField())
        cohort = {months[r["mi"]]: r for r in rb.filter(
            signed_up_at__gte=day0(first_m), signed_up_at__lt=end_excl,
        ).annotate(mi=bucket).values("mi").annotate(
            n=Count("id"),
            kyc=Count("id", filter=Q(kyc_status="approved")),
            ordered=Count("id", filter=Q(kyc_status="approved", first_order_date__isnull=False,
                                         first_order_date__lte=p.end)),
        ) if r["mi"] >= 0}
        signup_cohorts, m = [], first_m
        while m <= last_m:
            r = cohort.get(m) or {"n": 0, "kyc": 0, "ordered": 0}
            signup_cohorts.append({
                "month": mkey(m), "signed_up": r["n"], "kyc_approved": r["kyc"], "first_order": r["ordered"],
                "kyc_rate": pct(r["kyc"], r["n"]), "order_rate": pct(r["ordered"], r["kyc"]),
            })
            m = add_months(m, 1)

        # KYC -> first order conversion. The source has no KYC approval date, so "time to first order" runs from
        # the customer's created date (sign-up), which is when KYC is submitted in the app.
        conv_days = [(fo - timezone.localtime(su).date()).days for su, fo in rb.filter(
            kyc_status="approved", signed_up_at__isnull=False, first_order_date__isnull=False,
            first_order_date__lte=p.end).values_list("signed_up_at", "first_order_date")]
        conv_days = [d for d in conv_days if d >= 0]
        converted = rb.filter(kyc_status="approved", first_order_date__lte=p.end).count()
        within30 = sum(1 for d in conv_days if d <= 30)
        kyc_conversion = {
            "kyc_approved": agg["approved"], "converted": converted, "rate": pct(converted, agg["approved"]),
            "median_days": median(conv_days), "within_30d": within30,
            "within_30d_pct": pct(within30, len(conv_days)), "basis": "signup",
        }

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
            # warm / cold needs the BlueOrigin ledger match; until a ledger is loaded both are unknown (not 0)
            "never_ordered": {"total": agg["never"], "warm": agg["never_warm"] if warm_ready else None,
                              "cold": agg["never"] - agg["never_warm"] if warm_ready else None,
                              "flagged": agg["never_flagged"], "warm_available": warm_ready},
            "inactivity": {"d30": agg["d30"], "d60": agg["d60"], "d90": agg["d90"]},
            "signup_cohorts": signup_cohorts,
            "kyc_conversion": kyc_conversion,
            # deck slide 53: how much of the KYC-verified base TD actually trades with
            "kyc_penetration": {
                "kyc_approved": agg["approved"], "ever_ordered": converted, "ever_pct": pct(converted, agg["approved"]),
                "active": cur_orders.filter(retailer__kyc_status="approved").values("retailer_id").distinct().count(),
                "active_pct": pct(cur_orders.filter(retailer__kyc_status="approved").values("retailer_id")
                                  .distinct().count(), agg["approved"]),
                "period_label": p.label,
            },
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


def rsm_context():
    """(rsm names, region -> rsm) for labelling retailer rows with their RSM without per-row queries."""
    from warehouse.models import Rsm

    from ..rsm import region_rsm_map

    return dict(Rsm.objects.values_list("id", "name")), region_rsm_map()


def retailer_row(r, can_pii, today, rsm_ctx=None, rfm_rows=None):
    names, reg = rsm_ctx or rsm_context()
    rfm_seg = (rfm_rows.get(r.id) or {}).get("segment", "prospect") if rfm_rows is not None else None
    rsm_id = r.asm.rsm_id if r.asm_id and r.asm.rsm_id else reg.get(r.region_id)
    return {
        "id": r.id, "name": r.name, "phone": mask_phone(r.phone, can_pii),
        "state": r.state.name if r.state_id else None,
        "distributor": r.distributor.name if r.distributor_id else None,
        "asm": r.asm.name if r.asm_id else None,
        "rsm": names.get(rsm_id),
        "kyc_status": r.kyc_status,
        "first_order_date": r.first_order_date, "last_order_date": r.last_order_date,
        "days_since_last_order": (today - r.last_order_date).days if r.last_order_date else None,
        "orders": getattr(r, "period_orders", None) or 0,
        "sales": num(getattr(r, "period_sales", 0)),
        "lifetime_orders": r.orders_count, "lifetime_sales": num(r.total_sales),
        "segment": retailer_segment(r, today),
        "rfm_segment": rfm_seg,
        "rfm_label": rfm.label(rfm_rows.get(r.id)) if rfm_rows is not None else None,
        "rfm_priority": (rfm_rows.get(r.id) or {}).get("priority") if rfm_rows is not None else None,
        "warm_match": r.warm_match,
        "tier": r.tier or None,
    }


FUNNEL_STAGES = ("signed_up", "kyc_approved", "first_order", "repeat_order", "active_this_period", "kyc_pending",
                 "kyc_rejected", "never_flagged", "never_ordered", "inactive_30", "inactive_60", "inactive_90", "kyc_ever_ordered", "kyc_active", "first_order_30d")


def _month_arg(q, key):
    raw = (q.get(key) or "").strip()
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(raw + "-01")
    except ValueError:
        raise ValidationError({key: "must be YYYY-MM"}) from None


def funnel_drill(f, qs, q):
    """Retailers behind one number / bar on the Retailer Funnel page - the same definitions as FunnelView.

    stage=signed_up | kyc_approved | first_order | repeat_order | active_this_period   (the funnel stages)
          kyc_pending | kyc_rejected                (KYC status card)
          never_flagged                             (never ordered, no distributor or state)
          kyc_ever_ordered | kyc_active             (KYC base ever ordered / ordering in the period)
          first_order_30d                           (first order within 30 days of sign-up)
    signup_month=YYYY-MM       signed up that month (IST) - conversion chart
    first_order_month=YYYY-MM  first order that month - acquisition chart
    state_none=1               no state mapped (the "Unmapped" row of Adoption by state)"""
    p = f.period
    day0 = lambda d: timezone.make_aware(dt.datetime.combine(d, dt.time.min))  # noqa: E731
    stage = (q.get("stage") or "").strip()
    if stage and stage not in FUNNEL_STAGES:
        raise ValidationError({"stage": f"must be one of {list(FUNNEL_STAGES)}"})
    if stage == "signed_up":
        qs = qs.filter(Q(signed_up_at__isnull=True) | Q(signed_up_at__lt=day0(p.end + dt.timedelta(days=1))))
    elif stage == "kyc_approved":
        qs = qs.filter(kyc_by(p.end))
    elif stage == "kyc_pending":
        qs = qs.filter(kyc_status="pending", signed_up_at__lt=day0(p.end + dt.timedelta(days=1)))
    elif stage == "kyc_rejected":
        qs = qs.filter(kyc_status="rejected", signed_up_at__lt=day0(p.end + dt.timedelta(days=1)))
    elif stage == "never_ordered":
        qs = qs.filter(never_by(p.end))
    elif stage in ("inactive_30", "inactive_60", "inactive_90"):
        lo = int(stage[-2:])
        qs = qs.filter(id__in=inactive_ids(f, p.end, lo, None if lo == 90 else lo + 30))
    elif stage == "first_order":
        qs = qs.filter(first_order_date__lte=p.end)
    elif stage == "kyc_ever_ordered":
        qs = qs.filter(kyc_status="approved", first_order_date__lte=p.end)
    elif stage == "repeat_order":
        ids = (f.orders(end=p.end).values("retailer_id").annotate(n=Count("split_group", distinct=True))
               .filter(n__gte=2).values("retailer_id"))
        qs = qs.filter(id__in=ids)
    elif stage in ("active_this_period", "kyc_active"):
        qs = qs.filter(id__in=f.orders(start=p.start, end=p.end).values("retailer_id"))
        if stage == "kyc_active":
            qs = qs.filter(kyc_status="approved")
    elif stage == "never_flagged":
        qs = qs.filter(never_by(p.end) & (Q(distributor__isnull=True) | Q(state__isnull=True)))
    elif stage == "first_order_30d":
        ids = [rid for rid, su, fo in qs.filter(
            kyc_status="approved", signed_up_at__isnull=False, first_order_date__isnull=False,
            first_order_date__lte=p.end).values_list("id", "signed_up_at", "first_order_date")
               if 0 <= (fo - timezone.localtime(su).date()).days <= 30]
        qs = qs.filter(id__in=ids)
    m = _month_arg(q, "signup_month")
    if m:
        qs = qs.filter(signed_up_at__gte=day0(m), signed_up_at__lt=day0(add_months(m, 1)))
    m = _month_arg(q, "first_order_month")
    if m:
        qs = qs.filter(first_order_date__gte=m, first_order_date__lt=add_months(m, 1))
    if q.get("state_none") in ("1", "true"):
        qs = qs.filter(state__isnull=True)
    return qs


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
        if q.get("warm") in ("true", "1", "false", "0"):
            qs = qs.filter(warm_match=q["warm"] in ("true", "1"))
        qs = funnel_drill(f, qs, q)
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
        f = parse_filters(request)
        items = instance if many else [instance]
        ctx = rsm_context()
        rows = rfm.snapshot(rfm.as_of_for(f))["rows"]
        self.data = [retailer_row(r, can, f.today, ctx, rows) for r in items]
        if not many:
            self.data = self.data[0]


def blueorigin_block(r):
    """Offline (BlueOrigin) records phone-matched to this app retailer: tier per quarter, monthly purchase."""
    from warehouse.models import BoRetailer

    from ..filters import fy_quarter_label

    from masters.blueorigin import phone10

    ph = phone10(r.phone)
    out = []
    for b in BoRetailer.objects.filter(Q(td_retailer=r) | (Q(phone=ph) | Q(phone_alt=ph) if ph else Q(pk__in=[]))).select_related(
            "distributor").prefetch_related("quarters", "months").distinct():
        out.append({
            "bo_id": b.bo_id, "name": b.name, "distributor": b.distributor.name if b.distributor_id else None,
            "district": b.district or None, "tier": b.tier,
            "quarters": [{"quarter": fy_quarter_label(q.quarter), "tier": q.tier, "purchase": num(q.purchase),
                          "deliverables": q.deliverables or None} for q in b.quarters.all()],
            "monthly": [{"month": mkey(m.month), "value": num(m.value)} for m in b.months.all()],
        })
    return out


class RetailerDetailView(AnalyticsView):
    permission_code = "view_funnel"
    sources = ["supabase"]
    pii_sensitive = True
    export_key = "monthly"

    def compute(self, f, request, pk=None):
        r = retailer_base(f).select_related("state", "distributor", "asm", "region").filter(pk=pk).first()
        if r is None:
            raise Http404
        can = request.user.has_code("view_pii")
        snap = rfm.snapshot(rfm.as_of_for(f))
        profile = retailer_row(r, can, f.today, rfm_rows=snap["rows"])
        profile.update({
            "owner_name": r.owner_name, "email": (r.email if can else mask_email(r.email)) or None,
            "gstin": r.gstin or None, "udyam_number": r.udyam_number or None,
            "pincode": r.pincode, "city": r.city, "region": r.region.name if r.region_id else None,
            "signed_up_at": r.signed_up_at, "kyc_submitted_at": r.kyc_submitted_at,
            "kyc_approved_at": r.kyc_approved_at, "tier": r.tier or None,
            "orders": r.orders_count, "sales": num(r.total_sales),
            "aov": num(r.total_sales / r.orders_count) if r.orders_count else None,
            "first_order_date": r.first_order_date.isoformat() if r.first_order_date else None,
            "last_order_date": r.last_order_date.isoformat() if r.last_order_date else None,
        })
        for k in ("signed_up_at", "kyc_submitted_at", "kyc_approved_at"):
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
        rfm_block = rfm.describe(snap["rows"].get(r.id))
        rfm_block.update({"as_of": snap["as_of"].isoformat() if snap.get("as_of") else None,
                          "window_start": snap["window_start"].isoformat() if snap.get("window_start") else None})
        return {"profile": profile, "rfm": rfm_block, "monthly": monthly, "recent_orders": recent_orders,
                "blueorigin": blueorigin_block(r)}


class RfmView(AnalyticsView):
    """RFM segments of the retailers in scope, as of the end of the selected period (analytics/rfm.py).

    Cut-offs are ranked against ALL active buyers; region / ASM / distributor filters only choose who is counted."""

    permission_code = "view_funnel"
    sources = ["supabase"]
    export_key = "segments"

    def compute(self, f, request, **kw):
        as_of = rfm.as_of_for(f)
        snap = rfm.snapshot(as_of)
        in_scope = set(retailer_base(f).filter(id__in=list(snap["rows"])).values_list("id", flat=True))
        rows = {rid: r for rid, r in snap["rows"].items() if rid in in_scope}
        prospects = retailer_base(f).exclude(id__in=list(snap["rows"])).count()
        buyers = len(rows)
        total_value = sum(r["value"] for r in rows.values()) or 0.0
        agg = defaultdict(lambda: {"retailers": 0, "value": 0.0})
        prio = defaultdict(lambda: {"retailers": 0, "value": 0.0})
        grid = defaultdict(int)
        for r in rows.values():
            a = agg[r["segment"]]
            a["retailers"] += 1
            a["value"] += r["value"]
            if r.get("priority"):
                prio[r["priority"]]["retailers"] += 1
                prio[r["priority"]]["value"] += r["value"]
            if r.get("r_score"):
                grid[(r["r_score"], r["fm"])] += 1
        segments = []
        for key, (label, meaning, action) in rfm.SEGMENTS.items():
            if key == "prospect":
                n, v = prospects, 0.0
            else:
                n, v = agg[key]["retailers"], agg[key]["value"]
            segments.append({
                "segment": key, "label": label, "meaning": meaning, "action": action, "retailers": n,
                "pct_buyers": pct(n, buyers) if key != "prospect" else None,
                "value": round(v, 2), "pct_value": pct(v, total_value) if key != "prospect" else None,
                "scored": key in rfm.SCORED,
            })
            if key == "at_risk":  # the value priority inside At Risk - who to call first
                segments[-1]["priorities"] = [
                    {"priority": p, "segment": f"at_risk_{p}", "label": p_label, "action": p_action,
                     "retailers": prio[p]["retailers"], "pct_buyers": pct(prio[p]["retailers"], buyers),
                     "value": round(prio[p]["value"], 2), "pct_value": pct(prio[p]["value"], total_value)}
                    for p, (p_label, p_action) in rfm.PRIORITIES.items()]
        cut = snap.get("cutoffs") or {}
        return {
            "as_of": snap["as_of"].isoformat() if snap.get("as_of") else None,
            "window_start": snap["window_start"].isoformat() if snap.get("window_start") else None,
            "window_months": rfm.WINDOW_MONTHS,
            "summary": {"registered": buyers + prospects, "buyers": buyers,
                        "active": sum(1 for r in rows.values() if r["lifecycle"] == "active"),
                        "value": round(total_value, 2)},
            "population": snap.get("population"),
            "cutoffs": [{"measure": k, "p20": c[0], "p40": c[1], "p60": c[2], "p80": c[3]} for k, c in cut.items()],
            "grid": [{"r": r_, "fm": fm, "segment": rfm.GRID[r_][fm - 1], "retailers": grid[(r_, fm)]}
                     for r_ in (5, 4, 3, 2, 1) for fm in (1, 2, 3, 4, 5)],
            "segments": segments,
            "params": {"churn_ratio": rfm.CHURN_RATIO, "new_days": rfm.NEW_DAYS, "min_tenure_months": rfm.MIN_TENURE_M,
                       "shrink_k": rfm.SHRINK_K},
            "validation": rfm.backtest(snap["as_of"]) if snap.get("as_of") else None,
        }


__all__ = ["defaultdict", "envelope"]


class SegmentTrendView(AnalyticsView):
    """Retailer segments over time - see analytics/segment_trend.py. ?kind=rfm|lifecycle&grain=day|week|month|quarter"""

    permission_code = "view_funnel"
    sources = ["supabase"]

    def cache_extra(self, request, **kwargs):
        q = request.query_params
        return f"{q.get('kind', 'rfm')}|{q.get('grain', '')}|{q.get('count', '')}"

    def compute(self, f, request, **kw):
        from ..segment_trend import trend

        q = request.query_params
        return trend(f, grain=q.get("grain"), count=q.get("count"), kind=q.get("kind", "rfm"))
