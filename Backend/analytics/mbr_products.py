"""MBR page 1 - product matrix: what TD sold this month, by category and style, and what it means.

Windows are the scorecard's like-for-like ones (a month in progress is compared on the same days of last month).
Categories are Category III (trackpants, t-shirts, jackets ...). Each category gets a role from two lines:
  share  - its fair share of sales (100 / number of categories that sold), and
  growth - TD's own MoM growth (a category growing faster than TD is gaining mix).
    core    : big and gaining        -> keep stocked, push depth
    defend  : big but losing mix     -> find out why (stock, price, season)
    rising  : small but gaining      -> candidates to scale
    watch   : small and losing mix   -> rationalise or fix
"""
import datetime as dt
from collections import defaultdict

from django.db.models import Count, Min, Sum

from warehouse.models import OrderLine, Product

from .metrics import delta_pct, num, pct, ratio
from .styles import base_style

TOP_CATEGORIES = 10
NEW_LAUNCH_DAYS = 90


def _lines(f, s, e):
    from .views.products import line_qs

    return line_qs(f, s, e)


def _by_category(lines):
    out = {}
    for r in lines.values("product__category_l3").annotate(
            s=Sum("total"), u=Sum("quantity"), r=Count("order__retailer_id", distinct=True),
            st=Count("style", distinct=True)):
        key = (r["product__category_l3"] or "").strip().lower() or "uncategorised"
        o = out.setdefault(key, {"s": 0.0, "u": 0, "r": 0, "st": 0})
        o["s"] += float(r["s"] or 0)
        o["u"] += r["u"] or 0
        o["r"] += r["r"] or 0
        o["st"] += r["st"] or 0
    return out


def _by_style(lines):
    out = defaultdict(lambda: {"s": 0.0, "u": 0, "name": None})
    for r in lines.values("style", "product__name").annotate(s=Sum("total"), u=Sum("quantity")):
        code = base_style(r["style"]) or r["style"] or "?"
        o = out[code]
        o["s"] += float(r["s"] or 0)
        o["u"] += r["u"] or 0
        o["name"] = o["name"] or r["product__name"]
    return out


def _title(k):
    if k == "uncategorised":
        return "Uncategorised"
    return k.title() if k in ("t-shirts", "gym-vests") else k.replace("-", " ").title()


def _role(share, growth, fair, td_growth):
    big = share >= fair
    if growth is None:  # nothing sold in the comparison window
        return "rising" if not big else "core"
    gaining = growth >= (td_growth or 0)
    return ("core" if gaining else "defend") if big else ("rising" if gaining else "watch")


CALLS = {
    "scale": "Growing faster than TD: put depth and distributor stock behind it",
    "defend": "Big but growing slower than TD: check stock, price and season",
    "fix": "Demand is there but best sellers are out of stock at distributors",
    "watch": "Small and losing share: fix the range or rationalise",
}
FIX_STOCK_SHARE = 15  # losing share and stock-out demand >= this % of the category's month sales -> "fix"
TAIL_SHARE = 10  # the long tail = the smallest styles that together make this % of sales


def product_matrix(f, m, cur_w, prev_w, month_end_, ly_w=None):
    cur_l, prev_l = _lines(f, *cur_w), _lines(f, *prev_w)
    cur_c, prev_c = _by_category(cur_l), _by_category(prev_l)
    ly_c = _by_category(_lines(f, *ly_w)) if ly_w else {}
    total = sum(c["s"] for c in cur_c.values())
    prev_total = sum(c["s"] for c in prev_c.values())
    td_growth = delta_pct(total, prev_total) if prev_total else None
    td_change = total - prev_total
    buyers = cur_l.values("order__retailer_id").distinct().count()
    prev_buyers = prev_l.values("order__retailer_id").distinct().count()

    sold = [k for k, c in cur_c.items() if c["s"] > 0]
    fair = 100 / len(sold) if sold else 0
    top_style = {}
    for r in cur_l.values("product__category_l3", "style").annotate(s=Sum("total")).order_by("-s"):
        key = (r["product__category_l3"] or "").strip().lower() or "uncategorised"
        top_style.setdefault(key, base_style(r["style"]) or r["style"])

    cats = []
    for k in sorted(set(cur_c) | set(prev_c), key=lambda k: -cur_c.get(k, {}).get("s", 0)):
        c, p = cur_c.get(k, {"s": 0.0, "u": 0, "r": 0, "st": 0}), prev_c.get(k)
        if not c["s"] and not (p and p["s"]):
            continue
        share = pct(c["s"], total) or 0
        growth = delta_pct(c["s"], p["s"]) if p and p["s"] else None
        asp, prev_asp = ratio(c["s"], c["u"]), ratio(p["s"], p["u"]) if p else None
        cats.append({
            "key": k, "name": _title(k), "sales": num(c["s"]), "prev_sales": num(p["s"]) if p else 0.0,
            "change": num(c["s"] - (p["s"] if p else 0)), "share_pct": share,
            "share_change_pp": round(share - (pct(p["s"], prev_total) or 0), 1) if p and prev_total else None,
            "mom_pct": growth, "units": c["u"], "asp": num(asp) if asp else None,
            "asp_change_pct": delta_pct(asp, prev_asp) if asp and prev_asp else None,
            "retailers": c["r"], "reach_pct": pct(c["r"], buyers), "styles": c["st"],
            "top_style": top_style.get(k),
            "role": _role(share, growth, fair, td_growth) if c["s"] else "watch",
            "prev_share_pct": pct(p["s"], prev_total) if p and prev_total else None,
            "yoy_pct": delta_pct(c["s"], ly_c[k]["s"]) if ly_c.get(k) and ly_c[k]["s"] else None,
            # share of TD's ₹ growth; not meaningful in a month TD fell (the ₹ change is shown instead)
            "growth_contrib_pct": round((c["s"] - (p["s"] if p else 0)) / td_change * 100, 1) if td_change > 0 else None,
        })
    stock = _stock_by_category(f, m)
    for c in cats:
        o = stock["by_cat"].get(c["key"]) if stock else None
        c["oos_lines"] = o["lines"] if o else (0 if stock else None)
        c["oos_units_30d"] = o["units"] if o else (0 if stock else None)
        c["oos_value"] = num(o["units"] * (c["asp"] or 0)) if o else (0.0 if stock else None)
        c["call"] = _call(c)
        c["call_reason"] = CALLS[c["call"]]

    # styles: concentration, movers, new launches
    cur_s, prev_s = _by_style(cur_l), _by_style(prev_l)
    ranked = sorted(cur_s.items(), key=lambda kv: -kv[1]["s"])
    top10 = sum(v["s"] for _, v in ranked[:10])
    changes = [{"style": k, "name": (cur_s.get(k) or prev_s.get(k))["name"],
                "sales": num(cur_s[k]["s"] if k in cur_s else 0), "prev": num(prev_s[k]["s"] if k in prev_s else 0),
                "change": num((cur_s[k]["s"] if k in cur_s else 0) - (prev_s[k]["s"] if k in prev_s else 0))}
               for k in set(cur_s) | set(prev_s)]
    gainers = sorted([c for c in changes if c["change"] > 0], key=lambda c: -c["change"])[:5]
    decliners = sorted([c for c in changes if c["change"] < 0], key=lambda c: c["change"])[:5]

    firsts = defaultdict(lambda: None)
    for st, d in Product.objects.exclude(launched_on__isnull=True).values_list("style").annotate(
            d=Min("launched_on")).values_list("style", "d"):
        code = base_style(st) or st
        firsts[code] = d if firsts[code] is None or d < firsts[code] else firsts[code]
    cut = month_end_ - dt.timedelta(days=NEW_LAUNCH_DAYS - 1)
    new_codes = {k for k, d in firsts.items() if d and cut <= d <= month_end_}
    new_sales = sum(v["s"] for k, v in cur_s.items() if k in new_codes)
    new_selling = sum(1 for k in cur_s if k in new_codes)

    # breadth: distinct styles per buying retailer (cross-sell)
    def depth(lines):
        per = lines.values("order__retailer_id").annotate(n=Count("style", distinct=True))
        vals = [r["n"] for r in per]
        return round(sum(vals) / len(vals), 1) if vals else None

    units = sum(c["u"] for c in cur_c.values())
    prev_units = sum(c["u"] for c in prev_c.values())
    asp, prev_asp = ratio(total, units), ratio(prev_total, prev_units)
    pulse = {
        "styles_sold": len(cur_s), "prev_styles_sold": len(prev_s),
        "top10_share_pct": pct(top10, total), "top10_prev_share_pct": pct(
            sum(v["s"] for _, v in sorted(prev_s.items(), key=lambda kv: -kv[1]["s"])[:10]), prev_total),
        "new_launch_share_pct": pct(new_sales, total), "new_launch_sales": num(new_sales),
        "new_launches_selling": new_selling, "new_launches": len(new_codes),
        "styles_per_retailer": depth(cur_l), "prev_styles_per_retailer": depth(prev_l),
        "asp": num(asp) if asp else None, "asp_change_pct": delta_pct(asp, prev_asp) if asp and prev_asp else None,
        "buyers": buyers, "prev_buyers": prev_buyers,
    }
    pulse.update({"oos_top_sellers": stock["lines"], "oos_units_30d": stock["units"]} if stock else {"oos_top_sellers": None})

    # long tail: the smallest styles that together make the last TAIL_SHARE % of sales
    tail_n, tail_s = 0, 0.0
    for _, v in sorted(cur_s.items(), key=lambda kv: kv[1]["s"]):
        if total and (tail_s + v["s"]) / total * 100 > TAIL_SHARE:
            break
        tail_n, tail_s = tail_n + 1, tail_s + v["s"]
    tail = {"styles": tail_n, "of_styles": len(cur_s), "sales": num(tail_s), "share_pct": pct(tail_s, total)}

    oos_value = sum(c["oos_value"] or 0 for c in cats) if stock else None
    return {"categories": cats, "fair_share_pct": round(fair, 1), "td_growth_pct": td_growth,
            "td_change": num(td_change), "gainers": gainers, "decliners": decliners, "pulse": pulse, "tail": tail,
            "stock": {"value": num(oos_value), "lines": stock["lines"], "units": stock["units"],
                      "top_styles": stock["top_styles"]} if stock else None,
            "decisions": _decisions(cats, pulse, tail, stock, oos_value, td_growth, total, fair),
            "insights": _insights(cats, pulse, gainers, decliners, td_growth),
            "leaders": style_leaders(f, month_end_, firsts)}


LEADER_WINDOWS = (30, 60)
LEADER_N = 10


def _style_window(f, s, e):
    """{base style: {s, u, retailers:set, name, cat}} for the window."""
    out = defaultdict(lambda: {"s": 0.0, "u": 0, "r": set(), "name": None, "cat": None})
    for r in _lines(f, s, e).values("style", "product__name", "product__category_l3", "order__retailer_id").annotate(
            sv=Sum("total"), uv=Sum("quantity")).order_by():
        st, name, cat, rid, sv, uv = (r["style"], r["product__name"], r["product__category_l3"], r["order__retailer_id"],
                                      r["sv"], r["uv"])
        code = base_style(st) or st or "?"
        o = out[code]
        o["s"] += float(sv or 0)
        o["u"] += uv or 0
        if rid:
            o["r"].add(rid)
        o["name"] = o["name"] or name
        o["cat"] = o["cat"] or ((cat or "").strip().lower() or "uncategorised")
    return out


def style_leaders(f, end, firsts):
    """Top 10 styles per category and overall, and the top 10 new launches, over the last 30 and 60 days to `end`.
    Each style is compared with the same number of days just before (vs_prev_pct)."""
    out = {"windows": list(LEADER_WINDOWS), "new_launch_days": NEW_LAUNCH_DAYS}
    cut = end - dt.timedelta(days=NEW_LAUNCH_DAYS - 1)
    for days in LEADER_WINDOWS:
        s = end - dt.timedelta(days=days - 1)
        ps, pe = s - dt.timedelta(days=days), s - dt.timedelta(days=1)
        cur, prev = _style_window(f, s, end), _style_window(f, ps, pe)
        cat_tot = defaultdict(float)
        for v in cur.values():
            cat_tot[v["cat"]] += v["s"]
        total = sum(cat_tot.values())

        def row(code, v):
            p = prev.get(code)
            launched = firsts.get(code)
            live = (end - launched).days + 1 if launched else None
            return {"style": code, "name": v["name"], "category": _title(v["cat"]), "sales": num(v["s"]), "units": v["u"],
                    "retailers": len(v["r"]), "prev_sales": num(p["s"]) if p else 0.0,
                    "vs_prev_pct": delta_pct(v["s"], p["s"]) if p and p["s"] else None,
                    "share_of_category_pct": pct(v["s"], cat_tot[v["cat"]]), "share_of_td_pct": pct(v["s"], total),
                    "launched_on": launched.isoformat() if launched else None, "days_live": live,
                    "sales_per_day": num(v["s"] / min(live, days)) if live else None}

        ranked = sorted(cur.items(), key=lambda kv: -kv[1]["s"])
        by_cat = defaultdict(list)
        for code, v in ranked:
            if len(by_cat[v["cat"]]) < LEADER_N and v["s"] > 0:
                by_cat[v["cat"]].append(row(code, v))
        cats = [{"key": k, "name": _title(k), "sales": num(cat_tot[k]), "styles": sum(1 for v in cur.values() if v["cat"] == k)}
                for k in sorted(cat_tot, key=lambda k: -cat_tot[k]) if cat_tot[k] > 0]
        new = [row(code, v) for code, v in ranked if firsts.get(code) and cut <= firsts[code] <= end and v["s"] > 0][:LEADER_N]
        new_all = [c for c, d in firsts.items() if d and cut <= d <= end]
        out[str(days)] = {
            "from": s.isoformat(), "to": end.isoformat(), "prev_from": ps.isoformat(), "prev_to": pe.isoformat(),
            "total": num(total), "all": [row(c, v) for c, v in ranked[:LEADER_N] if v["s"] > 0],
            "categories": cats, "by_category": {k: by_cat[k] for k in by_cat},
            "new_launches": new, "new_launches_count": len(new_all),
            "new_launches_selling": sum(1 for c in new_all if cur.get(c, {}).get("s")),
            "new_launch_sales": num(sum(cur[c]["s"] for c in new_all if c in cur)),
        }
    return out


def _call(c):
    """Scale / defend / watch from the role; a category losing share while much of its demand sits at zero stock
    is "fix" - stock, not demand, is the likely reason."""
    base = {"core": "scale", "rising": "scale", "defend": "defend", "watch": "watch"}[c["role"]]
    if base != "scale" and c["oos_value"] and c["sales"] and c["oos_value"] / c["sales"] * 100 >= FIX_STOCK_SHARE:
        return "fix"
    return base


def _stock_by_category(f, m):
    """Best sellers at zero stock right now, by category. Only for the month in progress (stock is a live snapshot)."""
    from .filters import month_start

    if month_start(f.today) != m:
        return None
    from .views.products import latest_inventory, units_last_30d

    sold = units_last_30d(f)
    by_cat, styles, lines, units = {}, defaultdict(int), 0, 0
    seen = set()
    for d, sku, cat, st in latest_inventory(f).filter(quantity__lte=0).values_list(
            "distributor_id", "sku", "product__category_l3", "style"):
        u = sold.get((d, sku), 0)
        if u <= 0 or (d, sku) in seen:
            continue
        seen.add((d, sku))
        key = (cat or "").strip().lower() or "uncategorised"
        o = by_cat.setdefault(key, {"lines": 0, "units": 0})
        o["lines"] += 1
        o["units"] += u
        styles[base_style(st) or st or "?"] += u
        lines, units = lines + 1, units + u
    top = [{"style": k, "units": v} for k, v in sorted(styles.items(), key=lambda kv: -kv[1])[:3]]
    return {"by_cat": by_cat, "lines": lines, "units": units, "top_styles": top}


def _decisions(cats, pulse, tail, stock, oos_value, td_growth, total, fair):
    """The few calls leadership should take this month, each with the ₹ at stake."""
    out = []
    material = [c for c in cats if c["sales"] and c["share_pct"] >= 2 and c["mom_pct"] is not None]
    td = td_growth or 0
    up = [c for c in material if c["mom_pct"] > td and c["change"] > 0]
    if up:
        c = max(up, key=lambda c: c["change"])
        led = f", led by {c['top_style']}" if c["top_style"] else ""
        out.append({"kind": "scale", "title": f"Scale {c['name']}", "value": c["change"],
                    "reason": f"{c['mom_pct']:+.0f}% MoM against TD's {td:+.0f}%, {c['share_pct']:.1f}% of sales now{led}. "
                              "Put depth and distributor stock behind it.",
                    "value_label": "added vs last month"})
    if stock and oos_value:
        names = ", ".join(s["style"] for s in stock["top_styles"])
        out.append({"kind": "fix", "title": "Restock best sellers", "value": num(oos_value),
                    "reason": f"{stock['lines']:,} SKU lines at distributors are at zero although they sold "
                              f"{stock['units']:,} units in 30 days{f'; worst: {names}' if names else ''}.",
                    "value_label": "30-day demand at zero stock", "link": "/inventory"})
    big_losing = [c for c in cats if c["sales"] and c["share_pct"] >= fair and (c["share_change_pp"] or 0) <= -1]
    if big_losing:
        c = min(big_losing, key=lambda c: c["share_change_pp"])
        lost = (c["prev_share_pct"] - c["share_pct"]) / 100 * total if c["prev_share_pct"] is not None else 0
        def move(v):
            return "is new" if v is None else (f"grew {v:.0f}%" if v >= 0 else f"fell {-v:.0f}%")
        why = (f" {_inr(c['oos_value'])} of its 30-day demand is at zero stock." if c["call"] == "fix"
               else " Check stock, price and season.")
        out.append({"kind": "defend", "title": f"Defend {c['name']}", "value": num(lost),
                    "reason": f"{c['name']} {move(c['mom_pct'])} while TD {move(td_growth)}, so its share fell from "
                              f"{c['prev_share_pct']:.1f}% to {c['share_pct']:.1f}%.{why}",
                    "value_label": "sales short of last month's share"})
    if tail["styles"] >= 10:
        out.append({"kind": "watch", "title": "Trim the long tail", "value": tail["sales"],
                    "reason": f"{tail['styles']} of {tail['of_styles']} styles sold make only the last "
                              f"{tail['share_pct']:.0f}% of sales. Review them before the next buy.",
                    "value_label": "sales from the tail"})
    nl = pulse.get("new_launch_share_pct")
    if nl is not None:
        out.append({"kind": "launch", "title": "New launches" + (" are landing" if nl >= 10 else " below the 10% bar"),
                    "value": pulse["new_launch_sales"], "good": nl >= 10,
                    "reason": f"Styles launched in the last {NEW_LAUNCH_DAYS} days made {nl:.1f}% of sales; "
                              f"{pulse['new_launches_selling']} of {pulse['new_launches']} have sold.",
                    "value_label": "sales from new launches"})
    return out


def _insights(cats, pulse, gainers, decliners, td_growth):
    """Up to five plain sentences a reviewer can act on."""
    out = []
    live = [c for c in cats if c["sales"]]
    if len(live) >= 2:
        two = live[0]["share_pct"] + live[1]["share_pct"]
        out.append({"tone": "neutral", "text": f"{live[0]['name']} and {live[1]['name']} make {two:.0f}% of sales; "
                                                f"{len(live)} categories sold this month."})
    growers = [c for c in live if c["mom_pct"] is not None and c["sales"] >= 0.02 * sum(x["sales"] for x in live)]
    if growers:
        best = max(growers, key=lambda c: c["change"])
        worst = min(growers, key=lambda c: c["change"])
        if best["change"] > 0:
            out.append({"tone": "good", "text": f"{best['name']} added the most: {_inr(best['change'])} "
                                                f"({best['mom_pct']:+.0f}%), led by {best['top_style'] or 'its top style'}."})
        if worst["change"] < 0 and worst is not best:
            out.append({"tone": "bad", "text": f"{worst['name']} lost the most: {_inr(-worst['change'])} "
                                               f"({worst['mom_pct']:+.0f}%). Check stock and pricing."})
    lagging = [c for c in live[:4] if c["role"] == "defend" and c["mom_pct"] is not None and c["share_change_pp"]]
    if lagging and td_growth is not None:
        c = lagging[0]
        out.append({"tone": "warn", "text": f"{c['name']} is {c['mom_pct']:+.0f}% against TD's {td_growth:+.0f}%, "
                                            f"so its share moved {c['share_change_pp']:+.1f} pp to {c['share_pct']:.0f}%."})
    if pulse["new_launch_share_pct"] is not None:
        out.append({"tone": "good" if (pulse["new_launch_share_pct"] or 0) >= 10 else "warn",
                    "text": f"Launches of the last {NEW_LAUNCH_DAYS} days made {pulse['new_launch_share_pct']:.1f}% of sales "
                            f"({pulse['new_launches_selling']} of {pulse['new_launches']} new styles have sold)."})
    if pulse.get("oos_top_sellers"):
        out.append({"tone": "bad", "text": f"{pulse['oos_top_sellers']:,} SKU-distributor lines are out of stock although they "
                                           f"sold {pulse['oos_units_30d']:,} units in the last 30 days."})
    a, b = pulse["styles_per_retailer"], pulse["prev_styles_per_retailer"]
    if a is not None and b is not None and abs(a - b) >= 0.3:
        out.append({"tone": "good" if a > b else "warn",
                    "text": f"Each buying retailer took {a} styles on average, {'up' if a > b else 'down'} from {b}."})
    return out[:6]


def _inr(v):
    v = abs(v)
    if v >= 1e7:
        return f"₹{v / 1e7:.2f} Cr"
    if v >= 1e5:
        return f"₹{v / 1e5:.1f} L"
    return f"₹{v:,.0f}"
