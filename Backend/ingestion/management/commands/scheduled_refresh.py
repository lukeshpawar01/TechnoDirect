"""The 10:00 / 18:00 data refresh: the full chain (ingestion/tasks.py refresh_all_inline).

Supabase (TD data) -> PayU -> CRM sheet -> Channel Konnect -> BlueOrigin / settlement / distributor stock sheet
-> derived tables -> cache invalidation.

Run by the web server itself at SYNC_TIMES (ingestion/scheduler.py), or by hand. ingestion/locks.py stops two imports
overlapping (this refresh, a manual Supabase import, ...).
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Data refresh: Supabase TD data and the other sources, then the derived tables"

    def handle(self, *args, **opts):
        from ingestion.locks import import_lock
        from ingestion.tasks import refresh_all_inline

        with import_lock() as got:
            if not got:
                self.stdout.write("Another refresh / import is running - skipped.")
                return
            self.stdout.write(str(refresh_all_inline(triggered_by="schedule")))
