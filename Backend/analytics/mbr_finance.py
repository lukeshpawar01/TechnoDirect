"""MBR page 3 - the Finance card: what we ask Finance for, with the numbers behind each ask.

  settle_cadence - pay distributors twice a week: today's payout rhythm (batches per week, days from delivery to
                   payout) from the finance settlement tracker, what is due and overdue now, and what changes
  incentives     - full Finance support for the ASM and sales executive incentive plan: people on the plan,
                   eligible amount, what is payable at current achievement, and paying it on time
"""
import datetime as dt
from collections import Counter

from .metrics import median, num
from .settlement import SLA_DAYS, base_qs, bucket

WEEKS = 8


def _inr(v):
    v = float(v or 0)
    return f"₹{v / 1e7:.2f} Cr" if v >= 1e7 else f"₹{v / 1e5:.1f} L" if v >= 1e5 else f"₹{v:,.0f}"


def settlement_cadence(f, today):
    rows = list(base_qs(f, with_period=False).values(
        "settled_on", "delivered_date", "dispatch_date", "order_date", "settlement_status", "payment_status",
        "fulfilment", "payable"))
    if not rows:
        return None
    since = today - dt.timedelta(weeks=WEEKS)
    batches, lags = Counter(), []
    for r in rows:
        if r["settlement_status"] == "settled" and r["settled_on"] and r["settled_on"] >= since:
            batches[r["settled_on"]] += float(r["payable"] or 0)
            if r["delivered_date"]:
                lags.append((r["settled_on"] - r["delivered_date"]).days)
    due = overdue = 0.0
    due_n = overdue_n = 0
    for r in rows:
        b, age = bucket(r, today)
        if b == "due":
            due += float(r["payable"] or 0)
            due_n += 1
            if age is not None and age > SLA_DAYS:
                overdue += float(r["payable"] or 0)
                overdue_n += 1
    weekdays = Counter(d.strftime("%a") for d in batches)
    per_week = len(batches) / WEEKS
    lags.sort()
    med = median(lags) if lags else None
    p90 = lags[int(len(lags) * 0.9)] if lags else None
    avg_batch = sum(batches.values()) / len(batches) if batches else 0
    return {"batches": len(batches), "per_week": round(per_week, 1), "weeks": WEEKS,
            "weekdays": [d for d, _ in weekdays.most_common(3)], "median_days": med, "p90_days": p90,
            "avg_batch": num(avg_batch), "due": num(due), "due_orders": due_n,
            "overdue": num(overdue), "overdue_orders": overdue_n, "sla_days": SLA_DAYS}


def incentive_plan(month):
    """The plan for the month reviewed, or the latest month with an incentive sheet before it."""
    from masters.incentives import ELIGIBLE_DEFAULT, tracker
    from warehouse.models import TargetSplit

    sheet = TargetSplit.objects.filter(month__lte=month).order_by("-month").values_list("month", flat=True).first()
    if not sheet:
        return None
    try:
        t = tracker(sheet)
    except Exception:  # the incentive sheet is optional; the MBR must not fail without it
        return None
    people = t.get("people") or []
    if not people:
        return None
    asms = [p for p in people if p["role"] == "asm"]
    execs = [p for p in people if p["role"] != "asm"]
    eligible = sum((p["base_incentive"] if p["base_incentive"] is not None else ELIGIBLE_DEFAULT) for p in people)
    payable = sum(p["incentive"] or (ELIGIBLE_DEFAULT * p["payout_pct"] / 100 if p["base_incentive"] is None else 0)
                  for p in people)
    earning = sum(1 for p in people if p["payout_pct"] > 0)
    return {"people": len(people), "asms": len(asms), "executives": len(execs), "eligible": num(eligible),
            "payable": num(payable), "earning": earning, "as_of": t.get("as_of"),
            "sheet_month": sheet.isoformat()[:7], "is_current": sheet == month}


def finance_asks(f, card):
    m = dt.date.fromisoformat(card["month"] + "-01")
    nxt = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    asks = []
    c = settlement_cadence(f, f.today)
    if c:
        now = (f"{c['per_week']:g} payout runs a week" + (f" (mostly {', '.join(c['weekdays'][:2])})" if c["weekdays"] else ""))
        lag = f"{c['median_days']:g} days from delivery to payout at the median, {c['p90_days']} at p90" if c["median_days"] is not None else ""
        asks.append({
            "kind": "settle_cadence", "priority": "high" if c["overdue"] or c["per_week"] < 2 else "medium",
            "title": "Settle distributors twice a week (e.g. Tuesday and Friday)",
            "detail": f"Today: {now} over the last {c['weeks']} weeks, {lag}. {_inr(c['due'])} is due and not settled "
                      f"({c['due_orders']:,} orders), of which {_inr(c['overdue'])} is past {c['sla_days']} days "
                      f"({c['overdue_orders']:,} order{'' if c['overdue_orders'] == 1 else 's'}). Two fixed runs a week keep every distributor's wait under 4 days "
                      f"after a batch closes, cut the overdue to zero and keep distributors stocking TD orders. "
                      f"Finance to confirm the two days, the cut-off time, and the bank / approval steps needed.",
            "value": c["due"], "value_label": "due now, not settled",
            "facts": c,
        })
    inc = incentive_plan(m)
    if inc:
        asks.append({
            "kind": "incentives", "priority": "high",
            "title": "Fund and pay the ASM & sales executive incentive plan on time",
            "detail": ("" if inc["is_current"] else f"No sheet for {m:%b %Y} yet; figures are from the latest sheet ({dt.date.fromisoformat(inc['sheet_month'] + '-01'):%b %Y}). ")
                      + f"{inc['people']} people are on the plan ({inc['asms']} ASMs, {inc['executives']} executives / field staff), "
                      f"{_inr(inc['eligible'])} eligible a month. At achievement so far {inc['earning']} of them earn a payout, "
                      f"{_inr(inc['payable'])} payable. Finance to approve the budget, release payouts by the 10th of "
                      f"{nxt:%B} with the salary run, and sign off the KPI data (Incentive tracker) each month so the team trusts it.",
            "value": inc["eligible"], "value_label": "eligible incentive a month",
            "facts": inc,
        })
    else:
        asks.append({
            "kind": "incentives", "priority": "high",
            "title": "Approve and fund the ASM & sales executive incentive plan",
            "detail": "No incentive sheet is loaded for this month. Finance to approve the plan (TD target 50%, new retailers 20%, "
                      "BO Gold/Platinum/Silver 20%, KYC 10%; 90%+ pays in full, 70–89% pays 90%), the monthly budget per person, "
                      "and the payout date.",
            "value": None, "value_label": "", "facts": None,
        })
    return {"asks": asks}
