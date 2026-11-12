# TechnoDirect Live Dashboard — Build Plan

Sources: `TD_Live_Dashboard_Reqs.pdf` (requirements), `TD_DataDeck.pdf` (strategic review — the metrics we automate),
`technodirect-master-prd_v1.pdf` (system context).

## Decisions (confirmed with business owner, 11 Nov 2026)
| Topic | Decision |
|---|---|
| Order/retailer data | Read-only Postgres user / RDS read replica on the Medusa backend DB, incremental sync |
| Current integrations | Medusa read replica, Google Sheets (CRM complaint tracker), Channel Konnect stock. PayU, settlement sheet and CleverTap deferred |
| Targets & mappings | Maintained in the dashboard Admin pages, Excel template upload, versioned, effective-dated, audited |
| Access | Master admin creates users, custom roles and permissions; each user gets a data scope (all / regions / states / ASMs / distributors) |
| Stack | React (Vite + TS) · Django + DRF + Celery · AWS RDS PostgreSQL (warehouse) · ElastiCache Redis · S3/CloudFront · SES |

## Architecture
```
Medusa DB (read replica) ─┐
PayU API                  │   Celery workers (incremental, watermark per source,      AWS RDS Postgres
Google Sheets API         ├─▶ retries, SyncRun log)                              ─▶   core star schema + marts
Channel Konnect           │                                                         (derived nightly + on each sync)
CleverTap API            ─┘                                                                  │
                                                                                     Django REST API (JWT, RBAC,
                     Celery beat ─▶ daily MIS (SES email / WhatsApp webhook)          row-level scope, export, audit)
                                  ─▶ alert rules evaluation (every 15 min)                    │
                                                                                     React SPA (TanStack Query polling)
```
**Refresh schedule:** all sources are refreshed twice a day, at **10:00 and 18:00 IST** (env `SYNC_TIMES`), in one chained job:
Medusa → PayU → CRM sheet → Channel Konnect → derivations → cache invalidation. Admins with `trigger_sync` can force a refresh from Data Health.

Rule: no dashboard request touches a source system. Every number is read from the warehouse and every tile shows its freshness.

## Data model (warehouse, Django-managed)
- Dimensions: `Region`, `State`, `Pincode`(→state, ASM), `Asm`, `Distributor`, `Retailer` (KYC status, pincode, warm/cold match flag, tier), `Product` (style, category L1–L3, pack size), `ProductVariant` (sku, size, mrp).
- Facts: `Order` (gross value, status, payment status, payment mode, platform, distributor, split group, timestamps for placed/confirmed/shipped/delivered/cancelled), `OrderLine`, `LoyaltyEvent` (signed points per retailer event), `Payment`, `Refund`, `InventorySnapshot` (daily per distributor×sku, from CK), `CrmTicket`, `AppEventDaily` (CleverTap).
- Derived: `RetailerMonth` (status per retailer per month: new / retained / reactivated / lost; sales, orders), `Target` (month × scope), `DataQualityIssue`, `SyncRun`, `AlertRule`, `AlertEvent`, `AuditLog`.

## Metric definitions (defaults — editable in Metric Dictionary page)
- **Sales** = gross order value (order `total`, incl. taxes/charges), payment captured, excluding cancelled. Labelled "Gross order value" everywhere. Net sales = gross − refunds (shown when PayU refunds synced).
- **Active retailer (month)** = ≥1 qualifying order in month. **New** = first-ever order in month. **Retained** = active this and previous month. **Reactivated** = active this month, not previous, not new. **Lost** = active previous month, not this.
- **Inactive buckets** = days since last order 30/60/90+. **Never ordered** = KYC approved, zero orders; warm if matched to BlueOrigin ledger.
- **Split order** = orders sharing a parent cart/split group; counted once in order counts at the cart level, per distributor in distributor views.
- Financial year April–March, timezone IST, currency formatting lakh/crore.

## Pages
1. Executive Overview · 2. Retailer Funnel · 3. Distributor & Territory · 4. Orders & Payments · 5. Product & Inventory · 6. Retention & Growth · 7. Loyalty Points · 8. Data Health · 9. Admin (Users & Roles, Targets, Mappings, Alerts, Metric dictionary, Audit log).

## Phases (current build scope — confirmed 11 Nov 2026)
- P0: users/roles/scope, Medusa sync, warehouse, Overview, Funnel, Distributor & Territory, targets admin, Data Health.
- P1: Orders & Fulfilment (no payments), Products, CRM Google Sheet.
- P1: Inventory (Channel Konnect), Retention & cohorts.
- PayU (sales/order data only): transactions every 5 min → payment status/mode per order, live "today" strip, payment success/failure and mode mix, paid-but-no-order and order-without-PayU checks.
- **Deferred (not built now):** PayU settlement, payouts and refunds, settlement sheet, alerts + daily MIS (email/WhatsApp), CleverTap funnel, forecasting.
  Sales basis: gross value of non-cancelled orders with captured payment (PayU-verified, Medusa fallback), before returns.

## Data loading: CSV exports (13 Nov 2026)
All synthetic demo data (backend seeder and frontend mock mode) has been removed. Until the live connections are in place,
the warehouse is loaded from the data team's exports with `manage.py import_csv_data` (files in `Backend/data/import/`,
upsert, re-runnable). Column interpretation is documented at the top of `Backend/ingestion/csv_import.py`. Derived from the data:
- Product file `price` = MRP per box; every sales line is billed at exactly 60% of MRP, stored as `ProductVariant.price`.
- Customer `distributor_name` = "P1, P2" serviceable distributors; P1 is the retailer's mapped distributor.
- Inventory uses short distributor names ("Heera"); matched to the full names and kept in `Distributor.aliases`.
- No pincode → state table in the exports: the state comes from the PIN prefix (`warehouse/geo.py`) until the Medusa `pincode` table is connected.
- Regions default to South 1 / South 2 / South 3 / East / West / North by state; editable in Admin → Mappings.

When the Medusa replica is connected: before its first backfill, delete the orders loaded from CSV (`source_id`
starting `csv:`) so they are not counted twice. Retailers, products and variants carry the Medusa ids and update in place;
distributors loaded from CSV are adopted by name/alias on the first Medusa distributor sync.

## Open items needing business input
- Exact Medusa table/field names (edit `Backend/ingestion/connectors/medusa_queries.py`).
- Alert thresholds and recipients (configurable in Admin → Alerts).
- Reconciliation tolerance vs. existing MIS (default 1%).
