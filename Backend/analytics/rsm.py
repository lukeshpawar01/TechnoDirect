"""RSM (Regional Sales Manager) roll-up.

RSM is not stored on orders / retailers. It is derived from the record's ASM (Asm.rsm), falling back to the
RSM heading the record's region when the record has no ASM (distributor-managed territories). Deriving it at
query time means a change in the reporting lines (Master ASM Tracker) re-attributes history immediately,
exactly like an ASM change does.
"""
from django.db import models
from django.db.models import F, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce


def region_rsm_map():
    """{region_id: rsm_id} - the RSM heading each region (lowest id wins if a region has two)."""
    from warehouse.models import Rsm

    out = {}
    for rid, reg in Rsm.objects.filter(is_active=True, region__isnull=False).order_by("id").values_list(
            "id", "region_id"):
        out.setdefault(reg, rid)
    return out


def rsm_q(rsm_ids, mapping):
    """Q restricting a model (described by a dims mapping with 'asm' / 'region' lookups) to these RSMs."""
    from warehouse.models import Asm

    asm_f, reg_f = mapping.get("asm"), mapping.get("region")
    q = Q(pk__in=[])
    if asm_f:
        q |= Q(**{f"{asm_f}__in": list(Asm.objects.filter(rsm_id__in=rsm_ids).values_list("id", flat=True))})
    if reg_f:
        regions = [reg for reg, r in region_rsm_map().items() if r in rsm_ids]
        cond = Q(**{f"{reg_f}__in": regions})
        if asm_f:
            cond &= Q(**{f"{asm_f}__isnull": True})
        q |= cond
    return q


def with_rsm(qs, asm_path="asm", region_field="region_id", name="rsm_key"):
    """Annotate `name` = the record's RSM id (ASM's RSM, else its region's RSM)."""
    from warehouse.models import Rsm

    region_head = Subquery(Rsm.objects.filter(region_id=OuterRef(region_field), is_active=True)
                           .order_by("id").values("id")[:1])
    return qs.annotate(**{name: Coalesce(F(f"{asm_path}__rsm_id"), region_head,
                                         output_field=models.BigIntegerField())})


def rsm_name_for(asm, region_id, names=None, region_map=None):
    """Display name of a single record's RSM (for row-level lists)."""
    from warehouse.models import Rsm

    rid = asm.rsm_id if asm is not None and asm.rsm_id else (region_map or region_rsm_map()).get(region_id)
    if rid is None:
        return None
    if names is not None:
        return names.get(rid)
    return Rsm.objects.filter(id=rid).values_list("name", flat=True).first()
