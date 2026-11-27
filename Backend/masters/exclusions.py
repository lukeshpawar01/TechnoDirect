"""Distributors the user removed from the dashboard (ManualMapping kind "distributor_removed").

What removing means (user, 2026-11-27):
  * the distributor disappears from the dashboard NOW: lists, filters, pickers, stock, suggestions, sync status
    (Distributor.removed = True, is_active = False; its stock rows are deleted);
  * what it CONTRIBUTED stays in the months it happened: its orders (sales, MBR, P&L, retention...), the retailers who
    ordered, settlement rows, BlueOrigin rows, targets and ASM history keep counting, under its name;
  * a removed distributor with no history at all (or a copy another sheet created by name) is deleted.
Refreshes keep it removed: the TD import does not reactivate it or load its stock (`excluded_source_ids`), and
`apply()` runs after every import (analytics/derivations.py). Its new orders, if TD ever sends any, still count.
Each removal is one register entry: value = {"source_ids", "names", "details"}. Restoring (closing the entry) shows
it again, and the next refresh brings its stock back.
Admin page: Admin → Mappings → Removed distributors (masters/views.py RemovedDistributorsView).
"""
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.utils.timezone import localdate

from ingestion.normalize import norm

KIND = "distributor_removed"


def _entries():
    from .models import ManualMapping

    return ManualMapping.objects.filter(kind=KIND, status="active")


def _collect(key):
    out = set()
    for e in _entries():
        out.update((e.value or {}).get(key) or [])
    return out


def excluded_source_ids():
    return _collect("source_ids")


def excluded_names():
    return {norm(n) for n in _collect("names")}


# "purge" removals (internal / test accounts, e.g. Growthhive - user, 2026-11-27): everything goes, history included -
# the distributor, its orders (sales leave their months), the retailers who only bought from it, stock, settlement and
# BlueOrigin rows. The import then skips its orders and those retailers.
def _purge_entries():
    return [e for e in _entries() if (e.value or {}).get("mode") == "purge"]


def purged_source_ids():
    return {s for e in _purge_entries() for s in (e.value or {}).get("source_ids") or []}


def purged_retailer_ids():
    return {s for e in _purge_entries() for s in (e.value or {}).get("retailer_ids") or []}


def _purge(entry):
    """Delete a purge entry's distributors and all their data; record the retailers so the import skips them."""
    from warehouse.models import BoRetailer, Distributor, DistributorSettlement, Order, Retailer

    v = entry.value or {}
    names = {norm(n) for n in v.get("names") or []}
    ds = [d for d in Distributor.objects.only("id", "name", "source_id")
          if d.source_id in (v.get("source_ids") or []) or norm(d.name) in names]
    ids = [d.id for d in ds]
    orders = Order.objects.filter(distributor_id__in=ids)
    order_pks = list(orders.values_list("id", flat=True))
    cand = set(Retailer.objects.filter(distributor_id__in=ids).values_list("id", flat=True))
    cand |= set(orders.exclude(retailer__isnull=True).values_list("retailer_id", flat=True))
    cand |= set(Retailer.objects.filter(source_id__in=v.get("retailer_ids") or []).values_list("id", flat=True))
    elsewhere = dict(Order.objects.filter(retailer_id__in=cand).exclude(id__in=order_pks)
                     .exclude(distributor__isnull=True).order_by("placed_date")
                     .values_list("retailer_id", "distributor_id"))
    drop = [r for r in cand if r not in elsewhere]
    sids = set(Retailer.objects.filter(id__in=drop).exclude(source_id="").values_list("source_id", flat=True))
    if sids - set(v.get("retailer_ids") or []):
        entry.value = {**v, "retailer_ids": sorted(sids | set(v.get("retailer_ids") or []))}
        entry.save(update_fields=["value", "updated_at"])
    for rid, did in elsewhere.items():
        Retailer.objects.filter(id=rid, distributor_id__in=ids).update(distributor_id=did)
    by_name = [x.id for x in DistributorSettlement.objects.only("id", "sheet_distributor") if norm(x.sheet_distributor) in names]
    n = DistributorSettlement.objects.filter(Q(distributor_id__in=ids) | Q(order_id__in=order_pks) | Q(id__in=by_name)).delete()[0]
    n += BoRetailer.objects.filter(distributor_id__in=ids).delete()[0]
    n += Order.objects.filter(id__in=order_pks).delete()[0]
    n += Retailer.objects.filter(id__in=drop).delete()[0]
    n += Distributor.objects.filter(id__in=ids).delete()[0]
    return n


def matching(qs=None):
    """Distributors that are excluded, by TD id or by name."""
    from warehouse.models import Distributor

    sids, names = excluded_source_ids(), excluded_names()
    if not sids and not names:
        return Distributor.objects.none()
    qs = qs if qs is not None else Distributor.objects.all()
    by_name = [d.id for d in qs.only("id", "name") if norm(d.name) in names]
    return qs.filter(Q(source_id__in=sids) | Q(id__in=by_name))


def _has_history(ids):
    """Distributors (of `ids`) that contributed something: orders, settlement rows or offline (BlueOrigin) rows."""
    from warehouse.models import BoRetailer, DistributorSettlement, Order

    out = set(Order.objects.filter(distributor_id__in=ids).values_list("distributor_id", flat=True))
    out |= set(DistributorSettlement.objects.filter(distributor_id__in=ids).values_list("distributor_id", flat=True))
    out |= set(BoRetailer.objects.filter(distributor_id__in=ids).values_list("distributor_id", flat=True))
    return out


def impact(ids):
    """What removing these distributors does (shown before the admin confirms)."""
    from warehouse.models import Distributor, InventorySnapshot, Order, Retailer

    out = []
    for d in Distributor.objects.filter(id__in=ids).order_by("name"):
        o = Order.objects.filter(distributor=d)
        q = o.filter(is_qualifying=True).aggregate(v=Sum("gross_value"), n=Count("id"), last=Max("placed_date"))
        out.append({
            "id": d.id, "name": d.name, "city": d.city, "is_active": d.is_active,
            "orders": o.count(), "sales": float(q["v"] or 0), "last_order": q["last"].isoformat() if q["last"] else None,
            "retailers": Retailer.objects.filter(distributor=d).count(),
            "stock_units": InventorySnapshot.objects.filter(distributor=d, is_latest=True).aggregate(
                u=Sum("quantity"))["u"] or 0,
        })
    return out


@transaction.atomic
def apply():
    """Hide the excluded distributors (keeping their history) and delete copies with no history.
    Returns how many distributors changed."""
    from warehouse.models import Distributor, InventorySnapshot

    from .models import ManualMapping

    purged = sum(_purge(e) for e in _purge_entries())
    ds = list(matching())
    if not ds:
        if purged:
            from analytics.cache import bump_cache_version

            bump_cache_version()
        return 0
    ids = [d.id for d in ds]
    keep = _has_history(ids)
    gone = [i for i in ids if i not in keep]
    hide = Distributor.objects.filter(id__in=keep).filter(Q(removed=False) | Q(is_active=True))
    n = hide.update(removed=True, is_active=False)
    stock = InventorySnapshot.objects.filter(distributor_id__in=keep).delete()[0]  # current stock: not shown any more
    if gone:
        # register entries that point at them (e.g. an ASM given in chat) are closed and kept, not cascaded away
        for e in ManualMapping.objects.filter(distributor_id__in=gone).exclude(kind=KIND):
            e.value = {**(e.value or {}), "distributor_name": e.distributor.name}
            if e.status == "active":
                e.status, e.closed_on = "removed", localdate()
                e.closed_reason = "the distributor was removed from the dashboard"
            e.distributor = None
            e.save()
        Distributor.objects.filter(id__in=gone).delete()
        n += len(gone)
    if n or stock or purged:
        from analytics.cache import bump_cache_version

        bump_cache_version()
    return n


def unhide(entry):
    """Restoring a removal: show its distributors again (the next refresh sets is_active from TD and loads stock)."""
    from warehouse.models import Distributor

    v = entry.value or {}
    names = {norm(x) for x in v.get("names") or []}
    ids = [d.id for d in Distributor.objects.filter(removed=True).only("id", "name", "source_id")
           if d.source_id in (v.get("source_ids") or []) or norm(d.name) in names]
    return Distributor.objects.filter(id__in=ids).update(removed=False, is_active=True)


def remove_distributors(names_or_ids, said, given_on=None, user=None, purge=False):
    """Record the user's instruction and apply it. names_or_ids: Distributor ids.
    purge=True: internal / test account - its history goes too (see _purge)."""
    from warehouse.models import Distributor

    from .models import ManualMapping

    ds = list(Distributor.objects.filter(id__in=names_or_ids))
    e = ManualMapping.objects.create(
        kind=KIND, distributor=None, given_on=given_on or localdate(), said=said,
        value={"source_ids": sorted({d.source_id for d in ds if d.source_id}),
               "names": sorted({d.name for d in ds}),
               "details": impact([d.id for d in ds]),
               "removed_by": getattr(user, "email", "") or "", "mode": "purge" if purge else "hide"})
    return e, apply()


def removed_list():
    """Every removal (active and restored), newest first, for the admin page."""
    from .models import ManualMapping

    out = []
    for e in ManualMapping.objects.filter(kind=KIND).order_by("-id"):
        v = e.value or {}
        det = v.get("details") or []
        out.append({"id": e.id, "names": v.get("names") or [], "details": det, "mode": v.get("mode") or "hide",
                    "orders": sum(x.get("orders") or 0 for x in det), "sales": sum(x.get("sales") or 0 for x in det),
                    "said": e.said, "given_on": e.given_on.isoformat(), "status": e.status,
                    "closed_on": e.closed_on.isoformat() if e.closed_on else None})
    return out
