"""Warehouse star schema: dimensions, facts and derived tables.

Rule: dashboard requests only ever read these tables – never a source system.
Territory columns (region/state/asm/distributor) are denormalised onto facts so that
row-level data scope filtering is a single indexed predicate.
"""
from django.db import models


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ----------------------------------------------------------------------------- dimensions
class Region(TimeStamped):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class State(TimeStamped):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=100, unique=True)
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.SET_NULL, related_name="states")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Rsm(TimeStamped):
    """Regional Sales Manager: the level above ASM (from the Master ASM Tracker's reporting lines).

    A retailer / order belongs to the RSM of its ASM; with no ASM, to the RSM heading its region.
    """
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    emp_id = models.CharField(max_length=32, blank=True, db_index=True)
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.SET_NULL, related_name="rsms")
    joined_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Asm(TimeStamped):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    full_name = models.CharField(max_length=120, blank=True, help_text="Name in the HR master")
    emp_id = models.CharField(max_length=32, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.SET_NULL, related_name="asms")
    rsm = models.ForeignKey(Rsm, null=True, blank=True, on_delete=models.SET_NULL, related_name="asms")
    joined_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class AsmAssignment(TimeStamped):
    """Which ASM managed a distributor over which dates (asm empty = vacant).

    Orders are credited to the ASM in charge on the order date, so a handover (resignation, new joiner)
    keeps history with the person who made it. Distributor.asm is the current one.
    """
    distributor = models.ForeignKey("Distributor", on_delete=models.CASCADE, related_name="asm_history")
    asm = models.ForeignKey(Asm, null=True, blank=True, on_delete=models.SET_NULL, related_name="assignments")
    start = models.DateField()
    end = models.DateField(null=True, blank=True, help_text="Last day (inclusive); empty = still in charge")
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["distributor_id", "start"]
        constraints = [models.UniqueConstraint(fields=["distributor", "start"], name="uniq_asm_assignment_start")]

    def __str__(self):
        return f"{self.distributor_id}: {self.asm or 'vacant'} {self.start}–{self.end or ''}"


class FieldStaff(TimeStamped):
    """Senior / field sales executives under an ASM (or directly under an RSM). No contact details are kept."""
    emp_id = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    designation = models.CharField(max_length=64, blank=True)
    asm = models.ForeignKey(Asm, null=True, blank=True, on_delete=models.SET_NULL, related_name="field_staff")
    rsm = models.ForeignKey(Rsm, null=True, blank=True, on_delete=models.SET_NULL, related_name="field_staff")
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    base_city = models.CharField(max_length=100, blank=True)
    joined_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Distributor(TimeStamped):
    source_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=200)
    state = models.ForeignKey(State, null=True, blank=True, on_delete=models.SET_NULL, related_name="distributors")
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.SET_NULL, related_name="distributors")
    asm = models.ForeignKey(Asm, null=True, blank=True, on_delete=models.SET_NULL, related_name="distributors")
    city = models.CharField(max_length=100, blank=True)
    pincode = models.CharField(max_length=6, blank=True, help_text="Warehouse pincode (TD distributors table)")
    gstin = models.CharField(max_length=20, blank=True)
    ck_code = models.CharField(max_length=64, blank=True, help_text="Identifier in Channel Konnect")
    aliases = models.JSONField(default=list, blank=True,
                               help_text="Other spellings of this distributor in source files (e.g. 'Heera')")
    is_active = models.BooleanField(default=True)
    onboarded_on = models.DateField(null=True, blank=True)
    bo_only = models.BooleanField(default=False, help_text="Known only from BlueOrigin (offline) sheets, not on the app")
    is_internal = models.BooleanField(default=False, help_text="Company-internal account (not a real distributor): its "
                                      "orders never count as sales and it is hidden from lists")
    removed = models.BooleanField(default=False, help_text="Removed from the dashboard by an admin (masters/exclusions.py): "
                                  "hidden from lists, filters and stock; its past orders still count in their months")
    # from the "TechnoD Distributors" sheet (masters/distributor_sync.py): when stock was last updated on the app
    stock_updated_on = models.DateField(null=True, blank=True, help_text="Sheet 'Inventory Updated'")
    inventory_status = models.CharField(max_length=32, blank=True, help_text="Inventory Live / Inventory Pending / Not onboarded")
    stock_upload_mode = models.CharField(max_length=32, blank=True, help_text="Sheet 'Taken By': Manually / CK / ZOHO")
    stock_update_frequency = models.CharField(max_length=32, blank=True, help_text="Daily / Twice a week / ...")

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["state"]), models.Index(fields=["region"]), models.Index(fields=["asm"])]

    def __str__(self):
        return self.name


class Pincode(TimeStamped):
    pincode = models.CharField(max_length=6, unique=True)
    district = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.ForeignKey(State, null=True, blank=True, on_delete=models.SET_NULL, related_name="pincodes")
    asm = models.ForeignKey(Asm, null=True, blank=True, on_delete=models.SET_NULL, related_name="pincodes")
    distributor_p1 = models.ForeignKey(
        Distributor, null=True, blank=True, on_delete=models.SET_NULL, related_name="p1_pincodes"
    )
    distributor_p2 = models.ForeignKey(
        Distributor, null=True, blank=True, on_delete=models.SET_NULL, related_name="p2_pincodes"
    )
    is_serviceable = models.BooleanField(default=True)

    class Meta:
        ordering = ["pincode"]

    def __str__(self):
        return self.pincode


class Category(TimeStamped):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=100)
    level = models.PositiveSmallIntegerField(default=1)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(TimeStamped):
    source_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    style = models.CharField(max_length=32, db_index=True,
                             help_text="Article / style code, e.g. OR99 (re-launches reuse the code)")
    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="products")
    category_l1 = models.CharField(max_length=100, blank=True, db_index=True,
                                   help_text="Category I (root): men / women / kids / unisex")
    category_l2 = models.CharField(max_length=100, blank=True, help_text="Category II: topwear / bottomwear / ...")
    category_l3 = models.CharField(max_length=100, blank=True, help_text="Category III: trackpants / t-shirts / ...")
    pack_size = models.PositiveIntegerField(default=1, help_text="Pieces per box")
    launched_on = models.DateField(null=True, blank=True)
    is_important = models.BooleanField(default=False, help_text="Core article – alert when out of stock")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["style"]

    def __str__(self):
        return self.style


class ProductVariant(TimeStamped):
    source_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    sku = models.CharField(max_length=64, unique=True)
    size = models.CharField(max_length=16, blank=True)
    mrp = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Wholesale unit price")

    def __str__(self):
        return self.sku


class Retailer(TimeStamped):
    KYC_CHOICES = [
        ("not_submitted", "Not submitted"),
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]
    source_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    name = models.CharField(max_length=200)
    owner_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=20, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    gstin = models.CharField(max_length=20, blank=True, db_index=True)
    udyam_number = models.CharField(max_length=32, blank=True)
    has_account = models.BooleanField(default=False, help_text="Completed app account (vs. phone-only lead)")
    pincode = models.CharField(max_length=10, blank=True, db_index=True)
    city = models.CharField(max_length=100, blank=True)
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.SET_NULL, related_name="retailers")
    state = models.ForeignKey(State, null=True, blank=True, on_delete=models.SET_NULL, related_name="retailers")
    asm = models.ForeignKey(Asm, null=True, blank=True, on_delete=models.SET_NULL, related_name="retailers")
    distributor = models.ForeignKey(
        Distributor, null=True, blank=True, on_delete=models.SET_NULL, related_name="retailers",
        help_text="Mapped P1 distributor (by pincode)",
    )
    kyc_status = models.CharField(max_length=16, choices=KYC_CHOICES, default="not_submitted", db_index=True)
    signed_up_at = models.DateTimeField(null=True, blank=True)
    kyc_submitted_at = models.DateTimeField(null=True, blank=True)
    kyc_approved_at = models.DateTimeField(null=True, blank=True)
    warm_match = models.BooleanField(default=False, help_text="Matched to BlueOrigin ledger")
    tier = models.CharField(max_length=16, blank=True)
    # Aggregates maintained by analytics.derivations
    first_order_date = models.DateField(null=True, blank=True, db_index=True)
    last_order_date = models.DateField(null=True, blank=True, db_index=True)
    orders_count = models.PositiveIntegerField(default=0, db_index=True)
    total_sales = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    class Meta:
        indexes = [
            models.Index(fields=["kyc_status", "state"]),
            models.Index(fields=["state", "region"]),
            models.Index(fields=["distributor"]),
            models.Index(fields=["asm"]),
        ]

    def __str__(self):
        return self.name


# ----------------------------------------------------------------------------- facts
ORDER_STATUSES = ["received", "confirmed", "shipped", "delivered", "cancelled"]
# Medusa order payment_status (recorded in Medusa; no payment-gateway integration).
PAYMENT_STATUSES = ["awaiting", "captured", "partially_refunded", "refunded", "failed", "not_paid"]
QUALIFYING_PAYMENT_STATUSES = ["captured", "partially_refunded", "refunded"]


class Order(TimeStamped):
    STATUS_CHOICES = [(s, s.title()) for s in ORDER_STATUSES]
    PAYMENT_CHOICES = [(s, s.replace("_", " ").title()) for s in PAYMENT_STATUSES]

    source_id = models.CharField(max_length=64, unique=True)
    display_id = models.CharField(max_length=32, db_index=True)
    split_group = models.CharField(max_length=64, db_index=True, help_text="Parent cart id; same for split orders")
    is_split = models.BooleanField(default=False)
    payment_ref = models.CharField(
        max_length=64, blank=True, db_index=True, help_text="Merchant txnid sent to PayU (from Medusa)"
    )
    payu_txn_id = models.CharField(max_length=64, blank=True, help_text="mihpayid of the latest PayU txn")
    payment_mode = models.CharField(max_length=16, blank=True, help_text="UPI / CC / DC / NB / BNPL / ...")
    platform = models.CharField(max_length=16, blank=True, db_index=True, help_text="android / ios / web")
    payment_status_source = models.CharField(
        max_length=8, default="medusa", help_text="'payu' when status comes from a PayU txn, else 'medusa'"
    )
    medusa_payment_status = models.CharField(max_length=24, blank=True)
    retailer = models.ForeignKey(Retailer, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    distributor = models.ForeignKey(
        Distributor, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    state = models.ForeignKey(State, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    asm = models.ForeignKey(Asm, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="received")
    payment_status = models.CharField(max_length=24, choices=PAYMENT_CHOICES, default="awaiting")
    gross_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    units = models.PositiveIntegerField(default=0)
    placed_at = models.DateTimeField(db_index=True)
    placed_date = models.DateField(db_index=True, help_text="IST calendar date of placed_at")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    awb = models.CharField(max_length=64, blank=True)
    courier = models.CharField(max_length=64, blank=True)
    ts_order_status = models.CharField(max_length=32, blank=True, help_text="Raw Medusa order.ts_order_status")
    distributor_remark = models.CharField(max_length=255, blank=True, help_text="Medusa order.ts_remark")
    is_qualifying = models.BooleanField(
        default=False, db_index=True, help_text="Payment captured and not cancelled -> counts as Sales"
    )
    source_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["placed_date", "is_qualifying"]),
            models.Index(fields=["distributor", "placed_date"]),
            models.Index(fields=["state", "placed_date"]),
            models.Index(fields=["region", "placed_date"]),
            models.Index(fields=["asm", "placed_date"]),
            models.Index(fields=["retailer", "placed_date"]),
            models.Index(fields=["status", "placed_date"]),
        ]

    def save(self, *args, **kwargs):
        self.is_qualifying = compute_is_qualifying(self.status, self.payment_status)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_id


def sales_match_tracker():
    """settings.SALES_BASIS == "tracker": sales = every paid order, as the finance Order Tracking sheet lists them."""
    from django.conf import settings

    return getattr(settings, "SALES_BASIS", "tracker") == "tracker"


def compute_is_qualifying(status, payment_status):
    paid = payment_status in QUALIFYING_PAYMENT_STATUSES
    if sales_match_tracker():
        return paid  # cancelled orders stay in, as in the sheet (the "Cancelled %" metric still reads the status)
    return status != "cancelled" and paid


class OrderLine(TimeStamped):
    source_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.SET_NULL, related_name="lines")
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.SET_NULL, related_name="lines")
    style = models.CharField(max_length=32, blank=True, db_index=True)
    sku = models.CharField(max_length=64, blank=True, db_index=True)
    size = models.CharField(max_length=16, blank=True)
    quantity = models.PositiveIntegerField(default=0, help_text="Units (pieces) = boxes x pieces per box")
    boxes = models.PositiveIntegerField(default=0, help_text="Boxes ordered (Medusa line_item.quantity)")
    pieces_per_box = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Price per piece")
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)


PAYU_STATUSES = ["success", "failure", "pending", "userCancelled"]
PAYU_TO_ORDER_PAYMENT = {"success": "captured", "failure": "failed", "userCancelled": "failed",
                         "pending": "awaiting"}


class Payment(TimeStamped):
    """One row per PayU transaction (sales/order transactions only – no refunds / settlements)."""

    STATUS = [(s, s) for s in PAYU_STATUSES]
    source_id = models.CharField(max_length=64, unique=True, help_text="PayU mihpayid (payu_txn_id)")
    txnid = models.CharField(max_length=64, db_index=True, help_text="Merchant txnid")
    order_ref = models.CharField(max_length=64, blank=True, db_index=True,
                                 help_text="Order / cart reference sent in udf/productinfo")
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL, related_name="payments")
    split_group = models.CharField(max_length=64, blank=True, db_index=True, help_text="Matched cart id")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=16, choices=STATUS, db_index=True)
    mode = models.CharField(max_length=16, blank=True, help_text="UPI / CC / DC / NB / BNPL / ...")
    bank = models.CharField(max_length=64, blank=True, help_text="bankcode / issuer")
    added_on = models.DateTimeField(db_index=True)
    error_message = models.CharField(max_length=255, blank=True)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "added_on"])]


INVENTORY_SOURCES = [("td", "TechnoDirect app stock (ts_product_variant_inventory)"),
                     ("ck", "Channel Konnect")]


class InventorySnapshot(TimeStamped):
    """Daily stock per distributor x SKU. `is_latest` marks the current row.

    source='td' is the stock the retailer app actually shows (Medusa ts_product_variant_inventory);
    source='ck' is the distributor billing-system stock from Channel Konnect (used for mismatch checks).
    Dashboard views read settings.INVENTORY_PRIMARY_SOURCE.
    """

    source = models.CharField(max_length=4, choices=INVENTORY_SOURCES, default="td", db_index=True)
    distributor = models.ForeignKey(Distributor, on_delete=models.CASCADE, related_name="inventory")
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    sku = models.CharField(max_length=64)
    style = models.CharField(max_length=32, blank=True)
    size = models.CharField(max_length=16, blank=True)
    snapshot_date = models.DateField()
    quantity = models.IntegerField(default=0)
    synced_at = models.DateTimeField()
    is_latest = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "distributor", "sku", "snapshot_date"],
                                    name="uniq_inv_src_dist_sku_date")
        ]
        indexes = [
            models.Index(fields=["source", "is_latest", "distributor"]),
            models.Index(fields=["style"]),
            models.Index(fields=["snapshot_date"]),
        ]


def primary_inventory():
    """InventorySnapshot rows from the stock source the dashboard displays (settings.INVENTORY_PRIMARY_SOURCE)."""
    from django.conf import settings

    return InventorySnapshot.objects.filter(source=getattr(settings, "INVENTORY_PRIMARY_SOURCE", "td"))


class CrmTicket(TimeStamped):
    source_id = models.CharField(max_length=64, unique=True)
    ticket_type = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=32, db_index=True, help_text="open / in_progress / closed")
    priority = models.CharField(max_length=16, blank=True)
    retailer = models.ForeignKey(Retailer, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets")
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets")
    distributor = models.ForeignKey(Distributor, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    state = models.ForeignKey(State, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    asm = models.ForeignKey(Asm, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    opened_at = models.DateTimeField(db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    description = models.TextField(blank=True)
    raw = models.JSONField(default=dict, blank=True)


class PendingOrderJob(TimeStamped):
    """Mirror of Medusa ts_pending_order_job: the recovery job that creates an order after a
    successful payment. A job with no order and no refund is the "payment succeeded, order missing" case."""

    source_id = models.CharField(max_length=32, unique=True)
    cart_id = models.CharField(max_length=64, blank=True, db_index=True)
    payment_session_id = models.CharField(max_length=64, blank=True)
    order_source_id = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=32, blank=True, db_index=True)
    attempt = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=500, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    refund_initiated_at = models.DateTimeField(null=True, blank=True)
    job_created_at = models.DateTimeField(db_index=True)
    job_updated_at = models.DateTimeField(null=True, blank=True)


class LoyaltyEvent(TimeStamped):
    """Retailer loyalty-points ledger: one row per event (welcome bonus, points earned, points redeemed).

    `points` is signed: earned events are positive, redemptions negative.
    """

    EVENT_TYPES = [("new_customer", "New customer bonus"), ("earned", "Points earned"),
                   ("redeemed", "Points redeemed"), ("other", "Other")]
    source_id = models.CharField(max_length=64, unique=True, help_text="Stable hash of the source row")
    customer_source_id = models.CharField(max_length=64, db_index=True)
    retailer = models.ForeignKey(Retailer, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="loyalty_events")
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    order_display_id = models.CharField(max_length=32, blank=True)
    event_type = models.CharField(max_length=16, choices=EVENT_TYPES, db_index=True)
    event_label = models.CharField(max_length=64, blank=True, help_text="Raw event name from the source")
    points = models.IntegerField(default=0)
    event_date = models.DateField(db_index=True)
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    state = models.ForeignKey(State, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    asm = models.ForeignKey(Asm, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    distributor = models.ForeignKey(Distributor, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        indexes = [models.Index(fields=["event_date", "event_type"]), models.Index(fields=["retailer", "event_date"])]


# ----------------------------------------------------------------------------- derived
class RetailerMonth(models.Model):
    STATUS = [("new", "New"), ("retained", "Retained"), ("reactivated", "Reactivated"), ("lost", "Lost")]
    retailer = models.ForeignKey(Retailer, on_delete=models.CASCADE, related_name="months")
    month = models.DateField(help_text="First day of month")
    status = models.CharField(max_length=16, choices=STATUS)
    is_active = models.BooleanField(default=True)
    sales = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    orders = models.PositiveIntegerField(default=0)
    units = models.PositiveIntegerField(default=0)
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    state = models.ForeignKey(State, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    asm = models.ForeignKey(Asm, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    distributor = models.ForeignKey(Distributor, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["retailer", "month"], name="uniq_retailer_month")]
        indexes = [models.Index(fields=["month", "status"]), models.Index(fields=["state", "month"])]


class Target(TimeStamped):
    SCOPE_TYPES = [("overall", "Overall"), ("region", "Region"), ("rsm", "RSM"), ("state", "State"), ("asm", "ASM"),
                   ("distributor", "Distributor")]
    METRICS = [("sales", "Sales"), ("orders", "Orders"), ("new_retailers", "New retailers"),
               ("active_retailers", "Active retailers")]
    month = models.DateField(help_text="First day of month")
    scope_type = models.CharField(max_length=16, choices=SCOPE_TYPES, default="overall")
    scope_id = models.BigIntegerField(null=True, blank=True)
    metric = models.CharField(max_length=24, choices=METRICS, default="sales")
    value = models.DecimalField(max_digits=16, decimal_places=2)
    effective_from = models.DateField()
    version = models.PositiveIntegerField(default=1)
    notes = models.CharField(max_length=255, blank=True)
    updated_by = models.CharField(max_length=254, blank=True)

    class Meta:
        indexes = [models.Index(fields=["month", "scope_type", "metric"])]
        ordering = ["-month", "scope_type", "scope_id"]


class TargetSplit(TimeStamped):
    """Who carries a distributor's monthly sales target, person by person, as in the team's incentive sheet
    (ASM and executive lines). The distributor target is their sum; this keeps the split for display."""
    ROLES = [("asm", "ASM"), ("executive", "Executive")]
    month = models.DateField(help_text="First day of month")
    distributor = models.ForeignKey("Distributor", on_delete=models.CASCADE, related_name="target_splits")
    role = models.CharField(max_length=16, choices=ROLES)
    person = models.CharField(max_length=120, help_text="Name as written in the sheet ('Vacant' = no one)")
    asm = models.ForeignKey(Asm, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    field_staff = models.ForeignKey(FieldStaff, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    value = models.DecimalField(max_digits=16, decimal_places=2)
    # the sheet's other KPI targets (masters/incentives.py); empty = no target for that KPI
    new_retailer_target = models.PositiveIntegerField(null=True, blank=True)
    bo_gps_target = models.PositiveIntegerField(null=True, blank=True, help_text="New BO Gold/Platinum/Silver retailers")
    kyc_target = models.PositiveIntegerField(null=True, blank=True, help_text="KYC customers converted")
    base_incentive = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # achieved values typed in on the incentive table (empty = calculated from data); kept across re-saves of the month
    td_actual_override = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    new_actual_override = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    gps_actual_override = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    kyc_actual_override = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    override_by = models.CharField(max_length=254, blank=True)
    override_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["month", "distributor_id", "role", "-value"]
        indexes = [models.Index(fields=["month"])]


class DataQualityIssue(models.Model):
    SEVERITY = [("high", "High"), ("medium", "Medium"), ("low", "Low")]
    code = models.CharField(max_length=48, db_index=True)
    label = models.CharField(max_length=120)
    severity = models.CharField(max_length=8, choices=SEVERITY, default="medium")
    object_type = models.CharField(max_length=48, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    details = models.JSONField(default=dict, blank=True)
    detected_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["code", "resolved_at"])]


class TrackedDistributor(TimeStamped):
    """The sales team's distributor network list (one tracker sheet per distributor, with its state).

    Linked to the app distributor when it trades on TechnoDirect; unlinked = tracked by the team but not on the
    app yet (pipeline). Kept apart from Distributor so pipeline names never appear in sales / stock tables.
    """
    name = models.CharField(max_length=200, unique=True)
    state = models.ForeignKey(State, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    state_label = models.CharField(max_length=100, blank=True, help_text="State as written on the list")
    distributor = models.ForeignKey(Distributor, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="trackers")
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class TargetForecast(TimeStamped):
    """Suggested target for a month (TD Target Forecaster), made on `as_of` (the 27th of the month before).

    scope_type asm / distributor / overall, like Target. Kept apart from Target: a suggestion never changes a
    set target; it is shown next to it and can be copied in the Edit ASM & targets window.
    """
    month = models.DateField(help_text="First day of the forecast month")
    scope_type = models.CharField(max_length=16)
    scope_id = models.BigIntegerField(null=True, blank=True)
    value = models.DecimalField(max_digits=16, decimal_places=2, help_text="Suggested target (Rs)")
    sales_forecast = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    as_of = models.DateField(help_text="Data up to this day was used")
    model_version = models.CharField(max_length=32)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-as_of", "month"]
        constraints = [models.UniqueConstraint(fields=["month", "scope_type", "scope_id", "as_of"],
                                               name="uniq_target_forecast")]
        indexes = [models.Index(fields=["month", "scope_type"])]


# ----------------------------------------------------------------------------- BlueOrigin (offline)
TIERS = ["Platinum", "Gold", "Silver", "Green", "Yellow", "Untiered"]  # best first


class BoRetailer(TimeStamped):
    """A retailer in the BlueOrigin distributor sheets (offline purchase), deduped by BO's Retailer_ID.

    Hierarchy follows the TechnoDirect rules: ASM = the distributor's ASM today, RSM derived from the ASM."""
    bo_id = models.CharField(max_length=32, unique=True, help_text="BlueOrigin Retailer_ID, e.g. TIR-00615")
    name = models.CharField(max_length=200)
    distributor = models.ForeignKey(Distributor, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="bo_retailers")
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    state = models.ForeignKey(State, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    asm = models.ForeignKey(Asm, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    district = models.CharField(max_length=100, blank=True)
    pincode = models.CharField(max_length=10, blank=True)
    phone = models.CharField(max_length=20, blank=True, db_index=True)
    phone_alt = models.CharField(max_length=20, blank=True)
    td_retailer = models.ForeignKey(Retailer, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="bo_records", help_text="TechnoDirect app retailer (phone match)")
    first_quarter = models.DateField(null=True, blank=True)
    last_quarter = models.DateField(null=True, blank=True)
    tier = models.CharField(max_length=16, blank=True, help_text="Sheet 'New Tier' in its latest quarter")
    tier_quarter = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["distributor"]), models.Index(fields=["asm"]), models.Index(fields=["state"]),
                   models.Index(fields=["tier"])]

    def __str__(self):
        return f"{self.bo_id} {self.name}"


class BoRetailerQuarter(TimeStamped):
    """One BlueOrigin quarterly sheet row: purchase, tier (sheet 'New Tier', blank = Untiered), deliverables."""
    bo_retailer = models.ForeignKey(BoRetailer, on_delete=models.CASCADE, related_name="quarters")
    quarter = models.DateField(help_text="First day of the FY quarter")
    label = models.CharField(max_length=12, help_text="e.g. Q2 FY27")
    purchase = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text="Last 3 Months (Rs)")
    tier = models.CharField(max_length=16, default="Untiered")
    old_tier = models.CharField(max_length=16, blank=True)
    deliverables = models.CharField(max_length=16, blank=True, help_text="yes / no / cancelled")
    benefits = models.JSONField(default=dict, blank=True)
    distributor = models.ForeignKey(Distributor, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    state = models.ForeignKey(State, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    asm = models.ForeignKey(Asm, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["quarter"]
        constraints = [models.UniqueConstraint(fields=["bo_retailer", "quarter"], name="uniq_bo_retailer_quarter")]
        indexes = [models.Index(fields=["quarter", "tier"]), models.Index(fields=["asm"]),
                   models.Index(fields=["distributor"])]


class BoRetailerMonth(TimeStamped):
    """Monthly offline purchase of a BlueOrigin retailer (from the quarter sheets' month columns; zeros skipped)."""
    bo_retailer = models.ForeignKey(BoRetailer, on_delete=models.CASCADE, related_name="months")
    month = models.DateField()
    value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    distributor = models.ForeignKey(Distributor, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    state = models.ForeignKey(State, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    asm = models.ForeignKey(Asm, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["month"]
        constraints = [models.UniqueConstraint(fields=["bo_retailer", "month"], name="uniq_bo_retailer_month")]
        indexes = [models.Index(fields=["month"]), models.Index(fields=["asm"]), models.Index(fields=["distributor"])]


# ----------------------------------------------------------------------------- distributor settlement
SETTLEMENT_STATUSES = ["settled", "not_settled", "pending", "cancelled"]  # pending = not yet reviewed by finance
SETTLEMENT_PAYMENT_STATUSES = ["approved", "not_approved", "pending", "cancelled"]


class DistributorSettlement(TimeStamped):
    """One order row of the finance team's 'Technodirect Order Tracking - Tracker' sheet (masters/settlement.py).

    The distributor is paid order value - customer refund (loyalty points are NOT deducted), in payout batches
    roughly twice a week. `distributor` is the payee named in the sheet (it can differ from the app order's
    distributor when an order was reassigned); hierarchy copies follow the payee.
    """
    order_ref = models.CharField(max_length=32, unique=True, help_text="Order display id without '#'")
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL, related_name="settlements")
    sheet_distributor = models.CharField(max_length=200, blank=True)
    distributor = models.ForeignKey(Distributor, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    state = models.ForeignKey(State, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    asm = models.ForeignKey(Asm, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    customer = models.CharField(max_length=200, blank=True)
    destination = models.CharField(max_length=200, blank=True)
    order_date = models.DateField(db_index=True)
    dispatch_date = models.DateField(null=True, blank=True)
    delivered_date = models.DateField(null=True, blank=True)
    fulfilment = models.CharField(max_length=16, blank=True, help_text="delivered / in_transit / not_dispatched / cancelled")
    multi_distributor = models.BooleanField(default=False)
    courier_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    order_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    payu_value = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text="Check Value from PayU")
    customer_refund = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    refund_date = models.DateField(null=True, blank=True)
    pg_settlement = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True,
                                        help_text="'Customer Settlement': PayU -> TechnoSport after gateway charges")
    pg_settlement_date = models.DateField(null=True, blank=True)
    loyalty_points = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payable = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text="'Distributor Settlement'")
    payable_derived = models.BooleanField(default=False, help_text="Sheet value unreadable: order value - refund used")
    payment_mode = models.CharField(max_length=16, blank=True)
    transaction_id = models.CharField(max_length=64, blank=True)
    payment_status = models.CharField(max_length=16, default="pending", db_index=True)
    settlement_status = models.CharField(max_length=16, default="pending", db_index=True)
    settled_on = models.DateField(null=True, blank=True, db_index=True, help_text="Distributor Settlement Date")
    remark = models.CharField(max_length=255, blank=True)
    issues = models.JSONField(default=list, blank=True, help_text="Data-quality notes from the import")

    class Meta:
        ordering = ["-order_date", "order_ref"]
        indexes = [models.Index(fields=["distributor", "order_date"]), models.Index(fields=["asm"]),
                   models.Index(fields=["settlement_status", "order_date"])]

    def __str__(self):
        return f"#{self.order_ref}"
