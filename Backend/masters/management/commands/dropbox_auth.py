"""Connect the BlueOrigin import to Dropbox (one-time), and test the connection.

    python manage.py dropbox_auth                 step 1: prints the Dropbox page to approve the app
    python manage.py dropbox_auth --code CODE     step 2: swaps the code for a refresh token and saves it in .env
    python manage.py dropbox_auth --check         lists the BlueOrigin files the API sees and downloads changed ones

Needs DROPBOX_APP_KEY and DROPBOX_APP_SECRET in .env first. The refresh token is written to .env, never printed.
"""
import re
from pathlib import Path
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

AUTHORIZE = "https://www.dropbox.com/oauth2/authorize"


def save_env(key, value, path=None):
    """Set KEY=value in .env (replacing the line, or appending it)."""
    path = Path(path or Path(settings.BASE_DIR) / ".env")
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    line = f"{key}={value}"
    pat = re.compile(rf"^{re.escape(key)}=.*$", re.M)
    text = pat.sub(lambda _m: line, text, count=1) if pat.search(text) else text.rstrip("\n") + f"\n{line}\n"
    path.write_text(text, encoding="utf-8")
    return path


class Command(BaseCommand):
    help = "Connect the BlueOrigin import to Dropbox (get a refresh token) or test the connection."

    def add_arguments(self, parser):
        parser.add_argument("--code", help="The access code Dropbox shows after you click Allow")
        parser.add_argument("--check", action="store_true", help="Test the connection and list the files found")

    def handle(self, *args, **opts):
        from masters import dropbox_bo

        if opts["check"]:
            try:
                m = dropbox_bo.mirror()
            except dropbox_bo.DropboxError as exc:
                raise CommandError(str(exc)) from None
            self.stdout.write(self.style.SUCCESS(
                f"Connected. {m['files']} BlueOrigin files in Dropbox {dropbox_bo.remote_folder()}; "
                f"downloaded {len(m['downloaded'])} changed, removed {len(m['removed'])}. Local copy: {m['folder']}"))
            for n in m["downloaded"]:
                self.stdout.write(f"  downloaded {n}")
            return

        if not (settings.DROPBOX_APP_KEY and settings.DROPBOX_APP_SECRET):
            raise CommandError("Put DROPBOX_APP_KEY and DROPBOX_APP_SECRET in Backend/.env first "
                               "(Dropbox App Console > your app > Settings).")
        if not opts["code"]:
            # asking for the scopes by name makes Dropbox refuse on the Allow page when the app lacks one, instead
            # of handing out a token that fails later
            url = f"{AUTHORIZE}?{urlencode({'client_id': settings.DROPBOX_APP_KEY, 'response_type': 'code', 'token_access_type': 'offline', 'scope': ' '.join(dropbox_bo.SCOPES)})}"
            self.stdout.write("1. Open this page, sign in to the Dropbox account that has the BlueOrigin folder, click Allow:")
            self.stdout.write(f"   {url}")
            self.stdout.write("2. Copy the code it shows and run:  python manage.py dropbox_auth --code THE_CODE")
            return

        try:
            r = requests.post(dropbox_bo.TOKEN_URL, timeout=60, data={
                "grant_type": "authorization_code", "code": opts["code"].strip(),
                "client_id": settings.DROPBOX_APP_KEY, "client_secret": settings.DROPBOX_APP_SECRET})
        except requests.RequestException as exc:
            raise CommandError(f"Cannot reach Dropbox ({type(exc).__name__})") from None
        if r.status_code != 200:
            try:
                detail = r.json().get("error_description") or r.json().get("error")
            except ValueError:
                detail = r.text[:200]
            raise CommandError(f"Dropbox refused the code ({r.status_code}): {detail}. Codes work once and expire "
                               "in a few minutes - run step 1 again for a new one.")
        body = r.json()
        missing = dropbox_bo.missing_scopes(body.get("scope"))
        if missing:  # not saved: it would only fail at the first refresh
            raise CommandError(dropbox_bo.scope_fix(missing))
        token = body.get("refresh_token")
        if not token:
            raise CommandError("Dropbox sent no refresh token - the page link must include token_access_type=offline.")
        path = save_env("DROPBOX_REFRESH_TOKEN", token)
        self.stdout.write(self.style.SUCCESS(f"Saved DROPBOX_REFRESH_TOKEN in {path}."))
        self.stdout.write("Next: python manage.py dropbox_auth --check   then   python manage.py import_blueorigin")
