# TechnoDirect Dashboard: read-only data access request

**For:** AWS / database team  **From:** TD Operations (dashboard project)  **Date:** 12 Nov 2026

## What we need
A **read-only PostgreSQL login** on a **read replica** of the TechnoDirect Medusa database. The dashboard reads it
twice a day (10:00 and 18:00 IST) and copies the data into its own reporting database. It never writes to Medusa.

| Item | Request |
|---|---|
| Database | Read replica of the TechnoDirect Medusa Postgres DB (not the primary) |
| Login | New role `td_dashboard_ro` with `SELECT` only on the tables and columns below |
| Network | Allow the dashboard server's security group to reach the replica on port 5432, SSL required |
| Load | 2 incremental reads per day; each query uses `updated_at` filters; session is `read_only` with a 2-minute statement timeout |
| What to send back | Replica host, port, database name, username, password, so we can build the `MEDUSA_DATABASE_URL` connection string (share the password via a secure channel, not email) |

## Tables and columns requested (23 tables)

| Table | Columns | Used for |
|---|---|---|
| `customer` | id, email, first_name, last_name, phone, business_name, gst_number, udyam_number, ts_pincode, kyc, metadata, created_at, updated_at, deleted_at | Retailers, KYC funnel, territory |
| `address` | id, customer_id, company, phone, city, province, postal_code, created_at, updated_at, deleted_at | Retailer city / state fallback |
| `pincode` | id, pincode, district, state, delivery, created_at, updated_at | Pincode → state master |
| `tc_distributor` | id, business_name, gst_number, state, city, pincode, is_active, status, created_at, updated_at, deleted_at | Distributor master |
| `ts_distributor_serviceability` | all columns | Pincode → distributor (P1 / P2) |
| `product` | id, title, handle, status, type_id, ts_style, "ts_pcPerUnit", metadata, created_at, updated_at, deleted_at | Articles / styles, pieces per box |
| `product_variant` | id, product_id, sku, title, barcode, metadata, created_at, updated_at, deleted_at | SKU + size |
| `product_option` | id, title, product_id | Size option |
| `product_option_value` | id, value, option_id, variant_id, deleted_at | Size value |
| `product_category` | id, name, handle, parent_category_id, mpath | Category tree |
| `product_category_product` | all columns | Product → category |
| `product_type` | id, value | Product type (trackpants, t-shirts…) |
| `money_amount` | id, amount, currency_code, variant_id, price_list_id, min_quantity, deleted_at | Base selling price |
| `order` | id, display_id, status, fulfillment_status, payment_status, ts_order_status, distributor_id, cart_id, customer_id, ts_remark, metadata, created_at, updated_at, canceled_at, shipped_at, delivered_at | Orders, status, TAT |
| `line_item` | id, order_id, variant_id, unit_price, quantity, "ts_pcPerUnit", includes_tax, is_return | Order lines, units, value |
| `line_item_tax_line` | item_id, rate | Tax in order value |
| `shipping_method` | order_id, price | Delivery charge in order value |
| `fulfillment` | id, order_id, provider_id, tracking_numbers, created_at, shipped_at, canceled_at | Packed / shipped dates, AWB |
| `tracking_link` | fulfillment_id, tracking_number, deleted_at | AWB |
| `payment` | id, order_id, cart_id, data, captured_at, created_at | PayU transaction reference per order (`data` holds the gateway response) |
| `payment_session` | id, amount | Amount on stuck payments |
| `ts_product_variant_inventory` | distributor_id, product_variant_id, inventory_quantity, updated_at, deleted_at | Stock shown in the app, per distributor |
| `ts_pending_order_job` | id, cart_id, payment_session_id, order_id, status, attempt, error, refund_initiated_at, created_at, updated_at, deleted_at | "Payment succeeded, order missing" monitoring |

### Deliberately NOT requested
- **Secrets:** `customer.password_hash`, `customer.tc_api_token`, `tc_distributor.salt`, `salt_index`, `merchant_id`, `razorpay_id`, the whole `user` table, `payment_session.data`.
- **Out of current scope:** `settlement`, `refund`, `return*`, `claim_*`, `swap`, `loyalty_*`, `discount*`, `cart*`, `draft_order`, `gift_card*`, `notification*`, `invite`, `oauth`, `idempotency_key`, `batch_job`, `staged_job`, `store`, `region`, `tax_*`, `price_list*`, `customer_group*`, `stock_location*`, `inventory_*`, `reservation_item`.

Personal data note: retailer name, phone and email are needed for the inactive / never-ordered action lists. In the
dashboard, phone numbers are masked unless a user has the `view_pii` permission.

## Ready-to-run SQL (run on the primary; it replicates to the replica)
```sql
CREATE ROLE td_dashboard_ro LOGIN PASSWORD '<strong-password>'
  NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER ROLE td_dashboard_ro SET default_transaction_read_only = on;
ALTER ROLE td_dashboard_ro SET statement_timeout = '120s';
GRANT CONNECT ON DATABASE <medusa_db> TO td_dashboard_ro;
GRANT USAGE ON SCHEMA public TO td_dashboard_ro;

-- Whole tables (no sensitive columns)
GRANT SELECT ON pincode, ts_distributor_serviceability, product_option, product_option_value,
  product_category, product_category_product, product_type, money_amount, "order", line_item,
  line_item_tax_line, shipping_method, fulfillment, tracking_link, ts_product_variant_inventory,
  ts_pending_order_job, product, product_variant, address
TO td_dashboard_ro;

-- Column-level grants where the table holds secrets
GRANT SELECT (id, email, first_name, last_name, phone, business_name, gst_number, udyam_number,
              ts_pincode, kyc, metadata, created_at, updated_at, deleted_at)
  ON customer TO td_dashboard_ro;
GRANT SELECT (id, business_name, gst_number, state, city, pincode, is_active, status,
              created_at, updated_at, deleted_at)
  ON tc_distributor TO td_dashboard_ro;
GRANT SELECT (id, order_id, cart_id, data, captured_at, created_at) ON payment TO td_dashboard_ro;
GRANT SELECT (id, amount) ON payment_session TO td_dashboard_ro;
```

## Questions for the team (please answer with the credentials)
1. Are money columns (`line_item.unit_price`, `money_amount.amount`, `shipping_method.price`) stored in **paise** (Medusa default) or whole rupees?
2. `order.shipped_at` / `delivered_at` are `timestamp without time zone`. Are they stored in **UTC** or **IST**?
3. What are the values of the `ts_order_status` enum, and of `ts_pending_order_job.status`?
4. When one checkout is split across two distributors, how are the resulting orders linked: same `payment.data.txnid`, `order.metadata.parent_cart_id`, or something else?
5. Which keys does `payment.data` hold for PayU (we expect `txnid` and `mihpayid`)?
6. Is MRP stored anywhere (`product_variant.metadata.mrp`?), and is there a KYC approval date anywhere (e.g. `customer.metadata`)?
