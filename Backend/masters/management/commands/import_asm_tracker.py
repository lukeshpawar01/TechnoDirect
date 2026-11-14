"""Load a monthly ASM performance tracker (CSV) into the dashboard masters.

    python manage.py import_asm_tracker "data/import/asm_tracker/Technodirect Order Tracking - Nov 26.csv" --month 2026-11

Tracker columns: Distributor, Region, Order Value, No of Orders, Share %, ASM, Total Target, Target Remained,
Acheived %, Total Target Acheived (last row "Total").

What it writes (re-runnable; a changed value becomes a new target version):
  * Region of each distributor (South / East / West / North) and, from the distributors based there,
    the region of each state, so territory views use the tracker's four zones.
  * ASMs (created by name) and each distributor's ASM. "Vacant" or blank = no ASM.
  * Pincode ASM = ASM of the pincode's P1 distributor (only where no other ASM was set), then retailers and
    retailer-months are re-derived. Orders count for the ASM of the distributor that fulfilled them.
  * Monthly SALES targets: per distributor (the row's Total Target), per ASM and per region (sums) and
    overall (the Total row). A blank target means the distributor is covered by its ASM's target.

Order Value / No of Orders / Achieved are NOT imported: the dashboard computes actuals from the orders.
"""
import csv
import datetime as dt
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from analytics.cache import bump_cache_version
from analytics.derivations import attribute_orders_to_distributor_asm, run_all_derivations
from ingestion.csv_import import nice_name, norm
from masters.services import remap_retailers_for_pincodes
from warehouse.models import Asm, Distributor, Order, Pincode, Region, State, Target

NO_ASM = {"", "vacant", "na", "n/a", "-", "none"}


def money(v):
    v = re.sub(r"[^0-9.\-]", "", v or "")
    if not v:
        return None
    try:
        return Decimal(v)
    except InvalidOperation:
        return None


class Command(BaseCommand):
    help = "Import a monthly ASM performance tracker: ASMs, distributor ASM / region, monthly sales targets."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--month", required=True, help="Target month, YYYY-MM (e.g. 2026-11)")
        parser.add_argument("--dry-run", action="store_true", help="Show the matching without saving")

    def handle(self, *args, **o):
        path = Path(o["file"])
        if not path.is_file():
            raise CommandError(f"File not found: {path}")
        try:
            month = dt.date.fromisoformat(o["month"] + "-01")
        except ValueError as e:
            raise CommandError("--month must be YYYY-MM") from e

        with open(path, encoding="utf-8-sig", newline="") as fh:
            rows = [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(fh)]
        total_row = next((r for r in rows if r.get("Distributor", "").lower() == "total"), None)
        rows = [r for r in rows if r.get("Distributor") and r["Distributor"].lower() != "total"]

        matched = self.match_distributors([r["Distributor"] for r in rows], create=not o["dry_run"])
        for r in rows:
            d, how = matched[r["Distributor"]]
            self.stdout.write(f"  {r['Distributor']:<28} -> {d.name if d else '(new) ' + nice_name(r['Distributor']):<34}"
                              f" [{how}]  {r.get('Region', ''):<6} ASM={r.get('ASM') or '-'}")
        if o["dry_run"]:
            self.stdout.write("dry run: nothing saved")
            return

        with transaction.atomic():
            result = self.apply(rows, matched, month, total_row, path.name)
            from masters.asm_tracker import sync_state_targets

            result["state_targets"] = sync_state_targets(month)
        self.stdout.write("[tracker] re-deriving retailer months and data-quality checks...")
        run_all_derivations()
        bump_cache_version()
        for k, v in result.items():
            self.stdout.write(f"  {k:<28} {v}")
        self.stdout.write(self.style.SUCCESS("[tracker] done."))

    # ------------------------------------------------------------------ distributor matching
    def match_distributors(self, names, create):
        index = {}
        for d in Distributor.objects.all():
            for alias in [d.name, d.code, *(d.aliases or [])]:
                index.setdefault(norm(alias), d)
        out, taken = {}, set()
        # pass 1: exact name / alias, then unique prefix
        for name in names:
            n = norm(name)
            d, how = index.get(n), "exact"
            if d is None:
                pref = {x.id: x for k, x in index.items() if k.startswith(n)}
                if len(pref) == 1:
                    d, how = next(iter(pref.values())), "prefix"
            if d is not None:
                taken.add(d.id)
            out[name] = (d, how)
        # pass 2: unique first word, but never onto a distributor another row already matched
        # (e.g. "HEERA MAIN" must not merge into "HEERA")
        for name, (d, _) in list(out.items()):
            if d is not None:
                continue
            first = norm(name.split()[0])
            cands = {x.id: x for k, x in index.items() if k.startswith(first)}
            if len(cands) == 1 and next(iter(cands)) not in taken:
                d = next(iter(cands.values()))
                taken.add(d.id)
                out[name] = (d, "first word")
            else:
                out[name] = (None, "new")
        if create:
            used = set(Distributor.objects.values_list("code", flat=True))
            for name, (d, how) in out.items():
                if d is None:
                    base = re.sub(r"[^A-Z0-9]", "", name.upper())[:10] or "DIST"
                    code, i = base, 1
                    while code in used:
                        i += 1
                        code = f"{base[:8]}{i:02d}"
                    used.add(code)
                    d = Distributor.objects.create(code=code, name=nice_name(name)[:200],
                                                   source_id=f"name:{norm(name)}"[:64])
                    out[name] = (d, "new")
                if name != d.name and name not in (d.aliases or []):
                    d.aliases = sorted(set(d.aliases or []) | {name})
                    d.save(update_fields=["aliases", "updated_at"])
        return out

    # ------------------------------------------------------------------ apply
    def apply(self, rows, matched, month, total_row, filename):
        regions = {}
        for name in sorted({r.get("Region", "") for r in rows if r.get("Region")}):
            code = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")[:32]
            reg = Region.objects.filter(code=code).first() or Region.objects.filter(name__iexact=name).first()
            regions[name] = reg or Region.objects.create(code=code, name=name.title())

        # ASMs
        asms, asm_regions = {}, defaultdict(Counter)
        for r in rows:
            a = r.get("ASM", "")
            if a.lower() in NO_ASM:
                continue
            if r.get("Region"):
                asm_regions[a.lower()][r["Region"]] += 1
            if a.lower() not in asms:
                obj = Asm.objects.filter(name__iexact=a).first()
                if obj is None:
                    base = "ASM-" + re.sub(r"[^A-Z0-9]+", "", a.upper())[:20]
                    code, i = base, 1
                    while Asm.objects.filter(code=code).exists():
                        i += 1
                        code = f"{base}{i}"
                    obj = Asm.objects.create(code=code, name=nice_name(a) if a.islower() else a)
                asms[a.lower()] = obj
        for key, obj in asms.items():
            obj.region = regions[asm_regions[key].most_common(1)[0][0]] if asm_regions[key] else obj.region
            obj.is_active = True
            obj.save(update_fields=["region", "is_active", "updated_at"])

        # distributor ASM + region; pincodes follow the distributor's ASM
        changed_pins = set()
        for r in rows:
            d = matched[r["Distributor"]][0]
            new_asm = asms.get(r.get("ASM", "").lower())
            old_asm_id = d.asm_id
            d.asm = new_asm
            if r.get("Region"):
                d.region = regions[r["Region"]]
            d.save(update_fields=["asm", "region", "updated_at"])
            pins = Pincode.objects.filter(distributor_p1=d)
            fill = pins.filter(asm__isnull=True) if old_asm_id is None else pins.filter(asm_id__in=[old_asm_id, None])
            new_id = new_asm.id if new_asm else None
            touched = list(fill.exclude(asm_id=new_id).values_list("pincode", flat=True)) if new_id else \
                list(fill.exclude(asm__isnull=True).values_list("pincode", flat=True))
            fill.update(asm_id=new_id)
            changed_pins.update(touched)

        # state region = the tracker region of the distributors based in that state
        votes = defaultdict(Counter)
        for r in rows:
            d = matched[r["Distributor"]][0]
            if d.state_id and r.get("Region"):
                votes[d.state_id][r["Region"]] += 1
        state_changes = []
        for st in State.objects.filter(id__in=votes):
            reg = regions[votes[st.id].most_common(1)[0][0]]
            if st.region_id != reg.id:
                state_changes.append(f"{st.name}: {st.region.name if st.region else '-'} -> {reg.name}")
                st.region = reg
                st.save(update_fields=["region", "updated_at"])
        # states still in a region the tracker doesn't use (old South 1/2/3 defaults) move to its namesake
        for st in State.objects.exclude(region__in=regions.values()).exclude(region__isnull=True):
            target = next((reg for nm, reg in regions.items() if st.region.name.lower().startswith(nm.lower())), None)
            if target:
                state_changes.append(f"{st.name}: {st.region.name} -> {target.name}")
                st.region = target
                st.save(update_fields=["region", "updated_at"])

        # re-derive retailer / order territory (state region, pincode ASM)
        all_pins = set(Pincode.objects.filter(state__isnull=False).values_list("pincode", flat=True)) \
            if state_changes else changed_pins
        remapped = remap_retailers_for_pincodes(all_pins)
        fallback = attribute_orders_to_distributor_asm()

        # retire regions nothing points to any more (old defaults)
        removed = []
        for reg in Region.objects.exclude(id__in=[x.id for x in regions.values()]):
            in_use = (reg.states.exists() or reg.distributors.exists() or reg.asms.exists()
                      or reg.retailers.exists()
                      or User.scope_regions.through.objects.filter(region_id=reg.id).exists()
                      or Target.objects.filter(scope_type="region", scope_id=reg.id).exists())
            if not in_use:
                removed.append(reg.name)
                reg.delete()

        # targets
        notes = f"ASM tracker: {filename}"[:255]
        by_dist, by_asm, by_region = {}, defaultdict(Decimal), defaultdict(Decimal)
        for r in rows:
            v = money(r.get("Total Target"))
            if not v:
                continue
            d = matched[r["Distributor"]][0]
            by_dist[d.id] = by_dist.get(d.id, Decimal(0)) + v
            a = asms.get(r.get("ASM", "").lower())
            if a:
                by_asm[a.id] += v
            if r.get("Region"):
                by_region[regions[r["Region"]].id] += v
        overall = money(total_row.get("Total Target")) if total_row else None
        if overall is None:
            overall = sum(by_dist.values(), Decimal(0))
        written = Counter()
        for scope, values in (("distributor", by_dist), ("asm", by_asm), ("region", by_region),
                              ("overall", {None: overall})):
            for sid, value in values.items():
                written[self.put_target(month, scope, sid, value, notes)] += 1
        diff = overall - sum(by_dist.values(), Decimal(0))

        return {
            "distributors_in_tracker": len(rows),
            "asms": len(asms),
            "regions": ", ".join(sorted(regions)),
            "state_region_changes": "; ".join(state_changes) or "none",
            "regions_removed": ", ".join(removed) or "none",
            "pincodes_with_new_asm": len(changed_pins),
            "retailers_remapped": remapped,
            "orders_moved_to_distributor_asm": fallback,
            "targets": dict(written),
            "overall_target": f"{overall:,.0f}" + (f" (differs from sum of rows by {diff:,.0f})" if diff else ""),
        }

    @staticmethod
    def put_target(month, scope, scope_id, value, notes):
        """New row, or a new version when the value changed (latest version wins)."""
        cur = (Target.objects.filter(month=month, scope_type=scope, scope_id=scope_id, metric="sales")
               .order_by("-effective_from", "-version").first())
        if cur and cur.value == value:
            return "unchanged"
        if cur:
            Target.objects.create(month=month, scope_type=scope, scope_id=scope_id, metric="sales", value=value,
                                  effective_from=max(cur.effective_from, dt.date.today()), version=cur.version + 1,
                                  notes=notes, updated_by="import_asm_tracker")
            return "revised"
        Target.objects.create(month=month, scope_type=scope, scope_id=scope_id, metric="sales", value=value,
                              effective_from=month, notes=notes, updated_by="import_asm_tracker")
        return "created"
