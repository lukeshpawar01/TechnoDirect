"""MBR page 3 - the Marketing card: campaigns that promote TD, each sized from the data.

Every campaign has an audience (who, how many), a channel, an offer / message, and a ₹ estimate:
audience x an assumed conversion rate x today's spend per transacting retailer. The conversion rates are planning
assumptions (shown on the card), not measurements; replace them with real results after the first run.

  bo_top        - TechnoSport's best offline retailers (BlueOrigin Platinum / Gold / Silver) not on TD yet
  warm          - KYC done + buy TechnoSport offline, never ordered on TD
  kyc_never     - KYC done, never ordered, not known offline (cold)
  lapsed        - ordered on TD before, nothing for 60+ days
  launches      - new styles (last 90 days) to put in front of buyers, led by the best seller
  season        - next month's push behind the categories growing fastest (from the product section)
  region        - the state with the most KYC retailers but the lowest share ordering: a local push
"""
import datetime as dt

from django.db.models import Count, Q, Sum

from warehouse.models import BoRetailer, Retailer

from .metrics import num

LAPSED_DAYS = 60
RATES = {"bo_top": 0.05, "warm": 0.10, "kyc_never": 0.02, "lapsed": 0.15, "region": 0.03}


def _inr(v):
    v = float(v or 0)
    return f"₹{v / 1e7:.2f} Cr" if v >= 1e7 else f"₹{v / 1e5:.1f} L" if v >= 1e5 else f"₹{v:,.0f}"


def marketing_asks(f, card):
    path, prod = card["path"], card.get("products") or {}
    spend = path.get("spend_per_retailer") or 0
    today = f.today
    nxt = (dt.date.fromisoformat(card["month"] + "-01").replace(day=28) + dt.timedelta(days=4))
    out = []

    def add(kind, title, audience, channel, offer, detail, rate=None, value=None, priority="medium"):
        v = value if value is not None else (audience * rate * spend if rate else None)
        out.append({"kind": kind, "title": title, "audience": audience, "channel": channel, "offer": offer,
                    "detail": detail, "rate_pct": round(rate * 100) if rate else None,
                    "value": num(v) if v else None, "value_label": "monthly sales if it converts" if rate else "sales at stake",
                    "priority": priority})

    # 1. TechnoSport's best offline retailers, not on TD
    top = BoRetailer.objects.filter(td_retailer__isnull=True, tier__in=("Platinum", "Gold", "Silver"))
    tiers = dict(top.values_list("tier").annotate(n=Count("id")).values_list("tier", "n"))
    n_top = sum(tiers.values())
    if n_top:
        add("bo_top", "“Your TechnoSport, now on TD” for top offline retailers", n_top,
            "WhatsApp from the distributor's number + ASM visit",
            "First-order offer and app onboarding at the counter",
            f"{tiers.get('Platinum', 0):,} Platinum, {tiers.get('Gold', 0):,} Gold and {tiers.get('Silver', 0):,} Silver retailers buy "
            "TechnoSport offline (BlueOrigin) but are not on TD. They already sell the brand: the message is speed, full range "
            "and credit on the app, not the brand.", RATES["bo_top"], priority="high")

    # 2. warm and cold never-ordered KYC retailers
    never = Retailer.objects.filter(kyc_status="approved", first_order_date__isnull=True)
    warm = never.filter(warm_match=True).count()
    cold = never.count() - warm
    if warm:
        add("warm", "First-order push to warm KYC retailers", warm, "WhatsApp + call, then ASM visit",
            "Free delivery / extra margin on the first order this month",
            f"{warm:,} retailers finished KYC and buy TechnoSport offline but never ordered on TD. One reminder series with "
            "the 10 best sellers in their area and a first-order offer; ASMs follow up the ones who open it.",
            RATES["warm"], priority="high")
    if cold:
        add("kyc_never", "Welcome series for cold KYC retailers", cold, "WhatsApp / SMS series (3 messages over 2 weeks)",
            "Starter pack: best sellers in small packs, low minimum order",
            f"{cold:,} KYC-done retailers have never ordered and are not known offline. Teach them the app and start small: "
            "a starter pack lowers the first-order risk.", RATES["kyc_never"])

    # 3. lapsed TD buyers
    cut = today - dt.timedelta(days=LAPSED_DAYS)
    lapsed = Retailer.objects.filter(first_order_date__isnull=False, last_order_date__lt=cut)
    n_lapsed = lapsed.count()
    if n_lapsed:
        hist = lapsed.aggregate(s=Sum("total_sales"))["s"] or 0
        add("lapsed", f"Win back {n_lapsed:,} lapsed TD buyers", n_lapsed, "Call by distributor / ASM + WhatsApp",
            "“We miss you” reorder offer on their last-bought styles",
            f"They ordered on TD before (₹{float(hist) / 1e7:.2f} Cr in total) but nothing in {LAPSED_DAYS}+ days. "
            "Ask why (stock, delivery, price), fix it, and send their last-bought styles back in stock.",
            RATES["lapsed"], priority="high" if n_lapsed >= 200 else "medium")

    # 4. new launches
    p = prod.get("pulse") or {}
    lead = ((prod.get("leaders") or {}).get("30") or {}).get("new_launches") or []
    if p.get("new_launches"):
        best = ", ".join(x["style"] for x in lead[:3])
        add("launches", "New launch showcase", p.get("buyers") or 0, "App banner + WhatsApp catalogue + distributor counter display",
            "Launch price / bundle for the first 2 weeks",
            f"{p['new_launches']} styles launched in the last 90 days make {p.get('new_launch_share_pct') or 0:.1f}% of sales "
            f"(bar: 10%). Lead with what is already selling{f' ({best})' if best else ''} to this month's {p.get('buyers') or 0:,} buyers.",
            value=max((0.10 * (sum(c["sales"] for c in prod.get("categories", [])) or 0)) - (p.get("new_launch_sales") or 0), 0) or None,
            priority="medium" if (p.get("new_launch_share_pct") or 0) >= 10 else "high")

    # 5. season: the categories growing fastest
    scale = [c for c in prod.get("categories", []) if c.get("call") == "scale" and c.get("share_pct", 0) >= 1]
    if scale:
        scale.sort(key=lambda c: -(c["change"] or 0))
        names = ", ".join(c["name"] for c in scale[:3])
        lead_style = scale[0].get("top_style")
        add("season", f"{nxt:%B} push: {names}", p.get("buyers") or 0, "App home banner, WhatsApp, distributor counters",
            "Bundle: buy the season's set, get a better slab",
            f"These categories are growing faster than TD this month ({', '.join(f'{c['name']} {c['mom_pct']:+.0f}%' for c in scale[:3] if c.get('mom_pct') is not None)})"
            f"{f', led by {lead_style}' if lead_style else ''}. Put them in front of every buyer next month, with stock confirmed first.",
            value=sum(c["change"] for c in scale[:3] if c["change"] > 0) or None)

    # 6. the state with the most room: many KYC retailers, few ordering
    states = (Retailer.objects.filter(kyc_status="approved", state__isnull=False)
              .values("state__name").annotate(kyc=Count("id"), buying=Count("id", filter=Q(last_order_date__gte=today - dt.timedelta(days=30))))
              .filter(kyc__gte=200))
    rows = [(s["state__name"], s["kyc"], s["buying"], s["buying"] / s["kyc"] * 100) for s in states]
    if rows:
        st, kyc, buying, ad = min(rows, key=lambda r: (r[3], -r[1]))
        add("region", f"{st}: local push", kyc - buying, "Retailer meet with distributors + local WhatsApp groups",
            "Meet-day order offer",
            f"{kyc:,} KYC retailers in {st} but only {buying:,} ({ad:.1f}%) ordered in the last 30 days, the lowest of the bigger "
            "states. One retailer meet per major town with the distributor, app demo and orders on the spot.",
            RATES["region"])

    order = {"high": 0, "medium": 1}
    out.sort(key=lambda a: (order[a["priority"]], -(a["value"] or 0)))
    return {"asks": out, "spend_per_retailer": num(spend), "rates": {k: round(v * 100) for k, v in RATES.items()}}
