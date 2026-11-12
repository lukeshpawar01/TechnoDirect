"""Medusa (read replica) -> warehouse incremental sync.

All SQL lives in medusa_queries.py. This module only maps rows and upserts.
Order of entities matters: geography -> distributors -> serviceability -> catalogue -> retailers
-> orders -> inventory -> pending-order jobs.
"""
import datetime as dt
import logging
import re

from django.conf import settings
from django.db import connections, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from warehouse.models import (
    Category,
    Distributor,
    InventorySnapshot,
    Order,
    OrderLine,
    PendingOrderJob,
    Pincode,
    Product,
    ProductVariant,
    Region,
    Retailer,
    State,
    compute_is_qualifying,
)

from ..upsert import chunked, upsert
from . import medusa_queries as Q
from .base import BaseConnector

log = logging.getLogger(__name__)

EPOCH = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
OVERLAP = dt.timedelta(minutes=10)
KYC_VALUES = {"not_submitted", "pending", "approved", "rejected"}

# Default sales regions for states first seen in Medusa (matches the TD review's regional view).
# Regions remain editable in Admin > Mappings; existing assignments are never overwritten.
DEFAULT_STATE_REGION = {
    "South": ["Karnataka", "Telangana", "Andhra Pradesh", "Tamil Nadu", "Kerala", "Puducherry",
              "Lakshadweep", "Andaman And Nicobar Islands"],
    "West": ["Maharashtra", "Gujarat", "Goa", "Rajasthan", "Madhya Pradesh", "Chhattisgarh",
             "Dadra And Nagar Haveli And Daman And Diu", "Dadra And Nagar Haveli", "Daman And Diu"],
    "North": ["Delhi", "Uttar Pradesh", "Haryana", "Punjab", "Himachal Pradesh", "Uttarakhand",
              "Jammu And Kashmir", "Ladakh", "Chandigarh"],
    "East & North-East": ["West Bengal", "Odisha", "Bihar", "Jharkhand", "Assam", "Sikkim", "Meghalaya",
                          "Tripura", "Mizoram", "Manipur", "Nagaland", "Arunachal Pradesh"],
}
STATE_TO_REGION = {s.lower(): r for r, states in DEFAULT_STATE_REGION.items() for s in states}
STATE_ALIASES = {"orissa": "Odisha", "pondicherry": "Puducherry", "new delhi": "Delhi",
                 "nct of delhi": "Delhi", "the dadra and nagar haveli and daman and diu":
                     "Dadra And Nagar Haveli And Daman And Diu"}


def clean_state(name):
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not name:
        return ""
    name = name.title().replace(" & ", " And ")
    return STATE_ALIASES.get(name.lower(), name)


def map_order_status(medusa_status, fulfillment_status, shipped_at, delivered_at, confirmed_at, ts_status=""):
    """Medusa order/fulfillment enums + TD's ts_order_status -> received|confirmed|shipped|delivered|cancelled."""
    ts = (ts_status or "").lower()
    if medusa_status == "canceled" or fulfillment_status == "canceled" or "cancel" in ts:
        return "cancelled"
    if delivered_at or "deliver" in ts:
        return "delivered"
    if shipped_at or fulfillment_status in ("shipped", "partially_shipped") or "ship" in ts or "dispatch" in ts:
        return "shipped"
    if (confirmed_at or fulfillment_status in ("fulfilled", "partially_fulfilled")
            or any(k in ts for k in ("pack", "confirm", "process", "accept"))):
        return "confirmed"
    return "received"


def _ist_date(value):
    return timezone.localtime(value).date() if value else None


class MedusaConnector(BaseConnector):
    source = "medusa"

    def is_configured(self):
        return "medusa" in settings.DATABASES

    # ------------------------------------------------------------------ io
    def fetch(self, sql, since=None):
        params = {"since": since or EPOCH, "div": settings.MEDUSA_AMOUNT_DIVISOR,
                  "naive_tz": settings.MEDUSA_NAIVE_TZ}
        with connections["medusa"].cursor() as cur:
            cur.execute(sql, params)
            cols = [c[0] for c in cur.description]
            while True:
                batch = cur.fetchmany(5000)
                if not batch:
                    break
                for row in batch:
                    yield dict(zip(cols, row))

    def _since(self, entity):
        wm = self.watermark(entity)
        return (wm - OVERLAP) if wm else EPOCH

    def _advance(self, entity, rows):
        stamps = [r["updated_at"] for r in rows if r.get("updated_at")]
        if stamps:
            self.set_watermark(max(stamps), entity)

    # ------------------------------------------------------------------ sync
    def sync(self, run):
        total = 0
        counts = {}
        for name, fn in (
            ("pincodes", self.sync_pincodes),
            ("distributors", self.sync_distributors),
            ("serviceability", self.sync_serviceability),
            ("products", self.sync_products),
            ("variants", self.sync_variants),
            ("retailers", self.sync_retailers),
            ("orders", self.sync_orders),
            ("inventory", self.sync_inventory),
            ("pending_order_jobs", self.sync_pending_jobs),
        ):
            n = fn()
            counts[name] = n
            total += n
        run.details = {"rows_by_entity": counts}
        return total

    # ------------------------------------------------------------ geography
    def _state_index(self):
        return {s.name.lower(): s for s in State.objects.all()}

    def _ensure_states(self, names):
        """Create any unseen state (with a default region) and return the name -> State index."""
        states = self._state_index()
        for raw in names:
            name = clean_state(raw)
            if not name or name.lower() in states:
                continue
            region = None
            rname = STATE_TO_REGION.get(name.lower())
            if rname:
                region, _ = Region.objects.get_or_create(
                    code=re.sub(r"[^A-Z0-9]+", "_", rname.upper()).strip("_")[:32], defaults={"name": rname})
            code = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")[:32]
            st, _ = State.objects.get_or_create(name=name, defaults={"code": code, "region": region})
            states[name.lower()] = st
        return states

    def sync_pincodes(self):
        rows = list(self.fetch(Q.PINCODES_SQL, self._since("pincodes")))
        if not rows:
            return 0
        states = self._ensure_states({r.get("state_name") for r in rows})
        out = []
        for r in rows:
            st = states.get(clean_state(r.get("state_name")).lower())
            # asm / distributor columns are NOT touched here (admin + serviceability own them)
            out.append({"pincode": r["pincode"][:6], "district": (r.get("district") or "")[:100],
                        "city": (r.get("city") or "")[:100], "state_id": st.id if st else None})
        n = 0
        for chunk in chunked(out, 2000):
            n += upsert(Pincode, chunk, unique_fields=("pincode",))
        self._advance("pincodes", rows)
        return n

    def sync_distributors(self):
        rows = list(self.fetch(Q.DISTRIBUTORS_SQL, self._since("distributors")))
        states = self._ensure_states({r.get("state_name") for r in rows})
        out = []
        for r in rows:
            st = states.get(clean_state(r.get("state_name")).lower())
            out.append({
                "source_id": r["source_id"], "code": r["code"], "name": (r["name"] or r["code"])[:200],
                "state_id": st.id if st else None, "region_id": st.region_id if st else None,
                "city": (r.get("city") or "")[:100], "gstin": (r.get("gstin") or "")[:20],
                "is_active": bool(r.get("is_active", True)), "onboarded_on": r.get("onboarded_on"),
                # ck_code is admin-maintained: deliberately not written here
            })
        self._adopt_csv_distributors(out)
        n = upsert(Distributor, out)
        self._advance("distributors", rows)
        return n

    @staticmethod
    def _adopt_csv_distributors(rows):
        """Distributors first loaded from the CSV exports have no Medusa id (source_id 'name:...').
        Give them their Medusa id when the name matches, so the upsert updates them instead of duplicating."""
        from ingestion.csv_import import norm

        known = set(Distributor.objects.values_list("source_id", flat=True))
        by_name = {}
        for d in Distributor.objects.filter(source_id__startswith="name:"):
            for alias in [d.name, *(d.aliases or [])]:
                by_name.setdefault(norm(alias), d)
        for r in rows:
            if r["source_id"] in known:
                continue
            d = by_name.get(norm(r["name"]))
            if d and d.source_id.startswith("name:"):
                d.source_id = r["source_id"]
                d.save(update_fields=["source_id", "updated_at"])
                known.add(r["source_id"])
                r["code"] = d.code  # keep the existing code; avoids a unique clash

    def sync_serviceability(self):
        """Full refresh of P1/P2 distributor per pincode from ts_distributor_serviceability."""
        rows = list(self.fetch(Q.SERVICEABILITY_SQL))
        dists = dict(Distributor.objects.values_list("source_id", "id"))
        mapping = {}
        for r in rows:
            pin = (r.get("pincode") or "").strip()[:6]
            did = dists.get(r.get("distributor_source_id"))
            if not pin or not did:
                continue
            mapping.setdefault(pin, {})[int(r["rank"])] = did
        existing = set(Pincode.objects.values_list("pincode", flat=True))
        out = [{"pincode": pin, "distributor_p1_id": m.get(1), "distributor_p2_id": m.get(2),
                "is_serviceable": True} for pin, m in mapping.items()]
        with transaction.atomic():
            for chunk in chunked(out, 2000):
                upsert(Pincode, chunk, unique_fields=("pincode",))
            # pincodes no longer served by anyone
            Pincode.objects.filter(pincode__in=existing - set(mapping)).exclude(
                distributor_p1__isnull=True, distributor_p2__isnull=True
            ).update(distributor_p1=None, distributor_p2=None, is_serviceable=False)
            # keep retailer -> P1 distributor in step with the routing table
            for chunk in chunked(list(mapping.items()), 900):
                for pin, m in chunk:
                    Retailer.objects.filter(pincode=pin).exclude(distributor_id=m.get(1)).update(
                        distributor_id=m.get(1))
        return len(out)

    # ------------------------------------------------------------ catalogue
    def sync_products(self):
        rows = list(self.fetch(Q.PRODUCTS_SQL, self._since("products")))
        cats = {}
        for r in rows:
            code = (r.get("category_code") or "uncategorised")[:32]
            cats[code] = {"code": code, "name": (r.get("category_name") or code)[:100], "level": 1}
        upsert(Category, list(cats.values()), unique_fields=("code",))
        cat_ids = dict(Category.objects.values_list("code", "id"))
        # style must be unique; if two products share ts_style keep the latest one's row
        out = {}
        for r in rows:
            style = (r["style"] or r["source_id"])[:32]
            out[style] = {
                "source_id": r["source_id"], "style": style, "name": (r["name"] or "")[:200],
                "category_id": cat_ids.get((r.get("category_code") or "uncategorised")[:32]),
                "category_l1": (r.get("category_l1") or "")[:100],
                "category_l2": (r.get("category_l2") or "")[:100], "category_l3": (r.get("category_l3") or "")[:100],
                "pack_size": r.get("pack_size") or 1, "launched_on": r.get("launched_on"),
                "is_active": bool(r.get("is_active", True)),
            }
        n = upsert(Product, list(out.values()))
        self._advance("products", rows)
        return n

    def sync_variants(self):
        rows = list(self.fetch(Q.VARIANTS_SQL, self._since("variants")))
        prod = dict(Product.objects.values_list("source_id", "id"))
        out = {}
        for r in rows:
            if r["product_source_id"] not in prod:
                continue
            out[r["sku"]] = {
                "source_id": r["source_id"], "product_id": prod[r["product_source_id"]], "sku": r["sku"][:64],
                "size": (r.get("size") or "")[:16], "mrp": r.get("mrp") or 0, "price": r.get("price") or 0,
            }
        n = upsert(ProductVariant, list(out.values()))
        self._advance("variants", rows)
        return n

    # ------------------------------------------------------------ retailers
    def sync_retailers(self):
        rows = list(self.fetch(Q.RETAILERS_SQL, self._since("retailers")))
        if not rows:
            return 0
        states = self._ensure_states({r.get("state_name") for r in rows})
        pins = {p.pincode: p for p in Pincode.objects.select_related("state")}
        approved_before = dict(Retailer.objects.filter(kyc_approved_at__isnull=False)
                               .values_list("source_id", "kyc_approved_at"))
        first_load = not Retailer.objects.exists()
        now = timezone.now()
        out = []
        for r in rows:
            pin = (r.get("pincode") or "").strip()
            pm = pins.get(pin)
            st = (pm.state if pm and pm.state_id else None) or states.get(clean_state(r.get("state_name")).lower())
            kyc = (r.get("kyc_status") or "not_submitted").lower()
            approved_at = r.get("kyc_approved_at")
            if kyc == "approved" and not approved_at:
                # No KYC timestamp in Medusa: keep the first time we saw it approved
                approved_at = approved_before.get(r["source_id"]) or (r.get("signed_up_at") if first_load else now)
            out.append({
                "source_id": r["source_id"], "name": (r.get("name") or "")[:200] or r["source_id"],
                "owner_name": (r.get("owner_name") or "")[:200], "phone": (r.get("phone") or "")[:20],
                "email": (r.get("email") or "")[:254], "gstin": (r.get("gstin") or "")[:20], "pincode": pin[:10],
                "city": (r.get("city") or "")[:100],
                "state_id": st.id if st else None, "region_id": st.region_id if st else None,
                "asm_id": pm.asm_id if pm else None, "distributor_id": pm.distributor_p1_id if pm else None,
                "kyc_status": kyc if kyc in KYC_VALUES else "pending",
                "signed_up_at": r.get("signed_up_at"), "kyc_submitted_at": r.get("kyc_submitted_at"),
                "kyc_approved_at": approved_at if kyc == "approved" else None,
                "warm_match": bool(r.get("warm_match")), "tier": (r.get("tier") or "")[:16],
            })
        n = 0
        for chunk in chunked(out, 2000):
            n += upsert(Retailer, chunk)
        self._advance("retailers", rows)
        return n

    # ------------------------------------------------------------ orders
    def sync_orders(self):
        since = self._since("orders")
        rows = list(self.fetch(Q.ORDERS_SQL, since))
        if not rows:
            return 0
        retailers = {
            sid: (rid, st, rg, asm)
            for sid, rid, st, rg, asm in Retailer.objects.values_list("source_id", "id", "state_id", "region_id",
                                                                      "asm_id")
        }
        distributors = dict(Distributor.objects.values_list("source_id", "id"))
        out = []
        for r in rows:
            ret = retailers.get(r.get("customer_source_id"))
            status = map_order_status(r.get("medusa_status"), r.get("fulfillment_status"), r.get("shipped_at"),
                                      r.get("delivered_at"), r.get("confirmed_at"), r.get("ts_order_status"))
            pay = Q.PAYMENT_STATUS_MAP.get(r.get("payment_status") or "", "awaiting")
            out.append({
                "source_id": r["source_id"], "display_id": str(r.get("display_id") or r["source_id"])[:32],
                "split_group": (r.get("cart_id") or r["source_id"])[:64],
                "retailer_id": ret[0] if ret else None, "state_id": ret[1] if ret else None,
                "region_id": ret[2] if ret else None, "asm_id": ret[3] if ret else None,
                "distributor_id": distributors.get(r.get("distributor_source_id")),
                # payment_status here is the Medusa fallback; reconcile_payments() overrides it
                # with the PayU transaction status where a PayU txn is linked.
                "status": status, "payment_status": pay, "medusa_payment_status": pay,
                "payment_status_source": "medusa",
                "payment_ref": (r.get("payment_ref") or "")[:64],
                "is_qualifying": compute_is_qualifying(status, pay),
                "gross_value": r.get("gross_value") or 0,
                "placed_at": r["placed_at"], "placed_date": _ist_date(r["placed_at"]),
                "confirmed_at": r.get("confirmed_at"), "shipped_at": r.get("shipped_at"),
                "delivered_at": r.get("delivered_at"), "cancelled_at": r.get("cancelled_at"),
                "awb": (r.get("awb") or "")[:64], "courier": (r.get("courier") or "")[:64],
                "ts_order_status": (r.get("ts_order_status") or "")[:32],
                "distributor_remark": (r.get("ts_remark") or "")[:255],
                "source_updated_at": r.get("updated_at"),
            })
        with transaction.atomic():
            n = 0
            for chunk in chunked(out, 2000):
                n += upsert(Order, chunk)
            n += self.sync_lines(since, [r["source_id"] for r in rows])
            self._post_process([r["source_id"] for r in rows])
            from ..payments_link import reconcile_payments

            reconcile_payments(split_groups={o["split_group"] for o in out})
        self._advance("orders", rows)
        return n

    def sync_lines(self, since, order_source_ids):
        rows = list(self.fetch(Q.ORDER_LINES_SQL, since))
        order_ids = {}
        for chunk in chunked(order_source_ids):
            order_ids.update(dict(Order.objects.filter(source_id__in=chunk).values_list("source_id", "id")))
        variants = {
            sid: (vid, pid, style, size)
            for sid, vid, pid, style, size in ProductVariant.objects.values_list(
                "source_id", "id", "product_id", "product__style", "size")
        }
        out = []
        for r in rows:
            oid = order_ids.get(r["order_source_id"])
            if not oid:
                continue
            v = variants.get(r.get("variant_source_id"))
            boxes = int(r.get("boxes") or 0)
            ppb = int(r.get("pieces_per_box") or 1)
            pieces = boxes * ppb
            total = r.get("total") or 0
            out.append({
                "source_id": r["source_id"], "order_id": oid,
                "variant_id": v[0] if v else None, "product_id": v[1] if v else None,
                "style": (v[2] if v else "") or "", "size": (v[3] if v else "") or "",
                "sku": (r.get("sku") or "")[:64], "boxes": boxes, "pieces_per_box": ppb, "quantity": pieces,
                "unit_price": (total / pieces) if pieces else 0, "total": total,
            })
        n = 0
        for chunk in chunked(out, 2000):
            n += upsert(OrderLine, chunk)
        return n

    def _post_process(self, order_source_ids):
        """Recompute order units (pieces) and split flags for the touched orders / carts."""
        groups = set()
        for chunk in chunked(order_source_ids):
            qs = Order.objects.filter(source_id__in=chunk)
            units = dict(OrderLine.objects.filter(order__in=qs).values("order_id")
                         .annotate(u=Sum("quantity")).values_list("order_id", "u"))
            objs = []
            for o in qs.only("id", "split_group"):
                o.units = units.get(o.id, 0) or 0
                objs.append(o)
                groups.add(o.split_group)
            Order.objects.bulk_update(objs, ["units"])
        for chunk in chunked(groups):
            counts = dict(Order.objects.filter(split_group__in=chunk).values("split_group")
                          .annotate(n=Count("id")).values_list("split_group", "n"))
            split = [g for g, c in counts.items() if c > 1]
            Order.objects.filter(split_group__in=chunk).update(is_split=False)
            if split:
                Order.objects.filter(split_group__in=split).update(is_split=True)

    # ------------------------------------------------------------ inventory
    def sync_inventory(self):
        """Today's app stock per distributor x SKU (ts_product_variant_inventory) -> InventorySnapshot(source='td')."""
        rows = list(self.fetch(Q.INVENTORY_SQL))
        dists = dict(Distributor.objects.values_list("source_id", "id"))
        variants = {
            sid: (vid, pid, sku, style, size)
            for sid, vid, pid, sku, style, size in ProductVariant.objects.values_list(
                "source_id", "id", "product_id", "sku", "product__style", "size")
        }
        today = timezone.localdate()
        now = timezone.now()
        out = {}
        last_update = {}
        for r in rows:
            did = dists.get(r.get("distributor_source_id"))
            if not did:
                continue
            v = variants.get(r.get("variant_source_id"))
            sku = ((v[2] if v else None) or r.get("sku") or r.get("variant_source_id") or "")[:64]
            if not sku:
                continue
            key = (did, sku)
            prev = out.get(key)
            qty = int(r.get("quantity") or 0)
            out[key] = {
                "source": "td", "distributor_id": did, "sku": sku, "snapshot_date": today,
                "variant_id": v[0] if v else None, "product_id": v[1] if v else None,
                "style": ((v[3] if v else "") or "")[:32], "size": ((v[4] if v else "") or "")[:16],
                "quantity": qty + (prev["quantity"] if prev else 0),
                # synced_at = when the distributor's stock was last uploaded (drives the staleness badge)
                "synced_at": now, "is_latest": True,
            }
            if r.get("updated_at"):
                last_update[did] = max(last_update.get(did, r["updated_at"]), r["updated_at"])
        for row in out.values():
            row["synced_at"] = last_update.get(row["distributor_id"], now)
        with transaction.atomic():
            InventorySnapshot.objects.filter(source="td", is_latest=True).exclude(
                snapshot_date=today).update(is_latest=False)
            InventorySnapshot.objects.filter(source="td", snapshot_date=today).delete()
            n = 0
            for chunk in chunked(list(out.values()), 2000):
                n += upsert(InventorySnapshot, chunk,
                            unique_fields=("source", "distributor", "sku", "snapshot_date"))
        return n

    # ------------------------------------------------------------ pending order jobs
    def sync_pending_jobs(self):
        rows = list(self.fetch(Q.PENDING_JOBS_SQL, self._since("pending_order_jobs")))
        out = [{
            "source_id": r["source_id"], "cart_id": (r.get("cart_id") or "")[:64],
            "payment_session_id": (r.get("payment_session_id") or "")[:64],
            "order_source_id": (r.get("order_source_id") or "")[:64], "status": (r.get("status") or "")[:32],
            "attempt": r.get("attempt") or 0, "error": (r.get("error") or "")[:500], "amount": r.get("amount"),
            "refund_initiated_at": r.get("refund_initiated_at"), "job_created_at": r["created_at"],
            "job_updated_at": r.get("updated_at"),
        } for r in rows]
        n = upsert(PendingOrderJob, out)
        self._advance("pending_order_jobs", rows)
        return n
