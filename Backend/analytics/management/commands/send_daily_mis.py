"""Daily MIS email (analytics/daily_mis.py).

    manage.py send_daily_mis --preview mis.html        # write it to a file, send nothing
    manage.py send_daily_mis --to someone@technosport.in
    manage.py send_daily_mis                           # to MIS_RECIPIENTS (.env)
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from analytics import daily_mis


class Command(BaseCommand):
    help = "Send (or preview) the daily MIS email"

    def add_arguments(self, parser):
        parser.add_argument("--to", default="", help="comma-separated addresses (default: MIS_RECIPIENTS)")
        parser.add_argument("--preview", default="", help="write the HTML to this file instead of sending")

    def handle(self, *a, **o):
        if o["preview"]:
            subject, html = daily_mis.render(daily_mis.build())
            Path(o["preview"]).write_text(html, encoding="utf-8")
            self.stdout.write(f"Subject: {subject}\nWritten to {o['preview']} (nothing sent)")
            return
        to = [x.strip() for x in o["to"].split(",") if "@" in x] or None
        if not to and not daily_mis.recipients():
            raise CommandError("No recipients: set MIS_RECIPIENTS in .env or pass --to")
        sent = daily_mis.send(to)
        self.stdout.write(f"Sent to {', '.join(sent)}")
