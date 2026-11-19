"""Read a live Google Sheet tab through the service account (GOOGLE_SERVICE_ACCOUNT_JSON), as rows of text - the same
values a "File > Download > CSV" export gives, so the importers parse them exactly as they parsed the CSV files.

A sheet is configured by its normal browser link, e.g.
    https://docs.google.com/spreadsheets/d/<spreadsheet id>/edit#gid=<tab id>
(the #gid part picks the tab; without it the first tab is read). The sheet must be shared (Viewer) with the service
account's email. Read-only: the dashboard never writes to a Google Sheet.
"""
import hashlib
import json
import os
import re

from django.conf import settings

_ID = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]{20,})")
_GID = re.compile(r"[#?&]gid=(\d+)")


class SheetError(RuntimeError):
    pass


def configured():
    path = getattr(settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "")
    return bool(path) and os.path.isfile(path)


def parse_link(link):
    """(spreadsheet id, tab gid or None) from a browser link - or a bare spreadsheet id."""
    link = (link or "").strip()
    m = _ID.search(link)
    sid = m.group(1) if m else (link if re.fullmatch(r"[a-zA-Z0-9_-]{20,}", link) else None)
    if not sid:
        raise SheetError("Not a Google Sheets link (expected https://docs.google.com/spreadsheets/d/...)")
    g = _GID.search(link)
    return sid, (int(g.group(1)) if g else None)


def service_account_email():
    """The email to share the sheets with (read from the key file; nothing else is printed or logged)."""
    if not configured():
        return None
    with open(settings.GOOGLE_SERVICE_ACCOUNT_JSON, encoding="utf-8") as fh:
        return json.load(fh).get("client_email")


def _worksheet(link):
    import gspread

    if not configured():
        raise SheetError("GOOGLE_SERVICE_ACCOUNT_JSON is not set (or the key file is missing)")
    sid, gid = parse_link(link)
    try:
        sh = gspread.service_account(filename=settings.GOOGLE_SERVICE_ACCOUNT_JSON).open_by_key(sid)
        return sh.get_worksheet_by_id(gid) if gid is not None else sh.sheet1
    except gspread.exceptions.APIError as exc:
        code = getattr(getattr(exc, "response", None), "status_code", "")
        hint = (f" - share the sheet with {service_account_email()} (Viewer)" if code in (403, 404) else "")
        raise SheetError(f"Google Sheets error {code}: {str(exc)[:200]}{hint}") from None
    except gspread.exceptions.WorksheetNotFound:
        raise SheetError(f"No tab with gid={gid} in that sheet - copy the link while the right tab is open") from None


def read_values(link):
    """All cells of the tab as displayed text (list of rows)."""
    return _worksheet(link).get_all_values()


def read_table(link):
    """Rows as {header: value} dicts, first row = headers, fully empty rows skipped (like csv.DictReader)."""
    values = read_values(link)
    if not values:
        return []
    head = values[0]
    out = []
    for row in values[1:]:
        if not any((c or "").strip() for c in row):
            continue
        row = list(row) + [""] * (len(head) - len(row))
        out.append({h: row[i] for i, h in enumerate(head)})
    return out


def signature(rows):
    """Content hash: an unchanged sheet is not re-imported."""
    return hashlib.sha1(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
