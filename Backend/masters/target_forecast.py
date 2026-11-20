"""TD Target Forecaster: suggests next month's sales target per ASM (and per distributor / overall).

Runs on the 27th of every month for the next month (Celery beat), and on demand:
    python manage.py forecast_targets --month 2026-12            # suggestion for Dec-26 from data to date
    python manage.py forecast_targets --backtest                 # walk-forward check: Feb-26 .. latest month

Why this design (data: ~17 ASMs x ~11 months of targets): a heavy ML model would memorise noise. The forecaster
is a small, explainable ensemble whose two free parameters are chosen by walk-forward backtesting:

1. Sales forecast per DISTRIBUTOR (history survives ASM handovers), summed to the ASM in charge next month.
   * Current month, seen on the 27th, is incomplete: month-to-date / (share of a month's sales normally done by
     that day, pooled over the last 6 full months).
   * Level = 0.5*this month + 0.3*last month + 0.2*the month before, each capped at 1.5x the 6-month median
     (one-off spikes - e.g. a bulk order - don't inflate next month).
   * Trend = median month-on-month growth of the last 6 months, clipped to [-15%, +25%], damped by PHI.
2. Stretch: how far management sets targets above what is then sold (target / actual sales), per ASM as the
   median log-ratio, shrunk towards the company median (partial pooling, prior weight PRIOR_N months) so a
   new ASM borrows from everyone. Clipped to [0.8, 2.0].
3. Suggested target = ALPHA * anchor + (1 - ALPHA) * stretch * sales forecast (targets are sticky: ~half the
   time unchanged), rounded to Rs 0.5 L like the team's sheets. ANCHOR = this month's target ("last") or the
   higher of this and last month's ("max2", robust to a one-off low month such as a copied sheet).
Distributor suggestions split the ASM's suggestion by the distributors' share of its sales forecast.

Accuracy is measured as WAPE = sum|suggested - set target| / sum(set target), against the naive baseline
"same as this month's target".
"""
import datetime as dt

from django.utils.timezone import localdate  # India date (TIME_ZONE), not the server clock
import math
import statistics
from collections import defaultdict
from decimal import Decimal

from django.db import transaction

MODEL_VERSION = "td-target-forecaster-1"
PARAMS = {"alpha": 0.5, "phi": 0.5, "anchor": "last"}  # replaced by the backtest's best (stored on each forecast)
GRID = {"alpha": [0.0, 0.25, 0.5, 0.75, 1.0], "phi": [0.0, 0.5, 1.0], "anchor": ["last", "max2"]}
PRIOR_N = 3
FIRST_TARGET_MONTH = dt.date(2026, 1, 1)
ROUND_TO = 50000  # Rs 0.5 lakh


def add_months(m, k):
    y, mo = m.year, m.month + k
    while mo > 12:
        y, mo = y + 1, mo - 12
    while mo < 1:
        y, mo = y - 1, mo + 12
    return dt.date(y, mo, 1)


def days_in(m):
    return (add_months(m, 1) - m).days


def rnd(v):
    return float(round(v / ROUND_TO) * ROUND_TO)


class History:
    """Everything the forecaster reads, loaded once: qualifying orders and set targets."""

    def __init__(self):
        from analytics.metrics import target_values
        from warehouse.models import Asm, Distributor, Order

        self.orders = list(Order.objects.filter(is_qualifying=True, distributor__isnull=False).values_list(
            "distributor_id", "asm_id", "placed_date", "gross_value"))
        last = max((o[2] for o in self.orders), default=localdate())
        months = [add_months(FIRST_TARGET_MONTH, k) for k in range(0, 36)
                  if add_months(FIRST_TARGET_MONTH, k) <= add_months(last.replace(day=1), 1)]
        self.targets = defaultdict(dict)  # asm_id -> {month: value}
        for (aid, m), v in target_values("asm", None, months).items():
            if v:
                self.targets[aid][m] = float(v)
        self.dist_targets = {(d, m): float(v) for (d, m), v in target_values("distributor", None, months).items() if v}
        self.asms = {a.id: a for a in Asm.objects.all()}
        self.dists = {d.id: d for d in Distributor.objects.select_related("asm")}
        self.last_order_day = last

    def asm_of(self, month):
        """{distributor_id: asm_id | None} in charge on the 1st of `month` (handover history)."""
        from masters.asm_tracker import asm_in_charge

        m = asm_in_charge(list(self.dists.values()), month)
        return {did: (a.id if a else None) for did, a in m.items()}


def _sales_by(orders, as_of, key):
    out = defaultdict(lambda: defaultdict(float))
    for did, aid, day, v in orders:
        if day <= as_of:
            out[did if key == "dist" else aid][day.replace(day=1)] += float(v)
    return out


def _done_by_day_share(orders, as_of):
    """Share of a month's sales normally done by day `as_of.day` (pooled, last 6 full months)."""
    cur = as_of.replace(day=1)
    by_day = full = 0.0
    for k in range(1, 7):
        m = add_months(cur, -k)
        cutoff = m.replace(day=min(as_of.day, days_in(m)))
        for _, _, day, v in orders:
            if m <= day < add_months(m, 1):
                full += float(v)
                if day <= cutoff:
                    by_day += float(v)
    share = by_day / full if full else as_of.day / days_in(cur)
    return min(max(share, 0.3), 1.0)


def _dist_forecast(series, cur, cur_est, phi):
    """Next-month sales for one distributor from its monthly series (dict month -> sales)."""
    hist = [series.get(add_months(cur, -k), 0.0) for k in range(5, 0, -1)] + [cur_est]  # 6 months, oldest first
    nz = [x for x in hist if x > 0]
    if not nz:
        return 0.0
    cap = 1.5 * statistics.median(nz)
    h = [min(x, cap) for x in hist]
    level = 0.5 * h[-1] + 0.3 * h[-2] + 0.2 * h[-3]
    growth = [h[i] / h[i - 1] - 1 for i in range(1, len(h)) if h[i - 1] > 0 and h[i] > 0]
    g = min(max(statistics.median(growth), -0.15), 0.25) if growth else 0.0
    return max(level * (1 + phi * g), 0.0)


def _stretch(h, as_of_month, asm_sales):
    """{asm_id: stretch} from set targets / actual sales of completed months before as_of_month (partial pooling)."""
    logs, per = [], defaultdict(list)
    for aid, tm in h.targets.items():
        for m, t in tm.items():
            s = asm_sales.get(aid, {}).get(m, 0.0)
            if m < as_of_month and s > 100000 and t > 0:
                r = math.log(t / s)
                logs.append(r)
                per[aid].append(r)
    g = statistics.median(logs) if logs else math.log(1.2)
    out = {}
    for aid in set(h.targets) | set(h.asms):
        xs = per.get(aid, [])
        mu = (len(xs) * statistics.median(xs) + PRIOR_N * g) / (len(xs) + PRIOR_N) if xs else g
        out[aid] = min(max(math.exp(mu), 0.8), 2.0)
    out[None] = min(max(math.exp(g), 0.8), 2.0)
    return out


def forecast(h, month, as_of, alpha, phi, anchor="last"):
    """Suggestions for `month` using only data known on `as_of` (orders <= as_of, targets for months < month)."""
    cur = as_of.replace(day=1)
    orders = [o for o in h.orders if o[2] <= as_of]
    share = _done_by_day_share(orders, as_of)
    full_month = as_of.day >= days_in(cur)
    dist_sales = _sales_by(orders, as_of, "dist")
    asm_sales = _sales_by(orders, as_of, "asm")
    stretch = _stretch(h, cur, asm_sales)
    owner = h.asm_of(month)

    fd = {}
    for did in h.dists:
        s = dist_sales.get(did, {})
        cur_est = s.get(cur, 0.0) if full_month else s.get(cur, 0.0) / share
        fd[did] = _dist_forecast(s, cur, cur_est, phi)
    by_asm = defaultdict(float)
    for did, v in fd.items():
        by_asm[owner.get(did)] += v

    asm_rows = {}
    for aid, f in by_asm.items():
        if aid is None:
            continue
        a = h.asms.get(aid)
        if a is None or (not a.is_active and f == 0):
            continue
        tm = h.targets.get(aid, {})
        last_t = tm.get(cur)
        if anchor == "max2" and tm.get(add_months(cur, -1)) is not None:
            # robust anchor: a one-off low month (e.g. a copied sheet) should not pull next month down
            last_t = max(last_t or 0.0, tm[add_months(cur, -1)])
        model = stretch.get(aid, stretch[None]) * f
        value = model if last_t is None else alpha * last_t + (1 - alpha) * model
        asm_rows[aid] = {"value": rnd(value), "sales_forecast": round(f, 2), "stretch": round(stretch.get(aid, stretch[None]), 3),
                         "last_target": last_t, "model_target": round(model, 2)}
    dist_rows = {}
    for did, f in fd.items():
        aid = owner.get(did)
        if aid in asm_rows and by_asm[aid] > 0:
            dist_rows[did] = rnd(asm_rows[aid]["value"] * f / by_asm[aid])
        elif aid is None and f > 0:
            dist_rows[did] = rnd(stretch[None] * f)
    overall = sum(r["value"] for r in asm_rows.values()) + sum(v for d, v in dist_rows.items() if owner.get(d) is None)
    return {"asm": asm_rows, "distributor": {d: {"value": v, "sales_forecast": round(fd[d], 2)} for d, v in dist_rows.items()},
            "overall": rnd(overall), "share_done": round(share, 3)}


def wape(pred, actual):
    keys = [k for k, v in actual.items() if v > 0]
    den = sum(actual[k] for k in keys)
    return (sum(abs(pred.get(k, 0.0) - actual[k]) for k in keys) / den) if den else None


def backtest(h=None, months=None, alpha=None, phi=None, anchor=None):
    """Walk-forward: for each target month M, forecast on the 27th of M-1 and compare with the set ASM targets."""
    h = h or History()
    months = months or [m for m in sorted({m for tm in h.targets.values() for m in tm}) if m > FIRST_TARGET_MONTH]
    grid = [(alpha, phi, anchor or "last")] if alpha is not None else [
        (a, p, an) for a in GRID["alpha"] for p in GRID["phi"] for an in GRID["anchor"]]
    out = {}
    for a, p, an in grid:
        per = []
        for m in months:
            as_of = add_months(m, -1).replace(day=27)
            fc = forecast(h, m, as_of, a, p, an)
            actual = {aid: tm[m] for aid, tm in h.targets.items() if m in tm}
            pred = {aid: r["value"] for aid, r in fc["asm"].items()}
            naive = {aid: tm.get(add_months(m, -1), 0.0) for aid, tm in h.targets.items() if m in tm}
            per.append({"month": m.isoformat()[:7], "wape": wape(pred, actual), "baseline_wape": wape(naive, actual),
                        "asms": len(actual), "target": sum(actual.values()), "suggested": sum(pred.get(k, 0) for k in actual)})
        out[(a, p, an)] = per
    return out


def choose_params(h, train_months):
    res = backtest(h, train_months)
    score = {k: statistics.mean([r["wape"] for r in v if r["wape"] is not None]) for k, v in res.items()}
    best = min(score, key=score.get)
    return {"alpha": best[0], "phi": best[1], "anchor": best[2]}, score


def next_month_after(day):
    return add_months(day.replace(day=1), 1)


@transaction.atomic
def run(month=None, as_of=None, h=None, tune=True):
    """Forecast `month` (default: next month) from data up to `as_of` (default: today / latest data) and store it."""
    from warehouse.models import TargetForecast

    h = h or History()
    as_of = as_of or min(localdate(), h.last_order_day)
    month = month or next_month_after(as_of)
    params, scores = dict(PARAMS), {}
    if tune:
        train = [m for m in sorted({m for tm in h.targets.values() for m in tm})
                 if FIRST_TARGET_MONTH < m <= as_of.replace(day=1)]
        if len(train) >= 3:
            params, scores = choose_params(h, train)
    fc = forecast(h, month, as_of, params["alpha"], params["phi"], params.get("anchor", "last"))
    key = (params["alpha"], params["phi"], params.get("anchor", "last"))
    details = {"params": params, "share_done_by_day": fc["share_done"],
               "train_wape": round(scores[key], 4) if scores else None}
    TargetForecast.objects.filter(month=month, as_of=as_of).delete()
    rows = [TargetForecast(month=month, scope_type="asm", scope_id=aid, value=Decimal(str(r["value"])),
                           sales_forecast=Decimal(str(r["sales_forecast"])), as_of=as_of, model_version=MODEL_VERSION,
                           details={**details, "stretch": r["stretch"], "last_target": r["last_target"],
                                    "model_target": r["model_target"]})
            for aid, r in fc["asm"].items()]
    rows += [TargetForecast(month=month, scope_type="distributor", scope_id=did, value=Decimal(str(r["value"])),
                            sales_forecast=Decimal(str(r["sales_forecast"])), as_of=as_of, model_version=MODEL_VERSION,
                            details=details) for did, r in fc["distributor"].items()]
    rows.append(TargetForecast(month=month, scope_type="overall", scope_id=None, value=Decimal(str(fc["overall"])),
                               sales_forecast=Decimal(str(sum(r["sales_forecast"] for r in fc["asm"].values()))),
                               as_of=as_of, model_version=MODEL_VERSION, details=details))
    TargetForecast.objects.bulk_create(rows)
    return {"month": month, "as_of": as_of, "params": params, "asms": len(fc["asm"]), "overall": fc["overall"],
            "train_wape": details["train_wape"]}


def latest_for(month):
    """{'as_of', 'model', 'params', 'asm': {id: value}, 'distributor': {id: value}, 'overall'} or None."""
    from warehouse.models import TargetForecast

    last = TargetForecast.objects.filter(month=month).order_by("-as_of").first()
    if last is None:
        return None
    qs = TargetForecast.objects.filter(month=month, as_of=last.as_of)
    out = {"as_of": last.as_of.isoformat(), "model": last.model_version, "params": last.details.get("params"),
           "asm": {}, "distributor": {}, "overall": None}
    for f in qs:
        if f.scope_type == "overall":
            out["overall"] = float(f.value)
        else:
            out[f.scope_type][f.scope_id] = float(f.value)
    return out
