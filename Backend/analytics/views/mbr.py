"""GET /api/analytics/mbr/?month=YYYY-MM - MBR page 1 scorecard and the page 2 path to the monthly sales goal."""
import datetime as dt
from dataclasses import replace

from django.db.models import Sum

from rest_framework.exceptions import ValidationError

from ..filters import month_end, month_start
from ..metrics import num
from ..mbr_finance import finance_asks
from ..mbr_growth import growth_drivers
from ..mbr_marketing import marketing_asks
from ..mbr_sales import sales_asks
from ..mbr_summary import executive_summary
from ..mbr import GOAL_DEFAULT, default_goal_by, path_to_goal, scorecard
from .base import AnalyticsView


def parse_month(raw, today):
    if not raw:
        return month_start(today)
    try:
        m = dt.date.fromisoformat(f"{raw}-01" if len(raw) == 7 else raw)
    except ValueError:
        raise ValidationError({"month": "use YYYY-MM"}) from None
    if month_start(m) > month_start(today):
        raise ValidationError({"month": "that month has not started yet"})
    return month_start(m)


def goal_for(month, today):
    from masters.models import MbrReview

    r = MbrReview.objects.filter(month=month).first()
    goal = float(r.goal_monthly_sales) if r and r.goal_monthly_sales else GOAL_DEFAULT
    by = r.goal_by if r and r.goal_by else default_goal_by(today)
    return goal, by


def territory_share(f, card):
    """% of all-TD sales this territory made in the path's base months (the last 3 complete months)."""
    full = [t for t in card["_trend"] if not (card["partial"] and t["month"] == card["month"])][-3:]
    if not full:
        return None
    lo = dt.date.fromisoformat(full[0]["month"] + "-01")
    hi = month_end(dt.date.fromisoformat(full[-1]["month"] + "-01"))
    allf = replace(f, regions=[], states=[], asms=[], rsms=[])
    total = float(allf.orders(start=lo, end=hi).aggregate(s=Sum("gross_value"))["s"] or 0)
    mine = sum(t["sales"] for t in full)
    return round(mine / total * 100, 2) if total else None


def scope_label(f):
    """'East · ASM Ravi Kumar' for the territory filters in force, or None for all TD."""
    from warehouse.models import Asm, Region, Rsm, State

    parts = []
    for ids, model, prefix in ((f.regions, Region, ""), (f.rsms, Rsm, "RSM "), (f.states, State, ""),
                               (f.asms, Asm, "ASM ")):
        if ids:
            names = sorted(str(getattr(o, "name", o)) for o in model.objects.filter(id__in=ids))
            parts.append(prefix + ", ".join(names))
    return " · ".join(parts) or None


class MbrScorecardView(AnalyticsView):
    permission_code = "view_mbr"
    export_key = "rows"

    def cache_extra(self, request, **kwargs):
        from analytics.filters import today_ist

        m = parse_month(request.query_params.get("month"), today_ist())
        goal, by = goal_for(m, today_ist())
        return f"{super().cache_extra(request, **kwargs)}|{m}|{goal}|{by}"

    def compute(self, f, request, **kw):
        m = parse_month(request.query_params.get("month"), f.today)
        card = scorecard(f, m)
        goal, by = goal_for(m, f.today)
        national_goal, share_pct = goal, None
        if f.regions or f.states or f.asms or f.rsms:
            # a territory carries its share of the TD goal: its share of national sales in the same base months
            share_pct = territory_share(f, card)
            goal = national_goal * share_pct / 100 if share_pct else national_goal
        card["path"] = path_to_goal(f, card, goal, by)
        card["path"].update(national_goal=num(national_goal), territory_share_pct=share_pct)
        card["scope_label"] = scope_label(f)
        card["summary"] = executive_summary(card)
        card["sales_asks"] = sales_asks(f, card, card["path"])
        card["finance_asks"] = finance_asks(f, card)
        card["marketing_asks"] = marketing_asks(f, card)
        card["growth_drivers"] = growth_drivers(f, card)
        card.pop("_cur")
        card.pop("_trend")
        for t in card["trend"]:
            t.pop("_active", None)
        return card
