"""Live TD data: pull from Supabase when it has new data (run every 30 minutes by Task Scheduler).

    python manage.py supabase_live            import only if Supabase refreshed since the last import
    python manage.py supabase_live --force    import regardless

When nothing changed it exits in a second without touching the dashboard (no recompute, caches kept). After an
import it rebuilds the derived tables and clears the caches, like the 10:00 / 18:00 refresh.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from ingestion.connectors.supabase import ETL_KEY, SupabaseConnector
from ingestion.models import SyncRun, SyncWatermark
from ingestion.schedule import REFRESH_SOURCE


class Command(BaseCommand):
    help = "Import live TD data from Supabase if it changed (for the 30-minute scheduled task)"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Import even if Supabase reports no new data")

    def handle(self, *args, **opts):
        from ingestion.locks import import_lock

        with import_lock() as got:
            if not got:
                self.stdout.write("Another data import is running (refresh or live sync) - skipped.")
                return
            self.sync(opts["force"])

    def sync(self, force):
        from analytics.cache import bump_cache_version
        from analytics.derivations import run_all_derivations

        if force:
            SyncWatermark.objects.filter(key=ETL_KEY).delete()
        started = timezone.now()
        run = SupabaseConnector().run(triggered_by="live")
        if run.status != "success":
            self.stdout.write(f"Supabase sync {run.status}: {(run.error or run.details.get('message', ''))[:300]}")
            return
        if run.details.get("unchanged"):
            self.stdout.write(f"No new data in Supabase (last refreshed {run.details.get('supabase_refreshed_at')}).")
            return
        run_all_derivations()
        bump_cache_version()
        SyncRun.objects.create(source=REFRESH_SOURCE, status="success", started_at=started, finished_at=timezone.now(),
                               details={"via": "supabase_live"}, triggered_by="live")
        rows = run.details.get("rows", {})
        self.stdout.write(self.style.SUCCESS(
            f"Imported from Supabase: {rows.get('orders', 0):,} orders, {rows.get('retailers', 0):,} retailers "
            f"(Supabase refreshed {run.details.get('supabase_refreshed_at')})."))
