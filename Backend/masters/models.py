from django.db import models


class ReconciliationRef(models.Model):
    """Reference values from the existing (manual) MIS, to reconcile against the dashboard."""

    METRICS = [("sales", "Sales"), ("orders", "Orders"), ("active_retailers", "Active retailers"),
               ("new_retailers", "New retailers"), ("units", "Units")]
    metric = models.CharField(max_length=32, choices=METRICS)
    month = models.DateField(help_text="First day of month")
    mis_value = models.DecimalField(max_digits=16, decimal_places=2)
    tolerance_pct = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    notes = models.CharField(max_length=255, blank=True)
    updated_by = models.CharField(max_length=254, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["metric", "month"], name="uniq_recon_metric_month")]
        ordering = ["-month", "metric"]


class MetricDefinition(models.Model):
    code = models.CharField(max_length=48, unique=True)
    name = models.CharField(max_length=120)
    definition = models.TextField(blank=True)
    formula = models.TextField(blank=True)
    source = models.CharField(max_length=120, blank=True)
    owner = models.CharField(max_length=120, blank=True)
    refresh = models.CharField(max_length=120, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]


DEFAULT_METRICS = [
    ("sales", "Sales (Gross order value)",
     "Gross order value of paid orders (PayU-verified), before returns. Cancelled orders excluded.",
     "SUM(order.gross_value) WHERE status != cancelled AND payment captured (PayU success, else Medusa "
     "payment_status captured)", "Medusa orders + PayU transactions"),
    ("orders", "Orders", "Count of paid carts. A cart split across distributors counts once (per distributor "
     "in distributor views).", "COUNT(DISTINCT order.split_group)", "Medusa"),
    ("aov", "Average order value", "Sales / Orders", "sales / orders", "Derived"),
    ("units_per_order", "Units per order", "Units (pieces) / Orders", "SUM(units) / orders", "Derived"),
    ("realisation_per_unit", "Realisation per unit", "Sales / Units", "sales / SUM(units)", "Derived"),
    ("active_retailers", "Active retailers", "Retailers with >= 1 qualifying order in the period.",
     "COUNT(DISTINCT retailer_id)", "Medusa"),
    ("new_retailers", "New retailers", "Retailers whose first-ever qualifying order falls in the period.",
     "first_order_date BETWEEN from AND to", "Derived"),
    ("repeat_retailers", "Repeat (returning) retailers", "Active retailers whose first order was before "
     "the period.", "active_retailers - new_retailers", "Derived"),
    ("retained", "Retained retailers", "Active this month and the previous month.", "RetailerMonth.status",
     "Derived"),
    ("reactivated", "Reactivated retailers", "Active this month, not previous month, and not new.",
     "RetailerMonth.status", "Derived"),
    ("lost", "Lost retailers", "Active previous month, not active this month.", "RetailerMonth.status",
     "Derived"),
    ("inactive_buckets", "Inactive buckets", "Days since last qualifying order: 30-59, 60-89, 90+.",
     "today - last_order_date", "Derived"),
    ("never_ordered", "Never ordered", "KYC approved, zero qualifying orders. Warm = matched to BlueOrigin "
     "ledger; flagged = no distributor / state mapping.", "kyc_status=approved AND orders_count=0", "Medusa"),
    ("dispatch_pct", "Dispatch %", "Share of non-cancelled orders in the period that have shipped.",
     "shipped / non-cancelled", "Medusa"),
    ("target_run_rate", "Required run rate", "(Target - achieved) / remaining days in the target months.",
     "balance / remaining_days", "Targets (Admin)"),
]


def ensure_default_metrics(**kwargs):
    for code, name, definition, formula, source in DEFAULT_METRICS:
        MetricDefinition.objects.get_or_create(code=code, defaults={
            "name": name, "definition": definition, "formula": formula, "source": source,
            "owner": "Business Analytics", "refresh": "Twice daily (10:30 & 15:30 IST)"})


class PnlQuarter(models.Model):
    """One quarter of the TD P&L (Business Head / master admin only). The inputs entered in the dashboard; every other
    line is calculated exactly as in TD_P&L_QoQ_Rev.xlsx (masters/pnl.py)."""

    quarter_start = models.DateField(unique=True, help_text="First day of the FY quarter (1 Apr / Jul / Oct / Jan)")
    gross_revenue = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    returns = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True,
                                  help_text="Returns / refunds / cancellations")
    cogs_pct = models.DecimalField(max_digits=7, decimal_places=4, default=70, help_text="% of Net Revenue")
    pg_pct = models.DecimalField(max_digits=7, decimal_places=4, default=1, help_text="% of Gross Revenue")
    loyalty_pct = models.DecimalField(max_digits=7, decimal_places=4, default=0.25,
                                      help_text="% of Gross Revenue (the sheet: 0.5% / 2)")
    tech_platform_cost = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    manpower_operating_cost = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    misc_expense = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    updated_by = models.CharField(max_length=254, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["quarter_start"]

    def __str__(self):
        return f"P&L {self.quarter_start:%Y-%m}"


class PnlMonth(models.Model):
    """Figures entered for one month of the monthly P&L. Every field is optional: blank = the default (masters/pnl.py
    `month_inputs`): revenue from the TD orders, returns from the finance tracker, % and costs from the month's
    quarter (costs = quarter / 3)."""

    month = models.DateField(unique=True, help_text="First day of the month")
    gross_revenue = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    returns = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    cogs_pct = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    pg_pct = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    loyalty_pct = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    tech_platform_cost = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    manpower_operating_cost = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    misc_expense = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    updated_by = models.CharField(max_length=254, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["month"]

    def __str__(self):
        return f"P&L {self.month:%Y-%m}"


class PnlMonthData(models.Model):
    """Per-month totals from the TD data (same basis as PnlDataCheck), rebuilt at every import."""

    month = models.DateField(unique=True)
    orders = models.PositiveIntegerField(default=0)
    order_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    line_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    cancelled_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    points_redeemed = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["month"]


class PnlDataCheck(models.Model):
    """Per-quarter totals from the TD data (Supabase orders), rebuilt at every import - the P&L's 'check against data'."""

    quarter_start = models.DateField(unique=True)
    orders = models.PositiveIntegerField(default=0)
    order_value = models.DecimalField(max_digits=16, decimal_places=2, default=0,
                                      help_text="Order value incl. points redeemed (total_amount) of paid orders")
    line_value = models.DecimalField(max_digits=16, decimal_places=2, default=0, help_text="Order lines (= Sales)")
    cancelled_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    points_redeemed = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["quarter_start"]


class ManualMapping(models.Model):
    """A mapping the user gave in chat or by hand (no sheet / file / database behind it), kept apart so it can be
    retired the moment proper data arrives. It is applied to the dashboard like any mapping while it is active.

    status: active    - in use
            confirmed - proper data now says the same (closed; nothing changed on the dashboard)
            replaced  - proper data says something else and now drives the dashboard (closed)
            removed   - taken out by hand; its effect was undone (masters/manual_mappings.remove)
    """

    KINDS = [("distributor_asm", "Distributor's ASM"), ("asm_handover", "ASM handover (dated)"),
             ("distributor_alias", "Distributor alias"), ("distributor_merge", "Distributors merged"),
             ("distributor_removed", "Distributor removed from the dashboard")]
    STATUSES = [("active", "Active"), ("confirmed", "Confirmed by proper data"),
                ("replaced", "Replaced by proper data"), ("removed", "Removed")]
    kind = models.CharField(max_length=32, choices=KINDS)
    distributor = models.ForeignKey("warehouse.Distributor", null=True, blank=True, on_delete=models.CASCADE,
                                    related_name="manual_mappings")
    asm = models.ForeignKey("warehouse.Asm", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    start = models.DateField(null=True, blank=True, help_text="Handover: first day in charge")
    end = models.DateField(null=True, blank=True, help_text="Handover: last day (empty = still in charge)")
    value = models.JSONField(default=dict, blank=True, help_text="Kind-specific: alias text, merged name, previous ASM")
    given_on = models.DateField()
    said = models.TextField(blank=True, help_text="What the user said / gave")
    status = models.CharField(max_length=16, choices=STATUSES, default="active", db_index=True)
    closed_on = models.DateField(null=True, blank=True)
    closed_reason = models.CharField(max_length=255, blank=True)
    conflict = models.CharField(max_length=255, blank=True, help_text="Proper data that disagrees (not applied yet)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "kind", "distributor_id", "start"]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.distributor} -> {self.asm or self.value}"


# ----------------------------------------------------------------------------- Monthly Business Review (MBR)
class MbrReview(models.Model):
    """The written part of one month's MBR (page 1 commentary and the page 2 sales goal)."""

    month = models.DateField(unique=True, help_text="First day of the month reviewed")
    went_well = models.TextField(blank=True)
    needs_attention = models.TextField(blank=True)
    goal_monthly_sales = models.DecimalField(max_digits=16, decimal_places=2, default=100000000,
                                             help_text="Monthly TD sales the growth plan aims for (default ₹10 Cr)")
    goal_by = models.DateField(null=True, blank=True, help_text="Month the goal should be reached (empty = next quarter)")
    updated_by = models.CharField(max_length=254, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["month"]

    def __str__(self):
        return f"MBR {self.month:%Y-%m}"


class MbrItem(models.Model):
    """One line of an MBR: a growth action or bottleneck (page 2), a tech item (page 3) or a development (page 4)."""

    SECTIONS = [("growth", "Growth actions"), ("tech", "Tech updates"), ("other", "Other developments")]
    KINDS = {
        "growth": [("action", "Action"), ("bottleneck", "Bottleneck")],
        "tech": [("feature", "Feature"), ("integration", "Integration"), ("fix", "Fix"), ("infra", "Infrastructure")],
        "other": [("win", "Win"), ("risk", "Risk"), ("people", "People"), ("partner", "Partnership"),
                  ("policy", "Policy & compliance"), ("market", "Market & competition"), ("other", "Other")],
    }
    # Logistics, Legal and TUP were dropped on 2026-11-26 (user request); any old lines were moved to "other"
    TEAMS = [("sales", "Sales team"), ("tech", "Tech"), ("finance", "Finance"), ("data", "Data"),
             ("marketing", "Marketing"), ("operations", "Operations"), ("other", "Other")]
    LEVERS = [("adoption", "Adoption of TechnoSport retailers"), ("activation", "Activation of KYC'd retailers"),
              ("retention", "Retention / repeat orders"), ("new_retailers", "New retailers"),
              ("basket", "Basket size / spend"), ("distributors", "Distributor network"), ("other", "Other")]
    STATUSES = [("planned", "Planned"), ("in_progress", "In progress"), ("blocked", "Blocked"), ("done", "Done"),
                ("dropped", "Dropped")]
    PRIORITIES = [("high", "High"), ("medium", "Medium"), ("low", "Low")]
    OPEN = ("planned", "in_progress", "blocked")

    month = models.DateField(db_index=True, help_text="First day of the MBR month the item is reported in")
    section = models.CharField(max_length=16, choices=SECTIONS)
    kind = models.CharField(max_length=16)
    title = models.CharField(max_length=200)
    detail = models.TextField(blank=True)
    team = models.CharField(max_length=16, choices=TEAMS, blank=True,
                            help_text="Growth: support required from; tech: delivering team")
    lever = models.CharField(max_length=16, choices=LEVERS, blank=True)
    owner = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=16, choices=STATUSES, default="planned")
    priority = models.CharField(max_length=8, choices=PRIORITIES, default="medium")
    expected_impact = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True,
                                          help_text="Expected extra sales per month (₹)")
    planned_date = models.DateField(null=True, blank=True, help_text="Due date / planned go-live")
    revised_date = models.DateField(null=True, blank=True, help_text="New date when it slipped")
    done_date = models.DateField(null=True, blank=True)
    blocker = models.TextField(blank=True)
    event_date = models.DateField(null=True, blank=True, help_text="Developments: when it happened")
    carried_from = models.BigIntegerField(null=True, blank=True, help_text="id of last month's item it continues")
    sort = models.IntegerField(default=0)
    created_by = models.CharField(max_length=254, blank=True)
    updated_by = models.CharField(max_length=254, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["month", "section", "sort", "id"]
        indexes = [models.Index(fields=["month", "section"])]

    def __str__(self):
        return f"MBR {self.month:%Y-%m} {self.section}: {self.title}"
