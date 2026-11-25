"""GET /api/analytics/mbr/?month=YYYY-MM - MBR page 1 scorecard and the page 2 path to the monthly sales goal."""
import datetime as dt

from rest_framework.exceptions import ValidationError

from ..filters import month_start
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
        card["path"] = path_to_goal(f, card, goal, by)
        card.pop("_cur")
        card.pop("_trend")
        for t in card["trend"]:
            t.pop("_active", None)
        return card
