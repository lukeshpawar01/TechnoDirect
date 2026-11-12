# TechnoDirect Live Dashboard – Backend

Django 5 + DRF + Celery API behind the TechnoDirect business dashboard. Spec: `../docs/PLAN.md`, `../docs/API_CONTRACT.md`.

**Rule:** no dashboard request touches a source system. Celery copies Medusa, PayU, the CRM Google Sheet and
Channel Konnect into a warehouse schema. Every API response is read from that warehouse and reports its freshness.

## Layout
```
technodirect/   settings (django-environ), urls, celery app + beat schedule, DB router (medusa alias never migrated)
accounts/       email-login User (is_master_admin, Role, data scope), HasPerm('code'), scope helper, AuditLog,
                create_master_admin command, /auth/* and /admin/* endpoints
warehouse/      dimensions, facts and derived tables (Region, State, Asm, Distributor, Pincode, Category, Product,
                ProductVariant, Retailer, Order, OrderLine, Payment, InventorySnapshot, CrmTicket, RetailerMonth,
                Target, DataQualityIssue)
ingestion/      connectors/ (medusa.py + medusa_queries.py, payu.py, google_sheets.py, channel_konnect.py),
                SyncRun / SyncWatermark, payments_link.py (PayU <-> order matching), tasks.refresh_all, run_sync command
analytics/      filters.py (presets, FY/QTD in IST, compare period, scope intersection), envelope + freshness,
                cache (Redis/locmem, invalidated by refresh), export (csv/xlsx), derivations (RetailerMonth, DQ checks),
                every page endpoint, seed_demo_data command
masters/        targets / ASMs / pincodes / regions / states / reconciliation CRUD, xlsx template + upload, metric dictionary
```

## Local setup (Windows / PowerShell)
```powershell
cd Backend
py -3.12 -m venv .venv            # or: python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env       # then set MASTER_ADMIN_EMAIL / MASTER_ADMIN_PASSWORD
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py create_master_admin
.\.venv\Scripts\python.exe manage.py seed_demo_data      # synthetic, demo-ready data (about 30 s)
.\.venv\Scripts\python.exe manage.py runserver 8000
.\.venv\Scripts\python.exe manage.py test
```
With placeholder values (`REPLACE_ME`), the backend falls back to these local defaults:
* `DATABASE_URL` → SQLite `db.sqlite3`
* `REDIS_URL` → in-process cache, with Celery tasks running inline (eager)
* each connector → its `SyncRun` is recorded with status `not_configured`

Demo users from `seed_demo_data` all use the password `Demo@12345`:
* `head@technodirect.local` (all scope)
* `rm.south2@technodirect.local` (scope: region South 2)
* `asm.ka@technodirect.local` (scope: ASM01)
* `heera@technodirect.local` (scope: distributor Heera Exports)

Useful commands:
* `manage.py run_sync all|medusa|payu|google_sheets|channel_konnect` runs a sync inline.
* `POST /api/data-health/sync/ {"source":"all"}` does the same from the UI. It needs the `trigger_sync` permission.

## Refresh schedule
Data refreshes **twice a day at `SYNC_TIMES` (default `10:00,18:00` IST)**. Each refresh runs one chained Celery job,
`ingestion.tasks.refresh_all`:

`Medusa → PayU → CRM Google Sheet → Channel Konnect → derivations (payment reconciliation, retailer aggregates, RetailerMonth, DQ checks) → cache invalidation`

* Every step writes its own `SyncRun`. A failed step does not stop the steps after it.
* Each connector is incremental, using a per-entity watermark in `SyncWatermark`, and upserts its rows.
* Every envelope's `meta` includes `last_refresh_at`, `next_refresh_at` and per-source `freshness`:
  * `ok`: the last scheduled run succeeded.
  * `stale`: a scheduled slot was missed by more than `REFRESH_GRACE_MINUTES` (default 30).
  * `failed`: the last run errored.
* Analytics responses are cached per (endpoint, user scope, filters) until the next refresh.

## API conventions (implemented)
* Analytics and detail endpoints return `{data, meta}`, where `meta` holds:
  * `sales_basis`, `as_of`
  * `period` (`from`, `to`, `label`, `preset`, `compare_from`, `compare_to`)
  * `freshness[]`, `last_refresh_at`, `next_refresh_at`
* Lists return `{count, next, previous, results}` and accept:
  * `page`, `page_size` (default 50, max 1000)
  * `ordering=-field`, `search=`
  * `export=csv|xlsx` (needs the `export_data` permission)
* Analytics pages export one table with `?export=csv&table=<key>`, for example `/products/?export=csv&table=bottom_articles`.
* Percentages and shares are on a 0–100 scale. Money is in INR rupees. Dates are IST.
* Sales = gross order value of non-cancelled orders whose payment is captured. The payment state comes from the PayU
  transaction when one is linked, otherwise from the Medusa payment status.

## Connecting the real sources
### Medusa read replica
1. Ask the AWS team for the read-only role described in `../docs/AWS_DATA_ACCESS_REQUEST.md`
   (23 tables, column-level grants where tables hold secrets, ready-to-run SQL included).
2. Set `MEDUSA_DATABASE_URL=postgres://td_dashboard_ro:...@<replica-host>:5432/<db>`, plus
   `MEDUSA_AMOUNT_DIVISOR` (100 if money is in paise, 1 if rupees) and `MEDUSA_NAIVE_TZ` (UTC or Asia/Kolkata).
3. The SQL in `ingestion/connectors/medusa_queries.py` is written against the real TechnoDirect schema
   (`tc_distributor`, `ts_distributor_serviceability`, `customer.kyc`, `product.ts_style` / `ts_pcPerUnit`,
   `order.distributor_id` / `shipped_at` / `delivered_at`, `ts_product_variant_inventory`, `ts_pending_order_job`).
   Every query documents its output columns. `ingestion/tests.py` checks parameter escaping, that no query uses
   `SELECT *` (column grants would reject it) and that no secret column is read.
4. Run `python manage.py run_sync medusa` once; the first run backfills from 1 Jan 2024.

   The `medusa` alias is protected in three ways:
   * The router never migrates it.
   * The session sets `default_transaction_read_only=on` and `statement_timeout`.
   * Tests mirror it to the default database.

### PayU (sales transactions only)
Set `PAYU_MERCHANT_KEY` and `PAYU_MERCHANT_SALT`. The connector calls `get_Transaction_Details` (postservice) over
date windows and upserts one `Payment` per `mihpayid`.

Transactions are linked to orders in `ingestion/payments_link.py`:
* by merchant `txnid` against `Order.payment_ref`, or
* by order reference (`udf1` or `productinfo`, marked `TODO(TD)` in `payu.py`) against the cart, order id or display id.

Refunds, settlements and payouts are out of scope.

### CRM Google Sheet
1. Create a service account and share the sheet with its email.
2. Set `GOOGLE_SERVICE_ACCOUNT_JSON` (path to the key file), `CRM_SHEET_ID` and, optionally, `CRM_SHEET_TAB`.
3. Map the header names in `CRM_COLUMNS` in `ingestion/connectors/google_sheets.py`.

### Channel Konnect
Set `CK_BASE_URL`, `CK_API_KEY` and each distributor's `ck_code`. The endpoint and payload format are assumed;
adjust `fetch_distributor_stock` in `ingestion/connectors/channel_konnect.py` once the real API is known.

## AWS deployment
* **Warehouse:** RDS PostgreSQL 16, for example `db.t4g.medium` with Multi-AZ in prod. Set it as `DATABASE_URL` and run
  `manage.py migrate` once per release.
* **Medusa:** add an RDS read replica of the Medusa DB in the same VPC. Allow port 5432 in its security group only from
  the app's security group.
* **Redis:** ElastiCache Redis 7 (`REDIS_URL=redis://<primary-endpoint>:6379/0`). It is used for the cache and as the
  Celery broker.
* **Compute (ECS Fargate):** build this Dockerfile, push it to ECR, and run three services from the same image:
  * `web`: gunicorn, behind an ALB on `/api/*`, health check `/api/health/`
  * `worker`: `celery -A technodirect worker -l info`
  * `beat`: `celery -A technodirect beat --scheduler django_celery_beat.schedulers:DatabaseScheduler` — run **exactly one** task
* **Compute (EC2 alternative):** run `docker compose up -d` without the `db` and `redis` services, with the env vars
  pointing at RDS and ElastiCache.
* **Secrets:** keep them in SSM Parameter Store or Secrets Manager and inject them as environment variables. In
  production set `DEBUG=False` and a real `DJANGO_SECRET_KEY`. Set `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS` to the
  CloudFront domain.
* **Frontend:** the React build goes to S3 behind CloudFront. Route `/api/*` from CloudFront to the ALB.
