"""MBR written content: the month's commentary and goal (MbrReview) and its lines (MbrItem) for pages 2-4.

Tech adherence (page 3), per item with a planned date:
  on time   done on or before the planned date
  late      done after the planned date
  overdue   not done and the planned (or revised) date has passed
  slip      days between the planned date and the revised / done date (or today when overdue)
Adherence % = done on time ÷ (done + overdue) among items due by the end of the month.
"""
import datetime as dt
from decimal import Decimal, InvalidOperation

from django.utils.timezone import localdate
from rest_framework.exceptions import ValidationError

from analytics.filters import add_months, month_end

from .models import MbrItem, MbrReview

KIND_LABELS = {sec: dict(kinds) for sec, kinds in MbrItem.KINDS.items()}
TEXT = ("title", "detail", "owner", "blocker")
DATES = ("planned_date", "revised_date", "done_date", "event_date")
CHOICES = {"team": dict(MbrItem.TEAMS), "lever": dict(MbrItem.LEVERS), "status": dict(MbrItem.STATUSES),
           "priority": dict(MbrItem.PRIORITIES)}


def choices():
    return {
        "sections": [{"value": v, "label": l} for v, l in MbrItem.SECTIONS],
        "kinds": {sec: [{"value": v, "label": l} for v, l in kinds] for sec, kinds in MbrItem.KINDS.items()},
        **{k: [{"value": v, "label": l} for v, l in d.items()] for k, d in
           (("teams", CHOICES["team"]), ("levers", CHOICES["lever"]), ("statuses", CHOICES["status"]),
            ("priorities", CHOICES["priority"]))},
    }


def _date(v, field):
    if v in (None, ""):
        return None
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        raise ValidationError({field: "use YYYY-MM-DD"}) from None


def _amount(v, field):
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v).replace(",", "").replace("₹", "").strip())
    except (InvalidOperation, ValueError):
        raise ValidationError({field: "must be a number"}) from None
    if d < 0:
        raise ValidationError({field: "cannot be negative"})
    return d


def apply_item(item, data, partial):
    """Validate `data` onto `item` (unsaved changes)."""
    if not partial or "section" in data:
        sec = data.get("section")
        if sec not in KIND_LABELS:
            raise ValidationError({"section": "must be growth, tech or other"})
        item.section = sec
    if not partial or "kind" in data:
        kind = data.get("kind") or next(iter(KIND_LABELS[item.section]))
        if kind not in KIND_LABELS[item.section]:
            raise ValidationError({"kind": f"must be one of {', '.join(KIND_LABELS[item.section])}"})
        item.kind = kind
    for f in TEXT:
        if f in data:
            setattr(item, f, str(data[f] or "").strip())
    if not item.title:
        raise ValidationError({"title": "required"})
    if len(item.title) > 200:
        raise ValidationError({"title": "200 characters at most"})
    for f, opts in CHOICES.items():
        if f in data:
            v = data[f] or ""
            if v and v not in opts:
                raise ValidationError({f: f"must be one of {', '.join(opts)}"})
            if f in ("status", "priority") and not v:
                raise ValidationError({f: "required"})
            setattr(item, f, v)
    for f in DATES:
        if f in data:
            setattr(item, f, _date(data[f], f))
    if "expected_impact" in data:
        item.expected_impact = _amount(data["expected_impact"], "expected_impact")
    if "sort" in data:
        try:
            item.sort = int(data["sort"] or 0)
        except (TypeError, ValueError):
            raise ValidationError({"sort": "must be a whole number"}) from None
    if item.status == "done" and not item.done_date:
        item.done_date = localdate()
    if item.status != "done":
        item.done_date = None if "status" in data else item.done_date
    return item


def adherence(item, as_of):
    """On-time state of a dated item (tech page)."""
    if not item.planned_date:
        return {"state": "undated", "slip_days": None}
    due = item.revised_date or item.planned_date
    if item.status == "done" and item.done_date:
        slip = (item.done_date - item.planned_date).days
        return {"state": "on_time" if slip <= 0 else "late", "slip_days": max(slip, 0)}
    if item.status == "dropped":
        return {"state": "dropped", "slip_days": None}
    if due < as_of:
        return {"state": "overdue", "slip_days": (as_of - item.planned_date).days}
    slip = (item.revised_date - item.planned_date).days if item.revised_date else 0
    return {"state": "slipping" if slip > 0 else "on_track", "slip_days": max(slip, 0)}


def item_json(i, as_of):
    return {
        "id": i.id, "month": i.month.isoformat()[:7], "section": i.section, "kind": i.kind,
        "kind_label": KIND_LABELS.get(i.section, {}).get(i.kind, i.kind), "title": i.title, "detail": i.detail,
        "team": i.team, "team_label": CHOICES["team"].get(i.team, ""), "lever": i.lever,
        "lever_label": CHOICES["lever"].get(i.lever, ""), "owner": i.owner, "status": i.status,
        "status_label": CHOICES["status"][i.status], "priority": i.priority,
        "expected_impact": float(i.expected_impact) if i.expected_impact is not None else None,
        **{f: getattr(i, f).isoformat() if getattr(i, f) else None for f in DATES},
        "blocker": i.blocker, "carried_from": i.carried_from, "sort": i.sort,
        "updated_by": i.updated_by, "updated_at": i.updated_at.isoformat() if i.updated_at else None,
        **({"adherence": adherence(i, as_of)} if i.section == "tech" else {}),
    }


def tech_summary(items, month, today):
    as_of = min(month_end(month), today)
    due = [i for i in items if i.planned_date and (i.revised_date or i.planned_date) <= month_end(month)
           and i.status != "dropped"]
    states = [adherence(i, as_of)["state"] for i in due]
    done = [i for i in items if i.status == "done"]
    on_time = states.count("on_time")
    measured = on_time + states.count("late") + states.count("overdue")
    slips = [s for s in (adherence(i, as_of)["slip_days"] for i in items) if s]
    return {
        "total": len(items), "done": len(done), "on_time": on_time, "late": states.count("late"),
        "overdue": states.count("overdue"), "blocked": sum(1 for i in items if i.status == "blocked"),
        "in_progress": sum(1 for i in items if i.status == "in_progress"),
        "adherence_pct": round(on_time * 100 / measured, 1) if measured else None,
        "avg_slip_days": round(sum(slips) / len(slips), 1) if slips else None,
    }


def month_payload(month, today, can_edit):
    review = MbrReview.objects.filter(month=month).first()
    items = list(MbrItem.objects.filter(month=month))
    as_of = min(month_end(month), today)
    prev = add_months(month, -1)
    carried = set(MbrItem.objects.filter(month=month).exclude(carried_from=None).values_list("carried_from", flat=True))
    open_prev = MbrItem.objects.filter(month=prev, section__in=("growth", "tech"), status__in=MbrItem.OPEN) \
        .exclude(id__in=carried).count()
    return {
        "month": month.isoformat()[:7],
        "review": {
            "went_well": review.went_well if review else "", "needs_attention": review.needs_attention if review else "",
            "goal_monthly_sales": float(review.goal_monthly_sales) if review else None,
            "goal_by": review.goal_by.isoformat()[:7] if review and review.goal_by else None,
            "updated_by": review.updated_by if review else "",
            "updated_at": review.updated_at.isoformat() if review else None,
        },
        "items": [item_json(i, as_of) for i in items],
        "tech_summary": tech_summary([i for i in items if i.section == "tech"], month, today),
        "previous_open": open_prev, "previous_month": prev.isoformat()[:7],
        "choices": choices(), "can_edit": can_edit,
    }


def save_review(month, data, who):
    r, _ = MbrReview.objects.get_or_create(month=month)
    for f in ("went_well", "needs_attention"):
        if f in data:
            setattr(r, f, str(data[f] or "").strip())
    if "goal_monthly_sales" in data:
        g = _amount(data["goal_monthly_sales"], "goal_monthly_sales")
        if not g:
            raise ValidationError({"goal_monthly_sales": "must be more than 0"})
        r.goal_monthly_sales = g
    if "goal_by" in data:
        raw = data["goal_by"]
        r.goal_by = _date(f"{raw}-01" if raw and len(str(raw)) == 7 else raw, "goal_by")
        if r.goal_by:
            r.goal_by = r.goal_by.replace(day=1)
            if r.goal_by < month:
                raise ValidationError({"goal_by": "must be this month or later"})
    r.updated_by = who
    r.save()
    return r


def carry_forward(month, who):
    """Copy last month's open growth and tech lines into `month` (once each). Returns how many were copied."""
    prev = add_months(month, -1)
    done = set(MbrItem.objects.filter(month=month).exclude(carried_from=None).values_list("carried_from", flat=True))
    new = []
    for i in MbrItem.objects.filter(month=prev, section__in=("growth", "tech"), status__in=MbrItem.OPEN):
        if i.id in done:
            continue
        new.append(MbrItem(
            month=month, section=i.section, kind=i.kind, title=i.title, detail=i.detail, team=i.team, lever=i.lever,
            owner=i.owner, status=i.status, priority=i.priority, expected_impact=i.expected_impact,
            planned_date=i.planned_date, revised_date=i.revised_date, blocker=i.blocker, carried_from=i.id,
            sort=i.sort, created_by=who, updated_by=who))
    MbrItem.objects.bulk_create(new)
    # keep the goal too, so the new month's page 2 starts where the last one ended
    last = MbrReview.objects.filter(month=prev).first()
    if last and not MbrReview.objects.filter(month=month).exists():
        MbrReview.objects.create(month=month, goal_monthly_sales=last.goal_monthly_sales, goal_by=last.goal_by,
                                 updated_by=who)
    return len(new)
