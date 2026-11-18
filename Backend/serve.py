"""Production server for the single-machine Windows setup (see deploy/windows/HOSTING.md).

Waitress serves the API and, through WhiteNoise, the built dashboard (Frontend/dist) on one port. The Cloudflare
Tunnel connects to it locally, so nothing is opened to the internet directly.

    .venv\\Scripts\\python.exe serve.py          (normally started by the "TechnoDirect Dashboard" scheduled task)
"""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.chdir(BASE)
sys.path.insert(0, str(BASE))
os.environ.setdefault("TD_ENV_FILE", str(BASE / ".env.production"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "technodirect.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.core.wsgi import get_wsgi_application  # noqa: E402
from waitress import serve  # noqa: E402

if settings.DEBUG:
    sys.exit("Refusing to serve with DEBUG=True: check TD_ENV_FILE / .env.production")
if not settings.FRONTEND_DIST:
    sys.exit("FRONTEND_DIST is not set or the folder is missing: run deploy/windows/build_frontend.ps1 first")

call_command("migrate", interactive=False, verbosity=0)
call_command("collectstatic", interactive=False, verbosity=0)

from ingestion.scheduler import start as start_auto_refresh  # noqa: E402

start_auto_refresh()  # the 10:00 / 18:00 data refresh runs inside this server

host = os.environ.get("SERVE_HOST", "127.0.0.1")
port = int(os.environ.get("SERVE_PORT", "8080"))
print(f"TechnoDirect dashboard on http://{host}:{port}  (frontend: {settings.FRONTEND_DIST})", flush=True)
serve(
    get_wsgi_application(),
    host=host,
    port=port,
    threads=int(os.environ.get("SERVE_THREADS", "12")),
    # the Cloudflare Tunnel (cloudflared) runs on this machine and tells us the visitor used https
    trusted_proxy="127.0.0.1",
    trusted_proxy_headers="x-forwarded-for x-forwarded-proto",
    channel_timeout=300,  # long exports
    ident="TechnoDirect",
)
