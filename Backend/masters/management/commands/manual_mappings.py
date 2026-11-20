"""Mappings given by hand (in chat), kept apart until proper data replaces them - see masters/manual_mappings.py.

    manage.py manual_mappings list [--all]
    manage.py manual_mappings seed            # register the mappings given in chat (idempotent)
    manage.py manual_mappings check           # compare with the live incentive sheet
    manage.py manual_mappings remove <id> [--keep]   # take one out; --keep leaves the dashboard as it is
"""
from django.core.management.base import BaseCommand, CommandError

from masters import manual_mappings as mm
from masters.models import ManualMapping


class Command(BaseCommand):
    help = "List, check or remove mappings given by hand"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["list", "seed", "check", "remove"])
        parser.add_argument("id", nargs="?", type=int)
        parser.add_argument("--all", action="store_true", help="list closed entries too")
        parser.add_argument("--keep", action="store_true", help="remove: do not undo the effect")
        parser.add_argument("--reason", default="removed by hand")

    def handle(self, *a, **o):
        act = o["action"]
        if act == "seed":
            self.stdout.write(str(mm.seed()))
        elif act == "check":
            self.stdout.write(str(mm.check()))
        elif act == "remove":
            e = ManualMapping.objects.filter(id=o["id"]).first()
            if e is None:
                raise CommandError(f"no manual mapping {o['id']}")
            mm.remove(e, undo=not o["keep"], reason=o["reason"])
            self.stdout.write(f"removed #{e.id}: {e}")
        qs = ManualMapping.objects.select_related("distributor", "asm")
        if not o["all"]:
            qs = qs.filter(status="active")
        for e in qs:
            d = mm.as_dict(e)
            when = f" {d['start']}..{d['end'] or ''}" if d["start"] else ""
            what = d["asm"] or d["value"].get("alias") or d["value"].get("merged") or ""
            self.stdout.write(f"#{d['id']:<3} {d['status']:<9} {d['kind_label']:<22} {d['distributor']} -> {what}{when}"
                              f"  (given {d['given_on']}){'  ! ' + d['conflict'] if d['conflict'] else ''}"
                              f"{'  [' + d['closed_reason'] + ']' if d['closed_reason'] else ''}")
