"""Bulk upsert helper (INSERT ... ON CONFLICT DO UPDATE) for warehouse tables."""
from django.utils import timezone


def upsert(model, rows, unique_fields=("source_id",), batch_size=1000):
    """Upsert a list of dicts. Every dict must contain the unique fields.

    Returns number of rows written. Uses Django's bulk_create(update_conflicts=True),
    supported on PostgreSQL and SQLite >= 3.24.
    """
    if not rows:
        return 0
    now = timezone.now()
    field_names = {f.name for f in model._meta.concrete_fields} | {
        f.attname for f in model._meta.concrete_fields
    }
    keys = set()
    for r in rows:
        keys.update(r.keys())
    unique_all = set(unique_fields)
    for f in model._meta.concrete_fields:
        if f.name in unique_fields:
            unique_all.add(f.attname)
    update_fields = [k for k in keys if k not in unique_all and k in field_names]
    has_updated_at = "updated_at" in field_names
    if has_updated_at and "updated_at" not in update_fields:
        update_fields.append("updated_at")
    objs = []
    for r in rows:
        obj = model(**r)
        if has_updated_at:
            obj.updated_at = now
        objs.append(obj)
    # update_fields must use field *names* (not attnames)
    attname_to_name = {f.attname: f.name for f in model._meta.concrete_fields}
    update_fields = sorted({attname_to_name.get(f, f) for f in update_fields})
    model.objects.bulk_create(
        objs,
        batch_size=batch_size,
        update_conflicts=True,
        unique_fields=list(unique_fields),
        update_fields=update_fields,
    )
    return len(objs)


def chunked(seq, size=900):
    seq = list(seq)
    for i in range(0, len(seq), size):
        yield seq[i:i + size]
