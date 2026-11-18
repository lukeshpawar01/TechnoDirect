"""The TD tables on Supabase (project "technosport", schema public) that the dashboard reads.

The rows are fed to the TD mapping (ingestion/td_import.py).

TABLES: importer kind -> (table, columns read). The read-only login is granted exactly these tables
(`manage.py supabase_check --grant-sql`).
"""

TABLES = {
    "distributor": ("distributors", ["distributor_id", "distributor_name", "gst_number", "city", "state", "pincode",
                                     "is_active", "created_at", "deleted_at"]),
    "customer": ("customers", ["customer_id", "email", "first_name", "last_name", "business_name", "phone",
                               "has_account", "kyc", "gst_number", "udyam_number", "ts_pincode", "city", "province",
                               "distributor_name", "is_test", "created_at", "updated_at", "deleted_at"]),
    "product": ("products", ["variant_id", "product_id", "sku", "style", "product_title", "size", "price",
                             "pcs_per_unit", "category_level_1", "category_level_2", "category_level_3", "fabric", "gsm",
                             "usp1", "usp2", "usp3", "usp4", "usp5", "usp6", "product_status", "is_deleted",
                             "launch_date"]),
    "order": ("orders", ["order_id", "display_id", "customer_id", "distributor_id", "ts_order_status",
                         "settlement_status", "order_date", "dispatch_date", "delivered_date", "units", "line_total",
                         "payu_amount", "points_redeemed", "total_amount", "pg_charges", "mode", "platform", "city",
                         "province", "updated_at"]),
    "sales": ("sales", ["sales_id", "order_key", "order_id", "order_date", "customer_id", "distributor_id",
                        "ts_order_status", "variant_id", "product_id", "size", "quantity", "pieces", "unit_price",
                        "line_amount"]),
    # app stock: only the latest snapshot day (the table may keep history)
    "inventory": ("inventory_snapshot", ["inventory_pk", "snapshot_date", "variant_id", "location_id",
                                         "stock_location", "distributor_id", "stock", "reserved", "available"]),
    "loyalty": ("loyalty_ledger", ["ledger_id", "customer_id", "order_id", "event", "total_points", "signed_points",
                                   "discount_value", "event_date"]),
}

# Supabase's own loader bookkeeping: when did each table last refresh (used to skip unchanged syncs)
WATERMARK_TABLE = ("etl_watermark", ["table_name", "last_success_at", "rows_fetched"])

READ_TABLES = {t: cols for t, cols in TABLES.values()} | {WATERMARK_TABLE[0]: WATERMARK_TABLE[1]}


def qident(name):
    return '"' + name.replace('"', '""') + '"'


def select_sql(kind):
    table, cols = TABLES[kind]
    sql = f"SELECT {', '.join(qident(c) for c in cols)} FROM {qident(table)}"
    if kind == "inventory":
        sql += f" WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM {qident(table)})"
    elif kind == "distributor":
        # sign-ups still in registration (no name, no orders) are not distributors yet
        sql += (" WHERE NULLIF(TRIM(distributor_name), '') IS NOT NULL"
                " AND COALESCE(status, '') <> 'registration_pending'")
    return sql


ETL_CHANGED_SQL = "SELECT MAX(last_success_at), MIN(last_success_at), COUNT(*) FROM etl_watermark"
