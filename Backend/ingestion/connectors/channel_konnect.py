"""Channel Konnect -> InventorySnapshot (daily stock per distributor x SKU).

TODO(TD): the CK API contract is not yet documented for us. This connector assumes:
  GET {CK_BASE_URL}/inventory?distributor=<ck_code>&updated_since=<iso>&page=<n>
  headers: x-api-key: <CK_API_KEY>
  response: {"items": [{"sku": "...", "quantity": 12, "updated_at": "..."}], "next_page": 2|null}
Adjust `fetch_distributor_stock` once the real endpoint is known.
"""
import datetime as dt

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from warehouse.models import Distributor, InventorySnapshot, ProductVariant

from ..upsert import chunked, upsert
from .base import BaseConnector

TIMEOUT = 30


class ChannelKonnectConnector(BaseConnector):
    source = "channel_konnect"

    def is_configured(self):
        return bool(settings.CK_BASE_URL and settings.CK_API_KEY)

    def fetch_distributor_stock(self, ck_code, since):
        url = settings.CK_BASE_URL.rstrip("/") + "/inventory"
        headers = {"x-api-key": settings.CK_API_KEY, "Accept": "application/json"}
        page = 1
        while page:
            params = {"distributor": ck_code, "page": page}
            if since:
                params["updated_since"] = since.isoformat()
            resp = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            body = resp.json()
            yield from body.get("items", [])
            page = body.get("next_page")

    def sync(self, run):
        variants = {
            sku: (vid, pid, style, size)
            for sku, vid, pid, style, size in ProductVariant.objects.values_list(
                "sku", "id", "product_id", "product__style", "size")
        }
        today = timezone.localdate()
        now = timezone.now()
        total, errors = 0, {}
        for dist in Distributor.objects.filter(is_active=True).exclude(ck_code=""):
            # Full snapshot each day (stock is a level, not a delta); watermark per distributor.
            try:
                items = list(self.fetch_distributor_stock(dist.ck_code, None))
            except requests.RequestException as exc:
                errors[dist.code] = str(exc)[:200]
                continue
            rows = []
            for it in items:
                sku = str(it.get("sku") or "").strip()
                if not sku:
                    continue
                v = variants.get(sku)
                rows.append({
                    "source": "ck", "distributor_id": dist.id, "sku": sku[:64], "snapshot_date": today,
                    "variant_id": v[0] if v else None, "product_id": v[1] if v else None,
                    "style": (v[2] if v else "") or "", "size": (v[3] if v else "") or "",
                    "quantity": int(it.get("quantity") or 0), "synced_at": now, "is_latest": True,
                })
            with transaction.atomic():
                InventorySnapshot.objects.filter(source="ck", distributor=dist, is_latest=True).exclude(
                    snapshot_date=today).update(is_latest=False)
                for chunk in chunked(rows, 2000):
                    total += upsert(InventorySnapshot, chunk,
                                    unique_fields=("source", "distributor", "sku", "snapshot_date"))
            self.set_watermark(now, f"dist:{dist.code}")
        run.details = {"distributor_errors": errors}
        if errors and not total:
            raise RuntimeError(f"All CK requests failed: {list(errors.items())[:3]}")
        self.set_watermark(now)
        return total


__all__ = ["ChannelKonnectConnector", "dt"]
