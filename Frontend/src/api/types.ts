// Types mirroring docs/API_CONTRACT.md (v1). Fields the contract leaves
// unspecified are typed as optional so the UI degrades gracefully.

export type FreshnessStatus = 'ok' | 'stale' | 'failed';

export interface Freshness {
  source: string;
  last_success_at: string | null;
  status: FreshnessStatus;
  /** e.g. 'not_configured' when the source has not been set up yet */
  detail?: string;
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
  /** Scheduled refreshes run at 10:30 and 15:30 IST. */
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
  rsms?: (IdName & { region_id: number | null })[];
  asms: (IdName & { region_id: number; rsm_id?: number | null })[];
  distributors: (IdName & { state_id: number; bo_only?: boolean })[];
  categories: { code: string; name: string }[];
  order_statuses: string[];
  payment_statuses: string[];
  // module filters
  payment_modes?: string[];
  platforms?: string[];
  category_tree?: { l1: string; l2: string; l3: string }[];
  sizes?: string[];
  /** base style codes (OR99 covers OR99/B11, "OR35 Black" ...) */
  styles?: { code: string; name: string; l1: string; l2: string; l3: string }[];
  /** BlueOrigin tiers, best first */
  tiers?: string[];
  /** distributor payout dates (finance tracker), newest first */
  payout_dates?: string[];
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
  /** months (YYYY-MM) that carry a target; achievement counts sales in these months only */
  target_months?: string[];
  period_months?: number;
  projected: number;
}

export interface Overview {
  kpis: Record<KpiKey, KPI>;
  target: TargetBlock | null;
  /** why no target is shown (a tier / segment filter is on) */
  target_note?: string | null;
  daily_trend: { date: string; sales: number; orders: number; cum_sales: number; cum_target: number | null }[];
  monthly: { month: string; sales: number; orders: number; aov: number; active_retailers: number; prev_year_sales: number | null }[];
  order_funnel: { status: string; count: number; value: number }[];
  concentration: {
    top3_distributor_share: number;
    top_state: { name: string; share: number } | null;
    top10_retailer_share: number;
  } | null;
  top_distributors: { id: number; name: string; sales: number; share: number; growth_pct: number | null }[];
  top_states: { id: number; name: string; sales: number; share: number }[];
  exceptions: { code: string; severity: 'high' | 'medium' | 'low'; count: number | null; message: string; link: string }[];
}

// ---------------------------------------------------------------- funnel
export interface Funnel {
  stages: { key: string; label: string; count: number }[];
  kyc_status: { status: string; count: number }[];
  never_ordered: { total: number; warm: number | null; cold: number | null; flagged: number; warm_available?: boolean };
  inactivity: { d30: number; d60: number; d90: number };
  /** by month of sign-up (customer created date): current KYC approval and first-order conversion */
  signup_cohorts: { month: string; signed_up: number; kyc_approved: number; first_order: number; kyc_rate: number | null; order_rate: number | null }[];
  /** KYC-approved → first order; timing from sign-up (created date) because the source has no approval date */
  kyc_penetration?: { kyc_approved: number; ever_ordered: number; ever_pct: number | null; active: number; active_pct: number | null; period_label: string };
  kyc_conversion?: { kyc_approved: number; converted: number; rate: number | null; median_days: number | null; within_30d: number; within_30d_pct: number | null; basis: 'signup' | 'approval' };
  acquisition_monthly: { month: string; new_retailers: number; cumulative: number }[];
  by_state: { state_id: number | null; state: string; kyc_approved: number; ever_ordered: number; active: number; adoption_pct: number }[];
  /** TD inside the TechnoSport (BlueOrigin) retailer base, Way Forward deck slide 12 */
  techno_base?: {
    universe: number;
    bo_on_td: number;
    bo_on_td_pct: number | null;
    bo_transacting: number;
    bo_transacting_pct: number | null;
    bo_never_transacted: number;
    kyc: number;
    kyc_in_bo: number;
    kyc_new: number;
    expansion_pct: number | null;
    transacting: number;
    transacting_in_bo: number;
    transacting_new: number;
    ants: number;
    ants_in_bo: number;
    ants_new: number;
    ants_pct: number | null;
    attribution: { td_first: number; not_in_bo_established: number; same_quarter: number; bo_first: number; not_in_bo_new: number };
    acquired_by_td: number;
    acquired_by_td_pct: number | null;
    as_of: string;
  };
}

// ---------------------------------------------------------------- retailers
export interface RetailerRow {
  id: number;
  name: string;
  phone: string;
  state: string;
  distributor: string;
  asm: string;
  rsm?: string | null;
  kyc_status: string;
  first_order_date: string | null;
  last_order_date: string | null;
  days_since_last_order: number | null;
  orders: number;
  sales: number;
  segment: string;
  /** RFM segment key as of the end of the selected period (analytics/rfm.py) */
  rfm_segment?: string | null;
  rfm_label?: string | null;
  warm_match: boolean | null;
  /** BlueOrigin tier (latest sheet); null = not found in BlueOrigin */
  tier?: string | null;
}

// ---------------------------------------------------------------- RFM segmentation
export interface RfmSegment {
  segment: string;
  label: string;
  meaning: string;
  action: string;
  retailers: number;
  pct_buyers: number | null;
  value: number;
  pct_value: number | null;
  scored: boolean;
  /** At Risk only: the value priority inside it (who to call first); segment = at_risk_high / _medium / _low */
  priorities?: { priority: 'high' | 'medium' | 'low'; segment: string; label: string; action: string; retailers: number; pct_buyers: number | null; value: number; pct_value: number | null }[];
}
export interface RfmData {
  as_of: string | null;
  window_start: string | null;
  window_months: number;
  summary: { registered: number; buyers: number; active: number; value: number };
  population: { median_gap: number; p90_gap: number; buyers: number; active: number } | null;
  cutoffs: { measure: 'recency_ratio' | 'orders_per_month' | 'value_per_month'; p20: number; p40: number; p60: number; p80: number }[];
  grid: { r: number; fm: number; segment: string; retailers: number }[];
  segments: RfmSegment[];
  params: { churn_ratio: number; new_days: number; min_tenure_months: number; shrink_k: number };
  validation: { as_of: string; months: number; segments: { segment: string; label: string; retailers: number; returned_pct: number }[] } | null;
}
/** One retailer's RFM block (retailer detail) */
export interface RetailerRfm {
  segment: string;
  label: string;
  priority?: 'high' | 'medium' | 'low';
  priority_label?: string;
  meaning: string;
  action: string;
  lifecycle?: string;
  days_since?: number | null;
  expected_gap?: number | null;
  recency_ratio?: number | null;
  orders?: number | null;
  value?: number | null;
  tenure_months?: number | null;
  f?: number | null;
  m?: number | null;
  r_score?: number | null;
  f_score?: number | null;
  m_score?: number | null;
  fm?: number | null;
  as_of?: string | null;
  window_start?: string | null;
}

/** /retailers/<id>/ profile: lifetime orders / sales (not the selected period) */
export interface RetailerProfile extends RetailerRow {
  owner_name?: string | null;
  /** masked unless the user has PII access */
  email?: string | null;
  gstin?: string | null;
  udyam_number?: string | null;
  pincode?: string | null;
  city?: string | null;
  region?: string | null;
  signed_up_at?: string | null;
  kyc_submitted_at?: string | null;
  kyc_approved_at?: string | null;
  tier?: string | null;
  aov?: number | null;
}
export interface RetailerDetail {
  profile: RetailerProfile;
  rfm?: RetailerRfm;
  monthly: { month: string; sales: number; orders: number }[];
  recent_orders: OrderRow[];
  /** offline records phone-matched to this app retailer */
  blueorigin?: BoRecord[];
}

export interface BoRecord {
  bo_id: string;
  name: string;
  distributor: string | null;
  district: string | null;
  tier: string;
  quarters: { quarter: string; tier: string; purchase: number; deliverables: string | null }[];
  monthly: { month: string; value: number }[];
}

// ---------------------------------------------------------------- BlueOrigin (offline)
export interface BoWindow {
  from: string;
  to: string;
  label: string;
  months: number;
  /** the selected period is after the BO data: the latest BO quarter is shown */
  shifted: boolean;
  /** the selected period runs past the BO data: cut at data_until */
  clipped: boolean;
  data_from: string;
  data_until: string;
  tier_quarter: string | null;
  prev_tier_quarter: string | null;
  prev_label: string | null;
}
export interface BoAgg {
  purchase: number;
  prev_purchase: number;
  delta_pct: number | null;
  retailers: number;
  active: number;
  on_app: number;
  on_app_pct: number | null;
  app_buyers: number;
  app_buyers_pct: number | null;
  app_sales: number;
  tiered: number;
  tiers: Record<string, number>;
}
export interface BoSummary {
  available: boolean;
  window: BoWindow;
  kpis: BoAgg;
  by_tier: (BoAgg & { tier: string; avg_purchase: number | null })[];
  tier_mix: { quarter: string; label: string; tiers: Record<string, { retailers: number; purchase: number }> }[];
  movement: { from_quarter: string | null; to_quarter: string; cells: { from: string; to: string; retailers: number }[]; upgraded: number; downgraded: number; same: number; new: number; dropped: number };
  monthly: { month: string; offline: number; app: number }[];
}
export interface BoHierarchy {
  available: boolean;
  window: BoWindow;
  group_by: string;
  rows: (BoAgg & { id: number | null; name: string; offline_only: boolean })[];
  total: BoAgg;
}
export interface BoRetailerRow {
  id: number;
  bo_id: string;
  retailer: string;
  phone: string;
  district: string | null;
  state: string | null;
  distributor: string | null;
  offline_only_distributor: boolean;
  asm: string | null;
  rsm: string | null;
  tier: string;
  tier_history: { quarter: string; tier: string }[];
  purchase: number;
  on_app: boolean;
  td_retailer_id: number | null;
  td_retailer: string | null;
  app_orders: number | null;
}

// ---------------------------------------------------------------- distributors
export interface DistributorRow {
  id: number;
  name: string;
  state: string;
  region?: string | null;
  asm?: string | null;
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
  /** sales in the comparison period (null when the preset has none) */
  prev_sales?: number | null;
  /** last 3 months vs the 3 before them (null when that base is under ₹50K) */
  l3m_growth_pct?: number | null;
  p3m_sales?: number | null;
  sales_per_retailer?: number | null;
  target: number | null;
  achievement_pct: number | null;
  last_stock_sync: string | null;
  /** fresh = updated within 3 days, stale = older, never */
  stock_sync_status?: 'fresh' | 'stale' | 'never';
  inventory_status?: string | null;
  stock_upload_mode?: string | null;
  stock_update_frequency?: string | null;
  spark: number[];
}

export interface ArticleRow {
  style: string;
  /** base style code (OR99 for OR99/B11) - the Style filter value */
  code?: string;
  name: string;
  category: string;
  sales: number;
  units: number;
  orders: number;
  retailers: number;
  share: number;
  realisation?: number | null;
  units_per_order?: number | null;
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
  /** every day of the selected period / the 26 weeks up to its end */
  daily?: { date: string; sales: number; orders: number }[];
  weekly?: { week: string; sales: number; orders: number }[];
  /** latest app stock of this distributor */
  stock?: { skus: number; in_stock: number; oos: number; low: number; units: number; live_styles: number; low_threshold: number };
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
    rfm_label?: string;
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
  /** BlueOrigin retailers converted to TD in the period (by their BO territory) / the Gold, Platinum, Silver ones */
  bo_conversions: number;
  bo_gps: number;
  /** KYC base of 300+ with adoption below 80% of the network's (requirements 4.4) */
  low_adoption?: boolean;
  kyc_base: number;
  adoption_pct: number;
  distributors: number;
  growth_pct: number | null;
  sales_per_retailer?: number | null;
  // group_by=rsm
  asms?: number;
  region?: string | null;
  // group_by=rsm / asm
  field_staff?: number;
  // group_by=asm
  rsm_id?: number | null;
  rsm?: string | null;
  full_name?: string | null;
}
/** group_by=rsm: one row per RSM x ASM (asm_id null = distributor-managed sales in that RSM's region). */
export interface TerritoryTeamRow {
  rsm_id: number;
  asm_id: number | null;
  name: string;
  full_name: string | null;
  sales: number;
  target: number | null;
  achievement_pct: number | null;
  orders: number;
  active_retailers: number;
  growth_pct: number | null;
  field_staff: number;
  /** false = has left (sales stay credited to them for the months they were in charge) */
  is_active?: boolean;
  joined_on?: string | null;
}
export interface Territory {
  group_by?: string;
  rows: TerritoryRow[];
  network_adoption_pct?: number | null;
  monthly_by_group: { month: string; group: string; sales: number }[];
  breakdown?: TerritoryTeamRow[];
}

// ---------------------------------------------------------------- orders
export interface OrdersSummary {
  status_counts: { status: string; count: number; value: number }[];
  /** orders waiting for dispatch (received / confirmed), by the distributor responsible */
  pending_by_distributor?: { distributor_id: number | null; distributor: string; open: number; over_48h: number; oldest_hours: number; value: number }[];
  /** customer refunds from the finance tracker: refunded in the period, still pending */
  refunds?: { refunded: number; refunded_value: number; median_days_to_refund: number | null; within_7_days_pct: number | null; pending: number; pending_value: number; pending_oldest_days: number | null };
  /** open orders placed within open_window_days, by age bucket and status */
  ageing: { bucket: string; status: string; count: number }[];
  open_window_days?: number;
  /** older orders the TD export still shows as placed / confirmed / shipped (status never updated) */
  stale_open?: number;
  tat: {
    order_to_dispatch_median_h: number | null;
    order_to_delivery_median_h: number | null;
    trend: { month: string; dispatch_h: number | null; delivery_h: number | null; dispatch_pct?: number | null }[];
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
  crm: {
    connected: boolean;
    open: number;
    opened_in_period?: number;
    closed_in_period?: number;
    refund_in_period?: number;
    by_type: { type: string; count: number; open?: number }[];
  };
  /** paid, non-cancelled orders in the period by payment mode / platform (from the orders themselves) */
  order_payment_modes: { key: string; orders: number; value: number; share: number | null }[];
  order_platforms: { key: string; orders: number; value: number; share: number | null }[];
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
  /** calendar dates / whole days (the TD export records dates only) */
  shipped_on?: string | null;
  delivered_on?: string | null;
  dispatch_days?: number | null;
  transit_days?: number | null;
}

/** /orders/flow/ — Order flow & delays (analytics/views/fulfilment.py) */
export interface FlowPoint {
  date: string;
  received: number;
  shipped: number;
  delivered: number;
}
export interface LeadBucket {
  key: string;
  label: string;
  orders: number;
  /** the bucket is beyond the SLA */
  late: boolean;
}
export interface LeadStage {
  buckets: LeadBucket[];
  done: number;
  median_days: number | null;
  within_sla_pct: number | null;
  /** not finished yet, placed within the open window */
  waiting: number;
  waiting_late: number;
}
export interface DelayGroup {
  key: string;
  label: string;
  orders: number;
  median_dispatch_days: number | null;
  late_dispatch: number;
  late_dispatch_pct: number | null;
  median_transit_days: number | null;
  late_transit: number;
  late_transit_pct: number | null;
  late_orders: number;
  late_pct: number | null;
  late_dispatch_share: number | null;
  late_transit_share: number | null;
}
export interface FlowInsight {
  tone: 'bad' | 'warn' | 'good';
  text: string;
  title: string;
  params: Record<string, string> | null;
}
export interface OrderFlow {
  /** latest day with orders in the data */
  as_of: string;
  sla: { dispatch_days: number; transit_days: number };
  flow: { granularity: 'day' | 'week'; points: FlowPoint[] };
  latest_day: { date: string; today: FlowPoint | null; previous: FlowPoint | null } | null;
  orders: number;
  dispatch: LeadStage;
  transit: LeadStage;
  end_to_end_median_days: number | null;
  late_orders: number;
  insights: FlowInsight[];
  hotspots: { group_by: string; label: string; min_orders: number; rows: DelayGroup[] };
  dimensions: { key: string; label: string }[];
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
  /** Category I by region: sales, units, realisation and the category's share of the region */
  category_by_region?: { region: string; l1: string; sales: number; units: number; realisation: number | null; share_of_region: number | null }[];
  category_mix?: { l1: string; l2: string; sales: number; units: number; orders: number; share: number; realisation: number | null; units_per_order: number | null }[];
  category_mix_monthly_l1l2?: { month: string; l1: string; l2: string; sales: number }[];
  new_articles_6m?: { since: string; articles: number; sales: number; share: number };
  /** Style filter on: each selected style this period (line values) vs the comparison period */
  selected_styles?: SelectedStyle[] | null;
  style_monthly?: { month: string; code: string; sales: number; units: number }[] | null;
}

export interface SelectedStyle {
  code: string;
  name: string;
  l1: string;
  l2: string;
  l3: string;
  known: boolean;
  sales: number;
  units: number;
  orders: number;
  retailers: number;
  share: number;
  realisation: number | null;
  units_per_order: number | null;
  prev_sales: number | null;
  prev_units: number | null;
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
  sync: { distributor_id: number; distributor: string; last_sync_at: string | null; status: string; skus: number; in_stock_skus: number; inventory_status?: string | null; stock_upload_mode?: string | null; stock_update_frequency?: string | null }[];
  summary: { live_styles: number; oos_skus: number; low_stock_skus: number };
  oos_top_sellers: { style: string; size: string; distributor: string; units_sold: number }[];
  /** window (days) the units sold cover */
  sold_days?: number;
}
export interface InventoryItem {
  distributor: string;
  sku: string;
  style: string;
  name?: string;
  size: string;
  category?: string | null;
  quantity: number;
  stock_status: 'oos' | 'low_stock' | 'in_stock';
  /** units sold in the page's window (sold_days) */
  units_sold?: number;
  snapshot_date?: string;
  [k: string]: unknown;
}

// ---------------------------------------------------------------- retention
export interface Retention {
  movement: { month: string; active: number; retained: number; reactivated: number; new: number; lost: number; net: number; mom_retention: number | null }[];
  quarterly_retention: { quarter: string; rate: number }[];
  /** the same retention for FY quarters, halves and years; partial = the period is still running */
  period_retention?: Record<'quarter' | 'half' | 'year', { label: string; rate: number; retained: number | null; base: number | null; partial: boolean }[]>;
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
  sources: { source: string; status: FreshnessStatus | string; last_success_at: string | null; last_error: string | null; rows_last_run: number | null; next_run_at: string | null; via?: string | null; last_checked_at?: string | null; rows_loaded?: number }[];
  issues: { code: string; label: string; count: number; severity: string }[];
  reconciliation: { metric: string; period: string; dashboard_value: number; mis_value: number | null; diff_pct: number | null }[];
  /** dashboard vs its sources, checked after every refresh (analytics/source_recon.py) */
  source_check?: import('@/components/SourceCheck').SourceCheckData | null;
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
  /** the version the dashboard uses today; older versions stay listed for the audit trail */
  in_use?: boolean;
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

// ---------------------------------------------------------------- MoM trend (/trends/mom/)
export interface MomMonth {
  month: string;
  is_partial: boolean;
  days: number;
  basis: 'full_month' | 'same_days';
  sales: number;
  orders: number;
  pieces: number;
  boxes: number;
  avg_price_per_piece: number | null;
  prev_sales: number;
  prev_pieces: number;
  prev_boxes: number;
  sales_mom_pct: number | null;
  pieces_mom_pct: number | null;
  boxes_mom_pct: number | null;
  avg_price_mom_pct: number | null;
}
export interface MomTrend {
  months: MomMonth[];
  range: number;
  as_of: string;
  first_data_month: string | null;
}

// ---------------------------------------------------------------- Techno AI (/assistant/*)
export interface AiStatus {
  enabled: boolean;
  configured: boolean;
  model: string | null;
  provider: string;
  modules: string[];
  suggestions: string[];
}
export interface AiItem {
  text: string;
  refs: string[];
}
export interface AiAnswer {
  headline: string;
  what_to_do: AiItem[];
  data_points: AiItem[];
  explanation: string;
  not_authorised: string[];
  follow_ups: string[];
}
export interface AiSource {
  ref: string;
  tool: string;
  label: string;
  period: string | null;
  params: Record<string, string>;
  ok: boolean;
}
export interface AiReply {
  answer: AiAnswer;
  sources: AiSource[];
  model: string;
  took_ms: number;
  asked_at: string;
}

// ---------------------------------------------------------------- ASM tracker (/masters/asm-tracker/)
export interface AsmTrackerRow {
  distributor_id: number;
  distributor: string;
  region: string;
  asm_id: number | null;
  asm: string;
  sales: number;
  orders: number;
  share: number | null;
  target: number | null;
  remaining: number | null;
  achieved_pct: number | null;
  /** TD Target Forecaster suggestion for this month (when a forecast exists) */
  suggested?: number | null;
  /** who carries the target, person by person (months from the live incentive sheet) */
  split?: { person: string; role: 'asm' | 'executive'; value: number }[];
}
export interface AsmTrackerAsm {
  asm_id: number;
  asm: string;
  region: string;
  distributors: number;
  sales: number;
  orders: number;
  target: number | null;
  remaining: number | null;
  achieved_pct: number | null;
  /** 'distributors' = sum of its distributors' targets; 'asm' = one target for the ASM as a whole */
  target_from: 'distributors' | 'asm';
  suggested?: number | null;
}
export interface AsmTrackerForecast {
  as_of: string;
  model: string;
  params: Record<string, number | string> | null;
  overall: number | null;
  /** ASM name -> suggested target */
  asm: Record<string, number>;
  /** how far the suggestions were from the targets set for this month (WAPE %), when targets exist */
  wape_vs_set: number | null;
}
export interface AsmTrackerData {
  month: string;
  as_of: string;
  rows: AsmTrackerRow[];
  first_month: string;
  asm_summary: AsmTrackerAsm[];
  forecast: AsmTrackerForecast | null;
  /** this month's targets come from the live incentive sheet - edit them there */
  managed_by_sheet?: boolean;
  totals: { sales: number; orders: number; target: number | null; remaining: number | null; achieved_pct: number | null };
  regions: string[];
  asms: string[];
  states: { id: number; name: string; region: string | null }[];
  rsms: { id: number; name: string; region: string | null }[];
}

/* ---------------------------------------------------------------- /growth/ (TD_DataDeck slides 28-44, 56, 59-61) */
export interface GrowthMonth {
  month: string;
  is_partial: boolean;
  sales: number;
  orders: number;
  units: number;
  active_retailers: number;
  distributors: number;
  new_retailers: number;
  aov: number | null;
  units_per_order: number | null;
  realisation_per_unit: number | null;
  sales_per_retailer: number | null;
  orders_per_retailer: number | null;
  mom_pct: number | null;
  prev_year_sales: number | null;
  yoy_pct: number | null;
  cum_sales: number;
  cum_orders: number;
  cum_retailers: number;
  active_pct_of_base: number | null;
  new_sales: number;
  repeat_sales: number;
  repeat_share: number | null;
  articles_per_order: number | null;
  articles_sold: number;
}
export interface GrowthRollup { label: string; start: string; sales: number; orders: number; aov: number | null; active_retailers: number; growth_pct: number | null; is_partial: boolean }
export interface GrowthFactor { key: string; label: string; prev: number | null; cur: number | null; change_pct: number | null; share_pct: number | null; contribution: number | null }
export interface Growth {
  headline: { since: string; cum_sales: number; cum_orders: number; retailers: number; distributors: number; last_month: string | null; last_month_sales: number | null; repeat_share_last_month: number | null; record_month: string | null };
  monthly: GrowthMonth[];
  quarters: GrowthRollup[];
  fy: GrowthRollup[];
  milestones: { month: string; kind: 'cumulative' | 'month' | 'record'; label: string }[];
  decomposition: {
    period: { start: string; end: string };
    compare: { start: string; end: string };
    prev_sales: number;
    cur_sales: number;
    change: number;
    change_pct: number | null;
    factors: GrowthFactor[];
    aov_factors: GrowthFactor[];
    available: boolean;
  };
  bridge: {
    window: { start: string; end: string };
    prev_window: { start: string; end: string };
    prev_total: number;
    cur_total: number;
    like_for_like: { retailers: number; prev: number; cur: number; change: number; change_pct: number | null };
    new: { retailers: number; sales: number };
    lapsed: { retailers: number; sales: number };
  };
  retailer_value: {
    window: { start: string; end: string };
    transacting: number;
    avg_spend: number | null;
    median_spend: number | null;
    top_quartile: { retailers: number; avg_spend: number | null; share: number };
    histogram: { bucket: string; retailers: number }[];
    months_active: { months: number; retailers: number }[];
    avg_months_active: number | null;
    single_month: number;
    lifetime: { acquired: number; repeat_retailers: number; repeat_pct: number | null; repeat_sales_share: number; avg_orders: number | null; one_order: number; one_order_sales: number };
    first_vs_repeat_aov: { first_aov: number | null; first_orders: number; repeat_aov: number | null; repeat_orders: number };
    top_retailers: { id: number; name: string; orders: number; sales: number; months_active: number; last_order: string | null }[];
  };
}

/* ---------------------------------------------------------------- /distributors/insights/ (slides 49, 52, 62, 63) */
export interface DistributorInsights {
  trend: { months: string[]; series: { name: string; data: number[] }[] };
  top_articles: { id: number; name: string; sales: number; articles: { style: string; sales: number }[] }[];
  multi_distributor: { retailers: number; multi: number; multi_pct: number | null; avg_orders_multi: number | null; avg_orders_single: number | null; monthly: { month: string; active: number; multi: number; multi_pct: number | null }[] };
  transacting_monthly: { month: string; distributors: number; retailers: number }[];
  /** retailer-to-distributor distance by pincode (Way Forward deck slide 10) */
  proximity?: {
    rows: { band: string; label: string; meaning: string; retailers: number; retailers_pct: number | null; orders: number; orders_pct: number | null; sales: number; sales_pct: number | null }[];
    outside_district_pct: number | null;
    unknown_orders: number;
    unknown_sales: number;
  };
}

// ---------------------------------------------------------------- distributor settlements (finance tracker)
export type SettleStatus = 'settled' | 'not_settled' | 'pending' | 'cancelled';
export interface SettleAgg {
  orders: number;
  order_value: number;
  refunds: number;
  loyalty: number;
  payable: number;
  pg_charges: number;
  settled: number;
  settled_orders: number;
  settled_pct: number | null;
  due: number;
  due_orders: number;
  overdue: number;
  overdue_orders: number;
  not_yet_due: number;
  not_yet_due_orders: number;
  cancelled: number;
  cancelled_orders: number;
  median_days: number | null;
  p90_days: number | null;
  last_payout: string | null;
}
export interface SettlementSummary {
  available: boolean;
  basis: 'order' | 'payout';
  sla_days: number;
  data: { from: string; until: string; last_payout: string | null };
  kpis: SettleAgg;
  by_status: { status: SettleStatus; label: string; orders: number; payable: number; order_value: number }[];
  by_payment: { status: string; label: string; orders: number; payable: number; order_value: number }[];
  weekly: { week: string; orders: number; settled: number; due: number; not_yet_due: number }[];
  payouts: { date: string; orders: number; amount: number; distributors: number; median_days: number | null }[];
  ageing: { bucket: string; orders: number; amount: number }[];
  issues: { issue: string; orders: number }[];
  split: SplitBlock;
}
export interface SplitPart {
  order_ref: string;
  order_id: number | null;
  distributor: string | null;
  distributor_id: number | null;
  order_value: number;
  payable: number;
  courier: number;
  settlement_status: SettleStatus;
  settled_on: string | null;
  fulfilment: string;
}
export interface SplitCart {
  cart: string;
  date: string;
  customer: string;
  state: 'settled' | 'partly' | 'open' | 'cancelled';
  order_value: number;
  payable: number;
  settled: number;
  courier: number;
  parts: SplitPart[];
}
export interface SplitBlock {
  carts: number;
  parts: number;
  share_pct: number | null;
  order_value: number;
  payable: number;
  settled: number;
  remaining: number;
  courier: number;
  states: Record<'settled' | 'partly' | 'open' | 'cancelled', number>;
  pairs: { pair: string; carts: number; value: number }[];
  list: SplitCart[];
}
export interface SettlementDistributorRow {
  id: number | null;
  distributor: string;
  asm: string | null;
  state: string | null;
  orders: number;
  order_value: number;
  refunds: number;
  payable: number;
  settled: number;
  settled_pct: number | null;
  due: number;
  due_orders: number;
  overdue: number;
  overdue_orders: number;
  not_yet_due: number;
  payouts: number;
  last_payout: string | null;
  median_days: number | null;
  split_orders: number;
  split_payable: number;
}
export interface SettlementOrderRow {
  id: number;
  order_ref: string;
  order_id: number | null;
  order_date: string;
  delivered_date: string | null;
  fulfilment: string;
  customer: string;
  destination: string;
  distributor: string;
  distributor_id: number | null;
  asm: string | null;
  order_value: number;
  customer_refund: number;
  loyalty_points: number;
  payable: number;
  payment_mode: string;
  transaction_id: string;
  payment_status: string;
  settlement_status: SettleStatus;
  settled_on: string | null;
  days_to_settle: number | null;
  state: 'settled' | 'due' | 'not_yet_due' | 'cancelled';
  days_since_delivery: number | null;
  overdue: boolean;
  remark: string;
  issues: string[];
  is_split: boolean;
  split_with: { order_ref: string; order_id: number | null; distributor: string | null; distributor_id: number | null; payable: number; settlement_status: SettleStatus }[];
}
export interface SettlementStatement extends SettlementSummary {
  distributor: { id: number; name: string; asm: string | null; rsm: string | null; state: string | null };
  bridge: { order_value: number; cancelled: number; refunds: number; adjustments: number; payable: number; settled: number; due: number; not_yet_due: number; remaining: number };
  monthly: { month: string; orders: number; payable: number; settled: number; remaining: number }[];
  payouts: (SettlementSummary['payouts'][number] & { cumulative: number })[];
  payout_gap_days: number | null;
  open_orders: {
    order_ref: string;
    order_id: number | null;
    customer: string;
    order_date: string;
    delivered_date: string | null;
    fulfilment: string;
    payable: number;
    state: 'due' | 'not_yet_due';
    settlement_status: SettleStatus;
    payment_status: string;
    days_since_delivery: number | null;
    overdue: boolean;
  }[];
}
