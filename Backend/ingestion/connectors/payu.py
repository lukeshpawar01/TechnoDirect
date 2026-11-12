"""PayU -> Payment (sales / order transactions only: no refunds, settlements or payouts).

Uses PayU's merchant "postservice" API, command `get_Transaction_Details`, which returns
all transactions between two dates:

  POST {PAYU_BASE_URL}/merchant/postservice.php?form=2
  form: key, command=get_Transaction_Details, var1=YYYY-MM-DD (from), var2=YYYY-MM-DD (to),
        hash=sha512(key|command|var1|salt)

Incremental: the watermark is the max `addedon` seen; each run re-reads from
(watermark date - 1 day) to today and upserts by mihpayid, so late status changes
(pending -> success) are picked up.

TODO(TD): confirm which request field carries the Medusa order / cart reference
(assumed udf1, falling back to productinfo) – see ORDER_REF_FIELDS.
"""
import datetime as dt
import hashlib
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.utils import timezone

from warehouse.models import Payment

from ..payments_link import reconcile_payments
from ..upsert import chunked, upsert
from .base import BaseConnector

COMMAND = "get_Transaction_Details"
TIMEOUT = 60
ORDER_REF_FIELDS = ["udf1", "udf2", "productinfo"]  # TODO(TD)
INITIAL_FROM = dt.date(2024, 12, 1)
MAX_WINDOW_DAYS = 7  # PayU limits the date range per call

STATUS_MAP = {
    "success": "success", "captured": "success",
    "failure": "failure", "failed": "failure", "bounced": "failure",
    "usercancelled": "userCancelled", "dropped": "userCancelled", "cancelled": "userCancelled",
    "pending": "pending", "in progress": "pending", "initiated": "pending", "auth": "pending",
}
MODE_MAP = {"CC": "CC", "DC": "DC", "NB": "NB", "UPI": "UPI", "CASH": "WALLET", "EMI": "EMI",
            "BNPL": "BNPL", "PAYLATER": "BNPL", "WALLET": "WALLET"}


def normalise_status(raw):
    return STATUS_MAP.get(str(raw or "").strip().lower(), "pending")


def normalise_mode(raw):
    raw = str(raw or "").strip().upper()
    return MODE_MAP.get(raw, raw[:16])


def parse_added_on(raw):
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            return timezone.make_aware(dt.datetime.strptime(str(raw)[:19], fmt))  # PayU reports IST
        except ValueError:
            continue
    return None


def _amount(raw):
    try:
        return Decimal(str(raw or "0").replace(",", ""))
    except InvalidOperation:
        return Decimal("0")


def map_txn(t):
    """PayU transaction dict -> Payment row dict (None if unusable)."""
    mihpayid = str(t.get("id") or t.get("mihpayid") or "").strip()
    added = parse_added_on(t.get("addedon") or t.get("added_on"))
    if not mihpayid or not added:
        return None
    ref = ""
    for f in ORDER_REF_FIELDS:
        if t.get(f):
            ref = str(t[f]).strip()
            break
    return {
        "source_id": mihpayid[:64],
        "txnid": str(t.get("txnid") or "")[:64],
        "order_ref": ref[:64],
        "amount": _amount(t.get("transaction_amount") or t.get("amount")),
        "status": normalise_status(t.get("status") or t.get("unmappedstatus")),
        "mode": normalise_mode(t.get("mode")),
        "bank": str(t.get("issuing_bank") or t.get("bankcode") or t.get("bank_name") or "")[:64],
        "added_on": added,
        "error_message": str(t.get("error_Message") or t.get("error_message") or "")[:255],
        "raw": {k: (v if isinstance(v, (str, int, float, bool)) or v is None else str(v)) for k, v in t.items()},
    }


class PayUConnector(BaseConnector):
    source = "payu"

    def is_configured(self):
        return bool(settings.PAYU_MERCHANT_KEY and settings.PAYU_MERCHANT_SALT and settings.PAYU_BASE_URL)

    def _hash(self, var1):
        s = f"{settings.PAYU_MERCHANT_KEY}|{COMMAND}|{var1}|{settings.PAYU_MERCHANT_SALT}"
        return hashlib.sha512(s.encode()).hexdigest()

    def fetch(self, d_from, d_to):
        url = settings.PAYU_BASE_URL.rstrip("/") + "/merchant/postservice.php?form=2"
        var1, var2 = d_from.isoformat(), d_to.isoformat()
        resp = requests.post(url, data={
            "key": settings.PAYU_MERCHANT_KEY, "command": COMMAND, "var1": var1, "var2": var2,
            "hash": self._hash(var1),
        }, timeout=TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
        if str(body.get("status")) not in ("1", "true", "True") and not body.get("Transaction_details"):
            msg = str(body.get("msg") or "")
            if "no record" in msg.lower():
                return []
            raise RuntimeError(f"PayU error: {msg or body}")
        return body.get("Transaction_details") or []

    def sync(self, run):
        wm = self.watermark()
        today = timezone.localdate()
        start = (timezone.localtime(wm).date() - dt.timedelta(days=1)) if wm else INITIAL_FROM
        rows, cur = [], start
        while cur <= today:
            end = min(cur + dt.timedelta(days=MAX_WINDOW_DAYS - 1), today)
            for t in self.fetch(cur, end):
                m = map_txn(t)
                if m:
                    rows.append(m)
            cur = end + dt.timedelta(days=1)
        n = 0
        for chunk in chunked(rows, 2000):
            n += upsert(Payment, chunk)
        linked = reconcile_payments(split_groups=set())
        if rows:
            self.set_watermark(max(r["added_on"] for r in rows))
        run.details = {"window_from": start.isoformat(), "window_to": today.isoformat(),
                       "orders_updated": linked}
        return n
