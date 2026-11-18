"""Load the BlueOrigin (offline) quarterly sheets: python manage.py import_blueorigin [--dir FOLDER].

Without --dir: from Dropbox through the API when DROPBOX_* is set (changed files are downloaded first), else from
BLUEORIGIN_DIR.
"""
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from masters.blueorigin import import_folder


class Command(BaseCommand):
    help = "Rebuild BlueOrigin retailers / quarters / months from FY??_qtr?.csv and tag app retailers (tier, warm)."

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=None,
                            help="Folder with FY??_qtr?.csv (default: the Dropbox API if configured, else BLUEORIGIN_DIR)")

    def handle(self, *args, **opts):
        from masters import dropbox_bo

        folder, via = opts["dir"], "folder"
        if not folder and dropbox_bo.configured():
            try:
                m = dropbox_bo.mirror()
            except dropbox_bo.DropboxError as exc:
                raise CommandError(str(exc)) from None
            folder, via = m["folder"], "dropbox"
            self.stdout.write(f"Dropbox {dropbox_bo.remote_folder()}: {m['files']} files, "
                              f"downloaded {len(m['downloaded'])}, removed {len(m['removed'])}")
        folder = folder or settings.BLUEORIGIN_DIR
        if not folder:
            raise CommandError("Set the DROPBOX_* credentials or BLUEORIGIN_DIR in .env, or pass --dir")
        from django.utils import timezone

        from ingestion.models import SyncRun, SyncWatermark
        from masters.blueorigin import files_signature

        run = SyncRun.objects.create(source="blueorigin", status="running", triggered_by="manual")
        try:
            rep = import_folder(folder)
        except Exception as exc:
            run.status, run.error, run.finished_at = "failed", str(exc)[:4000], timezone.now()
            run.save()
            raise CommandError(str(exc)) from exc
        run.status, run.rows, run.finished_at = "success", rep["quarter_rows"], timezone.now()
        run.details = {k: rep[k] for k in ("retailers", "quarter_rows", "month_rows", "distributors_created", "td_match")}
        run.details["via"] = via
        run.save()
        SyncWatermark.put("blueorigin:files", timezone.now(), cursor=files_signature(folder))
        rep["month_totals"] = {k: round(v) for k, v in sorted(rep["month_totals"].items())}
        self.stdout.write(json.dumps(rep, indent=1, default=str))
