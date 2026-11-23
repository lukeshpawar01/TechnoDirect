"""Daily automated MIS (requirements doc 6.1) - one email after the morning refresh, the same numbers as the dashboard.

  Yesterday's sales and orders · MTD sales vs target, achievement and balance · new / active / repeat / reactivated
  retailers (MTD) · distributor-wise sales vs target (MTD) · pending orders, cancellations, refunds pending ·
  stock-sync and out-of-stock exceptions.

Sent only when MIS_RECIPIENTS is set (.env, comma-separated): the doc asks for recipients to be agreed first.
The scheduler sends it once a day after the first successful refresh (ingestion/scheduler.py).
    manage.py send_daily_mis --preview mis.html     # write the email to a file, send nothing
    manage.py send_daily_mis --to me@technosport.in # send to one address (test)
    manage.py send_daily_mis                        # send to MIS_RECIPIENTS
"""
import datetime as dt
from html import escape

from django.conf import settings
from django.db.models import Count, Q, Sum

WATERMARK = "daily_mis"


def recipients():
    return [x.strip() for x in (getattr(settings, "MIS_RECIPIENTS", "") or "").split(",") if "@" in x]


def build(today=None):
    """The MIS numbers (system scope: the whole business)."""
    from warehouse.models import Retailer, RetailerMonth

    from .alerts import behind_target, oos_top_sellers, refunds_pending
    from .filters import month_end, month_start, system_filters
    from .metrics import target_values
    from .views.overview import open_sla_breaches, stale_stock_distributors

    f = system_filters("mtd", today=today)
    t = f.today
    y = t - dt.timedelta(days=1)
    ms = month_start(t)

    def sales(qs):
        a = qs.aggregate(s=Sum("gross_value"), n=Count("split_group", distinct=True))
        return float(a["s"] or 0), a["n"] or 0

    y_sales, y_orders = sales(f.orders(start=y, end=y))
    m_sales, m_orders = sales(f.orders(start=ms, end=t))
    tv = target_values("overall", None, [ms], "sales", t)
    target = float(sum(tv.values())) if tv else None
    days_total = (month_end(t) - ms).days + 1
    days_left = (month_end(t) - t).days + 1
    mtd = f.orders(start=ms, end=t)
    active = mtd.values("retailer_id").distinct().count()
    new = Retailer.objects.filter(first_order_date__gte=ms, first_order_date__lte=t).count()
    react = RetailerMonth.objects.filter(month=ms, status="reactivated").count()
    by_d = {r["distributor__name"]: (float(r["s"] or 0), r["n"]) for r in mtd.values("distributor__name")
            .annotate(s=Sum("gross_value"), n=Count("split_group", distinct=True))}
    dt_targets = {}
    from warehouse.models import Distributor

    names = dict(Distributor.objects.values_list("id", "name"))
    for (did, _), v in target_values("distributor", None, [ms], "sales", t).items():
        dt_targets[names.get(did)] = float(v)
    dist_rows = []
    for name in sorted(set(by_d) | set(dt_targets), key=lambda n: -(by_d.get(n, (0, 0))[0])):
        s, n = by_d.get(name, (0.0, 0))
        tg = dt_targets.get(name)
        dist_rows.append({"distributor": name or "Unmapped", "sales": s, "orders": n, "target": tg,
                          "achievement_pct": round(s / tg * 100, 1) if tg else None})
    cancelled = f.orders(start=ms, end=t, qualifying=False, statuses=False).filter(status="cancelled").aggregate(
        n=Count("id"), v=Sum("gross_value"))
    pend = refunds_pending(f)
    return {
        "date": t, "yesterday": y, "month": ms,
        "y_sales": y_sales, "y_orders": y_orders, "m_sales": m_sales, "m_orders": m_orders,
        "target": target, "achievement_pct": round(m_sales / target * 100, 1) if target else None,
        "balance": max(target - m_sales, 0) if target else None,
        "required_per_day": (max(target - m_sales, 0) / days_left) if target and days_left else None,
        "days_total": days_total,
        "active": active, "new": new, "repeat": max(active - new - react, 0), "reactivated": react,
        "distributors": dist_rows,
        "behind": behind_target(f, "distributor"),
        "sla_breaches": open_sla_breaches(f).count(),
        "cancelled": cancelled["n"] or 0, "cancelled_value": float(cancelled["v"] or 0),
        "refunds_pending": pend.count(), "refunds_pending_value": float(pend.aggregate(s=Sum("customer_refund"))["s"] or 0),
        "stock_stale": len(stale_stock_distributors(f)), "oos": oos_top_sellers(f),
    }


def _inr(v):
    from .metrics import fmt_inr

    return fmt_inr(v) if v is not None else "–"


def render(d):
    """(subject, html) for the MIS numbers."""
    td = 'style="padding:6px 10px;border-bottom:1px solid #e5e7eb"'
    tr = 'style="padding:6px 10px;border-bottom:1px solid #e5e7eb;text-align:right"'
    th = 'style="padding:6px 10px;text-align:left;font-weight:600;border-bottom:2px solid #20174A"'
    thr = 'style="padding:6px 10px;text-align:right;font-weight:600;border-bottom:2px solid #20174A"'

    def kv(rows):
        return "".join(f"<tr><td {td}>{escape(k)}</td><td {tr}><b>{v}</b></td></tr>" for k, v in rows)

    month = d["month"].strftime("%b %Y")
    head = [("Yesterday's sales", _inr(d["y_sales"])), ("Yesterday's orders", f'{d["y_orders"]:,}'),
            (f"{month} sales so far", _inr(d["m_sales"])), (f"{month} orders so far", f'{d["m_orders"]:,}'),
            ("Monthly target", _inr(d["target"])),
            ("Achieved", f'{d["achievement_pct"]}%' if d["achievement_pct"] is not None else "–"),
            ("Balance to target", _inr(d["balance"])), ("Needed per day from today", _inr(d["required_per_day"]))]
    rets = [("Active retailers (ordered this month)", f'{d["active"]:,}'), ("New (first-ever order)", f'{d["new"]:,}'),
            ("Repeat", f'{d["repeat"]:,}'), ("Reactivated", f'{d["reactivated"]:,}')]
    ops = [("Orders not dispatched within SLA", f'{d["sla_breaches"]:,}'),
           (f"Cancelled orders ({month})", f'{d["cancelled"]:,} · {_inr(d["cancelled_value"])}'),
           ("Customer refunds pending over 7 days", f'{d["refunds_pending"]:,} · {_inr(d["refunds_pending_value"])}'),
           ("Distributors with stale stock sync (3+ days)", f'{d["stock_stale"]:,}'),
           ("Selling SKUs out of stock at their distributor", f'{len(d["oos"]):,}')]
    dist = "".join(
        f'<tr><td {td}>{escape(r["distributor"])}</td><td {tr}>{_inr(r["sales"])}</td><td {tr}>{r["orders"]:,}</td>'
        f'<td {tr}>{_inr(r["target"])}</td><td {tr}>{(str(r["achievement_pct"]) + "%") if r["achievement_pct"] is not None else "–"}</td></tr>'
        for r in d["distributors"][:40])
    behind = "".join(f"<li>{escape(b['name'])}: {_inr(b['sales'])} vs {_inr(b['expected'])} expected by now "
                     f"({b['pace_pct']:.0f}% of pace)</li>" for b in d["behind"][:10])
    url = (getattr(settings, "PUBLIC_DASHBOARD_URL", "") or "").strip()
    html = f"""<div style="font-family:Segoe UI,Arial,sans-serif;color:#111827;max-width:760px">
<h2 style="color:#20174A;margin:0 0 4px">TechnoDirect daily MIS · {d['date']:%d %b %Y}</h2>
<p style="color:#6b7280;margin:0 0 16px">Sales = gross value of paid, non-cancelled orders. Same numbers as the dashboard
after the morning refresh.{f' <a href="{escape(url)}">Open the dashboard</a>' if url else ''}</p>
<h3 style="margin:16px 0 6px">Sales and target</h3><table style="border-collapse:collapse;width:100%">{kv(head)}</table>
<h3 style="margin:16px 0 6px">Retailers ({month})</h3><table style="border-collapse:collapse;width:100%">{kv(rets)}</table>
<h3 style="margin:16px 0 6px">Exceptions</h3><table style="border-collapse:collapse;width:100%">{kv(ops)}</table>
{f'<h3 style="margin:16px 0 6px">Behind target pace</h3><ul style="margin:0;padding-left:18px">{behind}</ul>' if behind else ''}
<h3 style="margin:16px 0 6px">Distributor-wise ({month})</h3>
<table style="border-collapse:collapse;width:100%"><tr><th {th}>Distributor</th><th {thr}>Sales</th><th {thr}>Orders</th>
<th {thr}>Target</th><th {thr}>Achieved</th></tr>{dist}</table>
</div>"""
    subject = (f"TechnoDirect MIS {d['date']:%d %b}: yesterday {_inr(d['y_sales'])}, MTD {_inr(d['m_sales'])}"
               + (f" ({d['achievement_pct']}% of target)" if d["achievement_pct"] is not None else ""))
    return subject, html


def send(to=None, today=None):
    """Send the MIS to `to` (list) or MIS_RECIPIENTS. Returns the recipients it went to ([] = not sent)."""
    from django.core.mail import EmailMultiAlternatives
    from django.utils import timezone

    from ingestion.models import SyncWatermark

    to = to or recipients()
    if not to:
        return []
    subject, html = render(build(today))
    msg = EmailMultiAlternatives(subject, "Open this email in an HTML-capable mail app to see the MIS.",
                                 settings.DEFAULT_FROM_EMAIL, to)
    msg.attach_alternative(html, "text/html")
    msg.send()
    SyncWatermark.put(WATERMARK, timezone.now(), cursor=(today or timezone.localdate()).isoformat())
    return to


def due(today):
    """True when today's MIS has not gone out yet (and recipients are set)."""
    from ingestion.models import SyncWatermark

    if not recipients():
        return False
    wm = SyncWatermark.objects.filter(key=WATERMARK).first()
    return not (wm and wm.cursor == today.isoformat())
