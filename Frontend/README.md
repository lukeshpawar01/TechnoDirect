# TechnoDirect Dashboard — Frontend

Live business dashboard for **TechnoDirect** (Technosport's B2B wholesale ordering app), used by
Technosport management, operations and ASMs.

Stack: Vite + React 18 + TypeScript, react-router-dom, TanStack Query, axios (JWT access/refresh),
Apache ECharts (via echarts-for-react), Tailwind CSS, dayjs.

The API contract lives in `../docs/API_CONTRACT.md`; the build plan in `../docs/PLAN.md`.

## Quick start

```powershell
cd Frontend
npm install
copy .env.example .env      # then edit VITE_API_BASE_URL if needed
npm run dev                 # http://localhost:5173, talks to the Django API
```

### Demo mode (no backend)

```powershell
npm run dev:mock            # uses .env.mock → VITE_USE_MOCKS=true
```

Sign in with any email/password. `admin@technosport.in` is a master admin;
`asm@technosport.in` gets the restricted **ASM** role, so you can see permission-based navigation.
Sample data is deterministic and contract-shaped (≈ ₹2.95 Cr peak month, AOV ≈ ₹41k,
Heera Exports ≈ 37 % share). It lives in `src/mocks/` and is loaded lazily only when
`VITE_USE_MOCKS=true`.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000/api` | Django REST base URL (no trailing slash) |
| `VITE_USE_MOCKS` | `false` | `true` serves sample data from `src/mocks` instead of the API |

Vite inlines these at **build** time — rebuild for each environment.

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Dev server against the real API |
| `npm run dev:mock` | Dev server with mock data |
| `npm run typecheck` | TypeScript only |
| `npm run build` | Type-check (`tsc -b`) + production build to `dist/` |
| `npm run preview` | Serve `dist/` locally |

## How it behaves

- **Data refresh schedule.** The warehouse refreshes at **10:00 and 18:00 IST**. The UI does not poll:
  each filter set is cached (`staleTime: Infinity`) and refetched only when the filters/page change,
  when the user clicks **Refresh**, or when the clock passes `meta.next_refresh_at` (+2 min grace).
  Every page header shows "Data as of 10:00 AM, 11 Nov · next update 6:00 PM", coloured
  green / amber / red from `meta.freshness`.
- **Global filters** (date preset incl. FY Apr–Mar presets, region, state, ASM, distributor, category,
  segment, payment status) are stored in the URL, so every view and drill-down is a shareable link.
- **Permissions.** Sidebar items and routes are gated by `/auth/me/` permissions (master admin sees all).
  Export buttons appear only with `export_data`; "Refresh now" on Data Health needs `trigger_sync`.
- **Money** is shown in Indian format (₹2.95 Cr, ₹46.4 L, en-IN grouping) and money tiles carry the
  sales basis text from `meta.sales_basis`.
- **Charts** follow one palette (`src/charts/palette.ts`, validated for colour-vision deficiency in light
  and dark), never use dual axes, and every chart has a table view toggle.

## Project layout

```
src/
  api/          contract types + React Query hooks
  auth/         AuthContext (JWT login, /auth/me, permission checks)
  charts/       ECharts registration, palette, option builders
  components/   Layout, FilterBar, DataTable, KpiTile, ChartCard, TargetBullet, UI primitives
  lib/          axios client + refresh interceptor, filters (URL state), formatting, refresh scheduler
  mocks/        contract-shaped sample data + axios mock adapter
  pages/        Overview, Funnel, Retailers(+detail), Distributors(+detail), Territory, Orders,
                Products, Inventory, Retention, DataHealth, Login
  pages/admin/  Users, Roles, Targets, Mappings, Metrics, AuditLog
public/
  technosport-logo.svg   placeholder — replace with the real logo (same file name)
```

## Deploying to AWS (S3 + CloudFront)

1. **Build** with production values:
   ```powershell
   $env:VITE_API_BASE_URL = "https://api.dashboard.example.com/api"
   $env:VITE_USE_MOCKS = "false"
   npm ci
   npm run build
   ```
2. **Create an S3 bucket** (private, Block Public Access ON), e.g. `td-dashboard-web`.
3. **Create a CloudFront distribution**
   - Origin: the S3 bucket with **Origin Access Control (OAC)**; apply the bucket policy CloudFront suggests.
   - Default root object: `index.html`.
   - **SPA routing**: add custom error responses for **403 and 404 → `/index.html`, HTTP 200**
     (deep links like `/distributors/12` must load the app).
   - Viewer protocol: Redirect HTTP → HTTPS; attach an ACM certificate (us-east-1) for your domain.
   - Optional response-headers policy: HSTS, `X-Content-Type-Options`, `Referrer-Policy`, and a CSP
     allowing `connect-src` to your API origin.
4. **Upload** — hashed assets cache forever, `index.html` never:
   ```powershell
   aws s3 sync dist/ s3://td-dashboard-web/ --delete --exclude index.html --cache-control "public,max-age=31536000,immutable"
   aws s3 cp dist/index.html s3://td-dashboard-web/index.html --cache-control "no-cache,no-store,must-revalidate"
   aws cloudfront create-invalidation --distribution-id <DIST_ID> --paths "/index.html" "/"
   ```
5. **Backend CORS**: allow the CloudFront domain in Django's `CORS_ALLOWED_ORIGINS`
   (the SPA sends `Authorization: Bearer …`, no cookies).

## Replacing the logo

Drop the real file at `public/technosport-logo.svg` (keep the name). If the file fails to load the
sidebar falls back to a text wordmark.
