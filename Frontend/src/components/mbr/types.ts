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
  /** % of TD sales the filtered territory made in the base months (null = all TD) */
  territory_share_pct: number | null;
  goal_by: string;
  goal_by_label: string;
  base_month: string;
  base_label: string;
  base_sales: number;
  gap_sales: number;
  goal_pct: number | null;
  months_left: number;
  monthly_growth_needed_pct: number | null;
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

export interface Scorecard {
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
