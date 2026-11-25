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

start_auto_refresh()  # the 10:30 / 15:30 data refresh runs inside this server

# Render (and similar hosts) give the port in PORT and put their own HTTPS proxy in front; on this PC the Cloudflare
# Tunnel connects locally to 127.0.0.1:8080
on_host = bool(os.environ.get("PORT"))
host = os.environ.get("SERVE_HOST") or ("0.0.0.0" if on_host else "127.0.0.1")
port = int(os.environ.get("SERVE_PORT") or os.environ.get("PORT") or "8080")
proxy = os.environ.get("SERVE_TRUSTED_PROXY") or ("*" if on_host else "127.0.0.1")
print(f"TechnoDirect dashboard on http://{host}:{port}  (frontend: {settings.FRONTEND_DIST})", flush=True)
serve(
    get_wsgi_application(),
    host=host,
    port=port,
    threads=int(os.environ.get("SERVE_THREADS", "12")),
    # the proxy in front (cloudflared on this machine, or Render's) tells us the visitor used https
    trusted_proxy=proxy,
    trusted_proxy_count=1,
    trusted_proxy_headers="x-forwarded-for x-forwarded-proto",
    channel_timeout=300,  # long exports
    ident="TechnoDirect",
)
