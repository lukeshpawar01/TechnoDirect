/**
 * Contract-shaped, deterministic sample data for demo / frontend development.
 * Shape follows the TD strategic review: â‚¹2.95 Cr in Aug-26, AOV â‰ˆ â‚¹41k,
 * Heera Exports â‰ˆ 37% share, heavy concentration in a few states.
 */
import dayjs, { type Dayjs } from 'dayjs';
import type {
  ProductTree,
  ProductTreeRow,
  AdminUser,
  AuditEntry,
  DataHealth,
  DistributorDetail,
  DistributorRow,
  FilterOptions,
  Funnel,
  Inventory,
  InventoryItem,
  Me,
  Meta,
  MetricDef,
  OrderDetail,
  OrderRow,
  OrdersSummary,
  Overview,
  Permission,
  Products,
  RetailerDetail,
  RetailerRow,
  Retention,
  Role,
  Target,
  Territory,
} from '@/api/types';

// ------------------------------------------------------------------ rng
function mulberry32(a: number) {
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rng = mulberry32(20261111);
const r = () => rng();
const pick = <T,>(a: T[]) => a[Math.floor(r() * a.length)];
const between = (a: number, b: number) => a + r() * (b - a);
const round = (n: number, d = 0) => Math.round(n * 10 ** d) / 10 ** d;

export const NOW = dayjs();
const ISO = (d: Dayjs) => d.format('YYYY-MM-DDTHH:mm:ssZ');

// ------------------------------------------------------------------ dimensions
export const REGIONS = [
  { id: 1, name: 'West' },
  { id: 2, name: 'South' },
  { id: 3, name: 'North' },
  { id: 4, name: 'East' },
  { id: 5, name: 'Central' },
];
export const STATES = [
  { id: 1, name: 'Maharashtra', region_id: 1 },
  { id: 2, name: 'Gujarat', region_id: 1 },
  { id: 3, name: 'Karnataka', region_id: 2 },
  { id: 4, name: 'Tamil Nadu', region_id: 2 },
  { id: 5, name: 'Telangana', region_id: 2 },
  { id: 6, name: 'Kerala', region_id: 2 },
  { id: 7, name: 'Delhi', region_id: 3 },
  { id: 8, name: 'Uttar Pradesh', region_id: 3 },
  { id: 9, name: 'Punjab', region_id: 3 },
  { id: 10, name: 'Rajasthan', region_id: 3 },
  { id: 11, name: 'West Bengal', region_id: 4 },
  { id: 12, name: 'Madhya Pradesh', region_id: 5 },
];
export const ASMS = [
  { id: 1, name: 'Rahul Deshmukh', region_id: 1 },
  { id: 2, name: 'Priya Shah', region_id: 1 },
  { id: 3, name: 'Karthik Rao', region_id: 2 },
  { id: 4, name: 'Anitha Subramanian', region_id: 2 },
  { id: 5, name: 'Vikram Singh', region_id: 3 },
  { id: 6, name: 'Neha Gupta', region_id: 3 },
  { id: 7, name: 'Sourav Das', region_id: 4 },
  { id: 8, name: 'Amit Tiwari', region_id: 5 },
];
const DIST_SHARE = [37, 14, 10.5, 8, 7, 6, 5, 4, 3, 2.5, 1.7, 1.3];
export const DISTRIBUTORS = [
  { id: 1, name: 'Heera Exports', state_id: 1, asm_id: 1 },
  { id: 2, name: 'Shree Balaji Traders', state_id: 2, asm_id: 2 },
  { id: 3, name: 'Om Sai Distributors', state_id: 3, asm_id: 3 },
  { id: 4, name: 'Krishna Agencies', state_id: 4, asm_id: 4 },
  { id: 5, name: 'Mahalaxmi Enterprises', state_id: 1, asm_id: 1 },
  { id: 6, name: 'Sunrise Sportswear', state_id: 7, asm_id: 5 },
  { id: 7, name: 'Vinayak Marketing', state_id: 5, asm_id: 3 },
  { id: 8, name: 'Royal Distributors', state_id: 8, asm_id: 6 },
  { id: 9, name: 'Ganesh Trading Co.', state_id: 10, asm_id: 5 },
  { id: 10, name: 'Amar Sales Corporation', state_id: 11, asm_id: 7 },
  { id: 11, name: 'Patel Sports Hub', state_id: 12, asm_id: 8 },
  { id: 12, name: 'Southern Star Agencies', state_id: 6, asm_id: 4 },
];
export const CATEGORIES = [
  { code: 'TSH', name: 'T-Shirts' },
  { code: 'POL', name: 'Polos' },
  { code: 'TRK', name: 'Track Pants' },
  { code: 'SHO', name: 'Shorts' },
  { code: 'JKT', name: 'Jackets' },
  { code: 'JOG', name: 'Joggers' },
  { code: 'INN', name: 'Innerwear' },
  { code: 'ACC', name: 'Accessories' },
];
const CAT_SHARE = [34, 18, 15, 12, 8, 6, 4, 3];
const ORDER_STATUSES = ['received', 'confirmed', 'shipped', 'delivered', 'cancelled'];
const PAYMENT_STATUSES = ['success', 'failed', 'pending'];

export const filterOptions: FilterOptions = {
  regions: REGIONS,
  states: STATES,
  asms: ASMS,
  distributors: DISTRIBUTORS.map(({ id, name, state_id }) => ({ id, name, state_id })),
  categories: CATEGORIES,
  order_statuses: ORDER_STATUSES,
  payment_statuses: PAYMENT_STATUSES,
};

// ------------------------------------------------------------------ monthly backbone (â‚¹ lakh)
const MONTHLY_LAKH = [38, 52, 61, 74, 88, 96, 118, 131, 142, 160, 171, 189, 204, 221, 238, 252, 270, 295, 281, 276];
export const MONTHS: string[] = Array.from({ length: 21 }, (_, i) => NOW.subtract(20 - i, 'month').format('YYYY-MM'));
const daysInCur = NOW.daysInMonth();
const dayOfMonth = NOW.date();
const mtdLakh = round(268 * (dayOfMonth / daysInCur) * 1.04, 1);
// Index 17 is the peak month (Aug-26 when "today" is Nov-26): exactly â‚¹2.95 Cr, as in the review deck.
export const MONTHLY_SALES = [...MONTHLY_LAKH.map((l, i) => l * 1e5 * (i === 17 ? 1 : between(0.985, 1.015))), mtdLakh * 1e5];
const AOV_BASE = 41000;

export interface Q {
  [k: string]: string | undefined;
}

/** Shrink totals when the user narrows the scope, so filters visibly "do something". */
export function scaleFor(q: Q): number {
  let s = 1;
  if (q.distributor) {
    const ids = q.distributor.split(',').map(Number);
    s *= ids.reduce((a, id) => a + (DIST_SHARE[id - 1] ?? 2), 0) / 100;
  } else if (q.state) s *= Math.min(1, q.state.split(',').length * 0.22);
  else if (q.region) s *= Math.min(1, q.region.split(',').length * 0.3);
  if (q.asm && !q.distributor) s *= Math.min(1, q.asm.split(',').length * 0.16);
  if (q.category) s *= q.category.split(',').reduce((a, c) => a + (CAT_SHARE[CATEGORIES.findIndex((x) => x.code === c)] ?? 3), 0) / 100;
  if (q.segment) s *= q.segment === 'new' ? 0.12 : q.segment === 'repeat' || q.segment === 'retained' ? 0.7 : 0.18;
  if (q.payment_status === 'failed') s *= 0.06;
  else if (q.payment_status === 'pending') s *= 0.02;
  return Math.max(0.01, s);
}

// ------------------------------------------------------------------ periods
export function period(q: Q): { from: Dayjs; to: Dayjs; label: string; cFrom: Dayjs; cTo: Dayjs } {
  const p = q.preset ?? 'mtd';
  const t = NOW.startOf('day');
  switch (p) {
    case 'today':
      return { from: t, to: t, label: 'Today', cFrom: t.subtract(1, 'day'), cTo: t.subtract(1, 'day') };
    case 'yesterday':
      return { from: t.subtract(1, 'day'), to: t.subtract(1, 'day'), label: 'Yesterday', cFrom: t.subtract(2, 'day'), cTo: t.subtract(2, 'day') };
    case 'wtd': {
      const f = t.subtract((t.day() + 6) % 7, 'day');
      return { from: f, to: t, label: 'This week', cFrom: f.subtract(7, 'day'), cTo: t.subtract(7, 'day') };
    }
    case 'prev_month': {
      const f = t.subtract(1, 'month').startOf('month');
      return { from: f, to: f.endOf('month'), label: 'Previous month', cFrom: f.subtract(1, 'month'), cTo: f.subtract(1, 'month').endOf('month') };
    }
    case 'qtd': {
      const qm = Math.floor(t.month() / 3) * 3;
      const f = t.month(qm).startOf('month');
      return { from: f, to: t, label: 'QTD', cFrom: f.subtract(3, 'month'), cTo: t.subtract(3, 'month') };
    }
    case 'fytd': {
      const y = t.month() >= 3 ? t.year() : t.year() - 1;
      const f = dayjs(`${y}-04-01`);
      return { from: f, to: t, label: 'FYTD', cFrom: f.subtract(1, 'year'), cTo: t.subtract(1, 'year') };
    }
    case 'last_12m': {
      const f = t.subtract(12, 'month').add(1, 'day');
      return { from: f, to: t, label: 'Last 12 months', cFrom: f.subtract(12, 'month'), cTo: t.subtract(12, 'month') };
    }
    case 'custom': {
      const f = dayjs(q.date_from ?? t.startOf('month'));
      const to = dayjs(q.date_to ?? t);
      const len = to.diff(f, 'day') + 1;
      return { from: f, to, label: 'Custom', cFrom: f.subtract(len, 'day'), cTo: f.subtract(1, 'day') };
    }
    default: {
      const f = t.startOf('month');
      return { from: f, to: t, label: 'MTD', cFrom: f.subtract(1, 'month'), cTo: t.subtract(1, 'month') };
    }
  }
}

/** Sales between two dates using the monthly backbone spread evenly over days. */
function salesBetween(from: Dayjs, to: Dayjs): number {
  let s = 0;
  let d = from.startOf('day');
  let guard = 0;
  while (!d.isAfter(to, 'day') && guard++ < 800) {
    const idx = MONTHS.indexOf(d.format('YYYY-MM'));
    const month = idx >= 0 ? MONTHLY_SALES[idx] : 0;
    const denom = idx === MONTHS.length - 1 ? dayOfMonth : d.daysInMonth();
    const dow = [0.7, 1.08, 1.06, 1.04, 1.1, 1.12, 0.9][d.day()];
    s += (month / denom) * dow;
    d = d.add(1, 'day');
  }
  return s;
}

function refreshTimes() {
  const at = (d: Dayjs, h: number) => d.hour(h).minute(0).second(0).millisecond(0);
  const t = NOW;
  const candidates = [at(t.subtract(1, 'day'), 18), at(t, 10), at(t, 18), at(t.add(1, 'day'), 10)];
  const last = [...candidates].reverse().find((c) => !c.isAfter(t))!;
  const next = candidates.find((c) => c.isAfter(t))!;
  return { last, next };
}

export function meta(q: Q, freshnessOverride?: Meta['freshness']): Meta {
  const p = period(q);
  const { last, next } = refreshTimes();
  return {
    sales_basis: 'Gross order value of paid orders (PayU-verified), before returns',
    as_of: ISO(last.add(7, 'minute')),
    last_refresh_at: ISO(last),
    next_refresh_at: ISO(next),
    period: { from: p.from.format('YYYY-MM-DD'), to: p.to.format('YYYY-MM-DD'), label: p.label, compare_from: p.cFrom.format('YYYY-MM-DD'), compare_to: p.cTo.format('YYYY-MM-DD') },
    freshness: freshnessOverride ?? [
      { source: 'medusa', last_success_at: ISO(last.add(4, 'minute')), status: 'ok' },
      { source: 'payu', last_success_at: ISO(last.add(5, 'minute')), status: 'ok' },
      { source: 'sheets_crm', last_success_at: ISO(last.add(6, 'minute')), status: 'ok' },
      { source: 'channel_konnect', last_success_at: ISO(last.subtract(1, 'day')), status: 'stale' },
    ],
  };
}

// ------------------------------------------------------------------ overview
// Last point is the current (partial) month â€” project it to a full month so the sparkline doesn't fake a crash.
const spark12 = (vals: number[]) => vals.slice(-12).map((v, i, a) => round(i === a.length - 1 && vals.length === MONTHS.length ? (v * daysInCur) / dayOfMonth : v, 2));

export function overview(q: Q): Overview {
  const p = period(q);
  const s = scaleFor(q);
  const sales = salesBetween(p.from, p.to) * s;
  const cSales = salesBetween(p.cFrom, p.cTo) * s * 0.97;
  const aov = AOV_BASE * between(0.97, 1.04);
  const cAov = AOV_BASE * 0.96;
  const orders = Math.max(0, Math.round(sales / aov));
  const cOrders = Math.round(cSales / cAov);
  const monthlySales = MONTHLY_SALES.map((v) => v * s);
  const monthlyOrders = monthlySales.map((v) => v / AOV_BASE);
  const kpi = (value: number, compare: number | null, spark: number[]) => ({
    value: round(value, 2),
    compare: compare === null ? null : round(compare, 2),
    delta_pct: compare ? round(((value - compare) / compare) * 100, 1) : null,
    spark: spark12(spark),
  });
  const active = Math.round(orders / 1.55);
  const isMonthish = ['mtd', 'prev_month', 'today', 'yesterday', 'wtd'].includes(q.preset ?? 'mtd');
  const target = isMonthish ? 3.2e7 * s : null;
  const daysElapsed = dayOfMonth;
  const mtd = salesBetween(NOW.startOf('month'), NOW) * s;

  const daily: Overview['daily_trend'] = [];
  let cum = 0;
  let d = p.from;
  let guard = 0;
  while (!d.isAfter(p.to, 'day') && guard++ < 400) {
    const v = salesBetween(d, d) * s * between(0.8, 1.2);
    cum += v;
    const tgtDays = d.daysInMonth();
    daily.push({
      date: d.format('YYYY-MM-DD'),
      sales: round(v),
      orders: Math.round(v / AOV_BASE),
      cum_sales: round(cum),
      cum_target: target && p.from.isSame(p.to, 'month') ? round((3.2e7 * s * d.date()) / tgtDays) : null,
    });
    d = d.add(1, 'day');
  }

  const funnelTotal = Math.max(orders, 1);
  return {
    kpis: {
      sales: kpi(sales, cSales, monthlySales),
      orders: kpi(orders, cOrders, monthlyOrders),
      aov: kpi(aov, cAov, monthlySales.map((_, i) => AOV_BASE * (0.9 + i * 0.006))),
      units_per_order: kpi(between(46, 52), 47.5, monthlySales.map((_, i) => 44 + i * 0.3 + r())),
      realisation_per_unit: kpi(between(840, 880), 832, monthlySales.map((_, i) => 800 + i * 3 + r() * 10)),
      active_retailers: kpi(active, Math.round(cOrders / 1.6), monthlyOrders.map((o) => o / 1.55)),
      new_retailers: kpi(Math.round(active * 0.14), Math.round(cOrders / 1.6 * 0.16), monthlyOrders.map((o) => (o / 1.55) * 0.18)),
      repeat_retailers: kpi(Math.round(active * 0.62), Math.round(cOrders / 1.6 * 0.58), monthlyOrders.map((o) => (o / 1.55) * 0.55)),
      active_distributors: kpi(q.distributor ? q.distributor.split(',').length : 12, 12, Array.from({ length: 12 }, (_, i) => Math.min(12, 6 + Math.floor(i / 2)))),
    },
    target:
      target === null
        ? null
        : {
            target: round(target),
            achieved: round(mtd),
            achievement_pct: round((mtd / target) * 100, 1),
            balance: round(Math.max(0, target - mtd)),
            days_elapsed: daysElapsed,
            days_total: daysInCur,
            current_run_rate: round(mtd / daysElapsed),
            required_run_rate: round(Math.max(0, target - mtd) / Math.max(1, daysInCur - daysElapsed)),
            projected: round((mtd / daysElapsed) * daysInCur),
          },
    daily_trend: daily,
    monthly: MONTHS.map((m, i) => ({
      month: m,
      sales: round(monthlySales[i]),
      orders: Math.round(monthlyOrders[i]),
      aov: round(AOV_BASE * (0.9 + i * 0.006)),
      active_retailers: Math.round(monthlyOrders[i] / 1.55),
      prev_year_sales: i >= 12 ? round(monthlySales[i - 12]) : null,
    })),
    order_funnel: [
      { status: 'received', count: Math.round(funnelTotal * 0.08), value: round(sales * 0.08) },
      { status: 'confirmed', count: Math.round(funnelTotal * 0.11), value: round(sales * 0.11) },
      { status: 'shipped', count: Math.round(funnelTotal * 0.19), value: round(sales * 0.19) },
      { status: 'delivered', count: Math.round(funnelTotal * 0.58), value: round(sales * 0.58) },
      { status: 'cancelled', count: Math.round(funnelTotal * 0.04), value: round(sales * 0.04) },
    ],
    concentration: { top3_distributor_share: 61.5, top_state: { name: 'Maharashtra', share: 47.2 }, top10_retailer_share: 18.4 },
    top_distributors: DISTRIBUTORS.slice(0, 6).map((x, i) => ({ id: x.id, name: x.name, sales: round(sales * DIST_SHARE[i] / 100), share: DIST_SHARE[i], growth_pct: round(between(-12, 28), 1) })),
    top_states: [
      { id: 1, name: 'Maharashtra', sales: round(sales * 0.472), share: 47.2 },
      { id: 2, name: 'Gujarat', sales: round(sales * 0.14), share: 14 },
      { id: 3, name: 'Karnataka', sales: round(sales * 0.105), share: 10.5 },
      { id: 4, name: 'Tamil Nadu', sales: round(sales * 0.08), share: 8 },
      { id: 7, name: 'Delhi', sales: round(sales * 0.06), share: 6 },
      { id: 5, name: 'Telangana', sales: round(sales * 0.05), share: 5 },
    ],
    exceptions: [
      { code: 'sla_breach', severity: 'high', count: 23, message: 'orders not dispatched within 48 h', link: '/orders?order_status=confirmed' },
      { code: 'paid_no_order', severity: 'high', count: 3, message: 'PayU payments with no matching order', link: '/data-health' },
      { code: 'inactive_60', severity: 'medium', count: 412, message: 'retailers inactive for 60+ days', link: '/retailers?segment=inactive_60' },
      { code: 'never_ordered_warm', severity: 'medium', count: 186, message: 'warm KYC-approved retailers never ordered', link: '/retailers?segment=never_ordered&warm=true' },
      { code: 'stock_stale', severity: 'low', count: 2, message: 'distributors with stock older than 72 h', link: '/inventory' },
    ],
  };
}

// ------------------------------------------------------------------ funnel
export function funnel(q: Q): Funnel {
  const s = Math.sqrt(scaleFor(q));
  const n = (v: number) => Math.round(v * s);
  return {
    stages: [
      { key: 'signed_up', label: 'Signed up', count: n(6840) },
      { key: 'kyc_submitted', label: 'KYC submitted', count: n(5310) },
      { key: 'kyc_approved', label: 'KYC approved', count: n(4620) },
      { key: 'first_order', label: 'First order', count: n(2380) },
      { key: 'repeat_order', label: 'Repeat order', count: n(1460) },
      { key: 'active_this_period', label: 'Active this period', count: n(612) },
    ],
    kyc_status: [
      { status: 'approved', count: n(4620) },
      { status: 'pending', count: n(470) },
      { status: 'rejected', count: n(220) },
    ],
    never_ordered: { total: n(2240), warm: n(186), cold: n(1990), flagged: n(64) },
    inactivity: { d30: n(780), d60: n(412), d90: n(268) },
    kyc_to_first_order_by_month: MONTHS.slice(-12).map((m, i) => {
      const k = Math.round(between(180, 320) * s);
      const rate = Math.min(0.75, 0.32 + i * 0.022 + between(-0.03, 0.03));
      return { month: m, kyc_approved: k, converted: Math.round(k * rate), rate: round(rate * 100, 1) };
    }),
    acquisition_monthly: (() => {
      let c = n(380);
      return MONTHS.map((m, i) => {
        const v = Math.round((40 + i * 9 + between(-8, 8)) * s);
        c += v;
        return { month: m, new_retailers: v, cumulative: c };
      });
    })(),
    by_state: STATES.map((st, i) => {
      const k = Math.round((900 - i * 65) * s);
      const ever = Math.round(k * between(0.35, 0.62));
      return { state: st.name, kyc_approved: k, ever_ordered: ever, active: Math.round(ever * between(0.2, 0.35)), adoption_pct: round((ever / Math.max(1, k)) * 100, 1) };
    }),
  };
}

// ------------------------------------------------------------------ retailers
const SHOP_A = ['Sai', 'Shiv', 'Ganesh', 'Jai Ambe', 'New', 'Royal', 'Sports', 'Fashion', 'Star', 'Lucky', 'Shree', 'Krishna', 'Balaji', 'Om', 'Modern', 'City'];
const SHOP_B = ['Collection', 'Garments', 'Sports', 'Fashion Hub', 'Traders', 'Mens Wear', 'Emporium', 'Store', 'Creations', 'Apparel'];
const CITIES: Record<number, string[]> = {
  1: ['Mumbai', 'Pune', 'Nagpur', 'Nashik', 'Thane'],
  2: ['Ahmedabad', 'Surat', 'Vadodara'],
  3: ['Bengaluru', 'Mysuru', 'Hubballi'],
  4: ['Chennai', 'Coimbatore', 'Madurai'],
  5: ['Hyderabad', 'Warangal'],
  6: ['Kochi', 'Thiruvananthapuram'],
  7: ['New Delhi'],
  8: ['Lucknow', 'Kanpur', 'Noida'],
  9: ['Ludhiana', 'Amritsar'],
  10: ['Jaipur', 'Udaipur'],
  11: ['Kolkata', 'Howrah'],
  12: ['Indore', 'Bhopal'],
};

function weightedDistributor() {
  const x = r() * 100;
  let acc = 0;
  for (let i = 0; i < DISTRIBUTORS.length; i++) {
    acc += DIST_SHARE[i];
    if (x <= acc) return DISTRIBUTORS[i];
  }
  return DISTRIBUTORS[0];
}

export const RETAILERS: (RetailerRow & { pincode: string; city: string; state_id: number; distributor_id: number })[] = Array.from({ length: 960 }, (_, i) => {
  const dist = weightedDistributor();
  const st = STATES.find((s) => s.id === dist.state_id)!;
  const asm = ASMS.find((a) => a.id === dist.asm_id)!;
  const never = r() < 0.28;
  const orders = never ? 0 : Math.max(1, Math.round(Math.pow(r(), 2.2) * 40));
  const first = never ? null : NOW.subtract(Math.floor(between(5, 600)), 'day');
  const daysSince = never ? null : Math.floor(Math.pow(r(), 1.8) * Math.min(200, NOW.diff(first!, 'day')));
  const last = never ? null : NOW.subtract(daysSince!, 'day');
  const kyc = never && r() < 0.15 ? 'pending' : 'approved';
  let segment = 'repeat';
  if (never) segment = 'never_ordered';
  else if (daysSince! >= 90) segment = 'inactive';
  else if (orders === 1) segment = first!.isAfter(NOW.subtract(30, 'day')) ? 'new' : 'one_time';
  else if (daysSince! < 30) segment = r() < 0.75 ? 'retained' : 'reactivated';
  const phone = `98${String(Math.floor(between(10000000, 99999999)))}`;
  return {
    id: 1000 + i,
    name: `${pick(SHOP_A)} ${pick(SHOP_B)}`,
    phone: `${phone.slice(0, 2)}XXXXXX${phone.slice(-2)}`,
    state: st.name,
    state_id: st.id,
    distributor: dist.name,
    distributor_id: dist.id,
    asm: asm.name,
    kyc_status: kyc,
    first_order_date: first?.format('YYYY-MM-DD') ?? null,
    last_order_date: last?.format('YYYY-MM-DD') ?? null,
    days_since_last_order: daysSince,
    orders,
    sales: round(orders * AOV_BASE * between(0.6, 1.4)),
    segment,
    warm_match: never ? r() < 0.09 : r() < 0.3,
    pincode: String(Math.floor(between(110001, 799999))),
    city: pick(CITIES[st.id] ?? ['â€“']),
  };
});

export function retailerDetail(id: number): RetailerDetail | null {
  const x = RETAILERS.find((rr) => rr.id === id);
  if (!x) return null;
  const monthly = MONTHS.slice(-12).map((m) => {
    const o = x.orders === 0 ? 0 : Math.max(0, Math.round(between(-0.5, 2.5) * (x.orders / 12)));
    return { month: m, orders: o, sales: round(o * AOV_BASE * between(0.7, 1.3)) };
  });
  return {
    ...x,
    kyc_approved_at: x.kyc_status === 'approved' ? NOW.subtract(Math.floor(between(30, 700)), 'day').format('YYYY-MM-DD') : null,
    tier: x.sales > 1e6 ? 'Gold' : x.sales > 3e5 ? 'Silver' : 'Bronze',
    aov: x.orders ? round(x.sales / x.orders) : 0,
    monthly,
    recent_orders: ORDERS.filter((o) => o.retailer === x.name).slice(0, 10),
  };
}

// ------------------------------------------------------------------ orders
export const ORDERS: (OrderRow & { distributor_id: number })[] = Array.from({ length: 640 }, (_, i) => {
  const placed = NOW.subtract(Math.floor(Math.pow(r(), 1.5) * 75 * 24 * 60), 'minute');
  const ageH = NOW.diff(placed, 'hour');
  const rr = pick(RETAILERS.filter((x) => x.orders > 0).slice(0, 400));
  let status = 'delivered';
  if (r() < 0.04) status = 'cancelled';
  else if (ageH < 12) status = 'received';
  else if (ageH < 40) status = r() < 0.6 ? 'confirmed' : 'shipped';
  else if (ageH < 120) status = r() < 0.5 ? 'shipped' : 'delivered';
  else if (r() < 0.03) status = 'confirmed';
  const value = round(AOV_BASE * between(0.35, 2.2));
  const payment_status = status === 'cancelled' ? pick(['failed', 'success']) : r() < 0.02 ? 'pending' : 'success';
  const dispatchH = ['shipped', 'delivered'].includes(status) ? round(between(6, 70), 1) : null;
  return {
    id: 50000 + i,
    display_id: `TD${String(240000 + 640 - i)}`,
    placed_at: ISO(placed),
    retailer: rr.name,
    distributor: rr.distributor,
    distributor_id: rr.distributor_id,
    state: rr.state,
    status,
    payment_status,
    payment_mode: pick(['UPI', 'UPI', 'UPI', 'Card', 'Net banking', 'BNPL']),
    value,
    units: Math.round(value / between(780, 920)),
    awb: dispatchH ? `AWB${Math.floor(between(1e9, 9e9))}` : null,
    dispatch_hours: dispatchH,
    is_split: r() < 0.12,
  };
}).sort((a, b) => (a.placed_at < b.placed_at ? 1 : -1));

const STYLES = Array.from({ length: 60 }, (_, i) => {
  const cat = CATEGORIES[Math.min(CATEGORIES.length - 1, Math.floor(Math.pow(r(), 1.4) * CATEGORIES.length))];
  const names: Record<string, string[]> = {
    TSH: ['Dri-Fit Crew Tee', 'Cotton Round Neck', 'Raglan Sports Tee', 'Melange Tee'],
    POL: ['Pique Polo', 'Tipped Collar Polo', 'Performance Polo'],
    TRK: ['Classic Track Pant', 'Slim Fit Track Pant', 'Lycra Track Pant'],
    SHO: ['Training Shorts', 'Running Shorts', 'Bermuda Shorts'],
    JKT: ['Windcheater', 'Hooded Jacket', 'Bomber Jacket'],
    JOG: ['Cuffed Jogger', 'Cargo Jogger'],
    INN: ['Vest Pack', 'Brief Pack'],
    ACC: ['Sports Socks', 'Cap'],
  };
  return { style: `TS${String(1100 + i)}`, name: pick(names[cat.code]), category: cat.name };
});

export function orderDetail(id: number): OrderDetail | null {
  const o = ORDERS.find((x) => x.id === id);
  if (!o) return null;
  const placed = dayjs(o.placed_at);
  const nLines = 2 + Math.floor(r() * 4);
  const perLine = o.value / nLines;
  const lines = Array.from({ length: nLines }, () => {
    const st = pick(STYLES);
    const qty = Math.max(1, Math.round(perLine / 850));
    return { sku: `${st.style}-${pick(['S', 'M', 'L', 'XL', 'XXL'])}`, style: st.style, name: st.name, size: pick(['S', 'M', 'L', 'XL', 'XXL']), qty, price: round(perLine / qty), value: round(perLine) };
  });
  const tl: OrderDetail['timeline'] = [{ at: o.placed_at, status: 'received', note: `Placed by ${o.retailer}` }];
  if (o.payment_status === 'success') tl.push({ at: ISO(placed.add(2, 'minute')), event: 'payment_captured', note: `PayU Â· ${o.payment_mode}` });
  if (['confirmed', 'shipped', 'delivered'].includes(o.status)) tl.push({ at: ISO(placed.add(3, 'hour')), status: 'confirmed', actor: o.distributor });
  if (['shipped', 'delivered'].includes(o.status)) tl.push({ at: ISO(placed.add(o.dispatch_hours ?? 24, 'hour')), status: 'shipped', note: o.awb ?? undefined });
  if (o.status === 'delivered') tl.push({ at: ISO(placed.add((o.dispatch_hours ?? 24) + 60, 'hour')), status: 'delivered' });
  if (o.status === 'cancelled') tl.push({ at: ISO(placed.add(5, 'hour')), status: 'cancelled', note: 'Cancelled by retailer' });
  const payments: OrderDetail['payments'] = [];
  if (o.payment_status === 'failed' || r() < 0.1) payments.push({ txn_id: `PAYU${Math.floor(between(1e11, 9e11))}`, amount: o.value, status: 'failed', mode: 'Card', at: ISO(placed.add(1, 'minute')) });
  payments.push({ txn_id: `PAYU${Math.floor(between(1e11, 9e11))}`, amount: o.value, status: o.payment_status ?? 'pending', mode: o.payment_mode, at: ISO(placed.add(2, 'minute')) });
  return { ...o, lines, timeline: tl, payments };
}

export function ordersSummary(q: Q): OrdersSummary {
  const s = scaleFor(q);
  const base = overview(q);
  const total = base.order_funnel.reduce((a, b) => a + b.count, 0);
  const n = (v: number) => Math.round(v * Math.sqrt(s));
  return {
    status_counts: base.order_funnel,
    ageing: ['received', 'confirmed', 'shipped'].flatMap((st, si) =>
      ['0-1d', '1-2d', '2-4d', '4-7d', '7d+'].map((b, bi) => ({ bucket: b, status: st, count: n(Math.max(0, (40 - bi * 9 - si * 4) * between(0.6, 1.3))) })),
    ),
    tat: {
      order_to_dispatch_median_h: 26.5,
      order_to_delivery_median_h: 92,
      trend: MONTHS.slice(-12).map((m, i) => ({ month: m, dispatch_h: round(44 - i * 1.4 + between(-3, 3), 1), delivery_h: round(130 - i * 3.2 + between(-6, 6), 1) })),
    },
    cancellation_rate: round((base.order_funnel[4].count / Math.max(1, total)) * 100, 1),
    payment: {
      success: Math.round(total * 0.93),
      failed: Math.round(total * 0.055),
      pending: Math.round(total * 0.015),
      failed_value: round(total * 0.055 * AOV_BASE * 1.1),
      paid_no_order: 3,
      mode_mix: [
        { mode: 'UPI', count: Math.round(total * 0.58), value: round(total * 0.58 * AOV_BASE * 0.85) },
        { mode: 'Card', count: Math.round(total * 0.17), value: round(total * 0.17 * AOV_BASE * 1.2) },
        { mode: 'Net banking', count: Math.round(total * 0.15), value: round(total * 0.15 * AOV_BASE * 1.35) },
        { mode: 'BNPL', count: Math.round(total * 0.1), value: round(total * 0.1 * AOV_BASE * 0.95) },
      ],
    },
    split_orders: { split_carts: Math.round(total * 0.11), total_carts: total },
    sla_breaches: n(23),
    crm: {
      open: n(41),
      by_type: [
        { type: 'Delivery delay', count: n(14) },
        { type: 'Wrong / short item', count: n(9) },
        { type: 'Size exchange', count: n(8) },
        { type: 'Payment issue', count: n(6) },
        { type: 'Quality', count: n(4) },
      ],
    },
  };
}

// ------------------------------------------------------------------ distributors & territory
export function distributors(q: Q): { rows: DistributorRow[] } {
  const p = period(q);
  const total = salesBetween(p.from, p.to) * scaleFor({ ...q, distributor: undefined });
  const ids = q.distributor ? q.distributor.split(',').map(Number) : null;
  return {
    rows: DISTRIBUTORS.filter((d) => !ids || ids.includes(d.id)).map((d, _i) => {
      const i = d.id - 1;
      const sales = (total * DIST_SHARE[i]) / 100;
      const orders = Math.max(1, Math.round(sales / (AOV_BASE * between(0.85, 1.15))));
      const retailers = RETAILERS.filter((rr) => rr.distributor_id === d.id).length;
      const active = Math.round(orders / 1.5);
      const target = (3.2e7 * DIST_SHARE[i]) / 100;
      const syncH = i === 9 ? 100 : i === 6 ? 40 : between(1, 14);
      return {
        id: d.id,
        name: d.name,
        state: STATES.find((s) => s.id === d.state_id)!.name,
        sales: round(sales),
        share: DIST_SHARE[i],
        orders,
        aov: round(sales / orders),
        retailers,
        active_retailers: Math.min(retailers, active),
        new_retailers: Math.round(active * 0.15),
        repeat_pct: round(between(45, 78), 1),
        orders_per_retailer: round(orders / Math.max(1, active), 2),
        dispatch_pct: round(between(72, 98), 1),
        median_dispatch_days: round(between(0.6, 3.2), 1),
        l3m_sales: round(MONTHLY_SALES.slice(-4, -1).reduce((a, b) => a + b, 0) * DIST_SHARE[i] / 100),
        growth_pct: round(between(-15, 35), 1),
        target: round(target),
        achievement_pct: round((salesBetween(NOW.startOf('month'), NOW) * DIST_SHARE[i] / 100 / target) * 100, 1),
        last_stock_sync: i === 11 ? null : ISO(NOW.subtract(syncH, 'hour')),
        spark: spark12(MONTHLY_SALES.map((v) => round(((v * DIST_SHARE[i]) / 100) * between(0.85, 1.15)))),
      };
    }),
  };
}

export function distributorDetail(id: number, q: Q): DistributorDetail | null {
  const d = DISTRIBUTORS.find((x) => x.id === id);
  if (!d) return null;
  const row = distributors({ ...q, distributor: String(id) }).rows[0];
  const ov = overview({ ...q, distributor: String(id) });
  const st = STATES.find((s) => s.id === d.state_id)!;
  return {
    profile: {
      id,
      name: d.name,
      code: `DST-${String(id).padStart(3, '0')}`,
      state: st.name,
      region: REGIONS.find((rg) => rg.id === st.region_id)!.name,
      asm: ASMS.find((a) => a.id === d.asm_id)!.name,
      city: CITIES[st.id]?.[0],
      onboarded_on: NOW.subtract(400 + id * 20, 'day').format('YYYY-MM-DD'),
      last_stock_sync: row.last_stock_sync,
      gstin: `27AAB${String(id).padStart(4, '0')}F1Z5`,
    },
    kpis: { sales: ov.kpis.sales, orders: ov.kpis.orders, aov: ov.kpis.aov, active_retailers: ov.kpis.active_retailers, new_retailers: ov.kpis.new_retailers, repeat_retailers: ov.kpis.repeat_retailers },
    monthly: ov.monthly.map((m) => ({ month: m.month, sales: m.sales, orders: m.orders, active_retailers: m.active_retailers })),
    top_articles: products({ ...q, distributor: String(id) }).top_articles.slice(0, 15),
    retailers: RETAILERS.filter((rr) => rr.distributor_id === id)
      .sort((a, b) => b.sales - a.sales)
      .slice(0, 50)
      .map((rr) => ({ id: rr.id, name: rr.name, state: rr.state, orders: rr.orders, sales: rr.sales, last_order_date: rr.last_order_date, days_since_last_order: rr.days_since_last_order, segment: rr.segment })),
  };
}

export function territory(q: Q): Territory {
  const g = q.group_by ?? 'region';
  const p = period(q);
  const total = salesBetween(p.from, p.to) * scaleFor(q);
  const groups = g === 'region' ? REGIONS : g === 'state' ? STATES : ASMS;
  const weights = groups.map((_, i) => Math.pow(0.62, i) + 0.05);
  const wsum = weights.reduce((a, b) => a + b, 0);
  const rows = groups.map((x, i) => {
    const sales = (total * weights[i]) / wsum;
    const target = (3.2e7 * weights[i]) / wsum;
    const kyc = Math.round(4620 * weights[i] / wsum);
    const active = Math.round(sales / AOV_BASE / 1.5);
    return {
      id: x.id,
      name: x.name,
      sales: round(sales),
      target: round(target),
      achievement_pct: round((salesBetween(NOW.startOf('month'), NOW) * weights[i] / wsum / target) * 100 * between(0.85, 1.2), 1),
      orders: Math.round(sales / AOV_BASE),
      active_retailers: active,
      new_retailers: Math.round(active * 0.14),
      kyc_base: kyc,
      adoption_pct: round(between(32, 64), 1),
      distributors: Math.max(1, Math.round(12 * weights[i] / wsum)),
      growth_pct: round(between(-10, 30), 1),
    };
  });
  return {
    rows,
    monthly_by_group: MONTHS.slice(-13, -1).flatMap((m) => {
      const idx = MONTHS.indexOf(m);
      return groups.map((x, i) => ({ month: m, group: x.name, sales: round((MONTHLY_SALES[idx] * scaleFor(q) * weights[i]) / wsum * between(0.9, 1.1)) }));
    }),
  };
}

// ------------------------------------------------------------------ products & inventory
export function products(q: Q): Products {
  const p = period(q);
  const total = salesBetween(p.from, p.to) * scaleFor(q);
  const articles = STYLES.map((st, i) => {
    const w = Math.pow(0.9, i) + 0.01;
    return { ...st, w };
  });
  const wsum = articles.reduce((a, b) => a + b.w, 0);
  const rows = articles.map((a) => {
    const sales = (total * a.w) / wsum;
    const units = Math.round(sales / between(780, 920));
    return { style: a.style, name: a.name, category: a.category, sales: round(sales), units, orders: Math.max(1, Math.round(units / 14)), retailers: Math.max(1, Math.round(units / 22)), share: round((a.w / wsum) * 100, 2) };
  });
  return {
    categories: CATEGORIES.map((c, i) => ({ code: c.code, name: c.name, sales: round((total * CAT_SHARE[i]) / 100), units: Math.round((total * CAT_SHARE[i]) / 100 / 860), share: CAT_SHARE[i], realisation: round(between(620, 1150)) })),
    category_mix_monthly: MONTHS.slice(-12).flatMap((m) => {
      const idx = MONTHS.indexOf(m);
      return CATEGORIES.map((c, i) => ({ month: m, category: c.name, sales: round((MONTHLY_SALES[idx] * scaleFor(q) * CAT_SHARE[i]) / 100 * between(0.85, 1.15)) }));
    }),
    top_articles: rows.slice(0, 25),
    bottom_articles: rows.slice(-15).reverse(),
    new_launches: STYLES.slice(48, 56).map((st, i) => ({ style: st.style, name: st.name, launched_on: NOW.subtract(5 + i * 6, 'day').format('YYYY-MM-DD'), sales: round(between(1.5e5, 9e5) * scaleFor(q)), units: Math.round(between(150, 900)), retailers: Math.round(between(12, 80)) })),
    size_mix: [
      { size: 'S', units: 4200, share: 11 },
      { size: 'M', units: 9100, share: 24 },
      { size: 'L', units: 11400, share: 30 },
      { size: 'XL', units: 8000, share: 21 },
      { size: 'XXL', units: 4200, share: 11 },
      { size: '3XL', units: 1100, share: 3 },
    ],
    concentration: { top4_share: 21.6, top12_share: 47.3, distinct_articles: 186 },
  };
}

/** Mock /products/tree/: shares shaped like the real TD mix (men ≈ 94%, bottomwear > topwear, trackpants lead). */
const TREE_SHAPE: [string, string, string, number][] = [
  ['men', 'bottomwear', 'trackpants', 40.5], ['men', 'bottomwear', 'shorts', 7.4], ['men', 'bottomwear', 'plus-size', 2.5],
  ['men', 'bottomwear', 'joggers', 2.1], ['men', 'bottomwear', 'trousers', 1.6], ['men', 'bottomwear', 'tights', 0.4],
  ['men', 'bottomwear', 'cargo-shorts', 0.1], ['men', 'topwear', 't-shirts', 30.3], ['men', 'topwear', 'jackets', 4.4],
  ['men', 'topwear', 'gym-vests', 1.1], ['men', 'innerwear', 'underwear', 2.5], ['men', 'accessories', 'socks', 0.01],
  ['kids', 'bottomwear', 'trackpants', 1.2], ['kids', 'topwear', 't-shirts', 0.9],
  ['women', 'bottomwear', 'tights', 1.1], ['women', 'topwear', 't-shirts', 1.0], ['unisex', 'topwear', 'jackets', 0.5],
];

export function productTree(q: Q): ProductTree {
  const p = period(q);
  const total = salesBetween(p.from, p.to) * scaleFor(q);
  const rows: ProductTreeRow[] = [];
  let styleNo = 10;
  TREE_SHAPE.forEach(([l1, l2, l3, share]) => {
    const n = share > 20 ? 14 : share > 2 ? 7 : 3;
    const weights = Array.from({ length: n }, (_, i) => Math.pow(0.68, i));
    const ws = weights.reduce((a, b) => a + b, 0);
    weights.forEach((w, i) => {
      const amount = round(((total * share) / 100) * (w / ws));
      const realisation = l2 === 'bottomwear' ? between(2600, 3100) : between(1700, 2100);
      const style = l1 === 'men' && l3 === 'trackpants' && i < 4 ? ['OR99', 'OR89', 'OR25', 'OR675'][i] : `OR${(styleNo += 7)}`;
      rows.push({ l1, l2, l3, style, name: `${l3.replace('-', ' ')} ${style}`, amount, quantity: Math.round(amount / realisation), orders: Math.max(1, Math.round(amount / 41000)) });
    });
  });
  rows.sort((a, b) => b.amount - a.amount);
  return {
    levels: [{ key: 'l1', label: 'Category I' }, { key: 'l2', label: 'Category II' }, { key: 'l3', label: 'Category III' }, { key: 'style', label: 'Style' }],
    total: { amount: round(rows.reduce((s, r) => s + r.amount, 0)), quantity: rows.reduce((s, r) => s + r.quantity, 0) },
    rows,
  };
}

export function inventory(): Inventory {
  const d = distributors({});
  return {
    sync: d.rows.map((x) => {
      const skus = Math.round(between(600, 1800));
      return {
        distributor_id: x.id,
        distributor: x.name,
        last_sync_at: x.last_stock_sync,
        status: !x.last_stock_sync ? 'failed' : (Date.now() - new Date(x.last_stock_sync).getTime()) / 36e5 > 24 ? 'stale' : 'ok',
        skus,
        in_stock_skus: Math.round(skus * between(0.62, 0.93)),
      };
    }),
    summary: { live_styles: 214, oos_skus: 386, low_stock_skus: 512 },
    oos_top_sellers: Array.from({ length: 14 }, () => {
      const st = pick(STYLES.slice(0, 20));
      return { style: `${st.style} Â· ${st.name}`, size: pick(['M', 'L', 'XL']), distributor: pick(DISTRIBUTORS.slice(0, 6)).name, last_30d_units: Math.round(between(40, 420)) };
    }).sort((a, b) => b.last_30d_units - a.last_30d_units),
  };
}

export const INVENTORY_ITEMS: InventoryItem[] = Array.from({ length: 420 }, () => {
  const st = pick(STYLES);
  const size = pick(['S', 'M', 'L', 'XL', 'XXL']);
  const qty = r() < 0.12 ? 0 : Math.round(Math.pow(r(), 1.6) * 240);
  return {
    distributor: weightedDistributor().name,
    sku: `${st.style}-${size}`,
    style: st.style,
    name: st.name,
    size,
    category: st.category,
    qty,
    status: qty === 0 ? 'oos' : qty < 12 ? 'low_stock' : 'in_stock',
    snapshot_date: NOW.subtract(r() < 0.1 ? 3 : 0, 'day').format('YYYY-MM-DD'),
  };
});

// ------------------------------------------------------------------ retention
export function retention(q: Q): Retention {
  const s = Math.sqrt(scaleFor(q));
  // Completed months only â€” the partial current month would show a fake collapse.
  const months = MONTHS.slice(-16, -1);
  let prevActive = 0;
  const movement = months.map((m) => {
    const idx = MONTHS.indexOf(m);
    const active = Math.round((MONTHLY_SALES[idx] / AOV_BASE / 1.55) * s);
    const retained = prevActive ? Math.round(prevActive * between(0.52, 0.64)) : Math.round(active * 0.5);
    const lost = prevActive ? prevActive - retained : 0;
    const newR = Math.round(active * between(0.14, 0.24));
    const reactivated = Math.max(0, active - retained - newR);
    const row = { month: m, active, retained, reactivated, new: newR, lost, net: active - prevActive, mom_retention: prevActive ? round((retained / prevActive) * 100, 1) : null };
    prevActive = active;
    return row;
  });
  return {
    movement: movement.slice(1),
    quarterly_retention: ['Q1 FY26', 'Q2 FY26', 'Q3 FY26', 'Q4 FY26', 'Q1 FY27', 'Q2 FY27'].map((qq, i) => ({ quarter: qq, rate: round(48 + i * 2.6 + between(-2, 2), 1) })),
    cohorts: MONTHS.slice(-13, -1).map((m, i, arr) => {
      const len = arr.length - i;
      return {
        cohort: m,
        size: Math.round(between(60, 180) * s),
        values: Array.from({ length: len }, (_, k) => (k === 0 ? 100 : round(Math.max(8, 62 * Math.pow(0.86, k - 1) + between(-6, 6)), 1))),
      };
    }),
    contribution: movement.slice(1).map((mv) => {
      const idx = MONTHS.indexOf(mv.month);
      const total = MONTHLY_SALES[idx] * scaleFor(q);
      const nShare = mv.new / Math.max(1, mv.active) * 0.8;
      const rShare = mv.reactivated / Math.max(1, mv.active) * 0.9;
      return { month: mv.month, new_sales: round(total * nShare), reactivated_sales: round(total * rShare), repeat_sales: round(total * (1 - nShare - rShare)) };
    }),
    order_bands: [
      { band: '1', retailers: Math.round(620 * s), sales: round(2.4e7 * s) },
      { band: '2', retailers: Math.round(310 * s), sales: round(2.6e7 * s) },
      { band: '3-5', retailers: Math.round(420 * s), sales: round(7.9e7 * s) },
      { band: '6-10', retailers: Math.round(260 * s), sales: round(1.02e8 * s) },
      { band: '11-20', retailers: Math.round(140 * s), sales: round(1.21e8 * s) },
      { band: '21+', retailers: Math.round(48 * s), sales: round(1.05e8 * s) },
    ],
    pareto: [
      { top_n: 10, share: 18.4 },
      { top_n: 25, share: 31.2 },
      { top_n: 50, share: 44.8 },
      { top_n: 100, share: 59.6 },
      { top_n: 250, share: 78.1 },
      { top_n: 500, share: 91.5 },
    ],
    avg_days_between_orders: 23.4,
    orders_per_active_retailer: movement.slice(1).map((mv, i) => ({ month: mv.month, value: round(1.38 + i * 0.015 + between(-0.05, 0.05), 2) })),
  };
}

// ------------------------------------------------------------------ data health
export function dataHealth(): DataHealth {
  const m = meta({});
  const { last, next } = refreshTimes();
  return {
    sources: [
      { source: 'medusa', status: 'ok', last_success_at: m.freshness[0].last_success_at, last_error: null, rows_last_run: 1842, next_run_at: ISO(next) },
      { source: 'payu', status: 'ok', last_success_at: m.freshness[1].last_success_at, last_error: null, rows_last_run: 911, next_run_at: ISO(next) },
      { source: 'sheets_crm', status: 'ok', last_success_at: m.freshness[2].last_success_at, last_error: null, rows_last_run: 57, next_run_at: ISO(next) },
      { source: 'channel_konnect', status: 'stale', last_success_at: ISO(last.subtract(1, 'day')), last_error: 'Timeout fetching stock for 2 distributors (Amar Sales Corporation, Southern Star Agencies)', rows_last_run: 18320, next_run_at: ISO(next) },
      { source: 'clevertap', status: 'failed', last_success_at: ISO(last.subtract(3, 'day')), last_error: '401 Unauthorized â€” API passcode expired', rows_last_run: 0, next_run_at: ISO(next) },
    ],
    issues: [
      { code: 'payu_success_no_order', label: 'PayU success with no order', count: 3, severity: 'high' },
      { code: 'paid_order_no_payu_txn', label: 'Paid order with no PayU txn', count: 5, severity: 'high' },
      { code: 'retailer_no_pincode_map', label: 'Retailers with unmapped pincode', count: 64, severity: 'medium' },
      { code: 'order_missing_distributor', label: 'Orders missing distributor', count: 2, severity: 'medium' },
      { code: 'sku_missing_category', label: 'SKUs without category', count: 17, severity: 'low' },
      { code: 'duplicate_phone', label: 'Retailers sharing a phone number', count: 9, severity: 'low' },
    ],
    reconciliation: [
      { metric: 'sales', period: MONTHS[MONTHS.length - 2], dashboard_value: round(MONTHLY_SALES[MONTHS.length - 2]), mis_value: round(MONTHLY_SALES[MONTHS.length - 2] * 1.004), diff_pct: -0.4 },
      { metric: 'orders', period: MONTHS[MONTHS.length - 2], dashboard_value: 671, mis_value: 668, diff_pct: 0.45 },
      { metric: 'active_retailers', period: MONTHS[MONTHS.length - 2], dashboard_value: 433, mis_value: 448, diff_pct: -3.35 },
      { metric: 'sales', period: MONTHS[MONTHS.length - 3], dashboard_value: round(MONTHLY_SALES[MONTHS.length - 3]), mis_value: round(MONTHLY_SALES[MONTHS.length - 3] * 0.988), diff_pct: 1.21 },
    ],
  };
}

// ------------------------------------------------------------------ auth & admin
export const PERMISSIONS: Permission[] = [
  { code: 'view_overview', label: 'View executive overview', group: 'Dashboards' },
  { code: 'view_funnel', label: 'View retailer funnel & lists', group: 'Dashboards' },
  { code: 'view_distributors', label: 'View distributors', group: 'Dashboards' },
  { code: 'view_territory', label: 'View territory', group: 'Dashboards' },
  { code: 'view_orders', label: 'View orders & fulfilment', group: 'Dashboards' },
  { code: 'view_products', label: 'View products', group: 'Dashboards' },
  { code: 'view_inventory', label: 'View inventory', group: 'Dashboards' },
  { code: 'view_retention', label: 'View retention & growth', group: 'Dashboards' },
  { code: 'view_data_health', label: 'View data health', group: 'Dashboards' },
  { code: 'export_data', label: 'Export CSV / Excel', group: 'Data' },
  { code: 'view_pii', label: 'See unmasked phone numbers', group: 'Data' },
  { code: 'trigger_sync', label: 'Trigger data refresh', group: 'Data' },
  { code: 'manage_targets', label: 'Manage targets', group: 'Administration' },
  { code: 'manage_mappings', label: 'Manage mappings', group: 'Administration' },
  { code: 'manage_metrics', label: 'Edit metric dictionary', group: 'Administration' },
  { code: 'manage_users', label: 'Manage users & roles', group: 'Administration' },
];

const VIEW_ALL = PERMISSIONS.filter((p) => p.code.startsWith('view_') && p.code !== 'view_pii').map((p) => p.code);

export const db = {
  roles: [
    { id: 1, name: 'Management', description: 'Leadership â€” all dashboards, exports', permissions: [...VIEW_ALL, 'export_data'], user_count: 3 },
    { id: 2, name: 'Operations', description: 'Ops team â€” orders, inventory, data health', permissions: ['view_overview', 'view_orders', 'view_inventory', 'view_data_health', 'export_data', 'view_pii', 'trigger_sync', 'manage_mappings'], user_count: 4 },
    { id: 3, name: 'ASM', description: 'Area sales managers â€” their territory only', permissions: ['view_overview', 'view_funnel', 'view_distributors', 'view_territory', 'view_retention', 'export_data'], user_count: 8 },
    { id: 4, name: 'Finance', description: 'Targets and reconciliation', permissions: ['view_overview', 'view_territory', 'view_data_health', 'export_data', 'manage_targets'], user_count: 2 },
  ] as Role[],
  users: [
    { id: 1, email: 'admin@technosport.in', full_name: 'Master Admin', is_active: true, role_id: 1, scope: { all: true, regions: [], states: [], asms: [], distributors: [] }, last_login: ISO(NOW.subtract(5, 'minute')) },
    { id: 2, email: 'ceo@technosport.in', full_name: 'Sanjay Mehta', is_active: true, role_id: 1, scope: { all: true, regions: [], states: [], asms: [], distributors: [] }, last_login: ISO(NOW.subtract(3, 'hour')) },
    { id: 3, email: 'ops.lead@technosport.in', full_name: 'Deepa Nair', is_active: true, role_id: 2, scope: { all: true, regions: [], states: [], asms: [], distributors: [] }, last_login: ISO(NOW.subtract(1, 'day')) },
    { id: 4, email: 'asm@technosport.in', full_name: 'Rahul Deshmukh', is_active: true, role_id: 3, scope: { all: false, regions: [1], states: [], asms: [1], distributors: [] }, last_login: ISO(NOW.subtract(2, 'day')) },
    { id: 5, email: 'karthik.rao@technosport.in', full_name: 'Karthik Rao', is_active: true, role_id: 3, scope: { all: false, regions: [], states: [3, 5], asms: [3], distributors: [] }, last_login: null },
    { id: 6, email: 'finance@technosport.in', full_name: 'Meera Iyer', is_active: false, role_id: 4, scope: { all: true, regions: [], states: [], asms: [], distributors: [] }, last_login: ISO(NOW.subtract(40, 'day')) },
  ] as AdminUser[],
  targets: [] as Target[],
  asms: ASMS.map((a) => ({ id: a.id, name: a.name, code: `ASM${String(a.id).padStart(2, '0')}`, email: `${a.name.split(' ')[0].toLowerCase()}@technosport.in`, phone: `98XXXXXX${10 + a.id}`, region_id: a.region_id, region_name: REGIONS.find((r2) => r2.id === a.region_id)!.name, is_active: true })) as Record<string, unknown>[],
  pincodes: Array.from({ length: 80 }, (_, i) => {
    const st = STATES[i % STATES.length];
    const asm = ASMS.find((a) => a.region_id === st.region_id) ?? ASMS[0];
    return { id: i + 1, pincode: String(400001 + i * 37), city: CITIES[st.id]?.[0] ?? '', state_id: st.id, state_name: st.name, asm_id: asm.id, asm_name: asm.name };
  }) as Record<string, unknown>[],
  regions: REGIONS.map((x) => ({ ...x, code: x.name.slice(0, 1) })) as Record<string, unknown>[],
  states: STATES.map((x) => ({ ...x, code: x.name.slice(0, 2).toUpperCase(), region_name: REGIONS.find((r2) => r2.id === x.region_id)!.name })) as Record<string, unknown>[],
  reconciliation: [
    { id: 1, metric: 'sales', period: MONTHS[MONTHS.length - 2], mis_value: round(MONTHLY_SALES[MONTHS.length - 2] * 1.004), notes: 'From monthly MIS deck' },
    { id: 2, metric: 'orders', period: MONTHS[MONTHS.length - 2], mis_value: 668, notes: '' },
    { id: 3, metric: 'active_retailers', period: MONTHS[MONTHS.length - 2], mis_value: 448, notes: 'MIS counts KYC-approved actives' },
  ] as Record<string, unknown>[],
  metrics: [
    { code: 'sales', name: 'Sales', definition: 'Gross order value of paid orders (PayU-verified), incl. taxes/charges, excluding cancelled; before returns.', formula: 'SUM(order.total) WHERE payment_status = success AND status != cancelled', source: 'Medusa + PayU', owner: 'Finance', refresh: '10:00 & 18:00 IST' },
    { code: 'orders', name: 'Orders', definition: 'Qualifying orders, split carts counted once at cart level.', formula: 'COUNT(DISTINCT split_group)', source: 'Medusa', owner: 'Operations', refresh: '10:00 & 18:00 IST' },
    { code: 'aov', name: 'Average order value', definition: 'Sales Ã· orders.', formula: 'sales / orders', source: 'Derived', owner: 'Finance', refresh: '10:00 & 18:00 IST' },
    { code: 'active_retailers', name: 'Active retailers', definition: 'Retailers with â‰¥1 qualifying order in the period.', formula: 'COUNT(DISTINCT retailer_id)', source: 'Medusa', owner: 'Sales', refresh: '10:00 & 18:00 IST' },
    { code: 'new_retailers', name: 'New retailers', definition: 'First-ever qualifying order in the period.', formula: 'first_order_date IN period', source: 'Derived', owner: 'Sales', refresh: '10:00 & 18:00 IST' },
    { code: 'retained', name: 'Retained', definition: 'Active this month and previous month.', formula: 'active(m) AND active(m-1)', source: 'RetailerMonth', owner: 'Sales', refresh: 'Nightly' },
    { code: 'reactivated', name: 'Reactivated', definition: 'Active this month, not previous, not new.', formula: 'active(m) AND NOT active(m-1) AND NOT new(m)', source: 'RetailerMonth', owner: 'Sales', refresh: 'Nightly' },
    { code: 'lost', name: 'Lost', definition: 'Active previous month, not this month.', formula: 'active(m-1) AND NOT active(m)', source: 'RetailerMonth', owner: 'Sales', refresh: 'Nightly' },
    { code: 'never_ordered', name: 'Never ordered', definition: 'KYC approved with zero orders; warm if matched to the BlueOrigin ledger.', formula: 'kyc = approved AND orders = 0', source: 'Medusa + ledger', owner: 'Sales', refresh: '10:00 & 18:00 IST' },
    { code: 'payment_success_rate', name: 'Payment success rate', definition: 'Successful PayU attempts Ã· all attempts on orders in the period.', formula: 'success / (success + failed + pending)', source: 'PayU', owner: 'Operations', refresh: '10:00 & 18:00 IST' },
  ] as MetricDef[],
  audit: [] as AuditEntry[],
};

// seed targets for current month
(() => {
  const m = NOW.format('YYYY-MM');
  let id = 1;
  db.targets.push({ id: id++, month: m, scope_type: 'overall', scope_id: null, scope_name: '', metric: 'sales', value: 3.2e7, effective_from: NOW.startOf('month').format('YYYY-MM-DD'), notes: 'Board-approved' });
  db.targets.push({ id: id++, month: m, scope_type: 'overall', scope_id: null, scope_name: '', metric: 'orders', value: 780, effective_from: NOW.startOf('month').format('YYYY-MM-DD'), notes: '' });
  REGIONS.forEach((rg, i) => db.targets.push({ id: id++, month: m, scope_type: 'region', scope_id: rg.id, scope_name: rg.name, metric: 'sales', value: round(3.2e7 * [0.55, 0.22, 0.12, 0.06, 0.05][i]), effective_from: NOW.startOf('month').format('YYYY-MM-DD'), notes: '' }));
  DISTRIBUTORS.forEach((d, i) => db.targets.push({ id: id++, month: m, scope_type: 'distributor', scope_id: d.id, scope_name: d.name, metric: 'sales', value: round((3.2e7 * DIST_SHARE[i]) / 100), effective_from: NOW.startOf('month').format('YYYY-MM-DD'), notes: '' }));
})();

// seed audit
(() => {
  const acts = [
    ['update', 'target', 'Revised after Diwali push'],
    ['create', 'user', null],
    ['update', 'role', null],
    ['update', 'pincode', 'ASM reassignment'],
    ['login', 'user', null],
    ['trigger_sync', 'sync_run', null],
  ] as const;
  for (let i = 0; i < 120; i++) {
    const [action, object_type, reason] = pick([...acts]);
    db.audit.push({
      id: 5000 - i,
      at: ISO(NOW.subtract(i * 47 + Math.floor(r() * 40), 'minute')),
      user_email: pick(db.users).email,
      action,
      object_type,
      object_id: Math.floor(between(1, 40)),
      before: action === 'update' ? { value: Math.round(between(1e5, 9e6)), notes: '' } : null,
      after: action === 'update' || action === 'create' ? { value: Math.round(between(1e5, 9e6)), notes: reason ?? '' } : null,
      reason,
    });
  }
})();

export function me(email: string): Me {
  const u = db.users.find((x) => x.email === email);
  const isAsm = email.startsWith('asm');
  const role = db.roles.find((x) => x.id === (u?.role_id ?? (isAsm ? 3 : 1)))!;
  return {
    id: u?.id ?? 1,
    email,
    full_name: u?.full_name ?? 'Demo User',
    is_master_admin: !isAsm,
    role: { id: role.id, name: role.name },
    permissions: isAsm ? role.permissions : PERMISSIONS.map((p) => p.code),
    scope: u?.scope ?? { all: true, regions: [], states: [], asms: [], distributors: [] },
  };
}
