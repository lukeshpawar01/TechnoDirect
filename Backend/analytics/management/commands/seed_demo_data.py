"""Generate realistic synthetic TechnoDirect data so the dashboard is demoable before real creds.

Shape (from the strategic deck): Dec-2024 launch, monthly sales ~₹12L -> ~₹3Cr, AOV ₹15k -> ₹41k,
35 distributors (Heera Exports ~37% share), Karnataka-led state mix, ~13k KYC-approved retailers with
~2.4k ordering, retention / reactivation, split carts, PayU transactions, CK stock, CRM tickets, targets.

    python manage.py seed_demo_data            # wipes warehouse demo data and regenerates
    python manage.py seed_demo_data --seed 7   # different random universe
"""
import calendar
import datetime as dt
import math
import random
from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import PERMISSION_CODES, Role, User
from analytics.derivations import run_all_derivations
from analytics.filters import add_months, month_start
from ingestion.models import SyncRun, SyncWatermark
from ingestion.schedule import REFRESH_SOURCE
from masters.models import ReconciliationRef, ensure_default_metrics
from warehouse.models import (
    Asm,
    Category,
    CrmTicket,
    DataQualityIssue,
    Distributor,
    InventorySnapshot,
    Order,
    OrderLine,
    Payment,
    Pincode,
    Product,
    ProductVariant,
    Region,
    Retailer,
    RetailerMonth,
    State,
    Target,
    compute_is_qualifying,
)

D = lambda x: Decimal(str(round(x, 2)))  # noqa: E731

REGIONS = [("SOUTH1", "South 1 (Karnataka)"), ("SOUTH2", "South 2 (Telugu States)"), ("EAST", "East"),
           ("SOUTH3", "South 3 (TN & Kerala)"), ("WEST", "West")]
# code, name, region, retailer share, ordering share, pin prefixes, cities
STATES = [
    ("KA", "Karnataka", "SOUTH1", .35, .44, range(560, 592), ["Bengaluru", "Mysuru", "Hubballi", "Mangaluru", "Belagavi", "Davanagere"]),
    ("TS", "Telangana", "SOUTH2", .17, .17, range(500, 510), ["Hyderabad", "Warangal", "Karimnagar", "Nizamabad"]),
    ("AP", "Andhra Pradesh", "SOUTH2", .15, .15, range(515, 536), ["Vijayawada", "Visakhapatnam", "Guntur", "Tirupati", "Nellore"]),
    ("OD", "Odisha", "EAST", .12, .12, range(751, 771), ["Bhubaneswar", "Cuttack", "Rourkela", "Berhampur"]),
    ("TN", "Tamil Nadu", "SOUTH3", .07, .06, range(600, 644), ["Chennai", "Coimbatore", "Madurai", "Salem"]),
    ("KL", "Kerala", "SOUTH3", .04, .04, range(670, 696), ["Kochi", "Kozhikode", "Thrissur"]),
    ("MH", "Maharashtra", "WEST", .04, .03, range(400, 446), ["Pune", "Nagpur", "Kolhapur"]),
    ("WB", "West Bengal", "EAST", .02, .01, range(700, 744), ["Kolkata", "Howrah", "Siliguri"]),
    ("CG", "Chhattisgarh", "EAST", .02, .01, range(490, 498), ["Raipur", "Bhilai"]),
    ("GA", "Goa", "WEST", .02, .01, range(403, 404), ["Panaji", "Margao"]),
]
ASMS = [("ASM01", "Ravi Kumar", ["KA"]), ("ASM02", "Suresh Gowda", ["KA"]), ("ASM03", "Manjunath H", ["KA"]),
        ("ASM04", "Prakash Shetty", ["KA"]), ("ASM05", "Srinivas Reddy", ["TS"]), ("ASM06", "Venkat Rao", ["TS"]),
        ("ASM07", "Naidu P", ["AP"]), ("ASM08", "Kiran Varma", ["AP"]), ("ASM09", "Sanjay Mohanty", ["OD"]),
        ("ASM10", "Bibhu Das", ["OD"]), ("ASM11", "Karthik S", ["TN"]), ("ASM12", "Anoop Nair", ["KL"]),
        ("ASM13", "Amit Patil", ["MH", "GA"]), ("ASM14", "Sourav Ghosh", ["WB", "CG"])]
# state -> [(name, weight as P1)]
DISTRIBUTORS = {
    "KA": [("Heera Exports", .93), ("Zealous Sportswear", .03), ("Kaveri Sports Agencies", .01),
           ("Mysore Hosiery House", .01), ("Hubli Garments Hub", .01), ("Bangalore Sports Link", .01)],
    "TS": [("Om Sri Satnam Traders", .55), ("Deccan Apparel Distributors", .2), ("Charminar Sports", .12),
           ("Warangal Textiles", .08), ("Nizam Apparel", .05)],
    "AP": [("Virat Sports", .5), ("Godavari Garments", .18), ("Vijaya Sports Agencies", .12),
           ("Krishna Hosiery", .1), ("Tirupati Traders", .06), ("Vizag Sports Hub", .04)],
    "OD": [("Anand Sports", .55), ("Kalinga Sportswear", .2), ("Jagannath Enterprises", .12),
           ("Cuttack Cloth House", .08), ("Puri Hosiery", .05)],
    "TN": [("Chennai Active Wear", .5), ("Kovai Knit Distributors", .3), ("Madurai Sports Mart", .2)],
    "KL": [("Malabar Sports", .6), ("Kochi Apparel Co", .4)],
    "MH": [("Sahyadri Sportswear", .5), ("Pune Fitwear Distributors", .3), ("Nagpur Garments", .2)],
    "WB": [("Bengal Sports Emporium", .6), ("Howrah Hosiery", .4)],
    "CG": [("Raipur Sports House", .6), ("Bhilai Garments", .4)],
    "GA": [("Goa Coastal Traders", 1.0)],
}
CATEGORIES = [("TSH", "T-Shirts", .38), ("TRK", "Track Pants", .22), ("SHO", "Shorts", .14),
              ("JKT", "Jackets & Sweatshirts", .10), ("WMN", "Women's Activewear", .09), ("KID", "Kids", .07)]
def demo_tree(code, name):
    """Category I / II / III for demo products, mirroring the app's Men/Women/Kids > topwear/bottomwear tree."""
    n = name.lower()
    if code == "TSH":
        return "men", "topwear", "gym-vests" if "vest" in n else "t-shirts"
    if code == "TRK":
        return "men", "bottomwear", "joggers" if "jogger" in n else ("trousers" if "cargo" in n else "trackpants")
    if code == "SHO":
        return "men", "bottomwear", "shorts"
    if code == "JKT":
        return "men", "topwear", "jackets"
    if code == "WMN":
        if "bra" in n or "tee" in n:
            return "women", "topwear", "sports-bra" if "bra" in n else "t-shirts"
        return "women", "bottomwear", "tights"
    if "tee" in n:
        return "kids", "topwear", "t-shirts"
    return "kids", "bottomwear", "shorts" if "short" in n else "trackpants"


NAMED_STYLES = [("OR99", "TSH", "Round Neck Dri-Fit Tee"), ("OR89", "TSH", "Polo Performance Tee"),
                ("OR25", "TRK", "Classic Track Pant"), ("OR675", "TRK", "Slim Fit Jogger"),
                ("OR41", "SHO", "Running Shorts"), ("OR52", "TSH", "Sleeveless Gym Vest"),
                ("OR110", "JKT", "Zipper Track Jacket"), ("OR77", "WMN", "Women's Leggings"),
                ("OR305", "TSH", "Henley Tee"), ("OR18", "KID", "Kids Sports Tee"),
                ("OR250", "SHO", "Bermuda Shorts"), ("OR64", "JKT", "Hooded Sweatshirt")]
ADULT_SIZES, KID_SIZES = ["S", "M", "L", "XL", "XXL"], ["26", "28", "30", "32", "34"]
SHOP_A = ["Sri", "New", "Royal", "Classic", "Lakshmi", "Balaji", "Venkateshwara", "Om", "Sai", "Ganesh", "Star",
          "Fashion", "Trendz", "Kumar", "Raj", "Krishna", "Durga", "Ambika", "City", "Super", "Metro", "Jai"]
SHOP_B = ["Garments", "Textiles", "Sports", "Fashions", "Readymades", "Collections", "Hosiery", "Cloth Centre",
          "Dresses", "Apparels", "Sports World", "Men's Wear", "Family Store", "Traders"]
FIRST = ["Ramesh", "Suresh", "Mahesh", "Ganesh", "Lakshmi", "Priya", "Anil", "Sunil", "Vijay", "Ajay", "Kiran",
         "Raju", "Srinivas", "Venkat", "Manoj", "Deepak", "Arun", "Prasad", "Mohan", "Sita", "Kavya", "Naveen"]
LAST = ["Reddy", "Rao", "Gowda", "Shetty", "Naidu", "Patil", "Das", "Mohanty", "Nair", "Kumar", "Sharma", "Jain"]
CRM_TYPES = [("Delivery delay", .3), ("Short supply", .15), ("Wrong item", .12), ("Damaged goods", .1),
             ("Payment issue", .12), ("Return request", .08), ("App issue", .08), ("Pricing query", .05)]
PAY_MODES = [("UPI", .55), ("NB", .15), ("CC", .12), ("DC", .10), ("BNPL", .08)]
BANKS = {"UPI": ["PhonePe", "GPay", "Paytm", "BHIM"], "NB": ["HDFC", "SBI", "ICICI", "Axis", "Canara"],
         "CC": ["HDFC", "ICICI", "SBI Card", "Axis"], "DC": ["SBI", "HDFC", "Canara", "Union"],
         "BNPL": ["LazyPay", "Simpl", "ZestMoney"]}


def wchoice(rng, items, weights):
    return rng.choices(items, weights=weights, k=1)[0]


class Command(BaseCommand):
    help = "Wipe warehouse data and generate realistic synthetic demo data."

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--no-derive", action="store_true")

    def log(self, msg):
        self.stdout.write(f"[seed] {msg}")

    def handle(self, *args, **opts):
        self.rng = random.Random(opts["seed"])
        self.now = timezone.now()
        self.today = timezone.localdate()
        with transaction.atomic():
            self.wipe()
            self.geo()
            self.products()
            self.retailers()
        with transaction.atomic():
            self.orders()
        with transaction.atomic():
            self.inventory()
            self.crm()
            self.targets()
            self.reconciliation()
            self.roles_and_users()
            self.sync_runs()
        ensure_default_metrics()
        if not opts["no_derive"]:
            self.log("running derivations (retailer months, DQ checks)...")
            self.log(str(run_all_derivations()))
        self.log("done.")

    # ------------------------------------------------------------------ wipe
    def wipe(self):
        for m in [DataQualityIssue, RetailerMonth, Payment, OrderLine, CrmTicket, Order, InventorySnapshot,
                  Target, ReconciliationRef, Retailer, Pincode, ProductVariant, Product, Category]:
            m.objects.all().delete()
        for u in User.objects.all():
            u.scope_regions.clear(), u.scope_states.clear(), u.scope_asms.clear(), u.scope_distributors.clear()
        for m in [Distributor, Asm, State, Region, SyncRun, SyncWatermark]:
            m.objects.all().delete()
        self.log("wiped warehouse tables")

    # ------------------------------------------------------------------ geography
    def geo(self):
        rng = self.rng
        self.regions = {c: Region.objects.create(code=c, name=n) for c, n in REGIONS}
        self.states = {}
        for code, name, reg, *_ in STATES:
            self.states[code] = State.objects.create(code=code, name=name, region=self.regions[reg])
        self.asms_by_state = defaultdict(list)
        for code, name, sts in ASMS:
            a = Asm.objects.create(code=code, name=name, region=self.states[sts[0]].region,
                                   email=f"{name.split()[0].lower()}@technosport.example", phone=f"98{rng.randint(10**7, 10**8 - 1)}")
            for s in sts:
                self.asms_by_state[s].append(a)
        self.dists_by_state = defaultdict(list)
        n = 0
        for st, items in DISTRIBUTORS.items():
            for name, w in items:
                n += 1
                state = self.states[st]
                city = rng.choice(next(s[6] for s in STATES if s[0] == st))
                code = "".join(ch for ch in name.upper() if ch.isalpha())[:8] + f"{n:02d}"
                d = Distributor.objects.create(
                    source_id=f"dist_{n:03d}", code=code, name=name, state=state, region=state.region,
                    asm=rng.choice(self.asms_by_state[st]), city=city,
                    gstin=f"{rng.randint(10, 37)}ABCDE{rng.randint(1000, 9999)}F1Z{rng.randint(1, 9)}",
                    ck_code="" if name in ("Goa Coastal Traders", "Bhilai Garments") else f"CK{n:03d}",
                    onboarded_on=dt.date(2024, 11, 15) + dt.timedelta(days=rng.randint(0, 200)))
                self.dists_by_state[st].append((d, w))
        self.heera = Distributor.objects.get(name="Heera Exports")
        # pincodes
        self.pins_by_state = defaultdict(list)
        pins = []
        used = set()
        for code, name, reg, rshare, oshare, prefixes, cities in STATES:
            for _ in range(max(30, int(1500 * rshare))):
                while True:
                    pc = f"{rng.choice(list(prefixes))}{rng.randint(0, 999):03d}"
                    if pc not in used:
                        used.add(pc)
                        break
                ds = self.dists_by_state[code]
                p1 = wchoice(rng, [d for d, _ in ds], [w for _, w in ds])
                others = [d for d, _ in ds if d != p1]
                p2 = rng.choice(others) if others and rng.random() < 0.5 else None
                pins.append(Pincode(pincode=pc, state=self.states[code], city=rng.choice(cities),
                                    district=rng.choice(cities), asm=None if rng.random() < 0.03 else rng.choice(self.asms_by_state[code]),
                                    distributor_p1=p1, distributor_p2=p2))
        Pincode.objects.bulk_create(pins, batch_size=1000)
        for p in Pincode.objects.select_related("state", "asm", "distributor_p1", "distributor_p2"):
            self.pins_by_state[p.state.code].append(p)
        self.log(f"geo: {len(self.regions)} regions, {len(self.states)} states, {Asm.objects.count()} ASMs, "
                 f"{Distributor.objects.count()} distributors, {len(pins)} pincodes")

    # ------------------------------------------------------------------ products
    def products(self):
        rng = self.rng
        cats = {c: Category.objects.create(code=c, name=n, level=1) for c, n, _ in CATEGORIES}
        styles = list(NAMED_STYLES)
        taken = {s for s, _, _ in styles}
        names = {"TSH": ["Crew Tee", "V-Neck Tee", "Raglan Tee", "Training Tee", "Printed Tee"],
                 "TRK": ["Track Pant", "Jogger", "Training Pant", "Cargo Track"],
                 "SHO": ["Shorts", "Gym Shorts", "Board Shorts"],
                 "JKT": ["Windcheater", "Sweatshirt", "Puffer Jacket"],
                 "WMN": ["Sports Bra", "Capri", "Women's Tee", "Women's Jogger"],
                 "KID": ["Kids Shorts", "Kids Track Pant", "Kids Tee"]}
        while len(styles) < 120:
            num = rng.randint(10, 999)
            s = f"OR{num}"
            if s in taken:
                continue
            taken.add(s)
            c = wchoice(rng, [c for c, _, _ in CATEGORIES], [w for _, _, w in CATEGORIES])
            styles.append((s, c, rng.choice(names[c])))
        self.styles = []
        variants = []
        for rank, (s, c, nm) in enumerate(styles):
            recent = rank >= 100  # last 20 are recent launches
            launched = (self.today - dt.timedelta(days=rng.randint(10, 110))) if recent else (
                dt.date(2024, 11, 20) + dt.timedelta(days=rng.randint(0, 210)))
            l1, l2, l3 = demo_tree(c, nm)
            p = Product.objects.create(source_id=f"prod_{rank:03d}", style=s, name=nm, category=cats[c],
                                       category_l1=l1, category_l2=l2, category_l3=l3,
                                       pack_size=12 if c == "KID" else 10,
                                       launched_on=launched, is_important=rank < 12)
            price = rng.uniform(190, 320) if c in ("TSH", "SHO", "KID") else rng.uniform(300, 600)
            sizes = KID_SIZES if c == "KID" else ADULT_SIZES
            pv = []
            for sz in sizes:
                v = ProductVariant(source_id=f"var_{s}_{sz}", product=p, sku=f"{s}-{sz}", size=sz,
                                   price=D(price), mrp=D(price * 2.2))
                pv.append(v)
            variants += pv
            weight = 1.0 / ((rank + 1) ** 0.85)
            if recent:
                weight *= 0.6
            self.styles.append({"product": p, "weight": weight, "price": price, "sizes": sizes,
                                "launched": launched})
        ProductVariant.objects.bulk_create(variants, batch_size=1000)
        vmap = {v.sku: v for v in ProductVariant.objects.all()}
        for s in self.styles:
            s["variants"] = [vmap[f"{s['product'].style}-{sz}"] for sz in s["sizes"]]
        self.log(f"products: {len(self.styles)} styles, {len(variants)} variants")

    # ------------------------------------------------------------------ retailers
    def retailers(self):
        rng = self.rng
        total = 16000
        launch = dt.datetime(2024, 10, 20)
        span = (dt.datetime.combine(self.today, dt.time()) - launch).total_seconds()
        objs = []
        phones = []
        st_codes = [s[0] for s in STATES]
        st_w = [s[3] for s in STATES]
        for i in range(total):
            st = wchoice(rng, st_codes, st_w)
            state = self.states[st]
            # signups accelerate over time (sqrt distribution)
            signed = timezone.make_aware(launch + dt.timedelta(seconds=span * (rng.random() ** 0.8)))
            r = rng.random()
            kyc = "approved" if r < 0.816 else "pending" if r < 0.916 else "rejected" if r < 0.957 else "not_submitted"
            sub = signed + dt.timedelta(hours=rng.randint(1, 120)) if kyc != "not_submitted" else None
            appr = sub + dt.timedelta(hours=rng.randint(12, 240)) if kyc == "approved" else None
            if appr and appr > self.now:
                appr = self.now - dt.timedelta(hours=1)
            x = rng.random()
            if x < 0.02:  # unmapped (valid but not in master)
                pin = f"{rng.choice(list(next(s[5] for s in STATES if s[0] == st)))}{rng.randint(0, 999):03d}"
                pm = None
            elif x < 0.025:  # invalid
                pin = rng.choice(["0" + str(rng.randint(10000, 99999)), str(rng.randint(10000, 99999)), ""])
                pm = None
            else:
                pm = rng.choice(self.pins_by_state[st])
                pin = pm.pincode
            if pm is not None and pm.pincode != pin:
                pm = None
            if i > 50 and rng.random() < 0.003:
                phone = rng.choice(phones)  # duplicate phone
            else:
                phone = f"{rng.choice('6789')}{rng.randint(10**8, 10**9 - 1)}"
            phones.append(phone)
            gst = (f"{rng.randint(10, 37)}{''.join(rng.choice('ABCDEFGHJKLMNPQRSTUVWXYZ') for _ in range(5))}"
                   f"{rng.randint(1000, 9999)}{rng.choice('ABCDEFGH')}1Z{rng.randint(1, 9)}") if rng.random() < 0.6 else ""
            owner = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            city = pm.city if pm else rng.choice(next(s[6] for s in STATES if s[0] == st))
            objs.append(Retailer(
                source_id=f"cus_{i:05d}", name=f"{rng.choice(SHOP_A)} {rng.choice(SHOP_B)}" + (
                    f" {city}" if rng.random() < 0.3 else ""),
                owner_name=owner, phone=phone, email=f"{owner.split()[0].lower()}{i}@example.com" if rng.random() < 0.5 else "",
                gstin=gst, pincode=pin, city=city, state=state, region=state.region,
                asm=pm.asm if pm else None, distributor=pm.distributor_p1 if pm else None,
                kyc_status=kyc, signed_up_at=signed, kyc_submitted_at=sub, kyc_approved_at=appr,
                warm_match=rng.random() < 0.35, tier=rng.choice(["A", "B", "B", "C", "C", "C"]),
            ))
        # a few duplicate GSTINs
        for k in range(12):
            a, b = rng.sample(range(total), 2)
            if objs[a].gstin:
                objs[b].gstin = objs[a].gstin
        Retailer.objects.bulk_create(objs, batch_size=2000)
        self.retailer_list = list(Retailer.objects.select_related("state", "distributor").filter(kyc_status="approved"))
        self.pin_lookup = {p.pincode: p for ps in self.pins_by_state.values() for p in ps}
        self.log(f"retailers: {total} ({len(self.retailer_list)} KYC approved)")

    # ------------------------------------------------------------------ orders
    def month_targets(self):
        first = dt.date(2024, 12, 1)
        months = []
        m = first
        while m <= month_start(self.today):
            months.append(m)
            m = add_months(m, 1)
        g = (300 / 12) ** (1 / 22)
        out = []
        season = {10: 1.10, 11: 1.03, 3: 1.05, 6: 0.93, 7: 0.95}
        for i, m in enumerate(months):
            sales = 12e5 * (g ** min(i, 22)) * (1.03 ** max(0, i - 22)) * season.get(m.month, 1.0)
            aov = 15000 + (41000 - 15000) * (min(i, 22) / 22) ** 1.3
            last_day = calendar.monthrange(m.year, m.month)[1]
            days = last_day
            if m == month_start(self.today):
                days = self.today.day
                sales *= days / last_day
            out.append((m, sales, aov, days))
        return out

    def orders(self):
        rng = self.rng
        st_codes = [s[0] for s in STATES]
        o_w = dict((s[0], s[4]) for s in STATES)
        by_state = defaultdict(list)
        for r in self.retailer_list:
            by_state[r.state.code].append(r)
        for lst in by_state.values():
            lst.sort(key=lambda r: r.kyc_approved_at)
        ret_by_id = {r.id: r for r in self.retailer_list}
        ever, prev_active, lapsed = set(), set(), set()
        orders, lines, payments = [], [], []
        cart_no, disp_no, pay_no = 0, 1000, 0
        no_payu_left = 5
        style_w = [s["weight"] for s in self.styles]
        for idx, (m, target_sales, aov, days) in enumerate(self.month_targets()):
            month_end_dt = timezone.make_aware(dt.datetime.combine(m + dt.timedelta(days=days - 1), dt.time(23, 59)))
            n_carts = max(20, int(target_sales / aov))
            opr = 1.15 + 0.15 * min(idx, 22) / 22
            n_active = max(15, int(n_carts / opr))
            frac = days / calendar.monthrange(m.year, m.month)[1]  # partial current month
            keep_p = (0.32 + 0.12 * min(idx, 22) / 22) * (0.55 + 0.45 * frac)
            retained = {r for r in prev_active if rng.random() < keep_p}
            react = {r for r in lapsed if rng.random() < 0.065 * frac}
            active = retained | react
            need = max(0, n_active - len(active))
            tries = 0
            while need > 0 and tries < need * 20:
                tries += 1
                st = wchoice(rng, st_codes, [o_w[c] for c in st_codes])
                pool = by_state[st]
                if not pool:
                    continue
                r = pool[rng.randint(0, len(pool) - 1)]
                if r.id in ever or r.kyc_approved_at > month_end_dt:
                    continue
                active.add(r.id)
                ever.add(r.id)
                need -= 1
            if len(active) > n_active * 1.15:
                active = set(rng.sample(sorted(active), int(n_active * 1.15)))
            lapsed = (lapsed | prev_active) - active
            prev_active = active
            carts = []
            for rid in active:
                k = 1 if rng.random() < 0.8 else (2 if rng.random() < 0.75 else 3)
                for _ in range(k):
                    carts.append((rid, aov * math.exp(rng.gauss(0, 0.45))))
            scale = target_sales / sum(v for _, v in carts)
            for rid, val in carts:
                r = ret_by_id[rid]
                cart_no += 1
                value = val * scale
                day = rng.randint(1, days)
                placed = timezone.make_aware(dt.datetime.combine(m.replace(day=day), dt.time(rng.randint(8, 21), rng.randint(0, 59))))
                if placed > self.now:
                    placed = self.now - dt.timedelta(minutes=rng.randint(5, 600))
                if r.kyc_approved_at and placed < r.kyc_approved_at:
                    placed = min(r.kyc_approved_at + dt.timedelta(hours=rng.randint(2, 48)), self.now - dt.timedelta(minutes=5))
                pm = self.pin_lookup.get(r.pincode)
                ds = self.dists_by_state[r.state.code]
                p1 = r.distributor or wchoice(rng, [d for d, _ in ds], [w for _, w in ds])
                split = rng.random() < 0.07
                parts = [(p1, 1.0)]
                if split:
                    p2 = (pm.distributor_p2 if pm and pm.distributor_p2 else None) or rng.choice([d for d, _ in ds])
                    if p2 != p1:
                        parts = [(p1, 0.55), (p2, 0.45)]
                cart_id = f"cart_{cart_no:06d}"
                txnid = f"TD{cart_no:07d}"
                age_h = (self.now - placed).total_seconds() / 3600
                cancelled = rng.random() < 0.04
                unpaid = (not cancelled) and rng.random() < 0.015
                abandoned = unpaid and age_h > 72  # abandoned unpaid carts get auto-cancelled
                if abandoned:
                    unpaid, cancelled = False, True
                skip_payu = False
                if not cancelled and not unpaid and no_payu_left and idx >= 20 and rng.random() < 0.01:
                    skip_payu, no_payu_left = True, no_payu_left - 1
                cart_total = 0.0
                for dist, frac in parts:
                    disp_no += 1
                    sub_target = value * frac / 1.05
                    oid = f"order_{disp_no}"
                    sub, units, olines = 0.0, 0, []
                    while sub < sub_target * 0.97:
                        s = self.styles[rng.choices(range(len(self.styles)), weights=style_w)[0]]
                        if s["launched"] > placed.date():
                            continue
                        v = rng.choice(s["variants"])
                        qty = s["product"].pack_size * rng.randint(1, 3)
                        price = float(v.price)
                        olines.append(OrderLine(source_id=f"li_{disp_no}_{len(olines)}", product=s["product"], variant=v,
                                                style=s["product"].style, sku=v.sku, size=v.size, quantity=qty,
                                                unit_price=D(price), total=D(qty * price)))
                        sub += qty * price
                        units += qty
                    gross = sub * 1.05
                    cart_total += gross
                    # lifecycle
                    sla_slow = 1.6 if dist.name in ("Hubli Garments Hub", "Puri Hosiery", "Nagpur Garments") else 1.0
                    conf = placed + dt.timedelta(hours=rng.uniform(0.5, 8))
                    ship = conf + dt.timedelta(hours=rng.uniform(14, 52) * sla_slow)
                    deliv = ship + dt.timedelta(hours=rng.uniform(40, 140))
                    stuck = age_h < 240 and rng.random() < 0.04
                    if cancelled:
                        status, conf_at, ship_at, del_at = "cancelled", None, None, None
                        canc = placed + dt.timedelta(hours=rng.uniform(1, 30))
                    else:
                        canc = None
                        conf_at = conf if conf < self.now and not unpaid else None
                        ship_at = ship if ship < self.now and conf_at and not stuck else None
                        del_at = deliv if deliv < self.now and ship_at and rng.random() < 0.97 else None
                        status = ("delivered" if del_at else "shipped" if ship_at else "confirmed" if conf_at else "received")
                    pay = ("not_paid" if abandoned else "refunded") if cancelled else (
                        "awaiting" if unpaid else "captured")
                    orders.append(Order(
                        source_id=oid, display_id=str(disp_no), split_group=cart_id, is_split=len(parts) > 1,
                        payment_ref=txnid, retailer_id=r.id, distributor=dist, region_id=r.region_id,
                        state_id=r.state_id, asm_id=r.asm_id, status=status, payment_status=pay,
                        medusa_payment_status=pay, gross_value=D(gross), units=units, placed_at=placed,
                        placed_date=timezone.localtime(placed).date(), confirmed_at=conf_at, shipped_at=ship_at,
                        delivered_at=del_at, cancelled_at=canc,
                        awb=f"AWB{rng.randint(10**9, 10**10 - 1)}" if ship_at else "",
                        courier=rng.choice(["Delhivery", "DTDC", "Bluedart", "XpressBees"]) if ship_at else "",
                        is_qualifying=compute_is_qualifying(status, pay), source_updated_at=placed))
                    for li in olines:
                        li._order_source = oid
                    lines += olines
                # PayU transactions for the cart
                if skip_payu:
                    continue
                mode = wchoice(rng, [p for p, _ in PAY_MODES], [w for _, w in PAY_MODES])
                if rng.random() < 0.12:
                    pay_no += 1
                    fm = wchoice(rng, [p for p, _ in PAY_MODES], [w for _, w in PAY_MODES])
                    payments.append(Payment(
                        source_id=f"{14000000000 + pay_no}", txnid=f"{txnid}F", order_ref=cart_id, amount=D(cart_total),
                        status=rng.choice(["failure", "failure", "userCancelled"]), mode=fm, bank=rng.choice(BANKS[fm]),
                        added_on=placed - dt.timedelta(minutes=rng.randint(2, 20)),
                        error_message=rng.choice(["Transaction declined by bank", "OTP timeout", "Insufficient funds",
                                                  "User cancelled"])))
                pay_no += 1
                payments.append(Payment(
                    source_id=f"{14000000000 + pay_no}", txnid=txnid, order_ref=cart_id, amount=D(cart_total),
                    status="pending" if unpaid else ("userCancelled" if abandoned else "success"), mode=mode,
                    bank=rng.choice(BANKS[mode]),
                    added_on=placed - dt.timedelta(minutes=1)))
        # PayU successes with no Medusa order (DQ demo)
        for k in range(8):
            pay_no += 1
            payments.append(Payment(source_id=f"{14000000000 + pay_no}", txnid=f"TDX{k:05d}", order_ref=f"cart_x{k}",
                                    amount=D(rng.uniform(8000, 60000)), status="success", mode="UPI", bank="PhonePe",
                                    added_on=self.now - dt.timedelta(days=rng.randint(1, 20))))
        Order.objects.bulk_create(orders, batch_size=2000)
        oid_map = dict(Order.objects.values_list("source_id", "id"))
        for li in lines:
            li.order_id = oid_map[li._order_source]
        OrderLine.objects.bulk_create(lines, batch_size=5000)
        Payment.objects.bulk_create(payments, batch_size=2000)
        self.log(f"orders: {len(orders)} orders in {cart_no} carts, {len(lines)} lines, {len(payments)} PayU txns, "
                 f"{len(ever)} ordering retailers")

    # ------------------------------------------------------------------ inventory
    def inventory(self):
        rng = self.rng
        top = sorted(self.styles, key=lambda s: -s["weight"])
        rows = []
        stale = {"Kochi Apparel Co": 3, "Howrah Hosiery": 2, "Warangal Textiles": 2}
        for st, items in self.dists_by_state.items():
            for d, w in items:
                if not d.ck_code:
                    continue
                n_styles = 70 if w > 0.4 else 40
                lag = stale.get(d.name, 0)
                for back in (1, 0):
                    snap_day = self.today - dt.timedelta(days=lag + back)
                    synced = timezone.make_aware(dt.datetime.combine(snap_day, dt.time(10, rng.randint(0, 30))))
                    if synced > self.now:
                        synced = self.now - dt.timedelta(minutes=30)
                    rr = random.Random(hash((d.id, back)) & 0xffffffff)
                    for s in top[:n_styles]:
                        for v in s["variants"]:
                            x = rr.random()
                            qty = 0 if x < 0.07 else rr.randint(1, 5) if x < 0.15 else rr.randint(6, 160)
                            rows.append(InventorySnapshot(
                                distributor=d, product=s["product"], variant=v, sku=v.sku, style=s["product"].style,
                                size=v.size, snapshot_date=snap_day, quantity=qty, synced_at=synced,
                                is_latest=(back == 0)))
        InventorySnapshot.objects.bulk_create(rows, batch_size=5000)
        self.log(f"inventory: {len(rows)} snapshot rows")

    # ------------------------------------------------------------------ crm
    def crm(self):
        rng = self.rng
        recent_orders = list(Order.objects.filter(placed_date__gte=self.today - dt.timedelta(days=365)).values(
            "id", "retailer_id", "distributor_id", "state_id", "region_id", "asm_id", "placed_at"))
        rows = []
        for i in range(480):
            o = rng.choice(recent_orders)
            opened = o["placed_at"] + dt.timedelta(hours=rng.randint(6, 240))
            if opened > self.now:
                opened = self.now - dt.timedelta(hours=rng.randint(1, 48))
            age_d = (self.now - opened).days
            closed = None
            status = "open"
            if age_d > 10 or rng.random() < 0.6:
                status = "closed"
                closed = min(opened + dt.timedelta(hours=rng.randint(4, 200)), self.now)
            elif rng.random() < 0.4:
                status = "in_progress"
            t = wchoice(rng, [t for t, _ in CRM_TYPES], [w for _, w in CRM_TYPES])
            rows.append(CrmTicket(source_id=f"crm:TKT{i + 1:05d}", ticket_type=t, status=status,
                                  priority=rng.choice(["High", "Medium", "Low"]), retailer_id=o["retailer_id"],
                                  order_id=o["id"], distributor_id=o["distributor_id"], state_id=o["state_id"],
                                  region_id=o["region_id"], asm_id=o["asm_id"], opened_at=opened, closed_at=closed,
                                  description=f"{t} reported by retailer"))
        CrmTicket.objects.bulk_create(rows, batch_size=1000)
        self.log(f"crm: {len(rows)} tickets")

    # ------------------------------------------------------------------ targets
    def targets(self):
        from django.db.models import Sum

        rng = self.rng
        mt = {m: s for m, s, _, _ in self.month_targets()}
        cur = month_start(self.today)
        last_day = calendar.monthrange(cur.year, cur.month)[1]
        mt[cur] = mt[cur] * last_day / self.today.day  # full-month equivalent
        g = 1.03
        rows = []
        fy0 = dt.date(2025, 4, 1)
        m = fy0
        while m <= dt.date(2027, 3, 1):
            base = mt.get(m) or mt[cur] * (g ** ((m.year - cur.year) * 12 + m.month - cur.month))
            val = base * rng.uniform(1.05, 1.12)
            rows.append(Target(month=m, scope_type="overall", metric="sales", value=D(round(val, -4)),
                               effective_from=fy0 - dt.timedelta(days=20), notes="FY plan", updated_by="seed"))
            rows.append(Target(month=m, scope_type="overall", metric="orders", value=D(round(val / 38000)),
                               effective_from=fy0 - dt.timedelta(days=20), updated_by="seed"))
            rows.append(Target(month=m, scope_type="overall", metric="new_retailers", value=D(140),
                               effective_from=fy0 - dt.timedelta(days=20), updated_by="seed"))
            m = add_months(m, 1)
        # one revised version for the current month
        rows.append(Target(month=cur, scope_type="overall", metric="sales",
                           value=D(round(mt[cur] * 1.10, -4)), effective_from=cur, version=2,
                           notes="Revised at month start", updated_by="seed"))
        # distributor / state / region targets: share of last 3 months x overall
        l3 = add_months(cur, -3)
        qs = Order.objects.filter(is_qualifying=True, placed_date__gte=l3, placed_date__lt=cur)
        total = float(qs.aggregate(s=Sum("gross_value"))["s"] or 1)
        for field, scope in (("distributor_id", "distributor"), ("state_id", "state"), ("region_id", "region"),
                             ("asm_id", "asm")):
            shares = {r[field]: float(r["s"]) / total for r in qs.values(field).annotate(s=Sum("gross_value"))
                      if r[field]}
            for mm in (add_months(cur, -2), add_months(cur, -1), cur, add_months(cur, 1)):
                overall = (mt.get(mm) or mt[cur] * g) * 1.08
                for sid, sh in shares.items():
                    rows.append(Target(month=mm, scope_type=scope, scope_id=sid, metric="sales",
                                       value=D(round(overall * sh * rng.uniform(0.95, 1.12), -3)),
                                       effective_from=add_months(mm, -1), updated_by="seed"))
        Target.objects.bulk_create(rows, batch_size=1000)
        self.log(f"targets: {len(rows)}")

    def reconciliation(self):
        from django.db.models import Count, Sum

        rng = self.rng
        cur = month_start(self.today)
        rows = []
        for k in range(1, 7):
            m = add_months(cur, -k)
            qs = Order.objects.filter(is_qualifying=True, placed_date__gte=m, placed_date__lt=add_months(m, 1))
            a = qs.aggregate(s=Sum("gross_value"), n=Count("split_group", distinct=True))
            drift = 1.018 if k == 3 else rng.uniform(0.994, 1.006)
            rows.append(ReconciliationRef(metric="sales", month=m, mis_value=D(float(a["s"] or 0) * drift),
                                          notes="Finance MIS", updated_by="seed"))
            rows.append(ReconciliationRef(metric="orders", month=m, mis_value=D(round((a["n"] or 0) * rng.uniform(0.995, 1.005))),
                                          notes="Finance MIS", updated_by="seed"))
        ReconciliationRef.objects.bulk_create(rows)

    # ------------------------------------------------------------------ roles & users
    def roles_and_users(self):
        views = [c for c in PERMISSION_CODES if c.startswith("view_") and c != "view_pii"]
        roles = {
            "Business Head": views + ["export_data", "view_pii"],
            "Regional Manager": views + ["export_data"],
            "ASM": ["view_overview", "view_funnel", "view_distributors", "view_territory", "view_orders",
                    "view_inventory"],
            "Data Admin": ["view_data_health", "manage_targets", "manage_mappings", "manage_metrics",
                           "trigger_sync", "view_overview"],
        }
        rs = {}
        for name, perms in roles.items():
            rs[name], _ = Role.objects.update_or_create(name=name, defaults={
                "permissions": sorted(set(perms)), "description": f"Demo role: {name}"})
        demo = [("rm.south2@technodirect.local", "Regional Manager – Telugu States", "Regional Manager",
                 {"regions": [Region.objects.get(code="SOUTH2")]}),
                ("asm.ka@technodirect.local", "Ravi Kumar (ASM)", "ASM", {"asms": [Asm.objects.get(code="ASM01")]}),
                ("heera@technodirect.local", "Heera Exports (distributor)", "ASM", {"distributors": [self.heera]}),
                ("head@technodirect.local", "Business Head", "Business Head", {"all": True})]
        for email, name, role, scope in demo:
            u = User.objects.filter(email=email).first()
            if not u:
                u = User.objects.create_user(email=email, password="Demo@12345", full_name=name)
            u.role = rs[role]
            u.scope_all = bool(scope.get("all"))
            u.save()
            u.scope_regions.set(scope.get("regions", []))
            u.scope_asms.set(scope.get("asms", []))
            u.scope_distributors.set(scope.get("distributors", []))
        self.log("roles & demo users ready (password Demo@12345)")

    def sync_runs(self):
        from ingestion.schedule import last_scheduled

        slot = last_scheduled() or self.now
        start = max(slot, self.now - dt.timedelta(hours=12))
        if start > self.now:
            start = self.now
        t = start
        for s, rows in (("medusa", Order.objects.count()), ("payu", Payment.objects.count()),
                        ("google_sheets", CrmTicket.objects.count()),
                        ("channel_konnect", InventorySnapshot.objects.filter(is_latest=True).count()),
                        ("derivations", 0)):
            SyncRun.objects.create(source=s, status="success", started_at=t, finished_at=t + dt.timedelta(seconds=40),
                                   rows=rows, details={"seed": True}, triggered_by="seed")
            t += dt.timedelta(seconds=45)
        SyncRun.objects.create(source=REFRESH_SOURCE, status="success", started_at=start, finished_at=t,
                               details={"seed": True}, triggered_by="seed")
