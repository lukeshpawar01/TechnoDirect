"""Month-on-month trend of sales value and quantity (pieces / boxes) for the selected scope."""
import calendar
from collections import defaultdict

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from rest_framework.exceptions import ValidationError

from warehouse.models import OrderLine

from ..filters import add_months, month_start
from ..metrics import delta_pct, mkey, num, ratio
from .base import AnalyticsView

RANGES = (6, 12, 24)


def _month_end(m):
    return m.replace(day=calendar.monthrange(m.year, m.month)[1])


class MomTrendView(AnalyticsView):
    """GET /trends/mom/?months=12

    Months end at the selected period's end month. Each month: sales (qualifying order value), pieces, boxes,
    orders, average price per piece, and MoM % for each measure. When the last month is still running, its MoM
    is like-for-like: days 1..N of this month vs days 1..N of the previous month (`basis: "same_days"`).
    With a category / article filter, value and quantity come from the matching order lines only.
    """

    permission_code = "view_overview"
    export_key = "months"

    def cache_extra(self, request, **kwargs):
        return super().cache_extra(request, **kwargs) + f"|m={request.query_params.get('months', '12')}"

    def compute(self, f, request, **kw):
        try:
            n = int(request.query_params.get("months", 12))
        except ValueError as e:
            raise ValidationError({"months": "must be a number"}) from e
        if n not in RANGES:
            raise ValidationError({"months": f"must be one of {list(RANGES)}"})

        last = month_start(min(f.period.end, f.today))
        first = add_months(last, -(n - 1))
        prior = add_months(first, -1)  # needed for the first month's MoM
        end = min(_month_end(last), f.today)
        partial = end < _month_end(last)
        orders = f.orders(start=prior, end=end)
        line_filter = f.has_line_filters()

        def monthly(start, stop):
            """{month: {sales, orders, pieces, boxes}} for orders placed in [start, stop]."""
            out = defaultdict(lambda: {"sales": 0.0, "orders": 0, "pieces": 0, "boxes": 0})
            o = orders.filter(placed_date__gte=start, placed_date__lte=stop)
            for r in o.annotate(m=TruncMonth("placed_date")).values("m").annotate(
                    s=Sum("gross_value"), n=Count("split_group", distinct=True), u=Sum("units")):
                out[r["m"]].update(orders=r["n"], sales=float(r["s"] or 0), pieces=r["u"] or 0)
            lines = OrderLine.objects.filter(order__in=o)
            if line_filter:
                lines = lines.filter(f.lines_q())
            for r in lines.annotate(m=TruncMonth("order__placed_date")).values("m").annotate(
                    b=Sum("boxes"), q=Sum("quantity"), t=Sum("total")):
                row = out[r["m"]]
                row["boxes"] = r["b"] or 0
                if line_filter:  # only the filtered categories / articles count
                    row["pieces"], row["sales"] = r["q"] or 0, float(r["t"] or 0)
            return out

        data = monthly(prior, end)
        same_days = None
        if partial:
            prev = add_months(last, -1)
            cut = prev.replace(day=min(end.day, calendar.monthrange(prev.year, prev.month)[1]))
            same_days = monthly(prev, cut).get(prev, {"sales": 0.0, "orders": 0, "pieces": 0, "boxes": 0})

        rows = []
        m = first
        while m <= last:
            cur = data.get(m, {"sales": 0.0, "orders": 0, "pieces": 0, "boxes": 0})
            is_partial = partial and m == last
            prev = same_days if is_partial else data.get(add_months(m, -1))
            prev = prev or {"sales": 0.0, "orders": 0, "pieces": 0, "boxes": 0}
            asp = ratio(cur["sales"], cur["pieces"]) if cur["pieces"] else None
            prev_asp = ratio(prev["sales"], prev["pieces"]) if prev["pieces"] else None
            rows.append({
                "month": mkey(m), "is_partial": is_partial,
                "days": (end - m).days + 1 if is_partial else calendar.monthrange(m.year, m.month)[1],
                "basis": "same_days" if is_partial else "full_month",
                "sales": num(cur["sales"]), "orders": cur["orders"], "pieces": cur["pieces"], "boxes": cur["boxes"],
                "avg_price_per_piece": asp,
                "prev_sales": num(prev["sales"]), "prev_pieces": prev["pieces"], "prev_boxes": prev["boxes"],
                "sales_mom_pct": delta_pct(cur["sales"], prev["sales"]) if prev["sales"] else None,
                "pieces_mom_pct": delta_pct(cur["pieces"], prev["pieces"]) if prev["pieces"] else None,
                "boxes_mom_pct": delta_pct(cur["boxes"], prev["boxes"]) if prev["boxes"] else None,
                "avg_price_mom_pct": delta_pct(asp, prev_asp) if asp and prev_asp else None,
            })
            m = add_months(m, 1)
        return {"months": rows, "range": n, "as_of": end.isoformat(),
                "first_data_month": next((r["month"] for r in rows if r["sales"] or r["pieces"]), None)}

