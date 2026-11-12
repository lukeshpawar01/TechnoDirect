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


class Asm(TimeStamped):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.SET_NULL, related_name="asms")
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
    gstin = models.CharField(max_length=20, blank=True)
    ck_code = models.CharField(max_length=64, blank=True, help_text="Identifier in Channel Konnect")
    aliases = models.JSONField(default=list, blank=True,
                               help_text="Other spellings of this distributor in source files (e.g. 'Heera')")
    is_active = models.BooleanField(default=True)
    onboarded_on = models.DateField(null=True, blank=True)

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


def compute_is_qualifying(status, payment_status):
    return status != "cancelled" and payment_status in QUALIFYING_PAYMENT_STATUSES


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
    SCOPE_TYPES = [("overall", "Overall"), ("region", "Region"), ("state", "State"), ("asm", "ASM"),
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
