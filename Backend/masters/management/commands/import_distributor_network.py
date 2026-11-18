"""Load the sales team's distributor list (name + state): the state reference for each distributor.

    python manage.py import_distributor_network data/import/distributor_network.csv [--dry-run]

Columns: Links (tracker name, e.g. "Heera Export Tracker"), State (free text: "UP", "Bihar(Patna)", "Delhi NCR").
  * Each name is matched to the distributor with the same / near-same name; the list's name is added to its
    aliases so future sheets match, and the list's state becomes the distributor's state (region follows the
    state). A state written as two states ("Tripura/Mizoram") is left as it is.
  * Names that match no distributor are only listed in the output; they are not used anywhere.
  * NAME_FIXES corrects a distributor's display name where the list spells it right ("Jodhpur Apparels").
Re-runnable.
"""
import csv
import difflib
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analytics.cache import bump_cache_version
from ingestion.normalize import nice_name, norm
from warehouse import geo
from warehouse.models import Distributor, State, TrackedDistributor

STATE_ALIASES = {"up": "Uttar Pradesh", "mp": "Madhya Pradesh", "andhra": "Andhra Pradesh",
                 "jammu": "Jammu and Kashmir", "delhi ncr": "Delhi", "maharastra": "Maharashtra",
                 "tripura/mizoram": "Tripura"}
NAME_FIXES = {"Jodhpur Appearals": "Jodhpur Apparels"}  # app name -> correct spelling from the team's list
# tracker name -> app distributor, where the team's tracker uses another trading name (confirmed by the user)
LINKS = {"Sri Sai Enterprise": "Virat Sports Wear"}


def clean_name(raw):
    return re.sub(r"\s+tracker$", "", re.sub(r"\s+", " ", raw or "").strip(), flags=re.I)


def state_for(label):
    base = re.sub(r"\s*\(.*\)\s*", "", (label or "").strip()).strip()
    name = STATE_ALIASES.get(base.lower(), base)
    code = geo.state_code_for_name(name)
    return State.objects.filter(code=code).first() if code else State.objects.filter(name__iexact=name).first()


def match(name, index):
    k = norm(name)
    if k in index:
        return index[k]
    pref = {d.id: d for kk, d in index.items() if len(k) >= 5 and (kk.startswith(k) or k.startswith(kk))}
    if len(pref) == 1:
        return next(iter(pref.values()))
    close = difflib.get_close_matches(k, list(index), n=1, cutoff=0.8)
    return index[close[0]] if close else None


class Command(BaseCommand):
    help = "Import the team's distributor network list (name, state); unmatched names are the pipeline."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        try:
            with open(o["file"], encoding="utf-8-sig", newline="") as fh:
                rows = [r for r in csv.DictReader(fh) if (r.get("Links") or "").strip()]
        except FileNotFoundError:
            raise CommandError(f"File not found: {o['file']}") from None
        with transaction.atomic():
            for old, new in NAME_FIXES.items():
                d = Distributor.objects.filter(name=old).first()
                if d:
                    d.aliases = sorted(set(d.aliases or []) | {old})
                    d.name = new
                    d.save(update_fields=["name", "aliases", "updated_at"])
            index = {}
            for d in Distributor.objects.all():
                for a in [d.name, d.code, *(d.aliases or [])]:
                    index.setdefault(norm(a), d)
            linked, pipeline, state_diff = [], [], []
            seen = set()
            for r in rows:
                name = clean_name(r["Links"])
                st = state_for(r.get("State"))
                d = Distributor.objects.filter(name=LINKS[name]).first() if name in LINKS else match(name, index)
                if d:
                    linked.append(f"{name} -> {d.name}")
                    if name != d.name and name not in (d.aliases or []):
                        d.aliases = sorted(set(d.aliases or []) | {name})
                        d.save(update_fields=["aliases", "updated_at"])
                    if st and st.id != d.state_id and "/" not in (r.get("State") or ""):
                        state_diff.append(f"{d.name}: {d.state.name if d.state_id else '-'} -> {st.name}")
                        d.state, d.region_id = st, st.region_id or d.region_id
                        d.save(update_fields=["state", "region", "updated_at"])
                else:
                    pipeline.append(f"{name} ({st.name if st else r.get('State')})")
                TrackedDistributor.objects.update_or_create(name=nice_name(name)[:200], defaults={
                    "state": st, "state_label": (r.get("State") or "").strip()[:100], "distributor": d})
                seen.add(nice_name(name)[:200])
            removed = TrackedDistributor.objects.exclude(name__in=seen).delete()[0]
            no_tracker = list(Distributor.objects.filter(trackers__isnull=True, is_active=True)
                              .order_by("name").values_list("name", flat=True))
            if o["dry_run"]:
                transaction.set_rollback(True)
        self.stdout.write(f"  matched to distributors: {len(linked)}")
        self.stdout.write(f"  state set from the list: {'; '.join(state_diff) or 'none (all already match)'}")
        self.stdout.write(f"  names with no distributor (ignored): {', '.join(pipeline) or 'none'}")
        self.stdout.write(f"  distributors not on the list: {', '.join(no_tracker) or 'none'}")
        self.stdout.write(f"  removed from the list: {removed}")
        if not o["dry_run"]:
            bump_cache_version()
        self.stdout.write(self.style.SUCCESS("[network] dry run" if o["dry_run"] else "[network] done."))
