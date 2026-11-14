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
                ProductVariant, Retailer, Order, OrderLine, Payment, InventorySnapshot, CrmTicket, LoyaltyEvent,
                RetailerMonth, Target, DataQualityIssue); geo.py = pincode -> state reference + default regions
ingestion/      connectors/ (medusa.py + medusa_queries.py, payu.py, google_sheets.py, channel_konnect.py),
                SyncRun / SyncWatermark, payments_link.py (PayU <-> order matching), tasks.refresh_all, run_sync command,
                csv_import.py + import_csv_data command (loads the TD_*.csv exports)
analytics/      filters.py (presets, FY/QTD in IST, compare period, scope intersection), envelope + freshness,
                cache (Redis/locmem, invalidated by refresh), export (csv/xlsx), derivations (RetailerMonth, DQ checks),
                every page endpoint
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
.\.venv\Scripts\python.exe manage.py import_csv_data     # loads data/import/TD_*.csv (about 1 min)
.\.venv\Scripts\python.exe manage.py runserver 8000
.\.venv\Scripts\python.exe manage.py test
```
With placeholder values (`REPLACE_ME`), the backend falls back to these local defaults:
* `DATABASE_URL` → SQLite `db.sqlite3`
* `REDIS_URL` → in-process cache, with Celery tasks running inline (eager)
* each connector → its `SyncRun` is recorded with status `not_configured`

There is no demo or synthetic data. Users are created by the master admin on Admin > Users.

## Monthly ASM performance tracker
Each month's tracker CSV (Distributor, Region, ASM, Total Target, ...) sets the ASMs, each distributor's ASM and
region (South / East / West / North), and that month's sales targets per distributor, ASM, region and overall:
```powershell
.\.venv\Scripts\python.exe manage.py import_asm_tracker "data/import/asm_tracker/<file>.csv" --month 2026-12 --dry-run   # check matching
.\.venv\Scripts\python.exe manage.py import_asm_tracker "data/import/asm_tracker/<file>.csv" --month 2026-12
```
Actual sales are always computed from orders; an order counts for the ASM of the distributor that fulfilled it.

## Techno AI assistant (Ollama)
A chatbot (bottom-right "Techno AI" button) that explains dashboard metrics and answers questions from the data.
* **Authorisation:** it never queries the database itself. It calls the dashboard's own API endpoints *as the
  signed-in user*, so role permissions and data scope apply exactly as on screen; modules the role cannot see are
  never fetched and the answer says so. Using it needs the `use_assistant` permission (granted to existing roles
  that can view a dashboard). Every question is written to the Audit Log.
* **Flow:** the model plans which permitted sources to read (max 4) → they are fetched and trimmed → the model
  answers only from those numbers as JSON (headline, what to do, data points with R1/R2 references, metric
  explanation, follow-ups).
* **Configuration (`.env`, restart after changes):** `OLLAMA_BASE_URL` (`https://ollama.com` for Ollama Cloud or
  `http://localhost:11434` self-hosted), `OLLAMA_API_KEY` (Ollama Cloud key; blank when self-hosted),
  `OLLAMA_MODEL` (e.g. `gpt-oss:120b`), optional `OLLAMA_TIMEOUT`, `OLLAMA_NUM_CTX`, `ASSISTANT_RATE_LIMIT`,
  `ASSISTANT_ENABLED`.

## Login with emailed OTP
Signing in takes two steps: email + password, then a 6-digit code emailed to the user (valid 5 minutes,
5 wrong tries, resend after 30 s, at most 5 emails per sign-in; only an HMAC of the code is stored).
Mail goes through Django's SMTP backend; set these in `.env` and restart the backend:

| Variable | Gmail / Google Workspace value |
|---|---|
| `EMAIL_HOST` / `EMAIL_PORT` / `EMAIL_USE_TLS` | `smtp.gmail.com` / `587` / `True` |
| `EMAIL_HOST_USER` | the sending address, e.g. `dashboard@technosport.in` |
| `EMAIL_HOST_PASSWORD` | a Google **App Password** for that account (Google Account > Security > 2-Step Verification > App passwords) |
| `DEFAULT_FROM_EMAIL` | `TechnoDirect Dashboard <dashboard@technosport.in>` (must be that account or one of its aliases) |
| `LOGIN_OTP_ENABLED` | `True`; `False` turns the second step off |

While `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` are `REPLACE_ME` and `DEBUG=True`, the email (with the code) is printed
in the `runserver` console instead of being sent.

## Loading the CSV exports (until the live connections are in place)
Put the data team's exports in `data/import/` (git-ignored, they contain retailer PII). The importer picks the
largest file whose name contains `customer`, `product`, `inventory`, `sales` or `loyal`:

| Export | Loaded into |
|---|---|
| `TD_Customer_Data.csv` | Retailer (KYC, GST, Udyam, pincode, P1 distributor), Pincode (P1 / P2), Distributor |
| `TD_product data.csv` | Product (style, category I / II / III, launch date), ProductVariant (MRP), Category |
| `TD_Inventory _Data.csv` | InventorySnapshot (stock per distributor x SKU), pieces per box, SKU codes |
| `TD_Sales_Data*.csv` | Order + OrderLine (status from dispatch / delivered dates, payment mode, platform) |
| `TD_Loyality_Point*.csv` | LoyaltyEvent (welcome bonus, points earned, points redeemed) |

```powershell
.\.venv\Scripts\python.exe manage.py import_csv_data                  # upsert; safe to re-run with newer files
.\.venv\Scripts\python.exe manage.py import_csv_data --dir C:\exports  # another folder
.\.venv\Scripts\python.exe manage.py import_csv_data --wipe-all       # delete ALL warehouse rows first
```
Re-imports keep what admins maintain: regions, a state's region, ASMs, ASM per pincode, a distributor's ASM / state /
region once set, and targets. Distributor spellings that differ between exports ("Heera" vs "HEERA EXPORTS INC")
are matched automatically and stored in `Distributor.aliases`. How each source column is interpreted is listed at
the top of `ingestion/csv_import.py`.

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
