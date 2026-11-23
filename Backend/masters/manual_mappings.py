"""Mappings the user gave by hand (in chat, no sheet or file behind them) - see masters.models.ManualMapping.

They are applied to the dashboard like any mapping, but recorded here so proper data can take over:
  * ASM tracker / workbook / ASM editor sets a distributor's ASM for a month  -> `superseded()` closes the manual
    entries of that distributor covering that month: "confirmed" when it says the same, "replaced" when it differs
    (the proper data has already been applied by the loader - nothing is undone).
  * The live incentive sheet (TargetSplit rows) is compared by `check()` at every refresh: agreement closes the
    entry as "confirmed"; disagreement is only flagged (`conflict`) because targets follow the dashboard's ASM until
    the user decides (user, 2026-11-19).
  * `remove()` takes an entry out by hand and undoes its effect.

    manage.py manual_mappings list | check | seed | remove <id> [--keep]
"""
import datetime as dt

from django.db import transaction
from django.utils.timezone import localdate

D = dt.date

# What the user gave in chat (2026-11-14 .. 2026-11-18). distributor / ASM by name; `seed()` resolves them.
SEED = [
    # offline-only (BlueOrigin) distributors - pasted list, 18 Nov 2026
    *[{"kind": "distributor_asm", "distributor": d, "asm": a, "given_on": D(2026, 11, 18),
       "said": f"{said} (pasted list of offline-only distributors and their ASMs)"}
      for d, a, said in [
          ("Arti Hosiery", "Gaurav", "Arti hosiery - gaurav"),
          ("Kripal Traders", "Gaurav", "Kripal traders - Gaurav"),
          ("BK Enterprises", "Ankush", "Bk enterprise - Ankush"),
          ("Gandhi", "Sateesh", "Gandhi - Satish"),
          ("Radhe Radhe", "Sateesh", "Radhe radhe - Satish"),
          ("Noble", "Mohd Aameer", "Noble - Mohm Ameer"),
          ("Savo Investments", "JP", "Savo investment - JP"),
          ("Sri Sai Durga Trader - Jeypore", "Supriya", "Sri sai durga traders jeypore - Supriya"),
          ("U S Urbanic", "Danjith", "Us urbanic - Dhanjit"),
      ]],
    # Virat Sports Wear (AP) ASM history - 16/17 Nov 2026
    {"kind": "asm_handover", "distributor": "Virat Sports Wear", "asm": "Imran", "start": D(2025, 2, 1),
     "end": D(2025, 12, 31), "given_on": D(2026, 11, 16),
     "said": "Imrantulla handles AP (Andhra Pradesh) ... then resigned"},
    {"kind": "asm_handover", "distributor": "Virat Sports Wear", "asm": "Imran & Anil", "start": D(2026, 1, 1),
     "end": D(2026, 9, 30), "given_on": D(2026, 11, 16),
     "said": "before October Imran and Anil work together, so keep them together before October"},
    {"kind": "asm_handover", "distributor": "Virat Sports Wear", "asm": "Anil", "start": D(2026, 10, 1),
     "end": None, "given_on": D(2026, 11, 16),
     "said": "after October it's not Valluru Sreenivas, it's assigned to Anil only"},
    # ASM swap - 23 Nov 2026 (the Sep-26 handover and the Nov-26 tracker had these two the other way round)
    {"kind": "asm_handover", "distributor": "S H Hosiery", "asm": "Shankar", "start": D(2026, 9, 1), "end": None,
     "given_on": D(2026, 11, 23), "said": "sh hosiery ASM is Shankar"},
    {"kind": "asm_handover", "distributor": "Jodhpur Apparels", "asm": "Yatendra", "start": D(2026, 9, 1), "end": None,
     "given_on": D(2026, 11, 23), "said": "Jodhpur Apparel is Yatendra"},
    {"kind": "distributor_alias", "distributor": "Virat Sports Wear", "value": {"alias": "Sri Sai Enterprise"},
     "given_on": D(2026, 11, 17), "said": "Sri Sai Enterprise is Virat Sports Wear"},
    {"kind": "distributor_merge", "distributor": "Heera Exports Inc", "value": {"merged": "Heera Main"},
     "given_on": D(2026, 11, 14), "said": "heera main and heera distributors are not different"},
]


def _month(d):
    return d.replace(day=1)


def seed():
    """Register the SEED entries (idempotent: an entry already registered, in any status, is left alone)."""
    from warehouse.models import Asm, Distributor

    from .models import ManualMapping

    made, missing = 0, []
    for s in SEED:
        d = Distributor.objects.filter(name=s["distributor"]).first()
        a = Asm.objects.filter(name=s["asm"]).first() if s.get("asm") else None
        if d is None or (s.get("asm") and a is None):
            missing.append(f"{s['distributor']} / {s.get('asm')}")
            continue
        key = {"kind": s["kind"], "distributor": d, "start": s.get("start")}
        if s["kind"] in ("distributor_alias", "distributor_merge"):
            key["value"] = s["value"]
        if ManualMapping.objects.filter(**key).exists():
            continue
        value = s.get("value") or ({"previous_asm_id": None} if s["kind"] == "distributor_asm" else {})
        ManualMapping.objects.create(**{**key, "value": value}, asm=a, end=s.get("end"), given_on=s["given_on"],
                                     said=s["said"])
        made += 1
    return {"created": made, "missing": missing}


def _covering(distributor_id, month):
    """Active ASM entries of a distributor that apply in `month` (first day)."""
    from .models import ManualMapping

    out = []
    for e in ManualMapping.objects.filter(status="active", distributor_id=distributor_id,
                                          kind__in=("distributor_asm", "asm_handover")):
        if e.kind == "distributor_asm":
            out.append(e)
        elif _month(e.start) <= month and (e.end is None or e.end >= month):
            out.append(e)
    return out


def superseded(distributor, month, asm, source):
    """Proper data set `asm` (None = vacant) for `distributor` in `month`: close the manual entries it covers."""
    n = 0
    for e in _covering(distributor.id, _month(month)):
        same = (e.asm_id or None) == (asm.id if asm else None)
        e.status = "confirmed" if same else "replaced"
        e.closed_on = localdate()
        e.closed_reason = f"{source}: {asm.name if asm else 'vacant'} for {month:%b %Y}"[:255]
        e.conflict = ""
        e.save(update_fields=["status", "closed_on", "closed_reason", "conflict", "updated_at"])
        n += 1
    return n


def check():
    """Compare active ASM entries with the live incentive sheet's ASM lines (TargetSplit). Returns a summary."""
    from collections import defaultdict

    from warehouse.models import TargetSplit

    from .models import ManualMapping

    sheet = defaultdict(set)  # (distributor_id, month) -> {asm_id}
    for did, m, aid in TargetSplit.objects.filter(role="asm", asm__isnull=False).values_list(
            "distributor_id", "month", "asm_id"):
        sheet[(did, m)].add(aid)
    confirmed = conflicts = 0
    for e in ManualMapping.objects.filter(status="active", kind__in=("distributor_asm", "asm_handover")):
        months = sorted(m for (did, m) in sheet if did == e.distributor_id
                        and (e.kind == "distributor_asm" or (_month(e.start) <= m and (e.end is None or e.end >= m))))
        if not months:
            if e.conflict:
                e.conflict = ""
                e.save(update_fields=["conflict", "updated_at"])
            continue
        m = months[-1]
        ids = sheet[(e.distributor_id, m)]
        if e.asm_id in ids:
            e.status, e.closed_on, e.conflict = "confirmed", localdate(), ""
            e.closed_reason = f"Incentive sheet lists {e.asm.name} for {m:%b %Y}"
            e.save(update_fields=["status", "closed_on", "closed_reason", "conflict", "updated_at"])
            confirmed += 1
        else:
            from warehouse.models import Asm

            names = ", ".join(Asm.objects.filter(id__in=ids).values_list("name", flat=True))
            text = f"Incentive sheet says {names} for {m:%b %Y} (dashboard keeps {e.asm or 'vacant'} until you decide)"
            if e.conflict != text:
                e.conflict = text[:255]
                e.save(update_fields=["conflict", "updated_at"])
            conflicts += 1
    return {"active": ManualMapping.objects.filter(status="active").count(), "confirmed": confirmed,
            "conflicts": conflicts}


@transaction.atomic
def remove(entry, undo=True, reason="removed by hand"):
    """Take an entry out. undo=True reverses its effect on the dashboard (a merge cannot be split back)."""
    from analytics.cache import bump_cache_version
    from analytics.derivations import attribute_orders_to_distributor_asm
    from warehouse.models import AsmAssignment, Retailer

    from .services import current_asm_id

    d = entry.distributor
    note = reason
    if undo and d is not None:
        if entry.kind == "distributor_asm" and d.asm_id == entry.asm_id:
            prev = (entry.value or {}).get("previous_asm_id")
            d.asm_id = prev
            d.save(update_fields=["asm", "updated_at"])
            Retailer.objects.filter(distributor=d).update(asm_id=prev)
        elif entry.kind == "asm_handover":
            AsmAssignment.objects.filter(distributor=d, start=entry.start, asm_id=entry.asm_id).delete()
            current_asm_id(d, save=True)
        elif entry.kind == "distributor_alias":
            alias = (entry.value or {}).get("alias", "")
            d.aliases = [a for a in (d.aliases or []) if a.strip().lower() != alias.strip().lower()]
            d.save(update_fields=["aliases", "updated_at"])
        elif entry.kind == "distributor_merge":
            note = f"{reason} (the merge itself stays: split the distributors by hand if needed)"
        if entry.kind in ("distributor_asm", "asm_handover"):
            attribute_orders_to_distributor_asm()
        bump_cache_version()
    entry.status, entry.closed_on, entry.closed_reason = "removed", localdate(), note[:255]
    entry.save(update_fields=["status", "closed_on", "closed_reason", "updated_at"])
    return entry


def as_dict(e):
    return {"id": e.id, "kind": e.kind, "kind_label": e.get_kind_display(),
            "distributor": e.distributor.name if e.distributor_id else None,
            "asm": e.asm.name if e.asm_id else None,
            "start": e.start.isoformat() if e.start else None, "end": e.end.isoformat() if e.end else None,
            "value": e.value, "given_on": e.given_on.isoformat(), "said": e.said, "status": e.status,
            "status_label": e.get_status_display(), "closed_on": e.closed_on.isoformat() if e.closed_on else None,
            "closed_reason": e.closed_reason, "conflict": e.conflict}
