"""Google Sheets -> CrmTicket: the CRM issues tracker ("B2B Order Tracker CRM", tab "CRM Issues - December 2025
Onwards"), read live through the service account (CRM_SHEET_URL = the browser link incl. #gid; or CRM_SHEET_ID +
CRM_SHEET_TAB).

Columns used (first matching header wins, case-insensitive):
  DATE, ORDER ID, CUSTOMER NAME, DISTRIBUTOR, ISSUES TYPE, ASSIGNED TO, STATUS, CRM _REMARKS, FINAL ACTION,
  REFUND, REFUND DATE
The sheet has no ticket id: a ticket's id is built from date + order id + issue + customer (stable while those
cells stay the same). Each run reads the whole sheet and replaces the tickets (a deleted row disappears).
Linking: the order number gives retailer, distributor, state, region and ASM; without a matching order the
distributor name is matched (aliases, abbreviations). A date after today is taken as last year's (the tab starts in
Dec 2025, so "4-Dec-2026" is a typo for 2025) and flagged in raw["date_corrected"].
"""
import datetime as dt
import hashlib
import re
from collections import Counter

from django.conf import settings
from django.utils import timezone

from warehouse.models import CrmTicket, Distributor, Order

from ..upsert import chunked, upsert
from .base import BaseConnector

CRM_COLUMNS = {
    "opened_at": ["Date", "Created On", "Opened On", "Complaint Date", "Timestamp"],
    "order_id": ["Order ID", "Order No", "Order Number"],
    "customer": ["Customer Name", "Retailer", "Retailer Name"],
    "distributor": ["Distributor", "Distributor Name", "Distributor Code"],
    "ticket_type": ["Issues Type", "Issue Type", "Type", "Complaint Type", "Category"],
    "assigned_to": ["Assigned To", "Owner"],
    "status": ["Status"],
    "description": ["CRM _Remarks", "CRM Remarks", "Remarks", "Description", "Details"],
    "final_action": ["Final Action", "Action"],
    "refund": ["Refund", "Refund Amount"],
    "refund_date": ["Refund Date"],
    "ticket_id": ["Ticket ID", "Ticket No", "Complaint ID"],
    "closed_at": ["Closed On", "Resolved On", "Closed Date"],
    "priority": ["Priority"],
}
STATUS_MAP = {"open": "open", "new": "open", "pending": "open", "in progress": "in_progress", "wip": "in_progress",
              "closed": "closed", "resolved": "closed", "done": "closed", "": "open"}
# typed issue types -> one clean label (anything else is title-cased as typed)
TYPE_FIX = {"issues type": "Not specified", "issue type": "Not specified", "": "Not specified",
            "shot quantity": "Short Quantity"}
DATE_FORMATS = ["%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%d-%m-%Y",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d %b %Y", "%d-%b-%y"]


def parse_date(value):
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    s = " ".join(str(value).split())
    for fmt in DATE_FORMATS:
        try:
            return timezone.make_aware(dt.datetime.strptime(s, fmt))
        except ValueError:
            continue
    return None


def pick(record, candidates):
    lower = {" ".join(str(k).split()).lower(): v for k, v in record.items()}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def text(record, key):
    return " ".join(str(pick(record, CRM_COLUMNS[key]) or "").split())


def order_numbers(raw):
    """'#16904' / '# 16904' / '#123,#456' / '#123.' -> ['16904'] / ['123', '456']"""
    return re.findall(r"\d{3,}", raw or "")


def money(raw):
    s = re.sub(r"[^\d.]", "", raw or "")
    try:
        return float(s) if s else None
    except ValueError:
        return None


def issue_type(raw):
    k = " ".join(raw.replace(",", " ").split()).lower()
    return TYPE_FIX.get(k) or k.title()[:64]


class GoogleSheetsConnector(BaseConnector):
    source = "google_sheets"

    def link(self):
        if getattr(settings, "CRM_SHEET_URL", ""):
            return settings.CRM_SHEET_URL, getattr(settings, "CRM_SHEET_TAB", "")
        if getattr(settings, "CRM_SHEET_ID", ""):
            return settings.CRM_SHEET_ID, getattr(settings, "CRM_SHEET_TAB", "")
        return None, None

    def is_configured(self):
        from .. import gsheets

        return bool(self.link()[0]) and gsheets.configured()

    def sync(self, run):
        from .. import gsheets

        url, tab = self.link()
        return self.load_records(gsheets.read_table(url, tab or None))

    def load_records(self, records, today=None):
        from masters.name_match import distributor as match_distributor

        today = today or timezone.localdate()
        dists = list(Distributor.objects.all())
        nums = {n for r in records for n in order_numbers(text(r, "order_id"))}
        orders = {}
        for chunk in chunked(sorted(nums)):
            for o in Order.objects.filter(display_id__in=chunk).values(
                    "id", "display_id", "retailer_id", "distributor_id", "state_id", "region_id", "asm_id"):
                orders[o["display_id"]] = o
        dist_cache = {}
        seen = Counter()
        out = []
        for r in records:
            opened = parse_date(text(r, "opened_at"))
            if not opened:
                continue
            raw = {" ".join(str(k).split()): " ".join(str(v).split()) for k, v in r.items() if str(k).strip()}
            if opened.date() > today:  # the tab starts Dec 2025: "4-Dec-2026" is a typo for 2025
                raw["date_corrected"] = f"{opened.date().isoformat()} -> one year earlier (date was in the future)"
                opened = opened.replace(year=opened.year - 1)
            nums_r = order_numbers(text(r, "order_id"))
            o = next((orders[n] for n in nums_r if n in orders), None)
            dname = text(r, "distributor")
            if dname not in dist_cache:
                dist_cache[dname] = match_distributor(dname, dists)
            d = dist_cache[dname]
            tid = text(r, "ticket_id")
            if not tid:
                key = "|".join([opened.date().isoformat(), ",".join(nums_r), text(r, "ticket_type").lower(),
                                text(r, "customer").lower()])
                seen[key] += 1
                tid = hashlib.sha1(f"{key}|{seen[key]}".encode()).hexdigest()[:16]
            status = STATUS_MAP.get(text(r, "status").lower(), "open")
            closed = parse_date(text(r, "closed_at")) or (parse_date(text(r, "refund_date")) if status == "closed" else None)
            raw.update({"order_numbers": nums_r, "refund_amount": money(text(r, "refund"))})
            out.append({
                "source_id": f"crm:{tid}"[:64],
                "ticket_type": issue_type(text(r, "ticket_type")),
                "status": status,
                "priority": text(r, "priority")[:16],
                "retailer_id": o["retailer_id"] if o else None,
                "order_id": o["id"] if o else None,
                "distributor_id": (o["distributor_id"] if o and o["distributor_id"] else (d.id if d else None)),
                "state_id": o["state_id"] if o else (d.state_id if d else None),
                "region_id": o["region_id"] if o else (d.region_id if d else None),
                "asm_id": o["asm_id"] if o else (d.asm_id if d else None),
                "opened_at": opened,
                "closed_at": closed,
                "description": text(r, "description"),
                "raw": raw,
            })
        n = 0
        for chunk in chunked(out, 1000):
            n += upsert(CrmTicket, chunk)
        # the sheet is the full list: tickets whose row was deleted (or whose key cells changed) go away
        keep = {t["source_id"] for t in out}
        CrmTicket.objects.filter(source_id__startswith="crm:").exclude(source_id__in=keep).delete()
        if out:
            self.set_watermark(max(t["opened_at"] for t in out), "crm")
        return n
