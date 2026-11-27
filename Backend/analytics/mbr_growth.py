"""MBR page 3 (Growth actions) - what drove the month's growth: KYC, BlueOrigin tiers and new retailers.

Same like-for-like windows as the scorecard (a month in progress is compared on the same days of last month).
  tiers  - sales, transacting retailers and new retailers by BlueOrigin tier (Platinum ... Untiered, Not in
           BlueOrigin), the tier's share of TD's growth, and TD's reach in the tier (BlueOrigin retailers of that
           tier transacting on TD this month / all BlueOrigin retailers of the tier)
  kyc    - KYC-approved sign-ups of the month (the data has no approval date) and how many ordered, from the scorecard
  new    - first-time buyers: how many, their sales and share, and their first-month spend vs repeat buyers'
  reads  - three or four plain conclusions for planning
"""
import datetime as dt
from collections import defaultdict

from django.db.models import Count, Q

from warehouse.models import BoRetailer

from .filters import add_months
from .metrics import delta_pct, num, pct

TIERS = ["Platinum", "Gold", "Silver", "Green", "Yellow", "Untiered", "Not in BlueOrigin"]
TOP = {"Platinum", "Gold", "Silver"}


def _inr(v):
    v = float(v or 0)
    a = abs(v)
    s = f"₹{a / 1e7:.2f} Cr" if a >= 1e7 else f"₹{a / 1e5:.1f} L" if a >= 1e5 else f"₹{a:,.0f}"
    return ("−" if v < 0 else "") + s


def _windows(card):
    from .mbr import window

    m = dt.date.fromisoformat(card["month"] + "-01")
    today = dt.date.fromisoformat(card["as_of"]) if card["partial"] else None
    days = card["days_elapsed"] if card["partial"] else None
    cur = window(m, days, today or dt.date.max)
    prev = window(add_months(m, -1), days, cur[1])
    return cur, prev


def _by_tier(f, s, e):
    """{tier: {sales, retailers:set, new:set, new_sales}}"""
    out = defaultdict(lambda: {"sales": 0.0, "retailers": set(), "new": set(), "new_sales": 0.0})
    for rid, v, tier, first in f.orders(start=s, end=e).values_list(
            "retailer_id", "gross_value", "retailer__tier", "retailer__first_order_date"):
        t = tier if tier in TIERS else "Not in BlueOrigin"
        o = out[t]
        o["sales"] += float(v or 0)
        o["retailers"].add(rid)
        if first and s <= first <= e:
            o["new"].add(rid)
            o["new_sales"] += float(v or 0)
    return out


def growth_drivers(f, card):
    (cs, ce), (ps, pe) = _windows(card)
    cur, prev = _by_tier(f, cs, ce), _by_tier(f, ps, pe)
    total = sum(t["sales"] for t in cur.values())
    prev_total = sum(t["sales"] for t in prev.values())
    change = total - prev_total
    bo = {r["tier"]: r for r in BoRetailer.objects.filter(tier__in=TIERS).values("tier").annotate(
        n=Count("id"), on_td=Count("id", filter=Q(td_retailer__kyc_status="approved")))}  # on TD = KYC-approved link

    tiers = []
    for t in TIERS:
        c, p = cur.get(t), prev.get(t)
        cs_, ps_ = (c["sales"] if c else 0.0), (p["sales"] if p else 0.0)
        n_cur = len(c["retailers"]) if c else 0
        b = bo.get(t)
        tiers.append({
            "tier": t, "sales": num(cs_), "prev_sales": num(ps_), "change": num(cs_ - ps_),
            "mom_pct": delta_pct(cs_, ps_) if ps_ else None,
            "share_pct": pct(cs_, total), "growth_share_pct": round((cs_ - ps_) / change * 100, 1) if change > 0 else None,
            "retailers": n_cur, "prev_retailers": len(p["retailers"]) if p else 0,
            "new": len(c["new"]) if c else 0, "new_sales": num(c["new_sales"]) if c else 0.0,
            "spend": num(cs_ / n_cur) if n_cur else None,
            "bo_retailers": b["n"] if b else None, "bo_on_td": b["on_td"] if b else None,
            "reach_pct": pct(n_cur, b["n"]) if b and b["n"] else None,
        })

    rows = {r["key"]: r for r in card["rows"]}
    kyc = {k: {"value": rows[k]["value"], "prev": rows[k]["prev"]} for k in ("kyc_new", "kyc_to_order_pct", "kyc_base", "ants")
           if k in rows}

    new_n = sum(t["new"] for t in tiers)
    new_sales = sum(t["new_sales"] for t in tiers)
    all_n = sum(t["retailers"] for t in tiers)
    repeat_spend = (total - new_sales) / (all_n - new_n) if all_n - new_n else None
    new_spend = new_sales / new_n if new_n else None
    prev_new = sum(len(v["new"]) for v in prev.values())
    new = {"retailers": new_n, "prev_retailers": prev_new, "sales": num(new_sales), "share_pct": pct(new_sales, total),
           "spend": num(new_spend) if new_spend else None, "repeat_spend": num(repeat_spend) if repeat_spend else None,
           "from_bo": sum(t["new"] for t in tiers if t["tier"] != "Not in BlueOrigin")}

    return {"window": {"current": f"{cs:%d %b}–{ce:%d %b %Y}", "previous": f"{ps:%d %b}–{pe:%d %b %Y}"},
            "total": num(total), "change": num(change), "tiers": tiers, "kyc": kyc, "new": new,
            "reads": _reads(tiers, kyc, new, change, total)}


def _reads(tiers, kyc, new, change, total):
    out = []
    by = {t["tier"]: t for t in tiers}
    top = [by[t] for t in ("Platinum", "Gold", "Silver")]
    top_change = sum(t["change"] for t in top)
    top_sales = sum(t["sales"] for t in top)
    nobo = by["Not in BlueOrigin"]
    if change:
        out.append({"tone": "good" if change > 0 else "bad",
                    "text": f"Sales moved {_inr(change)}: Platinum/Gold/Silver {_inr(top_change)} "
                            f"({pct(top_sales, total) or 0:.0f}% of sales), retailers not in BlueOrigin {_inr(nobo['change'])}, "
                            f"Green/Yellow/Untiered {_inr(sum(by[t]['change'] for t in ('Green', 'Yellow', 'Untiered')))}."})
    bo_top = sum(t["bo_retailers"] or 0 for t in top)
    buying = sum(t["retailers"] for t in top)
    if bo_top:
        spend = top_sales / buying if buying else 0
        gap = bo_top - buying
        out.append({"tone": "warn",
                    "text": f"Only {buying:,} of {bo_top:,} Platinum/Gold/Silver BlueOrigin retailers ordered on TD this month "
                            f"({buying / bo_top * 100:.0f}% reach). Those buying spend {_inr(spend)} a month on average: "
                            f"bringing in 10% of the rest ({gap // 10:,}) at that spend adds about {_inr(gap // 10 * spend)} a month."})
    if new["retailers"]:
        cmp_ = (f", against {_inr(new['repeat_spend'])} for a repeat buyer" if new["repeat_spend"] else "")
        out.append({"tone": "neutral",
                    "text": f"{new['retailers']:,} new retailers ({new['from_bo']:,} of them known to BlueOrigin) brought "
                            f"{_inr(new['sales'])}, {new['share_pct'] or 0:.0f}% of sales; first-month spend {_inr(new['spend'])}{cmp_}."})
    k, conv = kyc.get("kyc_new"), kyc.get("kyc_to_order_pct")
    if k and conv and kyc.get("ants"):
        out.append({"tone": "warn" if (conv["value"] or 0) < 20 else "good",
                    "text": f"{k['value']:,} KYC approvals among this month's sign-ups (last month {k['prev']:,}); "
                            f"{conv['value'] or 0:.0f}% ordered in the same month. {kyc['ants']['value']:,} KYC-approved "
                            f"retailers have never ordered: the cheapest growth is converting them."})
    return out
