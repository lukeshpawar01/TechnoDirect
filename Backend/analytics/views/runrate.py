"""Run rate (Executive Overview → "Run rate"): how fast sales are coming in against the target.

For the period's months that have a target (same rule as the Overview target card, metrics.target_block):
  current run rate   = sales so far / days elapsed
  last-7-day rate    = sales of the last 7 days (up to today / the period end) / 7
  required run rate  = target left / days left
  projected          = current run rate x all days of the targeted months
Overall plus one row per region / state / ASM / distributor (their own targets), within the user's scope.
"""
import datetime as dt
from collections import defaultdict

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from rest_framework.exceptions import ValidationError

from accounts.scope import DISTRIBUTOR_DIMS
from warehouse.models import Asm, Distributor, Region, State

from ..filters import month_end, months_between
from ..metrics import num, share, target_block, target_values
from .base import AnalyticsView

GROUPS = {  # group_by -> (target scope, order field, model, distributor field)
    "region": ("region", "region_id", Region, "region_id"),
    "state": ("state", "state_id", State, "state_id"),
    "asm": ("asm", "asm_id", Asm, "asm_id"),
    "distributor": ("distributor", "distributor_id", Distributor, "id"),
}


def status_of(target, achieved, projected, days_left):
    if not target:
        return "no_target"
    if achieved >= target:
        return "achieved"
    if days_left <= 0:
        return "missed"  # the period is over
    if projected >= target:
        return "on_track"
    if projected >= 0.9 * target:
        return "at_risk"
    return "behind"


def rates(target, achieved, days_total, days_elapsed, last7):
    remaining = days_total - days_elapsed
    balance = max(target - achieved, 0.0)
    crr = achieved / days_elapsed if days_elapsed else 0.0
    projected = crr * days_total
    req = balance / remaining if remaining > 0 else 0.0
    return {
        "target": num(target), "achieved": num(achieved), "achievement_pct": share(achieved, target) if target else None,
        "balance": num(balance), "days_elapsed": days_elapsed, "days_total": days_total, "days_left": remaining,
        "current_run_rate": num(crr), "last7_run_rate": num(last7 / 7), "required_run_rate": num(req),
        "gap_per_day": num(max(req - crr, 0.0)), "projected": num(projected),
        "projected_pct": share(projected, target) if target else None,
        "status": status_of(target, achieved, projected, remaining),
    }


class RunRateView(AnalyticsView):
    permission_code = "view_overview"
    export_key = "rows"

    def compute(self, f, request, **kw):
        group_by = request.query_params.get("group_by", "region")
        if group_by not in GROUPS:
            raise ValidationError({"group_by": "must be region, state, asm or distributor"})
        p = f.period
        eff_end = min(p.end, f.today)
        last7_from = eff_end - dt.timedelta(days=6)
        orders = f.orders()
        overall, tmap = target_block(f, orders)
        base = {"group_by": group_by, "as_of": eff_end.isoformat(), "last7_from": last7_from.isoformat()}
        if not f.targets_comparable:
            return {**base, "overall": None, "rows": [],
                    "note": "Targets are set per territory, so run rate vs target is not shown with a BO tier or segment filter."}
        note = None
        if overall is None:  # no target for the scope as a whole; the breakdown can still have its own targets
            note = "No overall target is set for this period and scope."
        else:
            last7 = float(orders.filter(placed_date__gte=last7_from, placed_date__lte=eff_end)
                          .aggregate(s=Sum("gross_value"))["s"] or 0)
            overall = {**overall, **rates(overall["target"], overall["achieved"], overall["days_total"],
                                          overall["days_elapsed"], last7)}

        scope, ofield, model, dfield = GROUPS[group_by]
        months = months_between(p.start, p.end)
        allowed = set(Distributor.objects.filter(f.dims_q(DISTRIBUTOR_DIMS, retailer_field=None))
                      .exclude(**{f"{dfield}__isnull": True}).values_list(dfield, flat=True).distinct())
        tv = defaultdict(dict)  # id -> {month: target}
        for (gid, m), v in target_values(scope, list(allowed), months, as_of=f.today).items():
            if v:
                tv[gid][m] = float(v)
        sales = defaultdict(lambda: defaultdict(float))  # id -> {month: sales up to eff_end}
        for r in (orders.filter(placed_date__gte=p.start, placed_date__lte=eff_end).exclude(**{f"{ofield}__isnull": True})
                  .annotate(m=TruncMonth("placed_date")).values(ofield, "m").annotate(s=Sum("gross_value"))):
            m = r["m"].date() if hasattr(r["m"], "date") else r["m"]
            sales[r[ofield]][m] += float(r["s"] or 0)
        recent = {r[ofield]: float(r["s"] or 0) for r in orders.filter(
            placed_date__gte=last7_from, placed_date__lte=eff_end).values(ofield).annotate(s=Sum("gross_value"))}
        names = dict(model.objects.filter(id__in=set(tv) | set(sales)).values_list("id", "name"))
        rows = []
        for gid in set(tv) | set(sales):
            if gid not in names:
                continue
            tm = tv.get(gid, {})
            targeted = sorted(tm) or months  # no target: rates over the whole period
            days_total = days_elapsed = 0
            achieved = 0.0
            for m in targeted:
                me = month_end(m)
                days_total += (me - m).days + 1
                days_elapsed += max(0, min((eff_end - m).days + 1, (me - m).days + 1))
                achieved += sales[gid].get(m, 0.0)
            row = {"id": gid, "name": names[gid], **rates(sum(tm.values()), achieved, days_total, days_elapsed,
                                                           recent.get(gid, 0.0))}
            rows.append(row)
        order = {"behind": 0, "missed": 0, "at_risk": 1, "on_track": 2, "achieved": 3, "no_target": 4}
        rows.sort(key=lambda r: (order[r["status"]], -(r["gap_per_day"] or 0), -r["achieved"]))
        counts = defaultdict(int)
        for r in rows:
            counts[r["status"]] += 1
        return {**base, "overall": overall, "rows": rows, "counts": dict(counts), "note": note}
