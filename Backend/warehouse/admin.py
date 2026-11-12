from django.contrib import admin

from . import models

for m in [models.Region, models.State, models.Asm, models.Distributor, models.Pincode, models.Category,
          models.Product, models.Target, models.DataQualityIssue]:
    admin.site.register(m)


@admin.register(models.Retailer)
class RetailerAdmin(admin.ModelAdmin):
    list_display = ["name", "phone", "state", "kyc_status", "orders_count", "last_order_date"]
    search_fields = ["name", "phone", "gstin"]
    list_filter = ["kyc_status", "state"]


@admin.register(models.Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["display_id", "placed_at", "retailer", "distributor", "status", "payment_status", "gross_value"]
    search_fields = ["display_id", "source_id"]
    list_filter = ["status", "payment_status"]
    raw_id_fields = ["retailer"]
