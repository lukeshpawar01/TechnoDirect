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
ingestion/      connectors/ (supabase.py + supabase_queries.py = TD data, payu.py, google_sheets.py, channel_konnect.py),
                td_import.py (TD data -> warehouse mapping), normalize.py (shared parsing helpers), scheduler.py
                (automatic 10:00 / 18:00 refresh), SyncRun / SyncWatermark, payments_link.py (PayU <-> order matching),
                tasks.refresh_all, run_sync / scheduled_refresh / supabase_live / supabase_check commands
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
.\.venv\Scripts\python.exe manage.py supabase_live --force   # TD data from Supabase (SUPABASE_DB_* in .env, ~3 min)
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

## TD data
TD data (retailers, distributors, products, orders, order lines, stock and loyalty) comes only from Supabase. See
*Connecting the real sources → TD data on Supabase* below. There are no CSV exports to load any more.

Each import keeps what admins maintain: regions, a state's region, ASMs, ASM per pincode, a distributor's ASM / state /
region once set, and targets. Distributor spellings that differ ("Heera" vs "HEERA EXPORTS INC") are matched
automatically and stored in `Distributor.aliases`. How each column is interpreted is listed at the top of
`ingestion/td_import.py`.

Useful commands:
* `manage.py run_sync all|supabase|payu|google_sheets|channel_konnect` runs a sync inline.
* `manage.py supabase_live [--force]` imports TD data from Supabase now (only if it changed, unless `--force`).
* `POST /api/data-health/sync/ {"source":"all"}` does the same from the UI. It needs the `trigger_sync` permission.

## Refresh schedule
Data refreshes **automatically at `SYNC_TIMES` (default `10:00,18:00` IST)**. The web server runs the refresh itself
(`ingestion/scheduler.py`), so it works the same way on a laptop (`runserver`), on the Windows server (`serve.py`) or
on Render or any other host (gunicorn). No Task Scheduler, cron, Celery or Redis is needed.

* A background thread starts with the server (`technodirect/wsgi.py`, `serve.py`) and checks once a minute.
* When a slot has passed with no refresh since, it runs `manage.py scheduled_refresh`. A server that was off or asleep
  at 10:00 therefore catches up within a minute of starting.
* Several server processes never run the same slot twice. `ingestion/locks.py` lets one through, and the others then
  see its `SyncRun`.
* From the 27th, 11:00 IST, it also runs the TD Target Forecaster for next month, if it hasn't run yet.
* `AUTO_REFRESH=false` turns it off, for example for a second server pointed at the same database. Refreshing by hand
  still works: the **Refresh** button, `manage.py scheduled_refresh` or `manage.py supabase_live`.

The refresh runs these steps in order:

`Supabase (TD data) → PayU → CRM Google Sheet → Channel Konnect → BlueOrigin (Dropbox) → settlement tracker → distributor stock sheet → derivations (payment reconciliation, retailer aggregates, RetailerMonth, DQ checks) → cache invalidation`

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
  transaction when one is linked, otherwise from the TD app's own payment status.

## Connecting the real sources
### TD data on Supabase
Supabase (project "technosport", schema `public`) holds the ID-keyed TD export tables: `orders`, `sales`, `customers`,
`distributors`, `products`, `inventory_snapshot` and `loyalty_ledger`, plus its loader's `etl_watermark`.

`ingestion/connectors/supabase.py` reads them through a read-only login and passes the rows to the TD mapping
(`ingestion/td_import.py`).

1. Run `deploy/supabase_readonly.sql` in Supabase > SQL Editor. It creates `td_dashboard_ro`, which can only run select on
   those tables. The script is generated by `python manage.py supabase_check --grant-sql`.
2. In `.env`, fill in `SUPABASE_DB_HOST`, `SUPABASE_DB_USER` (`td_dashboard_ro.<project-ref>`) and `SUPABASE_DB_PASSWORD`,
   taken from Supabase > Connect > Session pooler.
3. Run `python manage.py supabase_check`. It confirms the session is read-only and uses SSL, that every table and column
   is present, and shows row counts and Supabase's last refresh.
4. Run `python manage.py supabase_live --force` once for the first import. After that, the server's 10:00 / 18:00
   refresh (see *Refresh schedule*) pulls from Supabase by itself and skips the CSV folder. Supabase is imported only
   when its `etl_watermark` changed. `supabase_live` remains available as a manual "import now".

   The `supabase` alias is protected in three ways:
   * The router never migrates it.
   * The session sets `default_transaction_read_only=on` and `statement_timeout`.
   * Tests mirror it to the default database.

### Dashboard edits kept in Supabase
What admins change in the dashboard is backed up to Supabase, laid out like the dashboard (`ingestion/edit_store.py`).
There is one schema ("folder") per module, and one table per kind of record, with real columns plus `_synced_at`, like
the TD tables:

| Schema (module) | Tables |
|---|---|
| `region_asm_performance` | `targets`, `asms`, `rsms`, `asm_handovers`, `field_staff`, `tracked_distributors`, `target_forecasts` |
| `distributors` | `distributors` (ASM, state and aliases set in the dashboard) |
| `mappings` | `regions`, `states`, `pincodes` |
| `admin` | `users`, `roles`, `audit_log`, `metric_definitions`, `reconciliation_refs` |

Everything else is rebuilt from the sources, so it is not copied. The login creates its own tables, and a field added
to the dashboard later becomes a new column automatically.

1. Run `deploy/supabase_edits.sql` in Supabase > SQL Editor (the password is set the first time only). It creates the
   four schemas and the login `td_dashboard_rw`, which can only use those schemas.
2. In `.env`, set `SUPABASE_EDITS_USER=td_dashboard_rw.<project-ref>` and `SUPABASE_EDITS_PASSWORD`.
3. Run `python manage.py edits_backup --check`, then `python manage.py edits_backup` for the first full copy.

After that it is automatic:
* A change made through the API is sent within about 5 seconds.
* Every 15 minutes the server sends anything else that changed, for example from commands. Only changed rows are sent.
* A new server with an empty database (Render, a new PC) restores the edits on its first start, before its first data
  import. By hand: `manage.py edits_restore`, or `edits_restore --force` to overwrite a database that already has users.

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

## Render deployment
* **Web service:** the build installs `requirements.txt`, runs `migrate` and builds the frontend. Start it with
  `gunicorn technodirect.wsgi --workers 2 --threads 4 --timeout 300`. Do **not** add `--preload`: the refresh thread
  must start inside each worker, after the fork.
* **Keep it awake:** use an always-on instance type. Free instances sleep when idle. The refresh still catches up when
  the service wakes, but only then.
* **Database:**
  * SQLite needs a Render persistent disk mounted where `db.sqlite3` lives, and one instance.
  * Or set `DATABASE_URL` to a Postgres database (Render Postgres, or a separate Supabase project) and run
    `manage.py migrate`.
* **Environment:** put the `.env` values in Render's environment settings:
  * `SUPABASE_DB_*`, `SUPABASE_EDITS_*` (so the dashboard edits are restored on the first start) and `DROPBOX_*`;
  * `DJANGO_SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS`.
* **Not available on Render yet:** the settlement tracker and the distributor stock sheet are read from CSV files on
  the office PC (`SETTLEMENT_TRACKER`, `DISTRIBUTOR_SYNC_SHEET`). Until they come from Google Sheets or Supabase, those
  two steps report "not configured".

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
