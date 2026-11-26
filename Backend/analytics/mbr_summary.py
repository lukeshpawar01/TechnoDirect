"""MBR executive summary: the conclusions and decisions a founders / CEO / directors review needs, built from the
scorecard (page 1) and the path to the goal (page 2). Pure functions of the card - no extra queries.

  bridge     - last month's sales -> this month's, split into new retailers, retailers who did not come back
               (net of reactivated) and spend per retailer. Exact: the three steps add up to the change.
  insights   - one line per area (sales, drivers, retailers, territory, product, goal, adoption, operations),
               most important first, each with a tone.
  decisions  - the calls for leadership, each with the ₹ at stake and the team that owns it.
"""
from .metrics import num, pct


def _inr(v):
    v = float(v or 0)
    a = abs(v)
    s = f"₹{a / 1e7:.2f} Cr" if a >= 1e7 else f"₹{a / 1e5:.1f} L" if a >= 1e5 else f"₹{a:,.0f}"
    return ("−" if v < 0 else "") + s


def _signed(v):
    return ("+" if (v or 0) >= 0 else "") + _inr(v)


def _pc(v, d=0):
    return "–" if v is None else f"{v:+.{d}f}%"


def bridge(rows):
    s0, s1 = rows["sales"]["prev"] or 0, rows["sales"]["value"] or 0
    r0, r1 = rows["active_retailers"]["prev"] or 0, rows["active_retailers"]["value"] or 0
    new = rows["new_retailers"]["value"] or 0
    spend0 = s0 / r0 if r0 else 0
    new_eff = new * spend0
    # repeat this month minus all of last month: retained + reactivated - last month's buyers
    base_eff = (r1 - new - r0) * spend0
    spend_eff = s1 - s0 - new_eff - base_eff
    return {
        "prev": num(s0), "current": num(s1), "change": num(s1 - s0),
        "steps": [
            {"key": "new", "label": "New retailers", "value": num(new_eff),
             "note": f"{new:,} first-time buyers × last month's {_inr(spend0)} per retailer"},
            {"key": "base", "label": "Repeat base", "value": num(base_eff),
             "note": f"{r1 - new:,} repeat buyers this month vs {r0:,} buyers last month"},
            {"key": "spend", "label": "Spend per retailer", "value": num(spend_eff),
             "note": f"{_inr(spend0)} → {_inr(s1 / r1 if r1 else 0)} per transacting retailer"},
        ],
    }


def _region_projection(card, r):
    if card["partial"] and card["days_elapsed"]:
        return r["sales"] / card["days_elapsed"] * card["days_total"]
    return r["sales"]


def executive_summary(card):
    rows = {r["key"]: r for r in card["rows"]}
    h, p, prod = card["headline"], card["path"], card.get("products") or {}
    br = bridge(rows)
    ins, dec = [], []
    sales = rows["sales"]

    # 1. the outcome
    if h["target"]:
        best = h["projected"] if card["partial"] else h["sales"]
        best_pct = h["projected_pct"] if card["partial"] else h["achievement_pct"]
        gap = (h["target"] or 0) - (best or 0)
        tone = "good" if best_pct and best_pct >= 100 else "warn" if best_pct and best_pct >= 90 else "bad"
        verb = "is heading for" if card["partial"] else "closed at"
        ins.append({"area": "sales", "tone": tone, "title": "Result vs target",
                    "text": f"TD {verb} {_inr(best)} against {_inr(h['target'])} ({best_pct or 0:.0f}%)"
                            + (f", {_inr(gap)} short." if gap > 0 else f", {_inr(-gap)} ahead.")
                            + f" Sales {_pc(h['mom_pct'], 1)} MoM" + (f", {_pc(h['yoy_pct'], 0)} YoY." if h["yoy_pct"] is not None else ".")})
        if card["partial"] and gap > 0 and h["required_per_day"]:
            days_left = card["days_total"] - card["days_elapsed"]
            dec.append({"area": "sales", "owner": "Sales (RSMs / ASMs)", "title": "Close this month's gap",
                        "value": num(gap), "value_label": "short of target at today's pace",
                        "reason": f"Needs {_inr(h['required_per_day'])} a day for the last {days_left} days against a "
                                  f"run rate of {_inr(h['run_rate_per_day'])}. Push open carts and top distributors."})
    else:
        ins.append({"area": "sales", "tone": "neutral", "title": "Result",
                    "text": f"Sales {_inr(h['sales'])}, {_pc(h['mom_pct'], 1)} MoM (no sales target set)."})

    # 2. what drove it
    steps = {s["key"]: s["value"] for s in br["steps"]}
    if br["change"]:
        lead = max(br["steps"], key=lambda s: abs(s["value"]))
        word = {"new": "new retailers", "base": "the repeat base", "spend": "spend per retailer"}[lead["key"]]
        ins.append({"area": "drivers", "tone": "good" if br["change"] > 0 else "bad", "title": "What drove it",
                    "text": f"Sales moved {_signed(br['change'])}: new retailers {_signed(steps['new'])}, repeat base "
                            f"{_signed(steps['base'])}, spend per retailer {_signed(steps['spend'])}. "
                            f"The biggest lever was {word}."})

    # 3. retailers: acquisition and retention
    ret, new = rows.get("retention_pct"), rows.get("new_retailers")
    if ret and new:
        drop = (ret["value"] or 0) - (ret["prev"] or 0)
        tone = "good" if drop >= 0 and (new["mom_pct"] or 0) >= 0 else "warn" if drop > -3 else "bad"
        ins.append({"area": "retailers", "tone": tone, "title": "Retailers",
                    "text": f"{rows['active_retailers']['value']:,} transacting ({_pc(rows['active_retailers']['mom_pct'], 0)}), "
                            f"{new['value']:,} of them new ({_pc(new['mom_pct'], 0)}). Month-on-month retention "
                            f"{ret['value'] or 0:.0f}% ({drop:+.1f} pp)."})
        base_loss = -steps.get("base", 0) if br["change"] else 0
        if drop <= -3 or base_loss >= 0.05 * (br["prev"] or 0):
            r0, r1, nw = rows["active_retailers"]["prev"] or 0, rows["active_retailers"]["value"] or 0, new["value"] or 0
            fewer = max(r0 - (r1 - nw), 0)
            dec.append({"area": "retailers", "owner": "Sales + CRM", "title": "Win back lapsed retailers",
                        "value": num(max(base_loss, 0)), "value_label": "sales lost from the repeat base",
                        "reason": f"{r1 - nw:,} repeat buyers against {r0:,} buyers last month ({fewer:,} fewer); retention "
                                  f"{ret['value'] or 0:.0f}% ({drop:+.1f} pp). Work the lapsed list from the Retention page and "
                                  "check stock and delivery at their distributors."})

    # 4. territory
    regions = [r for r in card["territory"]["region"] if r["target"]]
    if regions:
        for r in regions:
            r["_proj"] = _region_projection(card, r)
            r["_proj_pct"] = r["_proj"] / r["target"] * 100
        best, worst = max(regions, key=lambda r: r["_proj_pct"]), min(regions, key=lambda r: r["_proj_pct"])
        word = "heading for" if card["partial"] else "at"
        ins.append({"area": "territory", "tone": "bad" if worst["_proj_pct"] < 75 else "warn" if worst["_proj_pct"] < 95 else "good",
                    "title": "Territory",
                    "text": f"{best['name']} is {word} {best['_proj_pct']:.0f}% of target ({_pc(best['mom_pct'], 0)} MoM); "
                            f"{worst['name']} is {word} {worst['_proj_pct']:.0f}% ({_pc(worst['mom_pct'], 0)})."})
        short = worst["target"] - worst["_proj"]
        if short > 0 and worst["_proj_pct"] < 95:
            dec.append({"area": "territory", "owner": f"RSM / ASMs, {worst['name']}", "title": f"Recovery plan for {worst['name']}",
                        "value": num(short), "value_label": "short of the region's target",
                        "reason": f"{worst['name']} is {word} {worst['_proj_pct']:.0f}% of target with "
                                  f"{worst['active_retailers']:,} transacting retailers. Agree a distributor-wise plan for next month."})

    # 5. product (from the product section's own decisions)
    pd = {d["kind"]: d for d in prod.get("decisions", [])}
    if pd:
        bits = []
        if "scale" in pd:
            bits.append(pd["scale"]["title"].replace("Scale ", "") + f" is the growth engine ({_signed(pd['scale']['value'])})")
        if "fix" in pd:
            bits.append(f"{_inr(pd['fix']['value'])} of 30-day demand sits at zero stock")
        if "defend" in pd:
            bits.append(pd["defend"]["title"].replace("Defend ", "") + " is losing share")
        if bits:
            ins.append({"area": "product", "tone": "warn" if "fix" in pd or "defend" in pd else "good", "title": "Product",
                        "text": "; ".join(bits) + "."})
        for k, owner in (("fix", "Supply + distributors"), ("scale", "Product + category"), ("defend", "Product + category")):
            if k in pd:
                d = pd[k]
                dec.append({"area": "product", "owner": owner, "title": d["title"], "value": d["value"],
                            "value_label": d["value_label"], "reason": d["reason"], "link": d.get("link")})

    # 6. pace to the goal
    trend = [t for t in card["trend"] if not (card["partial"] and t["month"] == card["month"])]
    last = trend[-4:]
    growths = [(b["sales"] / a["sales"] - 1) * 100 for a, b in zip(last, last[1:]) if a["sales"]]
    avg = sum(growths) / len(growths) if growths else None
    need = p.get("monthly_growth_needed_pct")
    if need is not None:
        on = avg is not None and avg >= need
        ins.append({"area": "goal", "tone": "good" if on else "bad", "title": "Pace to the goal",
                    "text": f"{_inr(p['goal'])}/month by {p['goal_by_label']} needs {need:.1f}% growth every month; "
                            f"the last {len(growths)} months averaged {avg:.1f}%." if avg is not None else
                            f"{_inr(p['goal'])}/month by {p['goal_by_label']} needs {need:.1f}% growth every month."})
    # 7. adoption: where the retailers will come from
    if p.get("retailers_gap"):
        ins.append({"area": "adoption", "tone": "warn", "title": "Adoption",
                    "text": f"The goal needs {p['retailers_needed']:,} transacting retailers ({p['retailers_gap']:,} more). "
                            f"{p['ants']:,} KYC-done retailers have never ordered; converting "
                            f"{pct(p['retailers_gap'], p['ants']) or 0:.0f}% of them closes it."})
        per_month = -(-p["retailers_gap"] // max(p["months_left"], 1))
        dec.append({"area": "adoption", "owner": "Sales + Growth", "title": f"Activate {per_month:,} more retailers a month",
                    "value": num(p["retailers_gap"] * p["spend_per_retailer"]), "value_label": "monthly sales when the gap is closed",
                    "reason": f"{p['retailers_gap']:,} more transacting retailers are needed by {p['goal_by_label']} at "
                              f"{_inr(p['spend_per_retailer'])} each; {p['ants']:,} have done KYC but never ordered and KYC → "
                              f"first order is {rows['kyc_to_order_pct']['value'] or 0:.0f}%. Split the target by ASM."})

    # 8. operations, only when they got worse
    ops = []
    c, d = rows.get("cancel_pct"), rows.get("delivery_days")
    if c and c["value"] is not None and c["prev"] is not None and c["value"] - c["prev"] >= 0.5:
        ops.append(f"cancellations up to {c['value']:.1f}% of value ({c['value'] - c['prev']:+.1f} pp)")
    if d and d["value"] and d["prev"] and d["value"] - d["prev"] >= 0.5:
        ops.append(f"order-to-delivery {d['value']:.1f} days (was {d['prev']:.1f})")
    if ops:
        ins.append({"area": "operations", "tone": "warn", "title": "Operations", "text": "Watch: " + "; ".join(ops) + "."})

    return {"bridge": br, "insights": ins, "decisions": dec,
            "momentum": {"avg_growth_3m_pct": round(avg, 1) if avg is not None else None, "needed_pct": need}}
