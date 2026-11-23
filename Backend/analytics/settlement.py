"""Distributor settlement analytics. The data is the finance tracker, imported by masters/settlement.py.

Definitions (amounts in Rs; the "payable" is the sheet's Distributor Settlement = order value - customer refund):

Payable
    The amount owed to the distributor for an order. Loyalty points are carried by TechnoSport and are not
    deducted.
Settled
    Settlement status "Settled". `settled_on` is the payout ("Distributor Settlement Date").
Due, not settled
    The order is delivered, but its settlement status is Not settled or blank (not yet reviewed), and payment is
    not cancelled.
Not yet due
    The order is in transit or not dispatched, so it is not settled yet.
Overdue
    Due, not settled, and delivered more than `SLA_DAYS` days ago. Settled orders took 9 days from delivery at
    the median and 16 days at p90 (Feb–Nov 2026), so anything past 15 days is late.
PG charge
    PayU value - Customer Settlement (what PayU paid TechnoSport). Shown for context only; it is not deducted
    from the distributor.

Period
    By default the selected period filters the order date. With `date_basis=payout` it filters the payout date
    instead, which answers "what did we pay out this week".
"""
import datetime as dt
from collections import Counter, defaultdict

from .metrics import median

SLA_DAYS = 15
SDIMS = {"region": "region_id", "state": "state_id", "asm": "asm_id", "distributor": "distributor_id"}
STATUS_LABELS = {"settled": "Settled", "not_settled": "Not settled", "pending": "Not reviewed", "cancelled": "Cancelled"}
PAY_LABELS = {"approved": "Approved", "not_approved": "Not approved", "pending": "Not reviewed", "cancelled": "Cancelled"}
AGE_BUCKETS = [(0, 7, "0–7 days"), (8, 15, "8–15 days"), (16, 30, "16–30 days"), (31, 10 ** 6, "Over 30 days")]
FIELDS = ("id", "order_ref", "order_id", "distributor_id", "distributor__name", "order_date", "delivered_date",
          "dispatch_date",
          "fulfilment", "order_value", "payu_value", "customer_refund", "pg_settlement", "loyalty_points", "payable",
          "payment_status", "settlement_status", "settled_on", "issues", "multi_distributor", "courier_charge",
          "order__split_group", "customer")


def data_range():
    from django.db.models import Max, Min

    from warehouse.models import DistributorSettlement

    return DistributorSettlement.objects.aggregate(a=Min("order_date"), b=Max("order_date"), p=Max("settled_on"))


def base_qs(f, with_period=True, basis=None):
    """Settlement rows in scope, filters and (optionally) the period on the chosen date basis (`basis` overrides
    the page's Date basis: "payout" / "order")."""
    from warehouse.models import DistributorSettlement

    qs = DistributorSettlement.objects.filter(f.dims_q(SDIMS, retailer_field=None))
    if with_period:
        col = "settled_on" if (basis or f.date_basis) == "payout" else "order_date"
        # a chosen payout batch is shown whole: its orders' order dates may lie before the period
        if not (f.payout_dates and col == "order_date"):
            qs = qs.filter(**{f"{col}__gte": f.period.start, f"{col}__lte": f.period.end})
    if f.settle_statuses:
        qs = qs.filter(settlement_status__in=f.settle_statuses)
    if f.pay_statuses:
        qs = qs.filter(payment_status__in=f.pay_statuses)
    if f.payout_dates:
        qs = qs.filter(settled_on__in=f.payout_dates)
    if f.payment_modes:
        qs = qs.filter(payment_mode__in=f.payment_modes)
    if f.split_only is not None:  # Cart type: split (multi-distributor) parts only / single-distributor orders only
        qs = qs.filter(multi_distributor=f.split_only)
    return qs


def cart_parts(groups):
    """{split_group: [part, ...]} for split carts, ALL parts (also ones outside the filters, e.g. the partner)."""
    from warehouse.models import DistributorSettlement

    out = defaultdict(list)
    qs = (DistributorSettlement.objects.filter(order__split_group__in=[g for g in groups if g], multi_distributor=True)
          .values("order_ref", "order_id", "order__split_group", "distributor_id", "distributor__name", "order_value",
                  "payable", "courier_charge", "settlement_status", "payment_status", "settled_on", "fulfilment",
                  "delivered_date", "customer", "order_date")
          .order_by("order_ref"))
    for r in qs:
        out[r["order__split_group"]].append(r)
    return out


def split_block(rows, today):
    """Split (multi-distributor) carts among `rows`.

    It covers the share of all orders, the amount, how far settlement has got, which distributor pairs share carts,
    and a list of carts with every part. A cart is "partly settled" when one distributor has been paid and the
    other has not.
    """
    parts_in = [r for r in rows if r["multi_distributor"]]
    a = aggregate(parts_in, today)
    groups = {r["order__split_group"] for r in parts_in if r["order__split_group"]}
    all_parts = cart_parts(groups)
    carts, pairs = [], defaultdict(lambda: {"carts": 0, "value": 0.0})
    state_n = Counter()
    for g in groups:
        ps = all_parts.get(g, [])
        if not ps:
            continue
        names = sorted({p["distributor__name"] or "Unmapped" for p in ps})
        live = [p for p in ps if bucket(p, today)[0] != "cancelled"]  # a cancelled part owes nothing
        settled = [p for p in live if p["settlement_status"] == "settled"]
        if not live:
            state = "cancelled"
        elif len(settled) == len(live):
            state = "settled"
        else:
            state = "partly" if settled else "open"
        state_n[state] += 1
        value = sum(_f(p["order_value"]) for p in ps)
        # finance sometimes pays both parts to one distributor (part reassigned): say so instead of a one-name "pair"
        key = " + ".join(names) if len(names) > 1 else f"{names[0]} (both parts)"
        pairs[key]["carts"] += 1
        pairs[key]["value"] += value
        carts.append({
            "cart": g, "date": ps[0]["order_date"], "customer": ps[0]["customer"], "state": state,
            "order_value": round(value, 2), "payable": round(sum(_f(p["payable"]) for p in live), 2),
            "settled": round(sum(_f(p["payable"]) for p in settled), 2),
            "courier": round(sum(_f(p["courier_charge"]) for p in ps), 2),
            "parts": [{"order_ref": p["order_ref"], "order_id": p["order_id"], "distributor": p["distributor__name"],
                       "distributor_id": p["distributor_id"], "order_value": _f(p["order_value"]),
                       "payable": _f(p["payable"]), "courier": _f(p["courier_charge"]),
                       "settlement_status": p["settlement_status"], "settled_on": p["settled_on"],
                       "fulfilment": p["fulfilment"]} for p in ps],
        })
    order = {"partly": 0, "open": 1, "settled": 2, "cancelled": 3}
    carts.sort(key=lambda c: (order[c["state"]], -c["date"].toordinal(), c["cart"]))
    n_orders = len(rows)
    return {
        "carts": len(carts), "parts": len(parts_in),
        "share_pct": round(len(parts_in) / n_orders * 100, 1) if n_orders else None,
        "order_value": a["order_value"], "payable": a["payable"], "settled": a["settled"],
        "remaining": round(a["due"] + a["not_yet_due"], 2),
        "courier": round(sum(_f(r["courier_charge"]) for r in parts_in), 2),
        "states": {k: state_n.get(k, 0) for k in ("settled", "partly", "open", "cancelled")},
        "pairs": sorted(({"pair": k, "carts": v["carts"], "value": round(v["value"], 2)} for k, v in pairs.items()),
                        key=lambda x: -x["carts"])[:10],
        "list": carts[:150],
    }


def bucket(r, today):
    """settled / due / not_yet_due / cancelled, plus days since delivery for due rows."""
    if r["settlement_status"] == "settled":
        return "settled", None
    if r["settlement_status"] == "cancelled" or r["payment_status"] == "cancelled" or r["fulfilment"] == "cancelled":
        return "cancelled", None
    if r["fulfilment"] == "delivered":
        # finance often marks an order delivered before typing the delivery date: age it from the dispatch date
        # then (never later than the delivery), so it still ages and can turn overdue
        since = r["delivered_date"] or r.get("dispatch_date") or r["order_date"]
        return "due", (today - since).days
    return "not_yet_due", None


def _f(x):
    return float(x or 0)


def aggregate(rows, today):
    a = Counter()
    lags = []
    last = None
    for r in rows:
        b, age = bucket(r, today)
        pay = _f(r["payable"])
        a["orders"] += 1
        a["order_value"] += _f(r["order_value"])
        a["refunds"] += _f(r["customer_refund"])
        a["loyalty"] += _f(r["loyalty_points"])
        if b != "cancelled":
            a["payable"] += pay
        if r["pg_settlement"] is not None and r["payu_value"]:
            a["pg_charges"] += max(0.0, _f(r["payu_value"]) - _f(r["pg_settlement"]))
        a[f"{b}_orders"] += 1
        a[b] += pay if b != "cancelled" else _f(r["order_value"])
        if b == "due" and age is not None and age > SLA_DAYS:
            a["overdue"] += pay
            a["overdue_orders"] += 1
        if b == "settled" and r["settled_on"]:
            last = max(last, r["settled_on"]) if last else r["settled_on"]
            if r["delivered_date"]:
                lags.append((r["settled_on"] - r["delivered_date"]).days)
    lags.sort()
    out = {k: round(v, 2) if isinstance(v, float) else v for k, v in a.items()}
    for k in ("orders", "settled_orders", "due_orders", "not_yet_due_orders", "cancelled_orders", "overdue_orders"):
        out.setdefault(k, 0)
    for k in ("order_value", "refunds", "loyalty", "payable", "pg_charges", "settled", "due", "not_yet_due",
              "cancelled", "overdue"):
        out.setdefault(k, 0.0)
    out["settled_pct"] = round(out["settled"] / out["payable"] * 100, 1) if out["payable"] else None
    out["median_days"] = median(lags) if lags else None
    out["p90_days"] = lags[int(len(lags) * 0.9)] if lags else None
    out["last_payout"] = last.isoformat() if last else None
    return out


def _week(d):
    return d - dt.timedelta(days=d.weekday())


def summary(f):
    today = f.today
    rng = data_range()
    if rng["b"] is None:
        return {"available": False}
    rows = list(base_qs(f).values(*FIELDS))
    k = aggregate(rows, today)

    by_status = defaultdict(lambda: {"orders": 0, "payable": 0.0, "order_value": 0.0})
    by_pay = defaultdict(lambda: {"orders": 0, "payable": 0.0, "order_value": 0.0})
    for r in rows:
        for d, key in ((by_status, r["settlement_status"]), (by_pay, r["payment_status"])):
            d[key]["orders"] += 1
            d[key]["payable"] += _f(r["payable"])
            d[key]["order_value"] += _f(r["order_value"])

    # order weeks: what was ordered each week and how much of it is paid out
    weeks = defaultdict(Counter)
    for r in rows:
        b, _ = bucket(r, today)
        w = weeks[_week(r["order_date"])]
        w["orders"] += 1
        w[b] += _f(r["payable"]) if b != "cancelled" else 0
    weekly = [{"week": w.isoformat(), "orders": c["orders"], "settled": round(c["settled"], 2),
               "due": round(c["due"], 2), "not_yet_due": round(c["not_yet_due"], 2)}
              for w, c in sorted(weeks.items())]

    # payout batches (Distributor Settlement Date): always WHOLE batches - every order paid on a date in the period,
    # whatever its order date (with "Period = order date" a batch used to lose the older orders paid in it, e.g. the
    # 18 Nov 2026 batch showed Rs 1.15 Cr of its Rs 1.18 Cr: six October orders were cut)
    payout_rows = rows if f.date_basis == "payout" else list(base_qs(f, basis="payout").values(*FIELDS))
    batches = defaultdict(lambda: {"orders": 0, "amount": 0.0, "distributors": set(), "lags": []})
    for r in payout_rows:
        if r["settlement_status"] == "settled" and r["settled_on"]:
            b = batches[r["settled_on"]]
            b["orders"] += 1
            b["amount"] += _f(r["payable"])
            b["distributors"].add(r["distributor_id"])
            if r["delivered_date"]:
                b["lags"].append((r["settled_on"] - r["delivered_date"]).days)
    payouts = [{"date": d.isoformat(), "orders": b["orders"], "amount": round(b["amount"], 2),
                "distributors": len(b["distributors"]), "median_days": median(b["lags"]) if b["lags"] else None}
               for d, b in sorted(batches.items(), reverse=True)]

    ageing = [{"bucket": label, "orders": 0, "amount": 0.0} for _, _, label in AGE_BUCKETS]
    for r in rows:
        b, age = bucket(r, today)
        if b != "due":
            continue
        for i, (lo, hi, _) in enumerate(AGE_BUCKETS):
            if lo <= (age if age is not None else 0) <= hi:
                ageing[i]["orders"] += 1
                ageing[i]["amount"] = round(ageing[i]["amount"] + _f(r["payable"]), 2)
                break

    issues = Counter()
    for r in rows:
        for n in r["issues"] or []:
            issues["reassigned" if n.startswith("reassigned") else n] += 1

    return {
        "available": True,
        "basis": f.date_basis,
        "sla_days": SLA_DAYS,
        "data": {"from": rng["a"].isoformat(), "until": rng["b"].isoformat(),
                 "last_payout": rng["p"].isoformat() if rng["p"] else None},
        "kpis": k,
        "by_status": [{"status": s, "label": STATUS_LABELS[s], **{kk: round(v, 2) if isinstance(v, float) else v
                                                                  for kk, v in by_status[s].items()}}
                      for s in STATUS_LABELS if s in by_status],
        "by_payment": [{"status": s, "label": PAY_LABELS[s], **{kk: round(v, 2) if isinstance(v, float) else v
                                                               for kk, v in by_pay[s].items()}}
                       for s in PAY_LABELS if s in by_pay],
        "weekly": weekly,
        "payouts": payouts,
        "ageing": ageing,
        "issues": [{"issue": i, "orders": n} for i, n in issues.most_common()],
        "split": split_block(rows, today),
    }


def by_distributor(f):
    from warehouse.models import Distributor

    today = f.today
    groups = defaultdict(list)
    for r in base_qs(f).values(*FIELDS):
        groups[r["distributor_id"]].append(r)
    meta = {d.id: d for d in Distributor.objects.filter(id__in=[i for i in groups if i]).select_related("asm", "state")}
    rows = []
    for did, rs in groups.items():
        d = meta.get(did)
        a = aggregate(rs, today)
        payouts = {r["settled_on"] for r in rs if r["settlement_status"] == "settled" and r["settled_on"]}
        rows.append({
            "id": did, "distributor": d.name if d else "Unmapped", "asm": d.asm.name if d and d.asm_id else None,
            "state": d.state.name if d and d.state_id else None,
            "orders": a["orders"], "order_value": a["order_value"], "refunds": a["refunds"], "payable": a["payable"],
            "settled": a["settled"], "settled_pct": a["settled_pct"], "due": a["due"], "due_orders": a["due_orders"],
            "overdue": a["overdue"], "overdue_orders": a["overdue_orders"], "not_yet_due": a["not_yet_due"],
            "payouts": len(payouts), "last_payout": a["last_payout"], "median_days": a["median_days"],
            "split_orders": sum(1 for r in rs if r["multi_distributor"]),
            "split_payable": round(sum(_f(r["payable"]) for r in rs if r["multi_distributor"]), 2),
        })
    rows.sort(key=lambda r: (-r["due"], -r["payable"]))
    total = aggregate([r for rs in groups.values() for r in rs], today)
    return {"rows": rows, "total": total}


def _bridge(rows, k, today):
    """Order value - cancelled orders - refunds on live orders (+ sheet adjustments) = payable = settled + remaining."""
    ov = cancelled = refunds = payable = 0.0
    for r in rows:
        b, _ = bucket(r, today)
        ov += _f(r["order_value"])
        if b == "cancelled":
            cancelled += _f(r["order_value"])
        else:
            refunds += _f(r["customer_refund"])
            payable += _f(r["payable"])
    adj = payable - (ov - cancelled - refunds)
    return {"order_value": round(ov, 2), "cancelled": round(cancelled, 2), "refunds": round(refunds, 2),
            "adjustments": round(adj, 2) if abs(adj) >= 1 else 0.0, "payable": round(payable, 2),
            "settled": k["settled"], "due": k["due"], "not_yet_due": k["not_yet_due"],
            "remaining": round(k["due"] + k["not_yet_due"], 2)}


def distributor_statement(f, pk):
    """One distributor's statement in the period, with filters applied. It holds:
    - how order value reconciles to the payable;
    - how much of the payable is settled and how much remains;
    - payout history with a running total;
    - a monthly trend and the open orders.
    """
    from dataclasses import replace

    from warehouse.models import Distributor

    d = Distributor.objects.select_related("asm__rsm", "state").filter(id=pk).first()
    g = replace(f, distributors=[pk])
    data = summary(g)
    if not data.get("available"):
        return {"available": False}
    today = f.today
    rows = list(base_qs(g).values(*FIELDS))

    months = defaultdict(Counter)
    for r in rows:
        b, _ = bucket(r, today)
        m = months[r["order_date"].replace(day=1)]
        if b != "cancelled":
            m["payable"] += _f(r["payable"])
            m[b] += _f(r["payable"])
        m["orders"] += 1
    monthly = [{"month": m.isoformat(), "orders": c["orders"], "payable": round(c["payable"], 2),
                "settled": round(c["settled"], 2), "remaining": round(c["due"] + c["not_yet_due"], 2)}
               for m, c in sorted(months.items())]

    # payout history, oldest first with running total, then shown newest first
    run = 0.0
    hist = []
    for p in sorted(data["payouts"], key=lambda x: x["date"]):
        run += p["amount"]
        hist.append({**p, "cumulative": round(run, 2)})
    hist.reverse()
    gaps = [(dt.date.fromisoformat(a["date"]) - dt.date.fromisoformat(b["date"])).days
            for a, b in zip(hist, hist[1:])]

    open_rows = []
    for r in rows:
        b, age = bucket(r, today)
        if b in ("due", "not_yet_due"):
            open_rows.append({"order_ref": r["order_ref"], "order_id": r["order_id"], "customer": r["customer"],
                              "order_date": r["order_date"], "delivered_date": r["delivered_date"],
                              "fulfilment": r["fulfilment"], "payable": _f(r["payable"]), "state": b,
                              "settlement_status": r["settlement_status"], "payment_status": r["payment_status"],
                              "days_since_delivery": age, "overdue": b == "due" and age is not None and age > SLA_DAYS})
    open_rows.sort(key=lambda x: (x["state"] != "due", -(x["days_since_delivery"] or -1), -x["payable"]))

    k = data["kpis"]
    return {
        **data,
        "distributor": {"id": pk, "name": d.name if d else "Unmapped", "asm": d.asm.name if d and d.asm_id else None,
                        "rsm": d.asm.rsm.name if d and d.asm_id and d.asm.rsm_id else None,
                        "state": d.state.name if d and d.state_id else None},
        # order value -> payable -> settled + remaining
        "bridge": _bridge(rows, k, today),
        "monthly": monthly,
        "payouts": hist,
        "payout_gap_days": median(gaps) if gaps else None,
        "open_orders": open_rows,
    }
