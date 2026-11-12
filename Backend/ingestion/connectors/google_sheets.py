"""Google Sheets -> CrmTicket (CRM complaint tracker only).

The sheet is small, so every run reads all rows and upserts them by ticket id;
the watermark records the max "updated/opened" timestamp seen (informational) and
rows older than the watermark whose status is closed are skipped for speed.
"""
import datetime as dt
import os

from django.conf import settings
from django.utils import timezone

from warehouse.models import CrmTicket, Distributor, Order, Retailer

from ..upsert import chunked, upsert
from .base import BaseConnector

# TODO(TD): confirm the header names used in the CRM tracker sheet. Left = our field,
# right = candidate header names (first match wins, case-insensitive).
CRM_COLUMNS = {
    "ticket_id": ["Ticket ID", "Ticket No", "Complaint ID", "ID"],
    "opened_at": ["Date", "Created On", "Opened On", "Complaint Date", "Timestamp"],
    "ticket_type": ["Type", "Complaint Type", "Category", "Issue Type"],
    "status": ["Status"],
    "priority": ["Priority"],
    "retailer_phone": ["Retailer Phone", "Mobile", "Phone", "Contact"],
    "order_id": ["Order ID", "Order No", "Order Number"],
    "distributor": ["Distributor", "Distributor Name", "Distributor Code"],
    "description": ["Description", "Remarks", "Details", "Issue"],
    "closed_at": ["Closed On", "Resolved On", "Closed Date"],
}
STATUS_MAP = {"open": "open", "new": "open", "pending": "open", "in progress": "in_progress",
              "wip": "in_progress", "closed": "closed", "resolved": "closed", "done": "closed"}
DATE_FORMATS = ["%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%m/%d/%Y %H:%M:%S", "%d-%b-%Y"]


def parse_date(value):
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    s = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return timezone.make_aware(dt.datetime.strptime(s, fmt))
        except ValueError:
            continue
    return None


def pick(record, candidates):
    lower = {str(k).strip().lower(): v for k, v in record.items()}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


class GoogleSheetsConnector(BaseConnector):
    source = "google_sheets"

    def is_configured(self):
        path = settings.GOOGLE_SERVICE_ACCOUNT_JSON
        return bool(path and settings.CRM_SHEET_ID and os.path.exists(path))

    def _worksheet(self):
        import gspread  # imported lazily so the app runs without Google libs configured

        gc = gspread.service_account(filename=settings.GOOGLE_SERVICE_ACCOUNT_JSON)
        sh = gc.open_by_key(settings.CRM_SHEET_ID)
        return sh.worksheet(settings.CRM_SHEET_TAB) if settings.CRM_SHEET_TAB else sh.sheet1

    def sync(self, run):
        records = self._worksheet().get_all_records()
        return self.load_records(records)

    def load_records(self, records):
        retailers = {}
        for phone, rid, st, rg, asm, dist in Retailer.objects.exclude(phone="").values_list(
                "phone", "id", "state_id", "region_id", "asm_id", "distributor_id"):
            retailers[phone[-10:]] = (rid, st, rg, asm, dist)
        dist_by_name = {}
        for did, name, code in Distributor.objects.values_list("id", "name", "code"):
            dist_by_name[name.lower()] = did
            dist_by_name[code.lower()] = did
        order_refs = {str(pick(r, CRM_COLUMNS["order_id"]) or "").strip() for r in records} - {""}
        orders = {}
        for chunk in chunked(order_refs):
            orders.update(dict(Order.objects.filter(display_id__in=chunk).values_list("display_id", "id")))

        out, max_seen = [], None
        for r in records:
            tid = str(pick(r, CRM_COLUMNS["ticket_id"]) or "").strip()
            opened = parse_date(pick(r, CRM_COLUMNS["opened_at"]))
            if not tid or not opened:
                continue
            phone = "".join(ch for ch in str(pick(r, CRM_COLUMNS["retailer_phone"]) or "") if ch.isdigit())[-10:]
            ret = retailers.get(phone)
            dist = dist_by_name.get(str(pick(r, CRM_COLUMNS["distributor"]) or "").strip().lower())
            status_raw = str(pick(r, CRM_COLUMNS["status"]) or "open").strip().lower()
            out.append({
                "source_id": f"crm:{tid}"[:64],
                "ticket_type": str(pick(r, CRM_COLUMNS["ticket_type"]) or "Other").strip()[:64] or "Other",
                "status": STATUS_MAP.get(status_raw, "open"),
                "priority": str(pick(r, CRM_COLUMNS["priority"]) or "")[:16],
                "retailer_id": ret[0] if ret else None,
                "state_id": ret[1] if ret else None, "region_id": ret[2] if ret else None,
                "asm_id": ret[3] if ret else None,
                "distributor_id": dist or (ret[4] if ret else None),
                "order_id": orders.get(str(pick(r, CRM_COLUMNS["order_id"]) or "").strip()),
                "opened_at": opened,
                "closed_at": parse_date(pick(r, CRM_COLUMNS["closed_at"])),
                "description": str(pick(r, CRM_COLUMNS["description"]) or ""),
                "raw": {str(k): str(v) for k, v in r.items()},
            })
            max_seen = max(max_seen or opened, opened)
        n = 0
        for chunk in chunked(out, 1000):
            n += upsert(CrmTicket, chunk)
        if max_seen:
            self.set_watermark(max_seen, "crm")
        return n
