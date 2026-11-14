"""Load the distributor name-formatting sheet: how each distributor is spelt in every source system.

    python manage.py import_distributor_names "data/import/distributor_names/Distribuot Formatting - Sheet1.csv"
    python manage.py import_distributor_names <file> --dry-run

Each row lists one distributor's name per system (columns such as GSheets, Metabase, Inventory_db). For every row:
  * all spellings are matched (exact, ignoring case / spaces / punctuation) against existing distributor names and
    aliases; if none match exactly, a name that is a unique prefix of a distributor is used ("Kumar" ->
    "Kumar Enterprises");
  * one match -> every spelling in the row is stored as an alias of that distributor;
  * no match  -> the distributor is created (named after the first column) so future files match it;
  * spellings matching two different distributors -> reported, nothing changed (merge them with
    `merge_distributors` if they are the same business).
Display names are not changed.
"""
import csv
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analytics.cache import bump_cache_version
from ingestion.csv_import import nice_name, norm
from warehouse.models import Distributor


class Command(BaseCommand):
    help = "Store each distributor's spelling in every source system as aliases."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        path = Path(o["file"])
        if not path.is_file():
            raise CommandError(f"File not found: {path}")
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader)
            rows = [[c.strip() for c in r] for r in reader if any(c.strip() for c in r)]
        self.stdout.write(f"columns: {', '.join(header)}  rows: {len(rows)}")

        index = {}
        for d in Distributor.objects.all():
            for a in [d.name, d.code, *(d.aliases or [])]:
                index.setdefault(norm(a), set()).add(d.id)
        dists = {d.id: d for d in Distributor.objects.all()}

        plan, conflicts = [], []
        for r in rows:
            names = [n for n in r if n]
            hits = set()
            for n in names:
                hits |= index.get(norm(n), set())
            how = "exact"
            if not hits:
                for n in names:
                    pref = {i for k, ids in index.items() if k.startswith(norm(n)) for i in ids}
                    if len(pref) == 1:
                        hits, how = pref, f"prefix '{n}'"
                        break
            if len(hits) > 1:
                conflicts.append((names, [dists[i].name for i in hits]))
                continue
            plan.append((names, dists[next(iter(hits))] if hits else None, how if hits else "new"))

        for names, d, how in plan:
            self.stdout.write(f"  {' | '.join(names):<62} -> {d.name if d else '(create) ' + nice_name(names[0])}"
                              f"  [{how}]")
        for names, found in conflicts:
            self.stdout.write(self.style.WARNING(f"  CONFLICT {' | '.join(names)} matches {found}; skipped"))
        if o["dry_run"]:
            self.stdout.write("dry run: nothing saved")
            return

        created = updated = 0
        with transaction.atomic():
            used = set(Distributor.objects.values_list("code", flat=True))
            for names, d, _ in plan:
                if d is None:
                    base = re.sub(r"[^A-Z0-9]", "", names[0].upper())[:10] or "DIST"
                    code, i = base, 1
                    while code in used:
                        i += 1
                        code = f"{base[:8]}{i:02d}"
                    used.add(code)
                    d = Distributor.objects.create(code=code, name=nice_name(names[0])[:200],
                                                   source_id=f"name:{norm(names[0])}"[:64])
                    created += 1
                new = sorted(set(d.aliases or []) | {n for n in names if n != d.name})
                if new != (d.aliases or []):
                    d.aliases = new
                    d.save(update_fields=["aliases", "updated_at"])
                    updated += 1
        bump_cache_version()
        self.stdout.write(self.style.SUCCESS(
            f"done: {updated} distributors got new aliases, {created} created, {len(conflicts)} conflicts"))
