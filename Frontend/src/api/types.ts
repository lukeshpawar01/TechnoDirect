// Types mirroring docs/API_CONTRACT.md (v1). Fields the contract leaves
// unspecified are typed as optional so the UI degrades gracefully.

export type FreshnessStatus = 'ok' | 'stale' | 'failed';

export interface Freshness {
  source: string;
  last_success_at: string | null;
  status: FreshnessStatus;
}

export interface Period {
  from: string;
  to: string;
  label: string;
  compare_from?: string | null;
  compare_to?: string | null;
}

export interface Meta {
  sales_basis: string;
  as_of: string;
  period: Period;
  freshness: Freshness[];
  /** Scheduled refreshes run at 10:00 and 18:00 IST. */
  last_refresh_at?: string | null;
  next_refresh_at?: string | null;
}

export interface Envelope<T> {
  data: T;
  meta: Meta | null;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
  meta?: Meta;
}

// ---------------------------------------------------------------- auth
export interface Scope {
  all: boolean;
  regions: number[];
  states: number[];
  asms: number[];
  distributors: number[];
}

export interface Me {
  id: number;
  email: string;
  full_name: string;
  is_master_admin: boolean;
  role: { id: number; name: string } | null;
  permissions: string[];
  scope: Scope;
}

export interface AdminUser {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  role_id: number | null;
  scope: Scope;
  last_login: string | null;
}

export interface Role {
  id: number;
  name: string;
  description: string;
  permissions: string[];
  user_count: number;
}

export interface Permission {
  code: string;
  label: string;
  group: string;
}

export interface AuditEntry {
  id: number;
  at: string;
  user_email: string;
  action: string;
  object_type: string;
  object_id: string | number | null;
  before: unknown;
  after: unknown;
  reason: string | null;
}

// ---------------------------------------------------------------- filters
export interface IdName {
  id: number;
  name: string;
}
export interface FilterOptions {
  regions: IdName[];
  states: (IdName & { region_id: number })[];
  asms: (IdName & { region_id: number })[];
  distributors: (IdName & { state_id: number })[];
  categories: { code: string; name: string }[];
  order_statuses: string[];
  payment_statuses: string[];
}

// ---------------------------------------------------------------- overview
export interface KPI {
  value: number | null;
  compare: number | null;
  delta_pct: number | null;
  spark: number[];
}

export type KpiKey =
  | 'sales'
  | 'orders'
  | 'aov'
  | 'units_per_order'
  | 'realisation_per_unit'
  | 'active_retailers'
  | 'new_retailers'
  | 'repeat_retailers'
  | 'active_distributors';

export interface TargetBlock {
  target: number;
  achieved: number;
  achievement_pct: number;
  balance: number;
  days_elapsed: number;
  days_total: number;
  current_run_rate: number;
  required_run_rate: number;
  projected: number;
}

export interface Overview {
  kpis: Record<KpiKey, KPI>;
  target: TargetBlock | null;
  daily_trend: { date: string; sales: number; orders: number; cum_sales: number; cum_target: number | null }[];
  monthly: { month: string; sales: number; orders: number; aov: number; active_retailers: number; prev_year_sales: number | null }[];
  order_funnel: { status: string; count: number; value: number }[];
  concentration: {
    top3_distributor_share: number;
    top_state: { name: string; share: number } | null;
    top10_retailer_share: number;
  };
  top_distributors: { id: number; name: string; sales: number; share: number; growth_pct: number | null }[];
  top_states: { id: number; name: string; sales: number; share: number }[];
  exceptions: { code: string; severity: 'high' | 'medium' | 'low'; count: number; message: string; link: string }[];
}

// ---------------------------------------------------------------- funnel
export interface Funnel {
  stages: { key: string; label: string; count: number }[];
  kyc_status: { status: string; count: number }[];
  never_ordered: { total: number; warm: number; cold: number; flagged: number };
  inactivity: { d30: number; d60: number; d90: number };
  kyc_to_first_order_by_month: { month: string; kyc_approved: number; converted: number; rate: number }[];
  acquisition_monthly: { month: string; new_retailers: number; cumulative: number }[];
  by_state: { state: string; kyc_approved: number; ever_ordered: number; active: number; adoption_pct: number }[];
}

// ---------------------------------------------------------------- retailers
export interface RetailerRow {
  id: number;
  name: string;
  phone: string;
  state: string;
  distributor: string;
  asm: string;
  kyc_status: string;
  first_order_date: string | null;
  last_order_date: string | null;
  days_since_last_order: number | null;
  orders: number;
  sales: number;
  segment: string;
  warm_match: boolean | null;
}

export interface RetailerDetail extends RetailerRow {
  pincode?: string;
  city?: string;
  kyc_approved_at?: string | null;
  tier?: string | null;
  aov?: number;
  monthly: { month: string; sales: number; orders: number }[];
  recent_orders: OrderRow[];
}

// ---------------------------------------------------------------- distributors
export interface DistributorRow {
  id: number;
  name: string;
  state: string;
  sales: number;
  share: number;
  orders: number;
  aov: number;
  retailers: number;
  active_retailers: number;
  new_retailers: number;
  repeat_pct: number;
  orders_per_retailer: number;
  dispatch_pct: number;
  median_dispatch_days: number | null;
  l3m_sales: number;
  growth_pct: number | null;
  target: number | null;
  achievement_pct: number | null;
  last_stock_sync: string | null;
  spark: number[];
}

export interface ArticleRow {
  style: string;
  name: string;
  category: string;
  sales: number;
  units: number;
  orders: number;
  retailers: number;
  share: number;
}

export interface DistributorDetail {
  profile: {
    id: number;
    name: string;
    state?: string;
    region?: string;
    asm?: string;
    code?: string;
    city?: string;
    onboarded_on?: string | null;
    last_stock_sync?: string | null;
    [k: string]: unknown;
  };
  kpis: Partial<Record<string, KPI>>;
  monthly: { month: string; sales: number; orders?: number; active_retailers?: number }[];
  top_articles: ArticleRow[];
  retailers: {
    id: number;
    name: string;
    state?: string;
    orders: number;
    sales: number;
    last_order_date?: string | null;
    days_since_last_order?: number | null;
    segment?: string;
  }[];
}

// ---------------------------------------------------------------- territory
export interface TerritoryRow {
  id: number;
  name: string;
  sales: number;
  target: number | null;
  achievement_pct: number | null;
  orders: number;
  active_retailers: number;
  new_retailers: number;
  kyc_base: number;
  adoption_pct: number;
  distributors: number;
  growth_pct: number | null;
}
export interface Territory {
  rows: TerritoryRow[];
  monthly_by_group: { month: string; group: string; sales: number }[];
}

// ---------------------------------------------------------------- orders
export interface OrdersSummary {
  status_counts: { status: string; count: number; value: number }[];
  ageing: { bucket: string; status: string; count: number }[];
  tat: {
    order_to_dispatch_median_h: number | null;
    order_to_delivery_median_h: number | null;
    trend: { month: string; dispatch_h: number | null; delivery_h: number | null }[];
  };
  cancellation_rate: number;
  payment: {
    success: number;
    failed: number;
    pending: number;
    failed_value: number;
    paid_no_order: number;
    mode_mix: { mode: string; count: number; value: number }[];
  } | null;
  split_orders: { split_carts: number; total_carts: number };
  sla_breaches: number;
  crm: { open: number; by_type: { type: string; count: number }[] };
}

export interface OrderRow {
  id: number | string;
  display_id: string;
  placed_at: string;
  retailer: string;
  distributor: string;
  state: string;
  status: string;
  payment_status: string | null;
  payment_mode: string | null;
  value: number;
  units: number;
  awb: string | null;
  dispatch_hours: number | null;
  is_split: boolean;
}

export interface OrderPayment {
  txn_id: string;
  amount: number;
  status: string;
  mode: string | null;
  at: string;
}

export interface OrderDetail extends OrderRow {
  lines: { sku?: string; style?: string; name?: string; size?: string; qty?: number; quantity?: number; price?: number; value?: number }[];
  payments: OrderPayment[];
  timeline: { at: string; status?: string; event?: string; label?: string; note?: string; actor?: string }[];
}

// ---------------------------------------------------------------- products
export interface Products {
  categories: { code: string; name: string; sales: number; units: number; share: number; realisation: number }[];
  category_mix_monthly: { month: string; category: string; sales: number }[];
  top_articles: ArticleRow[];
  bottom_articles: ArticleRow[];
  new_launches: { style: string; launched_on: string; sales: number; units: number; retailers: number; name?: string }[];
  size_mix: { size: string; units: number; share: number }[];
  concentration: { top4_share: number; top12_share: number; distinct_articles: number };
}

/** GET /products/tree/ — one row per style; the client rolls rows up Category I > II > III > Style. */
export interface ProductTreeRow {
  l1: string;
  l2: string;
  l3: string;
  style: string;
  name: string;
  amount: number;
  quantity: number;
  orders: number;
}
export interface ProductTree {
  levels: { key: 'l1' | 'l2' | 'l3' | 'style'; label: string }[];
  total: { amount: number; quantity: number };
  rows: ProductTreeRow[];
}

// ---------------------------------------------------------------- inventory
export interface Inventory {
  sync: { distributor_id: number; distributor: string; last_sync_at: string | null; status: string; skus: number; in_stock_skus: number }[];
  summary: { live_styles: number; oos_skus: number; low_stock_skus: number };
  oos_top_sellers: { style: string; size: string; distributor: string; last_30d_units: number }[];
}
export interface InventoryItem {
  distributor: string;
  sku: string;
  style: string;
  name?: string;
  size: string;
  category?: string;
  qty: number;
  status?: string;
  snapshot_date?: string;
  [k: string]: unknown;
}

// ---------------------------------------------------------------- retention
export interface Retention {
  movement: { month: string; active: number; retained: number; reactivated: number; new: number; lost: number; net: number; mom_retention: number | null }[];
  quarterly_retention: { quarter: string; rate: number }[];
  cohorts: { cohort: string; size: number; values: (number | null)[] }[];
  contribution: { month: string; new_sales: number; repeat_sales: number; reactivated_sales: number }[];
  order_bands: { band: string; retailers: number; sales: number }[];
  pareto: { top_n: number; share: number }[];
  avg_days_between_orders: number | null;
  orders_per_active_retailer: { month: string; value: number }[];
}

// ---------------------------------------------------------------- loyalty
export interface LoyaltyTotals {
  points_issued: number;
  points_redeemed: number;
  net_points: number;
  redemption_rate: number | null;
  events: number;
  members: number;
  earning_retailers: number;
  redeeming_retailers: number;
  new_members: number;
}
export interface LoyaltyMember {
  retailer_id: number;
  retailer: string;
  owner: string;
  state: string | null;
  distributor: string | null;
  earned: number;
  redeemed: number;
  balance: number;
  orders: number;
  events: number;
  last_event: string | null;
}
export interface Loyalty {
  period: LoyaltyTotals;
  previous: LoyaltyTotals | null;
  lifetime: LoyaltyTotals;
  data_range: { first: string | null; last: string | null };
  monthly: { month: string; issued: number; redeemed: number; earners: number; new_members: number }[];
  by_event: { event: string; events: number; points: number }[];
  by_state: { state: string; members: number; issued: number; redeemed: number }[];
  top_members: LoyaltyMember[];
}

// ---------------------------------------------------------------- data health
export interface DataHealth {
  sources: { source: string; status: FreshnessStatus | string; last_success_at: string | null; last_error: string | null; rows_last_run: number | null; next_run_at: string | null }[];
  issues: { code: string; label: string; count: number; severity: string }[];
  reconciliation: { metric: string; period: string; dashboard_value: number; mis_value: number | null; diff_pct: number | null }[];
}

// ---------------------------------------------------------------- masters
export type TargetMetric = 'sales' | 'orders' | 'new_retailers' | 'active_retailers';
export type ScopeType = 'overall' | 'region' | 'state' | 'asm' | 'distributor';
export interface Target {
  id: number;
  month: string;
  scope_type: ScopeType;
  scope_id: number | null;
  scope_name: string;
  metric: TargetMetric;
  value: number;
  effective_from: string;
  notes: string;
}
export interface UploadResult {
  created: number;
  updated: number;
  errors: { row: number; message: string }[];
}
export interface MetricDef {
  code: string;
  name: string;
  definition: string;
  formula: string;
  source: string;
  owner: string;
  refresh: string;
}
