import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "technodirect.settings")
application = get_wsgi_application()

# fresh data at the fixed SYNC_TIMES wherever the server runs (runserver, gunicorn on Render, ...)
from ingestion.scheduler import start as start_auto_refresh  # noqa: E402

start_auto_refresh()
