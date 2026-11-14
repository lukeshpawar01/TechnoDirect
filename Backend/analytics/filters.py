"""Shared filter parser: date presets (IST, FY Apr-Mar), compare period, dimension filters.

Every analytics / list endpoint calls `parse_filters(request)` and then uses
`Filters.orders()` / `Filters.dims_q()` so the user's data scope is always intersected.
"""
import calendar
import datetime as dt
from dataclasses import dataclass, field

from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.scope import ORDER_DIMS, get_scope

PRESETS = ["today", "yesterday", "wtd", "last_week", "mtd", "prev_month", "q1", "q2", "q3", "q4", "qtd", "fytd",
           "last_7d", "last_30d", "last_90d", "last_12m", "all_time", "custom"]
QUARTER_MONTHS = {"q1": (4, "Apr–Jun"), "q2": (7, "Jul–Sep"), "q3": (10, "Oct–Dec"), "q4": (1, "Jan–Mar")}
ROLLING_DAYS = {"last_7d": 7, "last_30d": 30, "last_90d": 90}
ALL_TIME_FALLBACK = dt.date(2023, 9, 1)
SEGMENTS = ["new", "retained", "reactivated", "inactive", "one_time", "repeat",
            "never_ordered", "inactive_30", "inactive_60", "inactive_90"]


# ----------------------------------------------------------------------------- date math
def today_ist():
    return timezone.localdate()


def month_start(d):
    return d.replace(day=1)


def month_end(d):
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def fy_start(d):
    """Financial year starts 1 April."""
    return dt.date(d.year if d.month >= 4 else d.year - 1, 4, 1)


def fy_label(d):
    s = fy_start(d).year
    return f"FY{str(s)[2:]}-{str(s + 1)[2:]}"


def quarter_start(d):
    """FY quarters (Apr-Jun, Jul-Sep, Oct-Dec, Jan-Mar) align with calendar quarters."""
    return dt.date(d.year, ((d.month - 1) // 3) * 3 + 1, 1)


def fy_quarter_label(d):
    q = {4: 1, 7: 2, 10: 3, 1: 4}[quarter_start(d).month]
    return f"{fy_label(d)} Q{q}"


def months_between(start, end):
    """List of month-start dates from month(start) to month(end) inclusive."""
    out, cur = [], month_start(start)
    last = month_start(end)
    while cur <= last:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def days_between(start, end):
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


@dataclass
class Period:
    start: dt.date
    end: dt.date
    label: str
    preset: str
    cmp_start: dt.date | None = None
    cmp_end: dt.date | None = None

    def as_dict(self):
        return {
            "from": self.start.isoformat(),
            "to": self.end.isoformat(),
            "label": self.label,
            "preset": self.preset,
            "compare_from": self.cmp_start.isoformat() if self.cmp_start else None,
            "compare_to": self.cmp_end.isoformat() if self.cmp_end else None,
        }

    @property
    def days(self):
        return (self.end - self.start).days + 1


def resolve_period(preset="mtd", today=None, date_from=None, date_to=None, compare="prev_period"):
    """Resolve a preset to (start, end) and its comparison window.

    compare: prev_period (default, "same-length window before", month/quarter/FY aware)
             | prev_year (same dates 12 months earlier) | none
    """
    today = today or today_ist()
    preset = (preset or "mtd").lower()
    if preset not in PRESETS:
        raise ValidationError({"preset": f"must be one of {PRESETS}"})

    if preset == "today":
        s = e = today
        cs = ce = today - dt.timedelta(days=1)
        label = "Today"
    elif preset == "yesterday":
        s = e = today - dt.timedelta(days=1)
        cs = ce = s - dt.timedelta(days=1)
        label = "Yesterday"
    elif preset == "wtd":
        s, e = today - dt.timedelta(days=today.weekday()), today
        cs, ce = s - dt.timedelta(days=7), e - dt.timedelta(days=7)
        label = "WTD"
    elif preset == "mtd":
        s, e = month_start(today), today
        cs = add_months(s, -1)
        ce = min(add_months(today, -1), s - dt.timedelta(days=1))
        label = "MTD"
    elif preset == "prev_month":
        e = month_start(today) - dt.timedelta(days=1)
        s = month_start(e)
        ce = s - dt.timedelta(days=1)
        cs = month_start(ce)
        label = s.strftime("%b %Y")
    elif preset == "qtd":
        s, e = quarter_start(today), today
        cs = add_months(s, -3)
        ce = min(add_months(today, -3), s - dt.timedelta(days=1))
        label = f"QTD ({fy_quarter_label(today)})"
    elif preset == "fytd":
        s, e = fy_start(today), today
        cs = add_months(s, -12)
        ce = add_months(today, -12)
        label = f"YTD ({fy_label(today)}, from 1 Apr)"
    elif preset == "last_week":
        s = today - dt.timedelta(days=today.weekday() + 7)
        e = s + dt.timedelta(days=6)
        cs, ce = s - dt.timedelta(days=7), e - dt.timedelta(days=7)
        label = f"Last week ({s.strftime('%d %b')} – {e.strftime('%d %b')})"
    elif preset in QUARTER_MONTHS:
        # quarters of the CURRENT financial year; compared quarter-on-quarter with the whole previous quarter
        first_month, months_label = QUARTER_MONTHS[preset]
        fy = fy_start(today)
        s = dt.date(fy.year + (1 if first_month < 4 else 0), first_month, 1)
        q_end = month_end(add_months(s, 2))
        cs = add_months(s, -3)
        ce = s - dt.timedelta(days=1)
        if s > today:
            # not started yet: the real (future) range, so no data is shown rather than another year's
            e = q_end
            cs = ce = None
            label = f"{preset.upper()} {fy_label(s)} · {months_label} (not started)"
        else:
            e = min(q_end, today)
            label = f"{preset.upper()} {fy_label(s)} · {months_label}" + (" (to date)" if e < q_end else "")
    elif preset in ROLLING_DAYS:
        n = ROLLING_DAYS[preset]
        s, e = today - dt.timedelta(days=n - 1), today
        ce = s - dt.timedelta(days=1)
        cs = ce - dt.timedelta(days=n - 1)
        label = f"Last {n} days"
    elif preset == "all_time":
        from django.db.models import Min

        from warehouse.models import Order

        s = Order.objects.aggregate(m=Min("placed_date"))["m"] or ALL_TIME_FALLBACK
        s, e = min(s, today), today
        cs = ce = None
        label = "All time"
    elif preset == "last_12m":
        s, e = add_months(month_start(today), -11), today
        cs, ce = add_months(s, -12), add_months(e, -12)
        label = "Last 12 months"
    else:  # custom
        try:
            s = dt.date.fromisoformat(str(date_from))
            e = dt.date.fromisoformat(str(date_to))
        except (TypeError, ValueError):
            raise ValidationError({"date_from": "custom preset needs date_from and date_to (YYYY-MM-DD)"})
        if e < s:
            raise ValidationError({"date_to": "must be on or after date_from"})
        if (e - s).days > 3 * 366:
            raise ValidationError({"date_to": "range too long (max 3 years)"})
        n = (e - s).days
        ce = s - dt.timedelta(days=1)
        cs = ce - dt.timedelta(days=n)
        label = f"{s.strftime('%d %b %Y')} – {e.strftime('%d %b %Y')}"

    compare = (compare or "prev_period").lower()
    if compare == "prev_year":
        cs, ce = add_months(s, -12), add_months(e, -12)
    elif compare == "none":
        cs = ce = None
    return Period(s, e, label, preset, cs, ce)


# ----------------------------------------------------------------------------- filters
def _csv(value):
    if value is None or value == "":
        return []
    return [v.strip() for v in str(value).split(",") if v.strip()]


def _resolve_ids(values, model, code_field="code"):
    """Accept ids or codes, return ids."""
    if not values:
        return []
    ids = [int(v) for v in values if v.isdigit()]
    codes = [v for v in values if not v.isdigit()]
    if codes:
        ids += list(model.objects.filter(**{f"{code_field}__in": codes}).values_list("id", flat=True))
    return ids or [-1]  # explicit filter with nothing matching -> no rows


@dataclass
class Filters:
    period: Period
    user: object = None
    regions: list = field(default_factory=list)
    states: list = field(default_factory=list)
    asms: list = field(default_factory=list)
    distributors: list = field(default_factory=list)
    retailers: list = field(default_factory=list)
    categories: list = field(default_factory=list)
    articles: list = field(default_factory=list)
    segment: str | None = None
    order_status: list = field(default_factory=list)
    payment_status: list = field(default_factory=list)
    # module filters (sent only by the page that shows them)
    platforms: list = field(default_factory=list)
    payment_modes: list = field(default_factory=list)
    split_only: bool = False
    cat_l1: list = field(default_factory=list)
    cat_l2: list = field(default_factory=list)
    cat_l3: list = field(default_factory=list)
    sizes: list = field(default_factory=list)
    has_account: bool | None = None
    kyc_verified: bool | None = None  # customer `kyc` TRUE (= KYC approved) / FALSE
    kyc_statuses: list = field(default_factory=list)  # approved / pending / rejected / not_submitted
    event_types: list = field(default_factory=list)
    today: dt.date = field(default_factory=today_ist)

    @property
    def scope(self):
        return get_scope(self.user)

    def has_dim_filters(self):
        return bool(self.regions or self.states or self.asms or self.distributors)

    def cache_signature(self):
        p = self.period
        return "|".join(str(x) for x in [
            p.start, p.end, p.cmp_start, p.cmp_end, p.preset, sorted(self.regions), sorted(self.states),
            sorted(self.asms), sorted(self.distributors), sorted(self.retailers), sorted(self.categories),
            sorted(self.articles), self.segment, sorted(self.order_status), sorted(self.payment_status), self.today,
            sorted(self.platforms), sorted(self.payment_modes), self.split_only, sorted(self.cat_l1),
            sorted(self.cat_l2), sorted(self.cat_l3), sorted(self.sizes), self.has_account, sorted(self.event_types),
            self.kyc_verified, sorted(self.kyc_statuses),
        ])

    # -- dimension predicates ----------------------------------------------
    def dims_q(self, mapping=ORDER_DIMS, include_scope=True, retailer_field="retailer_id"):
        q = Q()
        for dim, ids in (("region", self.regions), ("state", self.states), ("asm", self.asms),
                         ("distributor", self.distributors)):
            f = mapping.get(dim)
            if ids and f:
                q &= Q(**{f"{f}__in": ids})
        if self.retailers and retailer_field:
            q &= Q(**{f"{retailer_field}__in": self.retailers})
        if include_scope:
            sq = self.scope.q(mapping)
            if sq is not None:
                q &= sq
        return q

    def apply(self, qs, mapping=ORDER_DIMS, retailer_field="retailer_id"):
        return qs.filter(self.dims_q(mapping, retailer_field=retailer_field))

    # -- segment -> retailer id subquery -------------------------------------
    def segment_retailers(self):
        from warehouse.models import Retailer, RetailerMonth

        seg = self.segment
        if not seg:
            return None
        t = self.today
        if seg in ("new", "retained", "reactivated"):
            return RetailerMonth.objects.filter(
                month__gte=month_start(self.period.start), month__lte=month_start(self.period.end), status=seg
            ).values("retailer_id")
        r = Retailer.objects.all()
        if seg == "inactive":
            r = r.filter(last_order_date__lte=t - dt.timedelta(days=30))
        elif seg == "inactive_30":
            r = r.filter(last_order_date__lte=t - dt.timedelta(days=30), last_order_date__gt=t - dt.timedelta(days=60))
        elif seg == "inactive_60":
            r = r.filter(last_order_date__lte=t - dt.timedelta(days=60), last_order_date__gt=t - dt.timedelta(days=90))
        elif seg == "inactive_90":
            r = r.filter(last_order_date__lte=t - dt.timedelta(days=90))
        elif seg == "one_time":
            r = r.filter(orders_count=1)
        elif seg == "repeat":
            r = r.filter(orders_count__gte=2)
        elif seg == "never_ordered":
            r = r.filter(orders_count=0)
        return r.values("id")

    # -- orders --------------------------------------------------------------
    def orders(self, start=None, end=None, qualifying=True, statuses=True):
        """Scoped + filtered Order queryset. start/end default to no date restriction."""
        from warehouse.models import Order, OrderLine

        qs = Order.objects.filter(self.dims_q())
        if qualifying:
            qs = qs.filter(is_qualifying=True)
        if start:
            qs = qs.filter(placed_date__gte=start)
        if end:
            qs = qs.filter(placed_date__lte=end)
        if statuses and self.order_status:
            qs = qs.filter(status__in=self.order_status)
        if statuses and self.payment_status:
            qs = qs.filter(payment_status__in=self.payment_status)
        if self.platforms:
            qs = qs.filter(platform__in=self.platforms)
        if self.payment_modes:
            qs = qs.filter(payment_mode__in=self.payment_modes)
        if self.split_only:
            qs = qs.filter(is_split=True)
        if self.has_line_filters():
            qs = qs.filter(id__in=OrderLine.objects.filter(self.lines_q()).values("order_id"))
        seg = self.segment_retailers()
        if seg is not None:
            qs = qs.filter(retailer_id__in=seg)
        return qs

    def has_line_filters(self):
        return bool(self.categories or self.articles or self.cat_l1 or self.cat_l2 or self.cat_l3)

    def lines_q(self, prefix="product__"):
        """Extra predicates for OrderLine querysets (category / article / category I-II-III)."""
        q = Q()
        if self.categories:  # global "Category" = Category I (men / women / kids / unisex)
            q &= Q(**{f"{prefix}category_l1__in": self.categories})
        if self.articles:
            q &= Q(style__in=self.articles)
        for lvl, vals in ((1, self.cat_l1), (2, self.cat_l2), (3, self.cat_l3)):
            if vals:
                q &= Q(**{f"{prefix}category_l{lvl}__in": vals})
        return q


def parse_filters(request, default_preset="mtd", today=None):
    from warehouse.models import Asm, Distributor, Region, State

    p = request.query_params if hasattr(request, "query_params") else request.GET
    period = resolve_period(p.get("preset") or default_preset, today=today, date_from=p.get("date_from"),
                            date_to=p.get("date_to"), compare=p.get("compare"))
    seg = p.get("segment") or None
    if seg and seg not in SEGMENTS:
        raise ValidationError({"segment": f"must be one of {SEGMENTS}"})
    return Filters(
        period=period,
        user=request.user,
        regions=_resolve_ids(_csv(p.get("region")), Region),
        states=_resolve_ids(_csv(p.get("state")), State),
        asms=_resolve_ids(_csv(p.get("asm")), Asm),
        distributors=_resolve_ids(_csv(p.get("distributor")), Distributor),
        retailers=[int(x) for x in _csv(p.get("retailer")) if x.isdigit()],
        categories=[c.lower() for c in _csv(p.get("category"))],
        articles=[a.upper() for a in _csv(p.get("article"))],
        segment=seg,
        order_status=_csv(p.get("order_status")),
        payment_status=_csv(p.get("payment_status")),
        platforms=[x.lower() for x in _csv(p.get("platform"))],
        payment_modes=[x.upper() for x in _csv(p.get("payment_mode"))],
        split_only=p.get("is_split") in ("1", "true"),
        cat_l1=_csv(p.get("cat_l1")),
        cat_l2=_csv(p.get("cat_l2")),
        cat_l3=_csv(p.get("cat_l3")),
        sizes=_csv(p.get("size")),
        has_account={"true": True, "1": True, "false": False, "0": False}.get((p.get("has_account") or "").lower()),
        kyc_statuses=[s.lower() for s in _csv(p.get("kyc_status"))],
        kyc_verified={"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False}.get((p.get("kyc_verified") or "").lower()),
        event_types=_csv(p.get("event_type")),
        today=today or today_ist(),
    )


def system_filters(preset="mtd", today=None):
    """Unscoped filters for background jobs (full data scope)."""
    t = today or today_ist()
    return Filters(period=resolve_period(preset, today=t), user=None, today=t)
