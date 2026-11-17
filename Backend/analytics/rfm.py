"""RFM segmentation of the retailer base ("RFM Segmentation Logic", TD, Nov-2026).

Replaces the Power BI RFM_FinalTable / RFMCategory (fixed DAX thresholds that scored all 2 lakh sign-ups).

1. Lifecycle first - every retailer gets exactly one:
     prospect          no valid order up to the as-of date (never scored)
     churned           silent > CHURN_RATIO x own expected gap  AND  > population P90 gap
     no_orders_in_range  not churned, but no order inside the F/M window
     active            everyone else who has ordered -> scored
2. Measures (active only)
     expected_gap  = (n * own_median_gap + K * population_median_gap) / (n + K)   n = order-days - 1
     recency_ratio = days_since_last_order / expected_gap                          (lower = better)
     tenure_months = max(MIN_TENURE_M, months from max(first order, window start) to as-of)
     F = orders in window / tenure_months,  M = value in window / tenure_months
3. Scores 1..5 against P20/P40/P60/P80 of ACTIVE buyers, strict comparisons (a tie stays at the lower score).
4. Segment = grid(R score, FM = round_half_up((F + M) / 2)); "new" (first order within NEW_DAYS) decided first.

Data rules (ours, stricter than the PDF's dispatch proxy, which the PDF says to replace with a real status):
valid order = is_qualifying (paid, not cancelled) and value > 0; value = gross order value (line totals, the
dashboard's sales basis); several orders on one IST day = one order-day for gaps; orders counted by split_group.
Cut-offs are always ranked against ALL active buyers, so "Champion" means the same for every distributor / ASM
(the PDF's p_rank_within_selection = false); dashboard filters only choose which retailers are shown.
"""
import datetime as dt
import math
import statistics
from collections import defaultdict

WINDOW_MONTHS = 24
# Chosen on our own order history (walk-forward back-tests, Jan/Mar/May-2026 + 6 months), not copied from the PDF:
# 4x writes off fewer retailers who do come back (20.9% vs 23.1% at 3x) and separates segments slightly better;
# shrink k = 2 and the 24-month window scored best; new-days and tenure floor made no difference.
CHURN_RATIO = 4.0
NEW_DAYS = 30
MIN_TENURE_M = 3
SHRINK_K = 2
DAYS_PER_MONTH = 30.4375

# (label, recommended action) in display order; keys are the API values
SEGMENTS = {
    "champions": ("Champions", "Ordering at or ahead of their usual rhythm, high frequency and value.",
                  "Early access to new styles, priority dispatch, referral asks."),
    "loyal": ("Loyal Customers", "High frequency and value, ordering roughly on rhythm.",
              "Upsell new categories, volume slabs."),
    "potential_loyalists": ("Potential Loyalists", "Recent, mid frequency and value.",
                            "Nudge into a regular reorder cycle; loyalty-point boosts."),
    "new_customers": ("New Customers", f"First order within the last {NEW_DAYS} days.",
                      "Onboarding call; second-order offer within 2-3 weeks."),
    "promising": ("Promising", "Recent but low frequency and value.", "Bigger-basket offers, best-seller bundles."),
    "needs_attention": ("Needs Attention", "Slightly behind rhythm, mid frequency and value.",
                        "Distributor follow-up; check stock-outs on their usual styles."),
    "about_to_sleep": ("About to Sleep", "Slightly behind rhythm, low frequency and value.",
                       "Reminder before their usual reorder date."),
    "cant_lose": ("Can't Lose Them", "Well behind rhythm but historically high value.",
                  "Personal call from distributor or ASM this week."),
    "at_risk": ("At Risk", "Well behind rhythm, mid value.", "Win-back offer; ask why they stopped."),
    "hibernating": ("Hibernating", "Well behind rhythm, low value.", "Low-cost automated reminders."),
    "no_orders_in_range": ("No Orders in Range", f"Not churned, but no order in the last {WINDOW_MONTHS} months.",
                           "Check if still trading; reactivation call."),
    "churned": ("Churned", f"Silent for over {CHURN_RATIO:g}x their usual gap and longer than 90% of all reorder gaps.",
                "Win-back campaign; call the high-value ones."),
    "prospect": ("Prospect", "Registered, never ordered.", "Activation funnel: KYC, first-order offer."),
}
SCORED = ["champions", "loyal", "potential_loyalists", "new_customers", "promising", "needs_attention",
          "about_to_sleep", "cant_lose", "at_risk", "hibernating"]

# rows R5..R1, columns FM1..FM5
GRID = {
    5: ["promising", "promising", "potential_loyalists", "champions", "champions"],
    4: ["promising", "promising", "potential_loyalists", "champions", "champions"],
    3: ["about_to_sleep", "about_to_sleep", "needs_attention", "loyal", "loyal"],
    2: ["hibernating", "hibernating", "at_risk", "cant_lose", "cant_lose"],
    1: ["hibernating", "hibernating", "at_risk", "cant_lose", "cant_lose"],
}


def add_months(d, k):
    y, m = d.year, d.month + k
    while m > 12:
        y, m = y + 1, m - 12
    while m < 1:
        y, m = y - 1, m + 12
    return d.replace(year=y, month=m, day=min(d.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28,
                                                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]))


def percentile(values, p):
    """Linear interpolation between closest ranks (= Postgres percentile_cont)."""
    v = sorted(values)
    x = p * (len(v) - 1)
    lo = math.floor(x)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (x - lo)


def cutoffs(values):
    """[P20, P40, P60, P80] of the values, or None when empty."""
    return [percentile(values, p) for p in (0.2, 0.4, 0.6, 0.8)] if values else None


def score_high(x, c):
    return 1 + sum(x > t for t in c)


def score_low(x, c):
    return 1 + sum(x < t for t in c)


def round_half_up(x):
    return int(math.floor(x + 0.5))


def load_orders(as_of=None):
    """[(retailer_id, day, split_group, value)] of valid orders up to as_of."""
    from warehouse.models import Order

    qs = Order.objects.filter(is_qualifying=True, gross_value__gt=0, retailer__isnull=False)
    if as_of:
        qs = qs.filter(placed_date__lte=as_of)
    return list(qs.values_list("retailer_id", "placed_date", "split_group", "gross_value"))


def compute(as_of=None, orders=None, window_months=WINDOW_MONTHS, churn_ratio=CHURN_RATIO, new_days=NEW_DAYS,
            min_tenure_m=MIN_TENURE_M, shrink_k=SHRINK_K):
    """RFM for every retailer that has ordered, as of `as_of` (default: latest order date; never a future date).

    Returns {"as_of", "window_start", "population": {...}, "cutoffs": {...}, "rows": {retailer_id: {...}}}.
    Retailers missing from rows are prospects (never ordered by as_of)."""
    if orders is None:
        orders = load_orders()
    orders = [o for o in orders if o[3] and float(o[3]) > 0]  # test / free orders are not sales
    if not orders:
        return {"as_of": as_of, "rows": {}, "cutoffs": None, "population": {}}
    latest = max(o[1] for o in orders)
    as_of = min(as_of or latest, latest)
    start = add_months(as_of, -window_months) + dt.timedelta(days=1)

    days = defaultdict(set)
    win_orders = defaultdict(set)
    win_value = defaultdict(float)
    for rid, d, grp, v in orders:
        if d > as_of or not v or float(v) <= 0:  # test / free orders are not sales
            continue
        days[rid].add(d)
        if d >= start:
            win_orders[rid].add(grp or (d, v))
            win_value[rid] += max(float(v), 0.0)

    own_gaps, all_gaps = {}, []
    for rid, ds in days.items():
        s = sorted(ds)
        g = [(b - a).days for a, b in zip(s, s[1:])]
        own_gaps[rid] = g
        all_gaps.extend(g)
    pop_median = statistics.median(all_gaps) if all_gaps else 30.0
    pop_p90 = percentile(all_gaps, 0.9) if all_gaps else pop_median

    rows = {}
    for rid, ds in days.items():
        s = sorted(ds)
        first, last = s[0], s[-1]
        g = own_gaps[rid]
        n = len(g)
        own_med = statistics.median(g) if g else pop_median
        expected = (n * own_med + shrink_k * pop_median) / (n + shrink_k)
        since = (as_of - last).days
        ratio = since / expected if expected > 0 else float(since)
        r = {"first_order": first, "last_order": last, "days_since": since, "order_days": len(s),
             "expected_gap": round(expected, 1), "recency_ratio": round(ratio, 3),
             "orders": len(win_orders.get(rid, ())), "value": round(win_value.get(rid, 0.0), 2)}
        if since > churn_ratio * expected and since > pop_p90:
            r["lifecycle"] = "churned"
        elif not win_orders.get(rid):
            r["lifecycle"] = "no_orders_in_range"
        else:
            r["lifecycle"] = "active"
            tenure = max(min_tenure_m, (as_of - max(first, start)).days / DAYS_PER_MONTH)
            r["tenure_months"] = round(tenure, 2)
            r["f"] = r["orders"] / tenure
            r["m"] = r["value"] / tenure
        rows[rid] = r

    active = [r for r in rows.values() if r["lifecycle"] == "active"]
    cut = None
    if active:
        cut = {"recency_ratio": cutoffs([r["recency_ratio"] for r in active]),
               "orders_per_month": cutoffs([r["f"] for r in active]),
               "value_per_month": cutoffs([r["m"] for r in active])}
        for r in active:
            r["r_score"] = score_low(r["recency_ratio"], cut["recency_ratio"])
            r["f_score"] = score_high(r["f"], cut["orders_per_month"])
            r["m_score"] = score_high(r["m"], cut["value_per_month"])
            r["fm"] = round_half_up((r["f_score"] + r["m_score"]) / 2)
            if (as_of - r["first_order"]).days < new_days:
                r["segment"] = "new_customers"
            else:
                r["segment"] = GRID[r["r_score"]][r["fm"] - 1]
    for r in rows.values():
        r.setdefault("segment", r["lifecycle"])
        if "f" in r:
            r["f"] = round(r["f"], 3)
            r["m"] = round(r["m"], 2)
    return {"as_of": as_of, "window_start": start, "rows": rows,
            "population": {"median_gap": pop_median, "p90_gap": round(pop_p90, 1), "buyers": len(rows),
                           "active": len(active)},
            "cutoffs": cut}


def returned_within(orders, as_of, months=6):
    """{retailer_id} with a valid order in (as_of, as_of + months]."""
    end = add_months(as_of, months)
    return {rid for rid, d, _, _ in orders if as_of < d <= end}


# ----------------------------------------------------------------------------- dashboard access
def as_of_for(f):
    """RFM is a state 'as of' the end of the selected period (never later than today / the latest order)."""
    return min(f.period.end, f.today)


def snapshot(as_of):
    """compute(as_of), cached until the data changes (bump_cache_version)."""
    from .cache import cache_version, get_or_compute

    return get_or_compute(f"rfm:v{cache_version()}:{as_of.isoformat()}", lambda: compute(as_of=as_of))


def retailer_ids(segment, as_of):
    """Retailer ids in an RFM segment (list), or a Retailer queryset of ids for 'prospect'."""
    from warehouse.models import Retailer

    rows = snapshot(as_of)["rows"]
    if segment == "prospect":
        return Retailer.objects.exclude(id__in=list(rows)).values("id")
    return [rid for rid, r in rows.items() if r["segment"] == segment]


def describe(row):
    """API block for one retailer's RFM row (None row -> prospect)."""
    seg = row["segment"] if row else "prospect"
    label, meaning, action = SEGMENTS[seg]
    out = {"segment": seg, "label": label, "meaning": meaning, "action": action}
    if row:
        out.update({k: row.get(k) for k in ("lifecycle", "days_since", "expected_gap", "recency_ratio", "orders",
                                            "value", "tenure_months", "f", "m", "r_score", "f_score", "m_score", "fm")})
    return out


def backtest(as_of, months=6):
    """Segments as of (as_of - months) vs who ordered again in the following `months` (validation)."""
    from .cache import cache_version, get_or_compute

    def _calc():
        orders = load_orders()
        then = add_months(as_of, -months)
        snap = compute(as_of=then, orders=orders)
        back = returned_within(orders, snap["as_of"], months)
        agg = defaultdict(lambda: [0, 0])
        for rid, r in snap["rows"].items():
            agg[r["segment"]][0] += 1
            agg[r["segment"]][1] += rid in back
        return {"as_of": snap["as_of"].isoformat(), "months": months,
                "segments": [{"segment": s, "label": SEGMENTS[s][0], "retailers": agg[s][0],
                              "returned_pct": round(agg[s][1] * 100 / agg[s][0], 1)}
                             for s in SEGMENTS if agg[s][0]]}

    return get_or_compute(f"rfm-bt:v{cache_version()}:{as_of.isoformat()}:{months}", _calc)
