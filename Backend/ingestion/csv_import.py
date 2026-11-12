"""Load the TechnoDirect CSV exports into the warehouse.

Bridge until the live Medusa / API connections are in place. It reads the five exports the
data team shares and upserts them, so it can be re-run with newer files at any time:

    customer   TD_Customer_Data*.csv   id, email, first_name, last_name, phone, has_account, created_at, ...,
                                       gst_number, business_name, ts_pincode, kyc, udyam_number, distributor_name
    product    TD_product*data*.csv    product_id, style, product_title, launch_date, variant_id, size, price,
                                       category_level_1..3
    inventory  TD_Inventory*.csv       Style, Product_id, Size, SKU, Piece Per Unit, Distributor, Stock
    sales      TD_Sales*.csv           one row per order line (order_id, timestamp, Dispatch/Delivered Date, ...)
    loyalty    TD_Loyal*.csv           customer_id, total_points, Event Date, ..., Order Id, Event

What is kept across re-imports (maintained by admins on the Mappings / Targets pages):
regions, a state's region, ASMs, ASM-per-pincode, distributor ASM / state / region once set, targets.

Interpretation of source fields (confirm with the data team; see docs/PLAN.md "CSV import"):
  * customer.distributor_name = "P1, P2" serviceable distributors for the retailer.
  * customer.kyc TRUE -> approved, FALSE -> not submitted (no KYC date in the export).
  * sales.quantity = boxes; pieces = boxes x "Piece Per Unit" from the inventory export.
  * sales.line_item_amount = line total (Rs); total_amount = order total incl. charges (Rs).
  * product.price = MRP per box (Rs). Retailers pay MRP less 40% (true for every line in the sales
    export), so variant.mrp = price / pieces per box and variant.price = mrp x WHOLESALE_SHARE.
  * Every order in the sales export is paid (it has a payment mode); status comes from the
    dispatch / delivered dates.
  * inventory.Stock = boxes on hand per distributor x SKU, as shown in the app.
  * Timestamps are UTC (Medusa default) unless --source-tz says otherwise.
"""
import csv
import datetime as dt
import hashlib
import logging
import os
import re
from collections import Counter, defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
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

from .upsert import chunked, upsert

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

FILE_KEYS = {
    "customer": ("customer",),
    "product": ("product",),
    "inventory": ("inventory",),
    "sales": ("sales",),
    "loyalty": ("loyal",),
}
DATE_FORMATS = ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%Y-%m-%d", "%m/%d/%Y"]
TWO = Decimal("0.01")
WHOLESALE_SHARE = Decimal("0.60")  # selling price / MRP observed on the sales export


# ----------------------------------------------------------------------------- helpers
def find_files(directory):
    """Map each export kind to the largest matching CSV in `directory` (full export beats a sample)."""
    found = {}
    for path in Path(directory).glob("*.csv"):
        name = path.name.lower()
        for kind, words in FILE_KEYS.items():
            if any(w in name for w in words):
                if kind not in found or path.stat().st_size > found[kind].stat().st_size:
                    found[kind] = path
    return found


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            yield {(k or "").strip(): (v or "").strip() for k, v in row.items()}


def norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def nice_name(name):
    name = re.sub(r"\s+", " ", (name or "").strip())
    if name.isupper() or name.islower():
        name = " ".join(w if len(w) <= 2 and w.isupper() else w.capitalize() for w in name.split(" "))
    return name


def parse_dt(value, tz):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            d = dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
        return d.replace(tzinfo=tz)
    raise ValueError(f"Unrecognised date '{value}'")


def parse_ddmmyyyy(value):
    value = (value or "").strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def to_bool(value):
    return (value or "").strip().lower() in ("true", "1", "yes", "y", "t")


def to_dec(value):
    try:
        return Decimal(str(value or "0").replace(",", ""))
    except Exception:
        return Decimal("0")


def to_int(value):
    try:
        return int(float(str(value or "0").replace(",", "")))
    except ValueError:
        return 0


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")[:32] or "uncategorised"


def end_of_day(date_value, not_before):
    """Date-only milestone -> 23:59 IST that day, never before `not_before`."""
    if not date_value:
        return None
    d = dt.datetime.combine(date_value.date() if isinstance(date_value, dt.datetime) else date_value,
                            dt.time(23, 59), tzinfo=IST)
    return max(d, not_before) if not_before else d


# ----------------------------------------------------------------------------- importer
class CsvImporter:
    def __init__(self, directory, source_tz="UTC", snapshot_date=None, stdout=None):
        self.dir = Path(directory)
        self.tz = ZoneInfo(source_tz)
        self.snapshot_date = snapshot_date
        self.out = stdout
        self.files = find_files(self.dir)
        self.stats = {}
        self.warnings = []

    def say(self, msg):
        log.info(msg)
        if self.out:
            self.out.write(f"[import] {msg}")

    def warn(self, msg):
        self.warnings.append(msg)
        self.say(f"WARNING: {msg}")

    # ------------------------------------------------------------------ run
    def run(self):
        missing = [k for k in FILE_KEYS if k not in self.files]
        if missing:
            self.warn(f"no file found for: {', '.join(missing)} (looked in {self.dir})")
        for kind, path in sorted(self.files.items()):
            self.say(f"{kind:<9} <- {path.name}")
        self.customers = list(read_csv(self.files["customer"])) if "customer" in self.files else []
        self.products_rows = list(read_csv(self.files["product"])) if "product" in self.files else []
        self.inventory_rows = list(read_csv(self.files["inventory"])) if "inventory" in self.files else []
        self.sales_rows = list(read_csv(self.files["sales"])) if "sales" in self.files else []
        self.loyalty_rows = list(read_csv(self.files["loyalty"])) if "loyalty" in self.files else []

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
        return {"files": {k: p.name for k, p in self.files.items()}, "rows": self.stats,
                "warnings": self.warnings}

    # ------------------------------------------------------------------ geography
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

        # pincode -> state code; a state named on a sales row beats the PIN-prefix rule
        self.sales_pin_state, self.sales_pin_city = {}, {}
        for r in self.sales_rows:
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

    # ------------------------------------------------------------------ distributors
    def load_distributors(self):
        """One distributor per business, matched across the spellings used by each export."""
        full_names = Counter()
        for r in self.customers:
            for part in (r.get("distributor_name") or "").split(","):
                if part.strip():
                    full_names[part.strip()] += 1
        for r in self.sales_rows:
            if r.get("distributor"):
                full_names[r["distributor"].strip()] += 1
        short_names = {r["Distributor"].strip() for r in self.inventory_rows if r.get("Distributor")}

        existing = list(Distributor.objects.all())
        by_norm = {}
        for d in existing:
            for alias in [d.name, d.code, *(d.aliases or [])]:
                by_norm.setdefault(norm(alias), d)

        groups = {}  # norm(full name) -> set of raw spellings
        for raw in full_names:
            groups.setdefault(norm(raw), set()).add(raw)

        def match_short(short):
            n = norm(short)
            if n in groups:
                return n
            pref = [k for k in groups if k.startswith(n)]
            if len(pref) == 1:
                return pref[0]
            first = norm(short.split()[0]) if short.split() else n
            tok = [k for k in groups if k.startswith(first)]
            return tok[0] if len(tok) == 1 else None

        for short in sorted(short_names):
            key = match_short(short)
            if key is None:
                self.warn(f"inventory distributor '{short}' matched no customer/sales distributor; created as new")
                groups.setdefault(norm(short), set()).add(short)
            else:
                groups[key].add(short)

        used_codes = set(Distributor.objects.values_list("code", flat=True))
        self.dist_by_norm = {}
        created = 0
        for key, spellings in groups.items():
            d = next((by_norm[norm(s)] for s in spellings if norm(s) in by_norm), None)
            longest = max(spellings, key=lambda s: (full_names.get(s, 0), len(s)))
            if d is None:
                base = re.sub(r"[^A-Z0-9]", "", longest.upper())[:10] or "DIST"
                code, i = base, 1
                while code in used_codes:
                    i += 1
                    code = f"{base[:8]}{i:02d}"
                used_codes.add(code)
                d = Distributor.objects.create(code=code, name=nice_name(longest)[:200], source_id=f"name:{key}"[:64])
                created += 1
            d.aliases = sorted(set(d.aliases or []) | {s for s in spellings if s != d.name})
            d.save(update_fields=["aliases", "updated_at"])
            for s in spellings:
                self.dist_by_norm[norm(s)] = d
            self.dist_by_norm[key] = d
        self.stats["distributors"] = len({d.id for d in self.dist_by_norm.values()})
        self.stats["distributors_created"] = created

    def dist(self, raw):
        return self.dist_by_norm.get(norm(raw)) if raw else None

    # ------------------------------------------------------------------ pincodes
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
        for r in self.sales_rows:
            pin = r.get("ts_pincode", "")
            if geo.is_valid_pincode(pin):
                pins.add(pin)
                if r.get("distributor") and not p1s[pin]:
                    p1s[pin][r["distributor"]] += 1

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

    # ------------------------------------------------------------------ products
    def load_products(self):
        ppu, sku_of = {}, {}
        for r in self.inventory_rows:
            pid = r.get("Product_id", "")
            n = to_int(r.get("Piece Per Unit"))
            if pid and n > 0:
                ppu[pid] = n
            if pid and r.get("SKU"):
                sku_of[(pid, r.get("Size", ""))] = r["SKU"]
        self.ppu = ppu

        cats = {}
        prods = {}
        for r in self.products_rows:
            pid = r["product_id"]
            l3 = (r.get("category_level_3") or "").strip()
            if l3:
                cats[slug(l3)] = l3.replace("-", " ").title()
            if pid not in prods:
                launched = parse_dt(r.get("launch_date"), self.tz)
                prods[pid] = {
                    "source_id": pid, "style": (r.get("style") or pid)[:32],
                    "name": (r.get("product_title") or r.get("style") or pid)[:200],
                    "category_l1": (r.get("category_level_1") or "")[:100],
                    "category_l2": (r.get("category_level_2") or "")[:100],
                    "category_l3": l3[:100], "pack_size": ppu.get(pid, 1),
                    "launched_on": timezone.localtime(launched, IST).date() if launched else None,
                    "is_active": True, "_cat": slug(l3) if l3 else None,
                }
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
            pid, size = r["product_id"], (r.get("size") or "")[:16]
            sku = (sku_of.get((pid, r.get("size", ""))) or r["variant_id"])[:64]
            if sku in seen_sku:
                sku = r["variant_id"][:64]
            seen_sku.add(sku)
            mrp = (to_dec(r.get("price")) / Decimal(ppu.get(pid, 1))).quantize(TWO, ROUND_HALF_UP)
            variants.append({"source_id": r["variant_id"], "product_id": self.product_ids[pid], "sku": sku,
                             "size": size, "mrp": mrp,
                             "price": (mrp * WHOLESALE_SHARE).quantize(TWO, ROUND_HALF_UP)})
        # a SKU can move to a different variant id between exports: free it first
        ProductVariant.objects.filter(sku__in=[v["sku"] for v in variants]).exclude(
            source_id__in=[v["source_id"] for v in variants]).delete()
        upsert(ProductVariant, variants)
        self.variant_by_pid_size = {(pid, size): (vid, sku) for vid, pid, size, sku in ProductVariant.objects
                                    .values_list("id", "product__source_id", "size", "sku")}
        self.stats["products"] = len(prods)
        self.stats["variants"] = len(variants)
        self.stats["categories"] = len(cats)

    # ------------------------------------------------------------------ retailers
    def load_retailers(self):
        rows = []
        for r in self.customers:
            pin = r.get("ts_pincode", "")
            pm = self.pins.get(pin)
            st = pm.state if pm else None
            parts = [p.strip() for p in (r.get("distributor_name") or "").split(",") if p.strip()]
            d = self.dist(parts[0]) if parts else (pm.distributor_p1 if pm else None)
            owner = " ".join(x for x in (r.get("first_name"), r.get("last_name")) if x).strip()
            kyc = "approved" if to_bool(r.get("kyc")) else "not_submitted"
            created = parse_dt(r.get("created_at"), self.tz)
            rows.append({
                "source_id": r["id"],
                "name": (r.get("business_name") or owner or r.get("phone") or r["id"])[:200],
                "owner_name": owner[:200], "phone": (r.get("phone") or "")[:20],
                "email": (r.get("email") or "")[:254], "gstin": (r.get("gst_number") or "")[:20],
                "udyam_number": (r.get("udyam_number") or "")[:32],
                "has_account": to_bool(r.get("has_account")), "pincode": pin[:10],
                "city": (pm.city if pm else "")[:100],
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
        by_order = defaultdict(list)
        for r in self.sales_rows:
            if r.get("order_id"):
                by_order[r["order_id"]].append(r)
        orders, lines = [], {}
        unknown_customers = 0
        for oid, items in by_order.items():
            h = items[0]
            placed = parse_dt(h.get("timestamp"), self.tz)
            if placed is None:
                self.warn(f"order {oid}: no timestamp, skipped")
                continue
            dispatch = max((parse_dt(i.get("Dispatch Date"), IST) for i in items if i.get("Dispatch Date")),
                           default=None)
            delivered = max((parse_dt(i.get("Delivered Date"), IST) for i in items if i.get("Delivered Date")),
                            default=None)
            shipped_at = end_of_day(dispatch, placed)
            delivered_at = end_of_day(delivered, shipped_at or placed)
            status = "delivered" if delivered_at else "shipped" if shipped_at else "received"
            ret = self.retailers.get(h.get("id"))
            if ret is None:
                unknown_customers += 1
                pin = h.get("ts_pincode", "")
                st = self.state_for_pin(pin)
                ret = (None, st.region_id if st else None, st.id if st else None, None, None)
            d = self.dist(h.get("distributor"))
            pay = "captured"
            units, olines = 0, []
            for n, i in enumerate(items):
                pid, size = i.get("product_id", ""), i.get("size", "")
                boxes = to_int(i.get("quantity"))
                per_box = self.ppu.get(pid, 1)
                pieces = boxes * per_box
                amount = to_dec(i.get("line_item_amount"))
                variant = self.variant_by_pid_size.get((pid, size[:16]))
                units += pieces
                olines.append({
                    "source_id": f"csv:{oid}:{n}", "product_id": self.product_ids.get(pid),
                    "variant_id": variant[0] if variant else None,
                    "style": (i.get("style") or self.product_style.get(pid, ""))[:32],
                    "sku": (variant[1] if variant else "")[:64], "size": size[:16],
                    "boxes": boxes, "pieces_per_box": per_box, "quantity": pieces,
                    "unit_price": (amount / pieces).quantize(TWO, ROUND_HALF_UP) if pieces else Decimal("0"),
                    "total": amount,
                })
            orders.append({
                "source_id": f"csv:{oid}", "display_id": oid, "split_group": f"csv:{oid}", "is_split": False,
                "retailer_id": ret[0], "region_id": ret[1], "state_id": ret[2], "asm_id": ret[3],
                "distributor_id": d.id if d else ret[4],
                "status": status, "payment_status": pay, "medusa_payment_status": pay,
                "payment_status_source": "medusa", "payment_mode": (h.get("mode") or "")[:16],
                "platform": (h.get("platform") or "").lower()[:16],
                "gross_value": to_dec(h.get("total_amount")), "units": units,
                "placed_at": placed, "placed_date": timezone.localtime(placed, IST).date(),
                "confirmed_at": None, "shipped_at": shipped_at, "delivered_at": delivered_at,
                "is_qualifying": compute_is_qualifying(status, pay), "source_updated_at": placed,
            })
            lines[f"csv:{oid}"] = olines
        upsert(Order, orders)
        ids = dict(Order.objects.filter(source_id__in=list(lines)).values_list("source_id", "id"))
        OrderLine.objects.filter(order_id__in=ids.values()).delete()
        all_lines = []
        for src, olines in lines.items():
            for li in olines:
                li["order_id"] = ids[src]
                all_lines.append(OrderLine(**li))
        OrderLine.objects.bulk_create(all_lines, batch_size=2000)
        if unknown_customers:
            self.warn(f"{unknown_customers} orders reference customers missing from the customer export")
        if self.sales_rows:
            span = sorted(o["placed_date"] for o in orders)
            self.stats["orders_period"] = f"{span[0]} to {span[-1]}" if span else ""
        self.stats["orders"] = len(orders)
        self.stats["order_lines"] = len(all_lines)

    # ------------------------------------------------------------------ inventory
    def load_inventory(self):
        if not self.inventory_rows:
            return
        path = self.files["inventory"]
        synced = dt.datetime.fromtimestamp(os.path.getmtime(path), tz=IST)
        snap = self.snapshot_date or synced.date()
        rows, seen = [], set()
        for r in self.inventory_rows:
            d = self.dist(r.get("Distributor"))
            sku = (r.get("SKU") or "")[:64]
            if not d or not sku or (d.id, sku) in seen:
                continue
            seen.add((d.id, sku))
            pid, size = r.get("Product_id", ""), (r.get("Size") or "")[:16]
            v = self.variant_by_pid_size.get((pid, size))
            rows.append(InventorySnapshot(
                source="td", distributor_id=d.id, product_id=self.product_ids.get(pid),
                variant_id=v[0] if v else None, sku=sku, style=(r.get("Style") or "")[:32], size=size,
                snapshot_date=snap, quantity=to_int(r.get("Stock")), synced_at=synced, is_latest=True))
        InventorySnapshot.objects.filter(source="td", snapshot_date=snap).delete()
        InventorySnapshot.objects.filter(source="td", is_latest=True, snapshot_date__lt=snap).update(is_latest=False)
        if InventorySnapshot.objects.filter(source="td", snapshot_date__gt=snap).exists():
            for o in rows:
                o.is_latest = False
        InventorySnapshot.objects.bulk_create(rows, batch_size=5000)
        self.stats["inventory_rows"] = len(rows)
        self.stats["inventory_snapshot_date"] = str(snap)

    # ------------------------------------------------------------------ loyalty
    def load_loyalty(self):
        if not self.loyalty_rows:
            return
        kinds = {"new customer": "new_customer", "points earned": "earned", "points redeemed": "redeemed"}
        orders = dict(Order.objects.values_list("display_id", "id"))
        seen = Counter()
        rows = []
        for r in self.loyalty_rows:
            label = r.get("Event", "")
            kind = kinds.get(label.strip().lower(), "other")
            pts = abs(to_int(r.get("total_points")))
            day = parse_ddmmyyyy(r.get("Event Date"))
            if day is None:
                self.warn(f"loyalty row for {r.get('customer_id')}: bad date '{r.get('Event Date')}', skipped")
                continue
            base = "|".join([r.get("customer_id", ""), str(day), label, str(pts), r.get("Order Id", "")])
            seen[base] += 1
            sid = hashlib.sha1(f"{base}|{seen[base]}".encode()).hexdigest()[:40]
            ret = self.retailers.get(r.get("customer_id"))
            rows.append({
                "source_id": sid, "customer_source_id": r.get("customer_id", "")[:64],
                "retailer_id": ret[0] if ret else None, "region_id": ret[1] if ret else None,
                "state_id": ret[2] if ret else None, "asm_id": ret[3] if ret else None,
                "distributor_id": ret[4] if ret else None,
                "order_id": orders.get(r.get("Order Id")), "order_display_id": (r.get("Order Id") or "")[:32],
                "event_type": kind, "event_label": label[:64],
                "points": -pts if kind == "redeemed" else pts, "event_date": day,
            })
        upsert(LoyaltyEvent, rows)
        self.stats["loyalty_events"] = len(rows)
