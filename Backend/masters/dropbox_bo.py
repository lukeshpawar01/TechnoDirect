"""BlueOrigin sheets straight from Dropbox through the Dropbox API (no Dropbox desktop app needed).

Each refresh lists the Dropbox folder (DROPBOX_BO_PATH, e.g. "/Power BI") and downloads only the BlueOrigin files
(FY??_qtr?.csv, Dist-state.xlsx) whose Dropbox content_hash changed into a local mirror (Backend/data/
blueorigin_dropbox, git-ignored). The normal import then reads the mirror, so an unchanged Dropbox means an unchanged
signature and the import is skipped as before.

Auth: a Dropbox app (Scoped access, read-only scopes files.metadata.read + files.content.read) and a long-lived
refresh token; a short-lived access token is fetched from it on every run. `manage.py dropbox_auth` gets the token.
Secrets are never logged or put in error messages.
"""
import fnmatch
import json
import logging
import os
import tempfile
from pathlib import Path

import requests
from django.conf import settings

log = logging.getLogger(__name__)

TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
API = "https://api.dropboxapi.com/2"
CONTENT = "https://content.dropboxapi.com/2"
WANTED = ("FY??_qtr?.csv", "Dist-state.xlsx")  # only what the BlueOrigin import reads
COMPACT = "TD_BO_dashboard.csv.gz"  # the BO_data notebook's dashboard file: when present, only it (+ Dist-state) is kept
MANIFEST = ".dropbox_manifest.json"
TIMEOUT = 60
SCOPES = ("files.metadata.read", "files.content.read")  # read-only: list the folder, download the sheets


class DropboxError(RuntimeError):
    pass


def scope_fix(missing):
    return (f"The Dropbox token is missing the permission {', '.join(missing)}. Fix: Dropbox App Console "
            "(https://www.dropbox.com/developers/apps) > your app > Permissions > tick files.metadata.read and "
            "files.content.read > Submit; then run manage.py dropbox_auth again and click Allow on the NEW link "
            "(a token keeps the permissions it was created with).")


def missing_scopes(granted):
    """Needed scopes absent from Dropbox's space-separated `scope` (empty when Dropbox did not say)."""
    if not granted:
        return []
    have = set(str(granted).split())
    return [s for s in SCOPES if s not in have]


def configured():
    return bool(settings.DROPBOX_APP_KEY and settings.DROPBOX_APP_SECRET and settings.DROPBOX_REFRESH_TOKEN)


def mirror_dir():
    return settings.DROPBOX_BO_MIRROR or str(Path(settings.BASE_DIR) / "data" / "blueorigin_dropbox")


def remote_folder():
    p = (settings.DROPBOX_BO_PATH or "/Power BI").replace("\\", "/").rstrip("/")
    return p if p.startswith("/") else "/" + p


def _fail(what, resp):
    """Dropbox's error summary (never the request, which carries the token)."""
    try:
        body = resp.json()
        detail = body.get("error_summary") or body.get("error_description") or body.get("error") or ""
    except ValueError:
        detail = (resp.text or "")[:200]
    hint = ""
    if resp.status_code in (400, 401) and what == "sign-in":
        hint = " - check DROPBOX_APP_KEY / DROPBOX_APP_SECRET / DROPBOX_REFRESH_TOKEN (run manage.py dropbox_auth)"
    elif "scope" in str(detail).lower():
        raise DropboxError(scope_fix([s for s in SCOPES if s in str(detail)] or list(SCOPES)))
    elif "not_found" in str(detail):
        hint = f" - no folder {remote_folder()} in this Dropbox (check DROPBOX_BO_PATH)"
    raise DropboxError(f"Dropbox {what} failed ({resp.status_code}): {detail}{hint}")


def access_token(session=requests):
    try:
        r = session.post(TOKEN_URL, timeout=TIMEOUT, data={
            "grant_type": "refresh_token", "refresh_token": settings.DROPBOX_REFRESH_TOKEN,
            "client_id": settings.DROPBOX_APP_KEY, "client_secret": settings.DROPBOX_APP_SECRET})
    except requests.RequestException as exc:
        raise DropboxError(f"Dropbox sign-in failed: cannot reach Dropbox ({type(exc).__name__})") from None
    if r.status_code != 200:
        _fail("sign-in", r)
    body = r.json()
    missing = missing_scopes(body.get("scope"))
    if missing:
        raise DropboxError(scope_fix(missing))
    return body["access_token"]


def list_files(token, session=requests):
    """{name: metadata} of the BlueOrigin files in the Dropbox folder."""
    headers = {"Authorization": f"Bearer {token}"}
    url, body, out = f"{API}/files/list_folder", {"path": remote_folder(), "recursive": False, "limit": 2000}, {}
    while True:
        try:
            r = session.post(url, json=body, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise DropboxError(f"Dropbox folder listing failed: {type(exc).__name__}") from None
        if r.status_code != 200:
            _fail("folder listing", r)
        page = r.json()
        for e in page.get("entries", []):
            if e.get(".tag") == "file" and any(fnmatch.fnmatch(e["name"].lower(), w.lower()) for w in WANTED + (COMPACT,)):
                out[e["name"]] = e
        if not page.get("has_more"):
            return out
        url, body = f"{API}/files/list_folder/continue", {"cursor": page["cursor"]}


def _download(token, entry, dest, session=requests):
    headers = {"Authorization": f"Bearer {token}", "Dropbox-API-Arg": json.dumps({"path": entry["id"]})}
    try:
        r = session.post(f"{CONTENT}/files/download", headers=headers, timeout=300, stream=True)
    except requests.RequestException as exc:
        raise DropboxError(f"Dropbox download of {entry['name']} failed: {type(exc).__name__}") from None
    if r.status_code != 200:
        _fail(f"download of {entry['name']}", r)
    fd, tmp = tempfile.mkstemp(dir=dest, prefix=".part-")
    try:
        with os.fdopen(fd, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)
        os.replace(tmp, os.path.join(dest, entry["name"]))  # all-or-nothing: the import never sees half a file
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def mirror(dest=None, session=requests):
    """Bring the local mirror in line with Dropbox. Returns {"folder", "files", "downloaded", "removed"}."""
    if not configured():
        raise DropboxError("Dropbox API is not configured (DROPBOX_APP_KEY / DROPBOX_APP_SECRET / DROPBOX_REFRESH_TOKEN)")
    dest = dest or mirror_dir()
    os.makedirs(dest, exist_ok=True)
    token = access_token(session)
    remote = list_files(token, session)
    compact = next((n for n in remote if n.lower() == COMPACT.lower()), None)
    if compact:  # one small file instead of every quarter sheet; local copies of the quarter files are removed below
        remote = {n: e for n, e in remote.items() if n == compact or not fnmatch.fnmatch(n.lower(), WANTED[0].lower())}
    elif not any(fnmatch.fnmatch(n.lower(), WANTED[0].lower()) for n in remote):
        raise DropboxError(f"No {WANTED[0]} files in Dropbox folder {remote_folder()} (check DROPBOX_BO_PATH)")
    man_path = os.path.join(dest, MANIFEST)
    try:
        with open(man_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        manifest = {}
    downloaded = []
    for name, e in sorted(remote.items()):
        if manifest.get(name) == e.get("content_hash") and os.path.exists(os.path.join(dest, name)):
            continue
        _download(token, e, dest, session)
        manifest[name] = e.get("content_hash")
        downloaded.append(name)
        with open(man_path, "w", encoding="utf-8") as fh:  # saved per file: a failed run resumes where it stopped
            json.dump(manifest, fh, indent=1)
    removed = []
    for name in list(manifest):  # a sheet deleted in Dropbox leaves the import too
        if name not in remote:
            p = os.path.join(dest, name)
            if os.path.exists(p):
                os.remove(p)
            manifest.pop(name)
            removed.append(name)
    with open(man_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    if downloaded or removed:
        log.info("Dropbox BlueOrigin mirror: downloaded %s, removed %s", downloaded, removed)
    return {"folder": dest, "files": len(remote), "downloaded": downloaded, "removed": removed}
