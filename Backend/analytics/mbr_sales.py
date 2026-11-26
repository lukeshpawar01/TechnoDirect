"""MBR page 3 - the Sales team card: what we ask RSMs, ASMs and executives to do next month, built from data.

Each ask names who acts (RSM / ASM), the distributor or area, the ₹ at stake and a plain next step. Kinds:
  warm      - warm never-ordered retailers per ASM, with a monthly activation target split by ASM
  no_asm    - distributors with no real ASM (none, or a placeholder named after the distributor): RSM decides
  new       - distributors with retailers mapped but no sales yet (a new warehouse / onboarding)
  stalled   - sold in the last 3 months, nothing in the month reviewed
  slow      - a real base, but growing slower than TD (or shrinking) over the last 3 months
  stretch   - per region, a next-month target for the biggest distributor that its own best month shows is feasible
  stock     - 30-day demand sitting at zero stock at the distributor (month in progress only)
  reassign  - a near-dead distributor next to a working one in the same state (same postal circle): move the retailers
"""
import datetime as dt
import math
from collections import defaultdict

from django.db.models import Count, Q

from warehouse.models import Asm, Distributor, Retailer, Rsm

from .filters import add_months
from .metrics import num
from .rsm import region_rsm_map

MAX_PER_KIND = 4
MIN_BASE = 200_000        # ₹/month: a distributor this size is worth a slow-growth flag
DEAD = 50_000             # ₹/month: below this over 3 months a distributor is near-dead
STRETCH_ROUND = 500_000   # stretch targets rounded up to ₹5 L


def _inr(v):
    v = float(v or 0)
    a = abs(v)
    return f"₹{a / 1e7:.2f} Cr" if a >= 1e7 else f"₹{a / 1e5:.1f} L" if a >= 1e5 else f"₹{a:,.0f}"


def _per_region(items, region_of, n=MAX_PER_KIND):
    """items already in priority order -> the first n of each region (so every region gets its own suggestions)."""
    seen, out = defaultdict(int), []
    for it in items:
        r = region_of(it)
        if seen[r] < n:
            seen[r] += 1
            out.append(it)
    return out


def _placeholder(asm, dist_name):
    """An ASM record that only stands in for the distributor (no employee id, named after it)."""
    return bool(asm and not asm.emp_id and asm.name and asm.name.split()[0].lower() in dist_name.lower())


def sales_asks(f, card, path):
    m = dt.date.fromisoformat(card["month"] + "-01")
    cur_e = dt.date.fromisoformat(card["as_of"])
    partial, days, days_total = card["partial"], card["days_elapsed"], card["days_total"]
    full = [add_months(m, -i) for i in range(6, 0, -1)]         # 6 complete months before m
    lo = full[0]

    sales = defaultdict(lambda: defaultdict(float))              # dist -> month -> ₹
    for d, day, v in f.orders(start=lo, end=cur_e).values_list("distributor_id", "placed_date", "gross_value"):
        if d:
            sales[d][day.replace(day=1)] += float(v or 0)
    ever = set(f.orders().values_list("distributor_id", flat=True).distinct())

    dists = {d.id: d for d in Distributor.objects.select_related("asm", "asm__rsm", "region", "state").all()}
    reg_rsm = region_rsm_map()
    rsm_names = dict(Rsm.objects.values_list("id", "name"))

    def rsm_of(d):
        rid = (d.asm.rsm_id if d.asm and d.asm.rsm_id else None) or reg_rsm.get(d.region_id)
        return rsm_names.get(rid) or "RSM"

    def owner(d):
        real = d.asm and not _placeholder(d.asm, d.name)
        return f"{d.asm.name} (ASM)" if real else f"{rsm_of(d)} (RSM)"

    def last3(d):
        return sum(sales[d].get(mm, 0) for mm in full[3:]) / 3

    def prev3(d):
        return sum(sales[d].get(mm, 0) for mm in full[:3]) / 3

    def current(d):
        v = sales[d].get(m, 0)
        return v / days * days_total if partial and days else v

    # retailers per distributor (KYC done), and warm never-ordered ones
    rbase = {r["distributor_id"]: r for r in Retailer.objects.filter(kyc_status="approved").values("distributor_id").annotate(
        n=Count("id"), never=Count("id", filter=Q(first_order_date__isnull=True)),
        warm=Count("id", filter=Q(first_order_date__isnull=True, warm_match=True)))}

    td_last3 = sum(last3(d) for d in sales)
    td_prev3 = sum(prev3(d) for d in sales)
    td_growth = (td_last3 / td_prev3 - 1) * 100 if td_prev3 else None
    spend = path.get("spend_per_retailer") or 0

    asks = []

    def add(kind, d, title, detail, value, value_label, priority="medium", who=None):
        asks.append({"kind": kind, "title": title, "detail": detail, "owner": who or (owner(d) if d else ""),
                     "distributor": d.name if d else None, "region": d.region.name if d and d.region else None,
                     "value": num(value) if value is not None else None, "value_label": value_label, "priority": priority})

    # 1. warm retailers by ASM, with the monthly activation target split by ASM
    per_month = math.ceil((path.get("retailers_gap") or 0) / max(path.get("months_left") or 1, 1))
    warm_asm = defaultdict(int)
    warm_noasm = defaultdict(lambda: {"n": 0, "dists": []})  # region -> warm retailers at distributors with no ASM
    for did, r in rbase.items():
        d = dists.get(did)
        if not d or not r["warm"]:
            continue
        if d.asm and not _placeholder(d.asm, d.name):
            warm_asm[d.asm_id] += r["warm"]
        else:
            w = warm_noasm[d.region.name if d.region else None]
            w["n"] += r["warm"]
            w["dists"].append((r["warm"], d.name))
    total_warm = sum(warm_asm.values()) + sum(w["n"] for w in warm_noasm.values())
    asm_by_id = {a.id: a for a in Asm.objects.select_related("rsm", "region").filter(id__in=list(warm_asm))}
    for aid, n in _per_region(sorted(warm_asm.items(), key=lambda kv: -kv[1]),
                              lambda kv: asm_by_id[kv[0]].region_id):
        a = asm_by_id[aid]
        target = max(math.ceil(per_month * n / total_warm), 1) if total_warm and per_month else None
        asks.append({"kind": "warm", "title": f"{a.name}: convert {target or 'more'} warm retailers this month",
                     "detail": f"{n:,} warm retailers (they buy TechnoSport offline in BlueOrigin) have done KYC but never ordered on TD. "
                               f"Visit with the distributor, place the first order in the visit, and log it.",
                     "owner": f"{a.name} (ASM){f' · {a.rsm.name} (RSM)' if a.rsm else ''}", "distributor": None,
                     "region": a.region.name if a.region else None,
                     "value": num((target or 0) * spend), "value_label": "monthly sales from the target",
                     "priority": "high" if n >= 150 else "medium"})
    rsm_by_region = {d.region.name: rsm_of(d) for d in dists.values() if d.region}
    for reg, w in sorted(warm_noasm.items(), key=lambda kv: -kv[1]["n"]):
        names = ", ".join(f"{name} ({k:,})" for k, name in sorted(w["dists"], reverse=True)[:3])
        asks.append({"kind": "warm", "title": f"{reg or 'No region'}: {w['n']:,} warm retailers with distributors that have no ASM",
                     "detail": f"Nobody is chasing them: {names}. Give each of these distributors an owner (see below) "
                               "or give the list to the regional sales executives.",
                     "owner": f"{rsm_by_region.get(reg, 'RSM')} (RSM)", "distributor": None, "region": reg,
                     "value": num(math.ceil(per_month * w["n"] / total_warm) * spend) if total_warm and per_month else None,
                     "value_label": "monthly sales at the same activation rate", "priority": "high" if w["n"] >= 50 else "medium"})

    # 2. distributors with no real ASM, 3. new ones with no sales yet
    for d in sorted(dists.values(), key=lambda d: -(last3(d.id) + current(d.id))):
        r = rbase.get(d.id, {})
        no_asm = not d.asm or _placeholder(d.asm, d.name)
        if d.id not in ever:
            # a new TD warehouse (not a BlueOrigin-only or internal account): who should move to it
            if d.bo_only or d.is_internal or not d.is_active or not d.pincode or len(d.pincode) < 3:
                continue
            area = Retailer.objects.filter(kyc_status="approved", pincode__startswith=d.pincode[:3]).exclude(distributor_id=d.id)
            n_area = area.count()
            if not (r.get("n") or n_area >= 10):
                continue
            never_area = area.filter(first_order_date__isnull=True).count()
            top = area.values("distributor__name").annotate(n=Count("id")).order_by("-n").first()
            mostly = f", mostly {top['distributor__name']}" if top and top["distributor__name"] else ""
            since = f" (onboarded {d.onboarded_on:%d %b})" if d.onboarded_on else ""
            fresh = d.onboarded_on and (cur_e - d.onboarded_on).days <= 90
            label = "New warehouse" if fresh or not d.onboarded_on else "Never ordered since onboarding"
            add("new", d, f"{label}: {d.name}{f', {d.city}' if d.city else ''}{since}",
                f"No orders yet. {n_area:,} KYC retailers in its district (pin {d.pincode[:3]}…) are served from other warehouses"
                f"{mostly}; "
                f"{never_area:,} of them never ordered. Map them to the nearer warehouse, put an ASM in charge"
                f"{'' if no_asm else f' ({d.asm.name})'}, and plan the first 20 orders.",
                never_area * spend * 0.05, "if 5% of the district's never-ordered retailers start ordering", "high",
                who=f"{rsm_of(d)} (RSM)" if no_asm else None)
            continue
        if no_asm and (last3(d.id) >= 20_000 or current(d.id) >= 20_000 or r.get("never", 0) >= 20):
            add("no_asm", d, f"{d.name}{f' ({d.city})' if d.city else ''} has no ASM",
                f"{_inr(last3(d.id))}/month over the last 3 months, {r.get('never', 0):,} KYC retailers never ordered. "
                f"{rsm_of(d)} to decide the next step: assign an ASM, cover it from a neighbouring ASM, or run it with a sales executive.",
                last3(d.id), "monthly sales now", "high" if last3(d.id) >= MIN_BASE or r.get("never", 0) >= 100 else "medium",
                who=f"{rsm_of(d)} (RSM)")

    # 4. stalled: sold in the last 3 months, nothing this month
    stalled = [d for d in sales if last3(d) >= 20_000 and not sales[d].get(m)]
    for did in _per_region(sorted(stalled, key=lambda d: -last3(d)), lambda d: dists[d].region_id):
        d = dists[did]
        add("stalled", d, f"{d.name}: zero sales in {card['label']}",
            f"It averaged {_inr(last3(did))}/month in the last 3 months{f' in {d.region.name}' if d.region else ''}. "
            "Find out why (stock, credit, relationship) this week and agree a restart order.",
            last3(did), "monthly sales at stake", "high")

    # 5. slow growth with a real base
    slow = []
    for did in sales:
        if did not in dists or last3(did) < MIN_BASE or not prev3(did):
            continue
        g = (last3(did) / prev3(did) - 1) * 100
        if g < 0 or (td_growth is not None and g < td_growth / 2):
            slow.append((did, g))
    for did, g in _per_region(sorted(slow, key=lambda x: x[1]), lambda x: dists[x[0]].region_id):
        d = dists[did]
        lost = max(prev3(did) * (1 + (td_growth or 0) / 100) - last3(did), 0)
        add("slow", d, f"{d.name}{f' ({d.city})' if d.city else ''}: growing {g:+.0f}% vs TD's {td_growth or 0:+.0f}%",
            f"{_inr(prev3(did))} → {_inr(last3(did))} a month (3 months vs the 3 before). Review its beat plan, "
            "retailer coverage and range; set a monthly target for new retailers.",
            lost, "monthly sales below TD's pace")

    # 6. stretch target per region: the biggest distributor, sized by its own best month
    best_by_region = {}
    for did in sales:
        d = dists.get(did)
        if not d or not d.region_id:
            continue
        size = max(current(did), last3(did))
        if size > best_by_region.get(d.region_id, (None, 0))[1]:
            best_by_region[d.region_id] = (did, size)
    for rid, (did, size) in sorted(best_by_region.items(), key=lambda kv: -kv[1][1]):
        d = dists[did]
        full_best = max((sales[did].get(mm, 0) for mm in full), default=0)
        best_month = max(full_best, size)
        # grow at TD's needed pace, kept between +10% and +25% so it is a stretch but believable
        grow = min(max(path.get("monthly_growth_needed_pct") or 10, 10), 25) / 100
        target = math.ceil(size * (1 + grow) / STRETCH_ROUND) * STRETCH_ROUND
        nxt = add_months(m, 1).strftime("%b %Y")
        r = rbase.get(did, {})
        why = (f"its best month was {_inr(full_best)}, so this is within reach" if full_best >= target
               else f"{_inr(target - full_best)} above its best month ({_inr(full_best)}): it needs new retailers, "
                    f"and {r.get('never', 0):,} KYC retailers here have never ordered")
        add("stretch", d, f"{d.region.name}: {d.name} to {_inr(target)} in {nxt}",
            f"Running at {_inr(size)}/month; {why}. Agree the order plan, the stock it needs, and the retailers it will add.",
            target - size, "extra over today's pace", "high" if target - size >= 1_000_000 else "medium")

    # 7. stock problems (month in progress only: stock is a live snapshot)
    if m == f.today.replace(day=1):
        from .views.products import latest_inventory, units_last_30d

        sold = units_last_30d(f)
        zero = defaultdict(int)
        for d, sku in latest_inventory(f).filter(quantity__lte=0).values_list("distributor_id", "sku"):
            u = sold.get((d, sku), 0)
            if u > 0:
                zero[d] += u
        start30 = cur_e - dt.timedelta(days=29)
        asp = {}
        for d, v, u in f.orders(start=start30, end=cur_e).values_list("distributor_id", "gross_value", "units"):
            a = asp.setdefault(d, [0.0, 0])
            a[0] += float(v or 0)
            a[1] += u or 0
        ranked = sorted((kv for kv in zero.items() if kv[0] in dists),
                        key=lambda kv: -kv[1] * (asp.get(kv[0], [0, 1])[0] / max(asp.get(kv[0], [0, 1])[1], 1)))
        for did, u in _per_region(ranked, lambda kv: dists[kv[0]].region_id):
            d = dists.get(did)
            if not d:
                continue
            price = asp.get(did, [0, 1])[0] / max(asp.get(did, [0, 1])[1], 1)
            add("stock", d, f"{d.name}: best sellers out of stock",
                f"{u:,} units sold in the last 30 days are on items now at zero stock. Raise the PO this week; "
                "see Inventory → Out-of-stock top styles for the styles and sizes.",
                u * price, "30-day demand at zero stock", "high" if u * price >= 500_000 else "medium")

    # 8. territory change: a near-dead distributor next to a working one (same state, same postal circle)
    alive = [d for d in dists.values() if last3(d.id) >= MIN_BASE / 2 and d.pincode]
    for d in dists.values():
        r = rbase.get(d.id, {})
        if d.id not in ever or last3(d.id) >= DEAD or not d.pincode or not r.get("n") or current(d.id) >= DEAD:
            continue
        near = [x for x in alive if x.id != d.id and x.state_id == d.state_id and x.pincode[:2] == d.pincode[:2]]
        if not near:
            continue
        x = min(near, key=lambda x: abs(int(x.pincode) - int(d.pincode)) if x.pincode.isdigit() and d.pincode.isdigit() else 10**6)
        add("reassign", d, f"Move {d.name}'s area to {x.name}?",
            f"{d.name}{f' ({d.city})' if d.city else ''} averaged {_inr(last3(d.id))}/month with {r['n']:,} retailers mapped "
            f"({r.get('never', 0):,} never ordered). {x.name}{f' ({x.city})' if x.city else ''} is nearby and does "
            f"{_inr(last3(x.id))}/month. {rsm_of(d)} to decide whether to hand the retailers over.",
            r.get("never", 0) * spend * 0.05, "if 5% of its never-ordered retailers start ordering", who=f"{rsm_of(d)} (RSM)")

    order = {"stretch": 0, "stalled": 1, "no_asm": 2, "warm": 3, "stock": 4, "slow": 5, "new": 6, "reassign": 7}
    asks.sort(key=lambda a: (order[a["kind"]], 0 if a["priority"] == "high" else 1, -(a["value"] or 0)))
    return {"asks": asks, "td_growth_3m_pct": round(td_growth, 1) if td_growth is not None else None,
            "warm_total": total_warm, "activation_per_month": per_month}
