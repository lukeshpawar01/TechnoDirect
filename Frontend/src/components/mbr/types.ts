/** Monthly Business Review API shapes: /api/mbr/ (numbers) and /api/masters/mbr/ (written content). */
export type Fmt = 'inr' | 'num' | 'pct' | 'dec';
export type RowStatus = 'good' | 'warn' | 'bad' | 'in_progress' | null;

export interface ScoreRow {
  key: string;
  label: string;
  group: 'business' | 'product';
  format: Fmt;
  higher_is_better: boolean;
  definition: string;
  value: number | null;
  prev: number | null;
  mom_pct: number | null;
  last_year: number | null;
  yoy_pct: number | null;
  target: number | null;
  achievement_pct: number | null;
  projected: number | null;
  projected_pct: number | null;
  status: RowStatus;
  trend: (number | null)[];
}

export interface TrendPoint {
  month: string;
  sales: number;
  orders: number;
  active_retailers: number;
  new_retailers: number;
  adoption_pct: number | null;
  kyc_base: number;
  target_sales: number | null;
  [k: string]: number | string | null;
}

export interface PathToGoal {
  /** the goal used on this page: the TD goal, or a territory's share of it when a territory filter is on */
  goal: number;
  national_goal: number;
  /** false for reviews before the goal started (GOAL_FROM, Nov 2026): the Growth page then shows no goal */
  goal_active: boolean;
  goal_from: string;
  /** % of TD sales the filtered territory made in the base months (null = all TD) */
  territory_share_pct: number | null;
  /** every month's sales against the goal (it applies to every month, there is no deadline) */
  months: { month: string; sales: number; goal_pct: number | null; short: number; partial: boolean }[];
  months_at_goal: number;
  avg_goal_pct_3m: number | null;
  base_month: string;
  base_label: string;
  base_sales: number;
  gap_sales: number;
  goal_pct: number | null;
  /** how much higher a month's sales must be than the base month to make the goal */
  growth_needed_pct: number | null;
  /** retailers who bought in the 3 months before the base month but not in it (the win-back pool) */
  lapsed: number;
  spend_per_retailer: number;
  active_retailers: number;
  retailers_needed: number | null;
  retailers_gap: number;
  kyc_base: number;
  adoption_pct: number | null;
  adoption_needed_pct: number | null;
  ants: number;
  ants_share_of_gap_pct: number | null;
  techno_universe: number;
  techno_transacting: number;
  techno_not_transacting: number;
  techno_adoption_pct: number | null;
  scenarios: { spend_uplift_pct: number; spend: number; retailers_needed: number | null; adoption_needed_pct: number | null; extra_retailers: number }[];
  adoption_trend: { month: string; adoption_pct: number | null; active_retailers: number; kyc_base: number; sales: number }[];
}

export type ProductRole = 'core' | 'defend' | 'rising' | 'watch';
export interface ProductCategory {
  key: string; name: string; sales: number; prev_sales: number; change: number;
  share_pct: number; share_change_pp: number | null; mom_pct: number | null;
  units: number; asp: number | null; asp_change_pct: number | null;
  retailers: number; reach_pct: number | null; styles: number; top_style: string | null; role: ProductRole;
  prev_share_pct: number | null; yoy_pct: number | null;
  /** category ₹ change ÷ TD ₹ change; null when TD did not grow */
  growth_contrib_pct: number | null;
  /** null when the month reviewed is not the current one (stock is a live snapshot) */
  oos_lines: number | null; oos_units_30d: number | null; oos_value: number | null;
  call: ProductCall; call_reason: string;
}
export type ProductCall = 'scale' | 'defend' | 'fix' | 'watch';
export interface ProductDecision {
  kind: 'scale' | 'fix' | 'defend' | 'watch' | 'launch';
  title: string; value: number; value_label: string; reason: string; link?: string; good?: boolean;
}
export interface StyleChange { style: string; name: string | null; sales: number; prev: number; change: number }
export interface ProductMatrix {
  categories: ProductCategory[];
  /** 100 / categories that sold */
  fair_share_pct: number;
  td_growth_pct: number | null;
  gainers: StyleChange[];
  decliners: StyleChange[];
  pulse: {
    styles_sold: number; prev_styles_sold: number;
    top10_share_pct: number | null; top10_prev_share_pct: number | null;
    new_launch_share_pct: number | null; new_launch_sales: number; new_launches_selling: number; new_launches: number;
    styles_per_retailer: number | null; prev_styles_per_retailer: number | null;
    asp: number | null; asp_change_pct: number | null; buyers: number; prev_buyers: number;
    /** null when the month reviewed is not the current one (stock is a live snapshot) */
    oos_top_sellers: number | null; oos_units_30d?: number;
  };
  insights: { tone: 'good' | 'bad' | 'warn' | 'neutral'; text: string }[];
  td_change: number;
  tail: { styles: number; of_styles: number; sales: number; share_pct: number | null };
  stock: { value: number; lines: number; units: number; top_styles: { style: string; units: number }[] } | null;
  decisions: ProductDecision[];
  leaders: StyleLeaders;
}
export interface LeaderRow {
  style: string; name: string | null; category: string; sales: number; units: number; retailers: number;
  prev_sales: number; vs_prev_pct: number | null; share_of_category_pct: number | null; share_of_td_pct: number | null;
  launched_on: string | null; days_live: number | null; sales_per_day: number | null;
}
export interface LeaderWindow {
  from: string; to: string; prev_from: string; prev_to: string; total: number;
  all: LeaderRow[];
  categories: { key: string; name: string; sales: number; styles: number }[];
  by_category: Record<string, LeaderRow[]>;
  new_launches: LeaderRow[]; new_launches_count: number; new_launches_selling: number; new_launch_sales: number;
}
export type StyleLeaders = { windows: number[]; new_launch_days: number } & Record<string, LeaderWindow>;

export type InsightArea = 'sales' | 'drivers' | 'retailers' | 'territory' | 'product' | 'goal' | 'adoption' | 'operations' | 'growth' | 'tech' | 'risk';
export interface ExecInsight { area: InsightArea; tone: 'good' | 'bad' | 'warn' | 'neutral'; title: string; text: string }
export interface ExecDecision {
  area: InsightArea; owner: string; title: string; reason: string;
  value: number | null; value_label: string; link?: string | null;
}
export interface ExecSummary {
  bridge: { prev: number; current: number; change: number; steps: { key: 'new' | 'base' | 'spend'; label: string; value: number; note: string }[] };
  insights: ExecInsight[];
  decisions: ExecDecision[];
  momentum: { goal: number; goal_pct: number | null; short: number; prev_goal_pct: number | null; avg_goal_pct_3m: number | null };
}

export type SalesAskKind = 'stretch' | 'stalled' | 'no_asm' | 'warm' | 'stock' | 'slow' | 'new' | 'reassign';
export interface SalesAsk {
  kind: SalesAskKind; title: string; detail: string; owner: string; distributor: string | null; region: string | null;
  value: number | null; value_label: string; priority: 'high' | 'medium';
}
export interface SalesAsks { asks: SalesAsk[]; td_growth_3m_pct: number | null; warm_total: number; activation_per_month: number }

export interface MarketingAsk {
  kind: string; title: string; audience: number; channel: string; offer: string; detail: string;
  rate_pct: number | null; value: number | null; value_label: string; priority: 'high' | 'medium';
}
export interface FinanceAsk {
  kind: 'settle_cadence' | 'incentives'; title: string; detail: string; priority: 'high' | 'medium';
  value: number | null; value_label: string;
}

export interface TierRow {
  tier: string; sales: number; prev_sales: number; change: number; mom_pct: number | null; share_pct: number | null;
  growth_share_pct: number | null; retailers: number; prev_retailers: number; new: number; new_sales: number;
  spend: number | null; bo_retailers: number | null; bo_on_td: number | null; reach_pct: number | null;
}
export interface GrowthDrivers {
  window: { current: string; previous: string };
  total: number; change: number; tiers: TierRow[];
  kyc: Partial<Record<'kyc_new' | 'kyc_to_order_pct' | 'kyc_base' | 'ants', { value: number | null; prev: number | null }>>;
  new: { retailers: number; prev_retailers: number; sales: number; share_pct: number | null; spend: number | null; repeat_spend: number | null; from_bo: number };
  reads: { tone: 'good' | 'bad' | 'warn' | 'neutral'; text: string }[];
}

export interface Scorecard {
  summary: ExecSummary;
  sales_asks: SalesAsks;
  growth_drivers?: GrowthDrivers;
  finance_asks?: { asks: FinanceAsk[] };
  marketing_asks?: { asks: MarketingAsk[]; spend_per_retailer: number; rates: Record<string, number> };
  products: ProductMatrix;
  /** territory filters in force ('East · ASM …'); null = all TD */
  scope_label?: string | null;
  month: string;
  label: string;
  partial: boolean;
  days_elapsed: number;
  days_total: number;
  as_of: string;
  compare: { prev: string; last_year: string | null; current: string };
  targets_note: string | null;
  headline: {
    sales: number;
    target: number | null;
    achievement_pct: number | null;
    projected: number | null;
    projected_pct: number | null;
    mom_pct: number | null;
    yoy_pct: number | null;
    status: RowStatus;
    run_rate_per_day: number;
    required_per_day: number | null;
  };
  rows: ScoreRow[];
  trend: TrendPoint[];
  /** sales vs target by region / RSM / state / ASM (page 1 card switch) */
  territory: Record<'region' | 'rsm' | 'state' | 'asm', { id: number | null; name: string; sales: number; target: number | null; achievement_pct: number | null; prev: number; mom_pct: number | null; active_retailers: number }[]>;
  movers: { up: Mover[]; down: Mover[] };
  path: PathToGoal;
}
export interface Mover { id: number; name: string; sales: number; prev: number; change: number }

export type Section = 'growth' | 'tech' | 'other';
export type ItemStatus = 'planned' | 'in_progress' | 'blocked' | 'done' | 'dropped';

export interface MbrItem {
  id: number;
  month: string;
  section: Section;
  kind: string;
  kind_label: string;
  title: string;
  detail: string;
  team: string;
  team_label: string;
  lever: string;
  lever_label: string;
  owner: string;
  status: ItemStatus;
  status_label: string;
  priority: 'high' | 'medium' | 'low';
  expected_impact: number | null;
  planned_date: string | null;
  revised_date: string | null;
  done_date: string | null;
  event_date: string | null;
  blocker: string;
  carried_from: number | null;
  sort: number;
  updated_by: string;
  updated_at: string | null;
  adherence?: { state: 'on_time' | 'late' | 'overdue' | 'slipping' | 'on_track' | 'dropped' | 'undated'; slip_days: number | null };
}

export interface Opt { value: string; label: string }
export interface MbrNotes {
  month: string;
  review: { went_well: string; needs_attention: string; goal_monthly_sales: number | null; goal_by: string | null; updated_by: string; updated_at: string | null };
  items: MbrItem[];
  tech_summary: { total: number; done: number; on_time: number; late: number; overdue: number; blocked: number; in_progress: number; adherence_pct: number | null; avg_slip_days: number | null };
  previous_open: number;
  previous_month: string;
  choices: { sections: Opt[]; kinds: Record<Section, Opt[]>; teams: Opt[]; levers: Opt[]; statuses: Opt[]; priorities: Opt[] };
  can_edit: boolean;
}
