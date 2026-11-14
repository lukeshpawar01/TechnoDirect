"""Merge duplicate distributors into one (e.g. "Heera Main" is the same business as "Heera Exports Inc").

    python manage.py merge_distributors "Heera Exports Inc" "Heera Main"          # keep the first, absorb the rest
    python manage.py merge_distributors "Heera Exports Inc" "Heera Main" --dry-run

Every reference moves to the kept distributor: orders, retailers, pincode P1/P2, stock, retailer months, loyalty,
CRM tickets, targets (values for the same month are added) and user data scopes. The merged names are kept as
aliases so future files with those spellings match the kept distributor.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analytics.cache import bump_cache_version
from ingestion.csv_import import norm
from warehouse.models import Distributor, InventorySnapshot, Target


def find_distributor(label):
    if str(label).isdigit():
        d = Distributor.objects.filter(pk=int(label)).first()
        if d:
            return d
    n = norm(label)
    hits = {d.id: d for d in Distributor.objects.all()
            if n in {norm(x) for x in [d.name, d.code, *(d.aliases or [])]}}
    if len(hits) != 1:
        raise CommandError(f"'{label}' matches {len(hits)} distributors; use the id instead")
    return next(iter(hits.values()))


def merge(keep, dup):
    """Move everything from `dup` to `keep` and delete `dup`. Returns {relation: rows moved}."""
    moved = {}
    # stock: same (source, sku, date) on both -> keep the kept distributor's row
    clash = InventorySnapshot.objects.filter(distributor=keep).values_list("source", "sku", "snapshot_date")
    clash = set(clash)
    drop = [i.id for i in InventorySnapshot.objects.filter(distributor=dup)
            if (i.source, i.sku, i.snapshot_date) in clash]
    InventorySnapshot.objects.filter(id__in=drop).delete()
    # every FK / M2M to Distributor, including hidden ones (related_name="+")
    for rel in Distributor._meta.get_fields(include_hidden=True):
        if not (rel.auto_created and not rel.concrete):
            continue
        model, field = rel.related_model, rel.field
        if rel.many_to_many:
            through = getattr(model, field.name).through
            col = f"{field.m2m_reverse_field_name()}_id"
            src = f"{field.m2m_field_name()}_id"
            owners = set(through.objects.filter(**{col: keep.id}).values_list(src, flat=True))
            qs = through.objects.filter(**{col: dup.id})
            qs.filter(**{f"{src}__in": owners}).delete()
            moved[f"{model.__name__}.{field.name}"] = qs.update(**{col: keep.id})
        else:
            moved[f"{model.__name__}.{field.name}"] = model.objects.filter(**{field.name: dup}).update(
                **{field.name: keep})
    # targets are keyed by scope_id, not a FK
    for t in Target.objects.filter(scope_type="distributor", scope_id=dup.id):
        twin = Target.objects.filter(scope_type="distributor", scope_id=keep.id, month=t.month, metric=t.metric,
                                     effective_from=t.effective_from, version=t.version).first()
        if twin:
            twin.value += t.value
            twin.notes = (twin.notes + f" + merged {dup.name}")[:255]
            twin.save(update_fields=["value", "notes", "updated_at"])
            t.delete()
        else:
            t.scope_id = keep.id
            t.save(update_fields=["scope_id", "updated_at"])
    for field in ("asm", "state", "region"):
        if getattr(keep, f"{field}_id") is None and getattr(dup, f"{field}_id") is not None:
            setattr(keep, f"{field}_id", getattr(dup, f"{field}_id"))
    for field in ("ck_code", "gstin", "city"):
        if not getattr(keep, field) and getattr(dup, field):
            setattr(keep, field, getattr(dup, field))
    keep.aliases = sorted(set(keep.aliases or []) | set(dup.aliases or []) | {dup.name})
    dup.delete()
    keep.save()
    return {k: v for k, v in moved.items() if v}


class Command(BaseCommand):
    help = "Merge duplicate distributors into the first one given."

    def add_arguments(self, parser):
        parser.add_argument("keep", help="Distributor to keep (name, alias or id)")
        parser.add_argument("duplicates", nargs="+", help="Distributors to merge into it")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        keep = find_distributor(o["keep"])
        dups = [find_distributor(x) for x in o["duplicates"]]
        if any(d.id == keep.id for d in dups):
            raise CommandError("A distributor cannot be merged into itself")
        for d in dups:
            self.stdout.write(f"merge '{d.name}' (id {d.id}, {d.orders.count()} orders, {d.retailers.count()} retailers)"
                              f" -> '{keep.name}' (id {keep.id})")
        if o["dry_run"]:
            self.stdout.write("dry run: nothing changed")
            return
        with transaction.atomic():
            for d in dups:
                self.stdout.write(f"  moved: {merge(keep, d) or 'nothing to move'}")
        bump_cache_version()
        self.stdout.write(self.style.SUCCESS(f"done. aliases of '{keep.name}': {keep.aliases}"))
