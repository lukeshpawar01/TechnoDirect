"""Map the TD data (Supabase tables: distributors, customers, products, orders, sales, inventory_snapshot,
loyalty_ledger) into the warehouse. The rows arrive as dicts of strings (ingestion/connectors/supabase.py turns the
Postgres values into the text form this mapping parses); `read_rows()` is provided by the connector.

Interpretation (checked against the TD_DataDeck figures, see docs/PLAN.md):
  * Sales = line_total (sum of the order's lines, before points). total_amount = payu_amount + points_redeemed,
    so it over-states sales once points are redeemed. Line totals reproduce the deck's month figures
    (first Rs 1 Cr month Jun-25, first Rs 2 Cr month Dec-25, record Rs 2.95 Cr Aug-26).
  * order_date is a calendar date only; placed_at is set to 12:00 IST that day.
  * Paid = a payment mode or a PayU amount is present. Pre-launch pilot orders have neither and do not count.
  * Stock on hand = `available` (stock less reserved), summed over a distributor's locations.
  * customers.distributor_name = "P1, P2" serviceable distributors for the retailer.
  * settlement_status is ignored (settlement comes from the finance tracker).

Admin-maintained mappings (ASM, state / region of a distributor, aliases, targets) are kept across imports.
"""
import datetime as dt
import difflib
import logging
from collections import Counter, defaultdict
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from warehouse import geo
from warehouse.models import (
    Category,
    Distributor,
    InventorySnapshot,
    LoyaltyEvent,
    Order,
    OrderLine,
    Pincode,
    Product,
    ProductVariant,
    Region,
    Retailer,
    State,
    compute_is_qualifying,
)

from .normalize import (IST, TWO, UTC, WHOLESALE_SHARE, end_of_day, nice_name, norm, parse_dt, slug, to_bool, to_date,
                        to_dec, to_int)
from .upsert import chunked, upsert

log = logging.getLogger(__name__)
STATUS_MAP = {
    "placed": "received", "confirmed": "confirmed", "packed": "confirmed", "on hold": "confirmed",
    "shipped": "shipped", "delivered": "delivered", "cancelled": "cancelled", "canceled": "cancelled",
}
LOYALTY_KINDS = {"new customer": "new_customer", "points earned": "earned", "earn": "earned",
                 "points redeemed": "redeemed"}
PLACED_TIME = dt.time(12, 0)


class TdImporter:
    """Full rebuild-by-upsert of the TD data. Subclasses provide read_rows()."""

    def __init__(self, source_tz="UTC", stdout=None):
        self.tz = ZoneInfo(source_tz)
        self.snapshot_date = None
        self.out = stdout
        self.stats = {}
        self.warnings = []
        self._fuzzy = {}
        self.sources = {}

    def say(self, msg):
        log.info(msg)
        if self.out:
            self.out.write(f"[import] {msg}")

    def warn(self, msg):
        self.warnings.append(msg)
        self.say(f"WARNING: {msg}")

    def read_rows(self):
        """{kind: [row dict of strings]} for distributor, customer, product, order, sales, inventory, loyalty; also
        sets self.sources {kind: label} and self.inventory_synced_at."""
        raise NotImplementedError

    # ------------------------------------------------------------------ run
    def run(self):
        data = self.read_rows()
        for kind, label in sorted(self.sources.items()):
            self.say(f"{kind:<11} <- {label}")
        rd = lambda k: data.get(k) or []  # noqa: E731
        self.dist_rows = rd("distributor")
        self.customers = [r for r in rd("customer") if not to_bool(r.get("is_test"))]
        self.products_rows = rd("product")
        self.inventory_rows = rd("inventory")
        self.order_rows = rd("order")
        self.sales_rows = rd("sales")
        self.loyalty_rows = rd("loyalty")

        with transaction.atomic():
            self.load_geography()
            self.load_distributors()
            self.load_pincodes()
        with transaction.atomic():
            self.load_products()
        with transaction.atomic():
            self.load_retailers()
        with transaction.atomic():
            self.load_orders()
        with transaction.atomic():
            self.load_inventory()
        with transaction.atomic():
            self.load_loyalty()
        with transaction.atomic():
            self.load_pnl_checks()
        return {"files": dict(self.sources), "rows": self.stats, "warnings": self.warnings}

    def load_pnl_checks(self):
        """Per-quarter order totals the P&L compares its entered figures with (masters/pnl.py)."""
        from masters.pnl import rebuild_data_checks

        self.stats["pnl_quarters"] = rebuild_data_checks(self.order_rows)

    # ------------------------------------------------------------------ geography / pincodes
    def load_geography(self):
        regions = {r.code: r for r in Region.objects.all()}
        for code, name in geo.REGIONS.items():
            if code not in regions:
                regions[code] = Region.objects.create(code=code, name=name)
        states = {s.code: s for s in State.objects.all()}
        for code, (name, reg) in geo.STATES.items():
            if code not in states:
                existing = State.objects.filter(name=name).first()
                states[code] = existing or State.objects.create(code=code, name=name, region=regions[reg])
            elif states[code].region_id is None:
                states[code].region = regions[reg]
                states[code].save(update_fields=["region", "updated_at"])
        self.states = states

        # pincode -> state code: a state named on a retailer beats the PIN-prefix rule
        self.sales_pin_state, self.sales_pin_city = {}, {}
        for r in self.customers:
            pin = r.get("ts_pincode", "")
            sc = geo.state_code_for_name(r.get("province"))
            if geo.is_valid_pincode(pin):
                if sc:
                    self.sales_pin_state[pin] = sc
                if r.get("city"):
                    self.sales_pin_city[pin] = r["city"].strip().title()
        self.stats["states"] = len(states)

    def state_for_pin(self, pin):
        code = self.sales_pin_state.get(pin) or geo.state_code_for_pincode(pin)
        return self.states.get(code) if code else None

    def load_pincodes(self):
        p1s, p2s = defaultdict(Counter), defaultdict(Counter)
        pins = set()
        for r in self.customers:
            pin = r.get("ts_pincode", "")
            if not geo.is_valid_pincode(pin):
                continue
            pins.add(pin)
            parts = [p.strip() for p in (r.get("distributor_name") or "").split(",") if p.strip()]
            if parts:
                p1s[pin][parts[0]] += 1
            if len(parts) > 1:
                p2s[pin][parts[1]] += 1

        rows = []
        for pin in sorted(pins):
            st = self.state_for_pin(pin)
            p1 = self.dist(p1s[pin].most_common(1)[0][0]) if p1s[pin] else None
            p2 = self.dist(p2s[pin].most_common(1)[0][0]) if p2s[pin] else None
            row = {"pincode": pin, "state_id": st.id if st else None,
                   "distributor_p1_id": p1.id if p1 else None,
                   "distributor_p2_id": p2.id if p2 and p2 != p1 else None, "is_serviceable": bool(p1)}
            if pin in self.sales_pin_city:
                row["city"] = self.sales_pin_city[pin][:100]
            rows.append(row)
        # split so that `city` is only overwritten when the source has one
        upsert(Pincode, [r for r in rows if "city" in r], unique_fields=("pincode",))
        upsert(Pincode, [r for r in rows if "city" not in r], unique_fields=("pincode",))
        self.pins = {p.pincode: p for p in Pincode.objects.select_related("state", "asm")}

        # distributor home state = where most of its P1 retailers are (only when not set by an admin)
        votes = defaultdict(Counter)
        for pin, c in p1s.items():
            st = self.pins.get(pin).state if pin in self.pins else None
            if st:
                for raw, n in c.items():
                    d = self.dist(raw)
                    if d:
                        votes[d.id][st.id] += n
        for d in {d.id: d for d in self.dist_by_norm.values()}.values():
            if d.state_id is None and votes.get(d.id):
                d.state_id = votes[d.id].most_common(1)[0][0]
                d.region_id = State.objects.get(id=d.state_id).region_id
                d.save(update_fields=["state", "region", "updated_at"])
        self.stats["pincodes"] = len(rows)

    def state_for_name(self, name):
        code = geo.state_code_for_name(name)
        return self.states.get(code) if code else None

    # ------------------------------------------------------------------ distributors
    def load_distributors(self):
        existing = list(Distributor.objects.all())
        by_src = {d.source_id: d for d in existing if d.source_id}
        by_norm = {}
        for d in existing:
            for alias in [d.name, d.code, *(d.aliases or [])]:
                by_norm.setdefault(norm(alias), d)

        def match(raw):
            n = norm(raw)
            if n in by_norm:
                return by_norm[n]
            pref = {d.id: d for k, d in by_norm.items() if len(k) >= 5 and (k.startswith(n) or n.startswith(k))}
            if len(pref) == 1:
                return next(iter(pref.values()))
            close = difflib.get_close_matches(n, list(by_norm), n=1, cutoff=0.88)
            return by_norm[close[0]] if close else None

        used_codes = set(Distributor.objects.values_list("code", flat=True))
        claimed, created = set(), 0
        self.dist_by_id = {}
        for r in sorted(self.dist_rows, key=lambda r: to_int(r.get("distributor_id"))):
            did, raw = r["distributor_id"].strip(), r.get("distributor_name", "").strip()
            sid = f"td:{did}"
            d = by_src.get(sid) or match(raw)
            if d is not None and d.id in claimed:
                d = None  # two export rows with the same name (e.g. "Ankit Jain") stay separate
            if d is None:
                base = norm(raw).upper()[:10] or "DIST"
                code, i = base, 1
                while code in used_codes:
                    i += 1
                    code = f"{base[:8]}{i:02d}"
                used_codes.add(code)
                d = Distributor(code=code, name=nice_name(raw)[:200])
                created += 1
            d.source_id = sid
            d.aliases = sorted(set(d.aliases or []) | ({raw} if raw and raw != d.name else set()))
            d.city = d.city or nice_name(r.get("city", ""))[:100]
            d.gstin = d.gstin or (r.get("gst_number") or "")[:20]
            d.is_active = to_bool(r.get("is_active")) and not r.get("deleted_at")
            created_at = parse_dt(r.get("created_at", "").replace("Z", ""), UTC)
            d.onboarded_on = d.onboarded_on or (timezone.localtime(created_at, IST).date() if created_at else None)
            if d.state_id is None:  # an admin-set state wins
                st = self.state_for_name(r.get("state"))
                if st:
                    d.state, d.region_id = st, st.region_id
            d.save()
            claimed.add(d.id)
            self.dist_by_id[did] = d
            by_norm.setdefault(norm(raw), d)

        # name lookup used by the customer file ("P1, P2") and stock locations; lowest export id wins a tie
        self.dist_by_norm = {}
        for d in sorted(Distributor.objects.all(), key=lambda d: to_int((d.source_id or "td:9999").split(":")[-1])):
            for alias in [d.name, d.code, *(d.aliases or [])]:
                self.dist_by_norm.setdefault(norm(alias), d)
        self.stats["distributors"] = len(self.dist_by_id)
        self.stats["distributors_created"] = created

    def dist(self, raw):
        """Distributor by any spelling, with a close-match fallback for typos (e.g. 'kumar-enterprieses')."""
        if not raw:
            return None
        n = norm(raw)
        if n in self.dist_by_norm:
            return self.dist_by_norm[n]
        if n not in self._fuzzy:
            close = difflib.get_close_matches(n, list(self.dist_by_norm), n=1, cutoff=0.85)
            self._fuzzy[n] = self.dist_by_norm[close[0]] if close else None
            if not close:
                self.warn(f"distributor '{raw}' matched no distributor")
        return self._fuzzy[n]

    # ------------------------------------------------------------------ products
    def load_products(self):
        cats, prods, ppu = {}, {}, {}
        for r in self.products_rows:
            pid = r["product_id"]
            n = to_int(r.get("pcs_per_unit")) or 1
            ppu.setdefault(pid, n)
            l3 = (r.get("category_level_3") or "").strip()
            if l3:
                cats[slug(l3)] = l3.replace("-", " ").title()
            live = r.get("product_status") == "published" and not to_bool(r.get("is_deleted"))
            if pid not in prods:
                launched = parse_dt((r.get("launch_date") or "").replace("Z", ""), UTC)
                prods[pid] = {
                    "source_id": pid, "style": (r.get("style") or pid)[:32],
                    "name": (r.get("product_title") or r.get("style") or pid)[:200],
                    "category_l1": (r.get("category_level_1") or "")[:100],
                    "category_l2": (r.get("category_level_2") or "")[:100],
                    "category_l3": l3[:100], "pack_size": n,
                    "launched_on": timezone.localtime(launched, IST).date() if launched else None,
                    "is_active": live, "_cat": slug(l3) if l3 else None,
                }
            elif live:
                prods[pid]["is_active"] = True
        self.ppu = ppu
        for code, name in cats.items():
            Category.objects.update_or_create(code=code, defaults={"name": name[:100], "level": 1})
        cat_ids = dict(Category.objects.values_list("code", "id"))
        for p in prods.values():
            p["category_id"] = cat_ids.get(p.pop("_cat"))
        upsert(Product, list(prods.values()))
        self.product_ids = dict(Product.objects.values_list("source_id", "id"))
        self.product_style = dict(Product.objects.values_list("source_id", "style"))

        variants, seen_sku = [], set()
        for r in self.products_rows:
            pid, vid = r["product_id"], r["variant_id"]
            sku = (r.get("sku") or vid)[:64]
            if sku in seen_sku:
                sku = vid[:64]
            seen_sku.add(sku)
            mrp = (to_dec(r.get("price")) / Decimal(ppu[pid])).quantize(TWO, ROUND_HALF_UP)
            variants.append({"source_id": vid, "product_id": self.product_ids[pid], "sku": sku,
                             "size": (r.get("size") or "")[:16], "mrp": mrp,
                             "price": (mrp * WHOLESALE_SHARE).quantize(TWO, ROUND_HALF_UP)})
        ProductVariant.objects.filter(sku__in=[v["sku"] for v in variants]).exclude(
            source_id__in=[v["source_id"] for v in variants]).delete()
        # variants whose SKU changed between exports: park them on their own id so SKUs can swap freely
        new_sku = {v["source_id"]: v["sku"] for v in variants}
        for pk, src, sku in ProductVariant.objects.filter(source_id__in=list(new_sku)).values_list("id", "source_id", "sku"):
            if new_sku[src] != sku:
                ProductVariant.objects.filter(id=pk).update(sku=f"~{src}"[:64])
        for chunk in chunked(variants, 2000):
            upsert(ProductVariant, chunk)
        self.variants = {src: (vid, sku, size) for src, vid, sku, size in ProductVariant.objects
                         .values_list("source_id", "id", "sku", "size")}
        self.stats["products"] = len(prods)
        self.stats["products_live"] = sum(1 for p in prods.values() if p["is_active"])
        self.stats["variants"] = len(variants)
        self.stats["categories"] = len(cats)

    # ------------------------------------------------------------------ retailers
    def load_retailers(self):
        rows = []
        for r in self.customers:
            pin = r.get("ts_pincode", "")
            pm = self.pins.get(pin)
            st = self.state_for_name(r.get("province")) or (pm.state if pm else None)
            parts = [p.strip() for p in (r.get("distributor_name") or "").split(",") if p.strip()]
            d = self.dist(parts[0]) if parts else (pm.distributor_p1 if pm else None)
            owner = " ".join(x for x in (r.get("first_name"), r.get("last_name")) if x).strip()
            kyc = "approved" if to_bool(r.get("kyc")) else "not_submitted"
            created = parse_dt((r.get("created_at") or "").replace("Z", ""), UTC)
            city = (r.get("city") or "").strip().title() or (pm.city if pm else "")
            rows.append({
                "source_id": r["customer_id"],
                "name": (r.get("business_name") or owner or r.get("phone") or r["customer_id"])[:200],
                "owner_name": owner[:200], "phone": (r.get("phone") or "")[:20],
                "email": (r.get("email") or "")[:254], "gstin": (r.get("gst_number") or "")[:20],
                "udyam_number": (r.get("udyam_number") or "")[:32],
                "has_account": to_bool(r.get("has_account")), "pincode": pin[:10], "city": city[:100],
                "state_id": st.id if st else None, "region_id": st.region_id if st else None,
                "asm_id": pm.asm_id if pm else None, "distributor_id": d.id if d else None,
                "kyc_status": kyc, "signed_up_at": created,
                "kyc_submitted_at": created if kyc == "approved" else None,
            })
        for chunk in chunked(rows, 5000):
            upsert(Retailer, chunk)
        self.retailers = {sid: (rid, reg, st, asm, dist) for sid, rid, reg, st, asm, dist in Retailer.objects
                          .values_list("source_id", "id", "region_id", "state_id", "asm_id", "distributor_id")}
        self.stats["retailers"] = len(rows)
        self.stats["retailers_kyc_approved"] = sum(1 for r in rows if r["kyc_status"] == "approved")

    # ------------------------------------------------------------------ orders
    def load_orders(self):
        lines_of = defaultdict(list)
        for r in self.sales_rows:
            lines_of[r["order_key"]].append(r)

        # the ID-keyed export replaces the orders loaded from the earlier sample files
        removed = Order.objects.filter(source_id__startswith="csv:").delete()[0]
        if removed:
            self.say(f"removed {removed} rows loaded from the earlier sample export")

        orders, lines, unknown = [], {}, 0
        for o in self.order_rows:
            oid = o["order_id"]
            day = to_date(o.get("order_date"))
            if not day:
                self.warn(f"order {oid}: no order date, skipped")
                continue
            placed = dt.datetime.combine(day, PLACED_TIME, tzinfo=IST)
            raw = (o.get("ts_order_status") or "").strip().lower()
            status = STATUS_MAP.get(raw, "received")
            shipped_at = end_of_day(to_date(o.get("dispatch_date")), placed)
            delivered_at = end_of_day(to_date(o.get("delivered_date")), shipped_at or placed)
            updated = parse_dt((o.get("updated_at") or "").replace("Z", ""), UTC)
            paid = bool((o.get("mode") or "").strip()) or to_dec(o.get("payu_amount")) > 0
            pay = "captured" if paid else "not_paid"

            ret = self.retailers.get(o.get("customer_id"))
            if ret is None:
                unknown += 1
                st = self.state_for_name(o.get("province"))
                ret = (None, st.region_id if st else None, st.id if st else None, None, None)
            elif ret[2] is None:
                st = self.state_for_name(o.get("province"))
                if st:
                    ret = (ret[0], st.region_id, st.id, ret[3], ret[4])
            d = self.dist_by_id.get((o.get("distributor_id") or "").strip())

            olines, units, value = [], 0, Decimal("0")
            for i in lines_of.get(oid, []):
                pid = i.get("product_id", "")
                v = self.variants.get(i.get("variant_id"))
                boxes, pieces = to_int(i.get("quantity")), to_int(i.get("pieces"))
                amount = to_dec(i.get("line_amount"))
                units += pieces
                value += amount
                olines.append({
                    "source_id": i["sales_id"][:64], "product_id": self.product_ids.get(pid),
                    "variant_id": v[0] if v else None, "style": self.product_style.get(pid, "")[:32],
                    "sku": (v[1] if v else "")[:64], "size": (i.get("size") or "")[:16],
                    "boxes": boxes, "pieces_per_box": (pieces // boxes) if boxes else self.ppu.get(pid, 1),
                    "quantity": pieces,
                    "unit_price": (amount / pieces).quantize(TWO, ROUND_HALF_UP) if pieces else Decimal("0"),
                    "total": amount,
                })
            orders.append({
                "source_id": oid[:64], "display_id": (o.get("display_id") or oid)[:32], "split_group": oid[:64],
                "is_split": False, "retailer_id": ret[0], "region_id": ret[1], "state_id": ret[2],
                "asm_id": ret[3], "distributor_id": d.id if d else ret[4],
                "status": status, "ts_order_status": raw[:32], "payment_status": pay,
                "medusa_payment_status": pay, "payment_status_source": "medusa",
                "payment_mode": (o.get("mode") or "")[:16], "platform": (o.get("platform") or "").lower()[:16],
                "gross_value": value if olines else to_dec(o.get("line_total")),
                "units": units, "placed_at": placed, "placed_date": day,
                "confirmed_at": None, "shipped_at": shipped_at, "delivered_at": delivered_at,
                "cancelled_at": updated if status == "cancelled" else None,
                "is_qualifying": compute_is_qualifying(status, pay), "source_updated_at": updated,
            })
            lines[oid] = olines
        for chunk in chunked(orders, 2000):
            upsert(Order, chunk)
        ids = dict(Order.objects.filter(source_id__in=list(lines)).values_list("source_id", "id"))
        OrderLine.objects.filter(order_id__in=list(ids.values())).delete()
        all_lines = []
        for src, olines in lines.items():
            for li in olines:
                li["order_id"] = ids[src]
                all_lines.append(OrderLine(**li))
        OrderLine.objects.bulk_create(all_lines, batch_size=2000)
        if unknown:
            self.warn(f"{unknown} orders reference customers missing from the customer export")
        span = sorted(o["placed_date"] for o in orders)
        self.stats["orders_period"] = f"{span[0]} to {span[-1]}" if span else ""
        self.stats["orders"] = len(orders)
        self.stats["orders_qualifying"] = sum(1 for o in orders if o["is_qualifying"])
        self.stats["order_lines"] = len(all_lines)

    # ------------------------------------------------------------------ inventory
    def load_inventory(self):
        if not self.inventory_rows:
            return
        synced = getattr(self, "inventory_synced_at", None) or timezone.now()
        qty, snap_dates = defaultdict(int), set()
        meta = {}
        for r in self.inventory_rows:
            d = self.dist_by_id.get((r.get("distributor_id") or "").strip()) or self.dist(r.get("stock_location"))
            v = self.variants.get(r.get("variant_id"))
            if not d or not v:
                continue
            snap_dates.add(r.get("snapshot_date"))
            key = (d.id, v[1])
            qty[key] += to_int(r.get("available"))
            meta[key] = (v[0], v[2])
        snap = self.snapshot_date or max(to_date(s) for s in snap_dates if to_date(s))
        vprod = dict(ProductVariant.objects.values_list("id", "product_id"))
        pstyle = dict(Product.objects.values_list("id", "style"))
        rows = []
        for (did, sku), q in qty.items():
            vid, size = meta[(did, sku)]
            pid = vprod.get(vid)
            rows.append(InventorySnapshot(
                source="td", distributor_id=did, product_id=pid, variant_id=vid, sku=sku,
                style=pstyle.get(pid, "")[:32], size=size, snapshot_date=snap, quantity=q,
                synced_at=synced, is_latest=True))
        InventorySnapshot.objects.filter(source="td", snapshot_date=snap).delete()
        InventorySnapshot.objects.filter(source="td", is_latest=True, snapshot_date__lt=snap).update(is_latest=False)
        if InventorySnapshot.objects.filter(source="td", snapshot_date__gt=snap).exists():
            for o in rows:
                o.is_latest = False
        InventorySnapshot.objects.bulk_create(rows, batch_size=5000)
        self.stats["inventory_rows"] = len(rows)
        self.stats["inventory_in_stock"] = sum(1 for o in rows if o.quantity > 0)
        self.stats["inventory_snapshot_date"] = str(snap)

    # ------------------------------------------------------------------ loyalty
    def load_loyalty(self):
        if not self.loyalty_rows:
            return
        LoyaltyEvent.objects.exclude(source_id__startswith="lpoint_").delete()  # rows from the sample export
        orders = dict(Order.objects.values_list("display_id", "id"))
        rows = []
        for r in self.loyalty_rows:
            day = to_date(r.get("event_date"))
            if day is None:
                self.warn(f"loyalty row {r.get('ledger_id')}: bad date, skipped")
                continue
            label = (r.get("event") or "").strip()
            kind = LOYALTY_KINDS.get(label.lower(), "other")
            ret = self.retailers.get(r.get("customer_id"))
            oref = (r.get("order_id") or "").strip()
            rows.append({
                "source_id": r["ledger_id"][:64], "customer_source_id": (r.get("customer_id") or "")[:64],
                "retailer_id": ret[0] if ret else None, "region_id": ret[1] if ret else None,
                "state_id": ret[2] if ret else None, "asm_id": ret[3] if ret else None,
                "distributor_id": ret[4] if ret else None,
                "order_id": orders.get(oref), "order_display_id": oref[:32],
                "event_type": kind, "event_label": label[:64],
                "points": int(to_dec(r.get("signed_points"))), "event_date": day,
            })
        for chunk in chunked(rows, 5000):
            upsert(LoyaltyEvent, chunk)
        self.stats["loyalty_events"] = len(rows)
