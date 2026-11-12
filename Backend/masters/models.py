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
            "owner": "Business Analytics", "refresh": "Twice daily (10:00 & 18:00 IST)"})
