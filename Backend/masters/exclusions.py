"""Distributors the user removed from the dashboard (ManualMapping kind "distributor_removed").

The TD export keeps listing them, so removing the rows once is not enough:
  * the TD import skips their source ids (`excluded_source_ids`), so a refresh does not bring them back;
  * `apply()` runs after every import (analytics/derivations.py) and deletes any copy that another import created
    by name (ASM tracker, BlueOrigin, distributor-name sheets), with its stock rows and ASM history.
Each removal is one register entry: value = {"source_ids": [...], "names": [...]}, distributor empty (the row it
pointed at is gone). Closing the entry (manual_mappings remove) lets the distributor come back at the next refresh.
"""
from django.db import transaction
from django.utils.timezone import localdate

from ingestion.normalize import norm

KIND = "distributor_removed"


def _entries():
    from .models import ManualMapping

    return ManualMapping.objects.filter(kind=KIND, status="active")


def excluded_source_ids():
    out = set()
    for e in _entries():
        out.update((e.value or {}).get("source_ids") or [])
    return out


def excluded_names():
    out = set()
    for e in _entries():
        out.update(norm(n) for n in (e.value or {}).get("names") or [])
    return out


def matching(qs=None):
    """Distributors that are excluded, by TD id or by name."""
    from django.db.models import Q

    from warehouse.models import Distributor

    sids, names = excluded_source_ids(), excluded_names()
    if not sids and not names:
        return Distributor.objects.none()
    qs = qs if qs is not None else Distributor.objects.all()
    by_name = [d.id for d in qs.only("id", "name") if norm(d.name) in names]
    return qs.filter(Q(source_id__in=sids) | Q(id__in=by_name))


@transaction.atomic
def apply():
    """Delete the excluded distributors that exist now. Returns how many were removed."""
    from .models import ManualMapping

    ds = list(matching())
    if not ds:
        return 0
    ids = [d.id for d in ds]
    # register entries that point at them (e.g. an ASM given in chat) are closed and kept, not cascaded away
    for e in ManualMapping.objects.filter(distributor_id__in=ids).exclude(kind=KIND):
        e.value = {**(e.value or {}), "distributor_name": e.distributor.name}
        if e.status == "active":
            e.status, e.closed_on = "removed", localdate()
            e.closed_reason = "the distributor was removed from the dashboard"
        e.distributor = None
        e.save()
    from warehouse.models import Distributor

    Distributor.objects.filter(id__in=ids).delete()  # stock rows, ASM history etc. go with it (cascade)
    from analytics.cache import bump_cache_version

    bump_cache_version()
    return len(ids)


def remove_distributors(names_or_ids, said, given_on=None):
    """Record the user's instruction and apply it. names_or_ids: Distributor ids."""
    from warehouse.models import Distributor

    from .models import ManualMapping

    ds = list(Distributor.objects.filter(id__in=names_or_ids))
    e = ManualMapping.objects.create(
        kind=KIND, distributor=None, given_on=given_on or localdate(), said=said,
        value={"source_ids": sorted({d.source_id for d in ds if d.source_id}),
               "names": sorted({d.name for d in ds}),
               "details": [{"name": d.name, "city": d.city, "source_id": d.source_id} for d in ds]})
    return e, apply()
