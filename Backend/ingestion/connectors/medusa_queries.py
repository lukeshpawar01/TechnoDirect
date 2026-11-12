"""ALL SQL run against the TechnoDirect Medusa (v1) read replica lives in this file.

Written against the real TechnoDirect schema (SQL_Tables.csv, Nov 2026). Tables read:

  customer, address, pincode                                -> retailers + geography
  tc_distributor, ts_distributor_serviceability             -> distributors + pincode routing (P1/P2)
  product, product_variant, product_option, product_option_value,
  product_category, product_category_product, product_type, money_amount -> catalogue
  "order", line_item, line_item_tax_line, shipping_method,
  fulfillment, tracking_link, payment                        -> orders & lines
  ts_product_variant_inventory                               -> app stock per distributor
  ts_pending_order_job                                       -> "paid but order missing" recovery jobs

Columns deliberately NEVER selected (secrets / PII not needed): customer.password_hash,
customer.tc_api_token, tc_distributor.salt, tc_distributor.salt_index, tc_distributor.merchant_id,
tc_distributor.razorpay_id, the whole "user" table, payment_session.data.

Conventions
  * Every query takes %(since)s (timestamptz incremental watermark; the connector subtracts an overlap)
    and %(div)s (money divisor: Medusa stores minor units, so 100 -> rupees; set
    MEDUSA_AMOUNT_DIVISOR=1 in .env if TechnoDirect stores whole rupees).
  * Each query MUST return exactly the documented output columns.
  * "order".shipped_at / delivered_at and settlement-era columns are `timestamp WITHOUT time zone`;
    they are interpreted as UTC (Medusa/Node default). Change MEDUSA_NAIVE_TZ if they are IST.
"""

# ---------------------------------------------------------------------------
# Distributors  (tc_distributor)
# Output: source_id, code, name, state_name, city, pincode, gstin, ck_code, is_active,
#         onboarded_on, updated_at
# ck_code is not stored in Medusa -> maintained in the dashboard (Admin > Mappings) when CK is enabled.
# ---------------------------------------------------------------------------
DISTRIBUTORS_SQL = """
SELECT d.id::text                                   AS source_id,
       'D' || d.id::text                            AS code,
       COALESCE(NULLIF(TRIM(d.business_name), ''), 'Distributor ' || d.id) AS name,
       INITCAP(TRIM(d.state))                       AS state_name,
       INITCAP(TRIM(d.city))                        AS city,
       TRIM(d.pincode)                              AS pincode,
       UPPER(TRIM(d.gst_number))                    AS gstin,
       NULL::text                                   AS ck_code,
       (d.deleted_at IS NULL AND COALESCE(d.is_active, true))  AS is_active,
       (d.created_at AT TIME ZONE 'Asia/Kolkata')::date        AS onboarded_on,
       GREATEST(d.updated_at, COALESCE(d.deleted_at, d.updated_at)) AS updated_at
FROM   tc_distributor d
WHERE  GREATEST(d.updated_at, COALESCE(d.deleted_at, d.updated_at)) >= %(since)s
"""

# ---------------------------------------------------------------------------
# India Post pincode master (pincode table has one row per post office -> pick one per pincode)
# Output: pincode, district, city, state_name, updated_at
# ---------------------------------------------------------------------------
PINCODES_SQL = """
SELECT DISTINCT ON (TRIM(p.pincode))
       TRIM(p.pincode)              AS pincode,
       INITCAP(TRIM(p.district))    AS district,
       INITCAP(TRIM(p.district))    AS city,
       INITCAP(TRIM(p.state))       AS state_name,
       COALESCE(p.updated_at, p.created_at) AS updated_at
FROM   pincode p
WHERE  p.pincode ~ '^[1-9][0-9]{5}$'
  AND  COALESCE(p.updated_at, p.created_at, now()) >= %(since)s
ORDER  BY TRIM(p.pincode), (p.delivery ILIKE 'delivery') DESC, p.id
"""

# ---------------------------------------------------------------------------
# Distributor serviceability (pincode -> distributor). There is no tier column, so per pincode the
# earliest-created live mapping is P1 and the next one is P2 (matches how P2 was added later).
# Always a full read (small table) so deletions are reflected.
# Output: pincode, distributor_source_id, rank (1 = P1, 2 = P2)
# ---------------------------------------------------------------------------
SERVICEABILITY_SQL = """
SELECT pincode, distributor_source_id, rnk AS rank
FROM (
    SELECT TRIM(s.pincode)                AS pincode,
           s.distributor_id::text         AS distributor_source_id,
           ROW_NUMBER() OVER (PARTITION BY TRIM(s.pincode) ORDER BY s.created_at, s.id) AS rnk
    FROM   ts_distributor_serviceability s
    WHERE  s.deleted_at IS NULL
) x
WHERE rnk <= 2
"""

# ---------------------------------------------------------------------------
# Retailers  (customer)  -- includes non-KYC sign-ups so the funnel has its top stage.
# KYC is a boolean in Medusa (customer.kyc). Status derivation:
#   kyc = true                                  -> approved
#   kyc = false and GST / Udyam number entered  -> pending (submitted, not verified)
#   otherwise                                   -> not_submitted
# There is no KYC timestamp column; kyc_approved_at uses metadata if present, else the connector
# stamps the first sync that sees kyc=true (customer.created_at on the initial backfill).
# Output: source_id, name, owner_name, phone, email, gstin, pincode, city, state_name, kyc_status,
#         signed_up_at, kyc_submitted_at, kyc_approved_at, warm_match, tier, updated_at
# ---------------------------------------------------------------------------
RETAILERS_SQL = """
SELECT c.id                                                     AS source_id,
       COALESCE(NULLIF(TRIM(c.business_name), ''),
                NULLIF(TRIM(a.company), ''),
                NULLIF(TRIM(COALESCE(c.first_name,'') || ' ' || COALESCE(c.last_name,'')), ''),
                c.phone)                                        AS name,
       TRIM(COALESCE(c.first_name,'') || ' ' || COALESCE(c.last_name,''))   AS owner_name,
       COALESCE(NULLIF(c.phone, ''), a.phone)                   AS phone,
       c.email                                                  AS email,
       UPPER(NULLIF(TRIM(c.gst_number), ''))                    AS gstin,
       COALESCE(NULLIF(TRIM(c.ts_pincode), ''), TRIM(a.postal_code))        AS pincode,
       INITCAP(COALESCE(NULLIF(TRIM(a.city), ''), pm.district))             AS city,
       INITCAP(COALESCE(pm.state, NULLIF(TRIM(a.province), '')))           AS state_name,
       CASE WHEN c.kyc IS TRUE THEN 'approved'
            WHEN NULLIF(TRIM(c.gst_number), '') IS NOT NULL
              OR NULLIF(TRIM(c.udyam_number), '') IS NOT NULL THEN 'pending'
            ELSE 'not_submitted' END                            AS kyc_status,
       c.created_at                                             AS signed_up_at,
       CASE WHEN NULLIF(TRIM(c.gst_number), '') IS NOT NULL
              OR NULLIF(TRIM(c.udyam_number), '') IS NOT NULL OR c.kyc IS TRUE
            THEN COALESCE(NULLIF(c.metadata ->> 'kyc_submitted_at', '')::timestamptz, c.created_at)
       END                                                      AS kyc_submitted_at,
       CASE WHEN c.kyc IS TRUE
            THEN NULLIF(c.metadata ->> 'kyc_approved_at', '')::timestamptz END AS kyc_approved_at,
       false                                                    AS warm_match,   -- BlueOrigin ledger not in Medusa
       NULL::text                                               AS tier,
       c.updated_at                                             AS updated_at
FROM   customer c
LEFT JOIN LATERAL (
       SELECT ad.company, ad.phone, ad.postal_code, ad.city, ad.province
       FROM   address ad
       WHERE  ad.customer_id = c.id AND ad.deleted_at IS NULL
       ORDER  BY ad.updated_at DESC
       LIMIT  1
) a ON TRUE
LEFT JOIN LATERAL (
       SELECT p.state, p.district FROM pincode p
       WHERE  p.pincode = COALESCE(NULLIF(TRIM(c.ts_pincode), ''), TRIM(a.postal_code))
       LIMIT  1
) pm ON TRUE
WHERE  c.deleted_at IS NULL
  AND  c.updated_at >= %(since)s
"""

# ---------------------------------------------------------------------------
# Products. Category tree comes from product_category.mpath ("rootId.childId.leafId.").
#   category      = <gender root> + <level-2>, e.g. "Men · Bottomwear"
#   category_l3   = leaf category, falling back to product_type (e.g. "Trackpants")
# Output: source_id, style, name, category_code, category_name, category_l1, category_l2, category_l3,
#         pack_size, launched_on, is_active, updated_at
# ---------------------------------------------------------------------------
PRODUCTS_SQL = """
SELECT p.id                                                   AS source_id,
       UPPER(COALESCE(NULLIF(TRIM(p.ts_style), ''), NULLIF(TRIM(p.handle), ''), p.id)) AS style,
       p.title                                                AS name,
       LOWER(COALESCE(root.handle, 'uncategorised')
             || COALESCE('-' || l2.handle, ''))               AS category_code,
       COALESCE(root.name, 'Uncategorised') || COALESCE(' · ' || l2.name, '') AS category_name,
       root.name                                              AS category_l1,
       l2.name                                                AS category_l2,
       COALESCE(CASE WHEN leaf.id NOT IN (root.id, COALESCE(l2.id, '')) THEN leaf.name END,
                pt.value)                                     AS category_l3,
       GREATEST(COALESCE(p."ts_pcPerUnit", 1), 1)             AS pack_size,
       (p.created_at AT TIME ZONE 'Asia/Kolkata')::date       AS launched_on,
       (p.deleted_at IS NULL AND p.status::text = 'published') AS is_active,
       GREATEST(p.updated_at, COALESCE(p.deleted_at, p.updated_at)) AS updated_at
FROM   product p
LEFT JOIN product_type pt ON pt.id = p.type_id
LEFT JOIN LATERAL (
       SELECT pc.id, pc.name, pc.mpath FROM product_category_product pcp
       JOIN   product_category pc ON pc.id = pcp.product_category_id
       WHERE  pcp.product_id = p.id
       ORDER  BY LENGTH(pc.mpath) DESC NULLS LAST            -- deepest (most specific) category
       LIMIT  1
) leaf ON TRUE
LEFT JOIN product_category root ON root.id = SPLIT_PART(leaf.mpath, '.', 1)
LEFT JOIN product_category l2   ON l2.id   = NULLIF(SPLIT_PART(leaf.mpath, '.', 2), '')
WHERE  GREATEST(p.updated_at, COALESCE(p.deleted_at, p.updated_at)) >= %(since)s
"""

# ---------------------------------------------------------------------------
# Variants (style + size). Price = INR base price from money_amount (no price list) = BOX price.
# MRP is not a column in Medusa; read from variant/product metadata if present.
# Output: source_id, product_source_id, sku, size, mrp, price, updated_at
# ---------------------------------------------------------------------------
VARIANTS_SQL = """
SELECT v.id                                         AS source_id,
       v.product_id                                 AS product_source_id,
       COALESCE(NULLIF(TRIM(v.sku), ''), v.id)      AS sku,
       COALESCE(size_val.value, v.title)            AS size,
       COALESCE(NULLIF(v.metadata ->> 'mrp', '')::numeric,
                NULLIF(p.metadata ->> 'mrp', '')::numeric, 0)  AS mrp,
       COALESCE(price.amount, 0) / %(div)s::numeric AS price,
       GREATEST(v.updated_at, COALESCE(v.deleted_at, v.updated_at)) AS updated_at
FROM   product_variant v
JOIN   product p ON p.id = v.product_id
LEFT JOIN LATERAL (
       SELECT pov.value FROM product_option_value pov
       JOIN   product_option po ON po.id = pov.option_id
       WHERE  pov.variant_id = v.id AND pov.deleted_at IS NULL AND po.title ILIKE 'size%%'
       LIMIT  1
) size_val ON TRUE
LEFT JOIN LATERAL (
       SELECT ma.amount FROM money_amount ma
       WHERE  ma.variant_id = v.id AND LOWER(ma.currency_code) = 'inr'
         AND  ma.price_list_id IS NULL AND ma.deleted_at IS NULL
       ORDER  BY ma.min_quantity NULLS FIRST
       LIMIT  1
) price ON TRUE
WHERE  GREATEST(v.updated_at, COALESCE(v.deleted_at, v.updated_at)) >= %(since)s
"""

# ---------------------------------------------------------------------------
# Orders. Medusa v1 stores no order total, so gross = line items (+ tax when prices exclude tax)
# + shipping. Loyalty-point redemptions are NOT deducted (the distributor is settled on full value).
# Split carts: one PayU payment covers all per-distributor orders of a cart, so the split group is
# metadata.parent_cart_id -> PayU txnid -> cart_id.
# Output: source_id, display_id, cart_id, customer_source_id, distributor_source_id, medusa_status,
#         fulfillment_status, payment_status, ts_order_status, ts_remark, gross_value, placed_at,
#         confirmed_at, shipped_at, delivered_at, cancelled_at, awb, courier, payment_ref, updated_at
# ---------------------------------------------------------------------------
ORDERS_SQL = """
WITH changed AS (
    SELECT o.id, o.display_id, o.cart_id, o.customer_id, o.distributor_id, o.status, o.fulfillment_status,
           o.payment_status, o.ts_order_status, o.ts_remark, o.metadata, o.created_at, o.updated_at,
           o.canceled_at, o.shipped_at, o.delivered_at
    FROM   "order" o
    WHERE  o.updated_at >= %(since)s
),
lines AS (
    SELECT li.order_id,
           SUM(li.unit_price * li.quantity) AS subtotal,
           SUM(CASE WHEN li.includes_tax THEN 0
                    ELSE li.unit_price * li.quantity * COALESCE(tx.rate, 0) / 100.0 END) AS tax
    FROM   line_item li
    JOIN   changed c ON c.id = li.order_id
    LEFT JOIN (SELECT item_id, SUM(rate) AS rate FROM line_item_tax_line GROUP BY item_id) tx
           ON tx.item_id = li.id
    WHERE  COALESCE(li.is_return, false) = false
    GROUP  BY li.order_id
),
ship AS (
    SELECT sm.order_id, SUM(sm.price) AS shipping
    FROM   shipping_method sm JOIN changed c ON c.id = sm.order_id
    GROUP  BY sm.order_id
),
ful AS (
    SELECT f.order_id,
           MIN(f.created_at)        AS packed_at,
           MIN(f.shipped_at)        AS shipped_at,
           MIN(COALESCE(tl.tracking_number, f.tracking_numbers ->> 0)) AS awb,
           MIN(f.provider_id)       AS courier
    FROM   fulfillment f
    JOIN   changed c ON c.id = f.order_id
    LEFT JOIN tracking_link tl ON tl.fulfillment_id = f.id AND tl.deleted_at IS NULL
    WHERE  f.canceled_at IS NULL
    GROUP  BY f.order_id
)
SELECT c.id                                                  AS source_id,
       c.display_id::text                                    AS display_id,
       COALESCE(NULLIF(c.metadata ->> 'parent_cart_id', ''),
                NULLIF(pay.data ->> 'txnid', ''),
                c.cart_id, c.id)                             AS cart_id,
       c.customer_id                                         AS customer_source_id,
       c.distributor_id::text                                AS distributor_source_id,
       c.status::text                                        AS medusa_status,
       c.fulfillment_status::text                            AS fulfillment_status,
       c.payment_status::text                                AS payment_status,
       c.ts_order_status::text                               AS ts_order_status,
       c.ts_remark                                           AS ts_remark,
       (COALESCE(l.subtotal, 0) + COALESCE(l.tax, 0) + COALESCE(s.shipping, 0)) / %(div)s::numeric AS gross_value,
       c.created_at                                          AS placed_at,
       f.packed_at                                           AS confirmed_at,
       COALESCE(c.shipped_at AT TIME ZONE %(naive_tz)s, f.shipped_at)  AS shipped_at,
       c.delivered_at AT TIME ZONE %(naive_tz)s              AS delivered_at,
       c.canceled_at                                         AS cancelled_at,
       f.awb                                                 AS awb,
       f.courier                                             AS courier,
       COALESCE(NULLIF(pay.data ->> 'txnid', ''), NULLIF(pay.data ->> 'mihpayid', '')) AS payment_ref,
       c.updated_at                                          AS updated_at
FROM   changed c
LEFT JOIN lines l ON l.order_id = c.id
LEFT JOIN ship  s ON s.order_id = c.id
LEFT JOIN ful   f ON f.order_id = c.id
LEFT JOIN LATERAL (
       SELECT p.data FROM payment p
       WHERE  p.order_id = c.id OR (c.cart_id IS NOT NULL AND p.cart_id = c.cart_id)
       ORDER  BY p.captured_at DESC NULLS LAST, p.created_at DESC
       LIMIT  1
) pay ON TRUE
"""

# ---------------------------------------------------------------------------
# Order lines. Medusa line quantity = BOXES and unit_price = BOX price; pieces per box is stored on
# the line (ts_pcPerUnit) with the product value as fallback.
# Output: source_id, order_source_id, variant_source_id, sku, boxes, pieces_per_box, total
# ---------------------------------------------------------------------------
ORDER_LINES_SQL = """
SELECT li.id                                                        AS source_id,
       li.order_id                                                  AS order_source_id,
       li.variant_id                                                AS variant_source_id,
       v.sku                                                        AS sku,
       li.quantity                                                  AS boxes,
       GREATEST(COALESCE(li."ts_pcPerUnit", p."ts_pcPerUnit", 1), 1) AS pieces_per_box,
       (li.unit_price * li.quantity) / %(div)s::numeric             AS total
FROM   line_item li
JOIN   "order" o ON o.id = li.order_id
LEFT JOIN product_variant v ON v.id = li.variant_id
LEFT JOIN product p ON p.id = v.product_id
WHERE  o.updated_at >= %(since)s
  AND  COALESCE(li.is_return, false) = false
"""

# ---------------------------------------------------------------------------
# App stock per distributor x variant (what retailers see, after the distributor's buffer).
# Full read each refresh (stock is a level, not a delta).
# Output: distributor_source_id, variant_source_id, sku, quantity, updated_at
# ---------------------------------------------------------------------------
INVENTORY_SQL = """
SELECT i.distributor_id::text        AS distributor_source_id,
       i.product_variant_id          AS variant_source_id,
       v.sku                         AS sku,
       COALESCE(i.inventory_quantity, 0) AS quantity,
       i.updated_at                  AS updated_at
FROM   ts_product_variant_inventory i
LEFT JOIN product_variant v ON v.id = i.product_variant_id
WHERE  i.deleted_at IS NULL
"""

# ---------------------------------------------------------------------------
# Pending-order recovery jobs (payment succeeded -> order creation). Only recent jobs are read.
# Output: source_id, cart_id, payment_session_id, order_source_id, status, attempt, error, amount,
#         refund_initiated_at, created_at, updated_at
# ---------------------------------------------------------------------------
PENDING_JOBS_SQL = """
SELECT j.id::text                AS source_id,
       j.cart_id                 AS cart_id,
       j.payment_session_id      AS payment_session_id,
       j.order_id                AS order_source_id,
       j.status::text            AS status,
       COALESCE(j.attempt, 0)    AS attempt,
       LEFT(j.error, 500)        AS error,
       ps.amount / %(div)s::numeric AS amount,
       j.refund_initiated_at     AS refund_initiated_at,
       j.created_at              AS created_at,
       j.updated_at              AS updated_at
FROM   ts_pending_order_job j
LEFT JOIN payment_session ps ON ps.id = j.payment_session_id
WHERE  j.deleted_at IS NULL
  AND  j.updated_at >= %(since)s
"""

# Medusa enum -> dashboard enum mappings ------------------------------------------------
PAYMENT_STATUS_MAP = {
    "captured": "captured",
    "partially_refunded": "partially_refunded",
    "refunded": "refunded",
    "awaiting": "awaiting",
    "not_paid": "not_paid",
    "canceled": "failed",
    "requires_action": "awaiting",
}
