from django.core.management.base import BaseCommand

from ingestion.connectors import CONNECTORS
from ingestion.tasks import refresh_all_inline, run_single_inline


class Command(BaseCommand):
    help = "Run a sync inline: medusa | payu | google_sheets | channel_konnect | all (= refresh_all chain)"

    def add_arguments(self, parser):
        parser.add_argument("source", choices=sorted(CONNECTORS) + ["all"])

    def handle(self, *args, source, **opts):
        if source == "all":
            self.stdout.write(str(refresh_all_inline(triggered_by="cli")))
        else:
            self.stdout.write(str(run_single_inline(source, triggered_by="cli")))
