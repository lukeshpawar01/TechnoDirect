import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import dayjs from 'dayjs';
import type { Params } from './api';

/** Date presets, in dropdown order. `group` renders as an <optgroup>; `hidden` presets stay valid in old links but are not offered. */
export const PRESETS = [
  { value: 'today', label: 'Daily', group: 'Day' },
  { value: 'yesterday', label: 'Previous day', group: 'Day' },
  { value: 'wtd', label: 'This week', group: 'Week' },
  { value: 'last_week', label: 'Last week', group: 'Week' },
  { value: 'mtd', label: 'Monthly · MTD', group: 'Month' },
  { value: 'prev_month', label: 'Last month', group: 'Month' },
  { value: 'q1', label: 'Q1 · Apr–Jun', group: 'Quarter (FY)' },
  { value: 'q2', label: 'Q2 · Jul–Sep', group: 'Quarter (FY)' },
  { value: 'q3', label: 'Q3 · Oct–Dec', group: 'Quarter (FY)' },
  { value: 'q4', label: 'Q4 · Jan–Mar', group: 'Quarter (FY)' },
  { value: 'qtd', label: 'Quarter to date', group: 'Quarter (FY)', hidden: true },
  { value: 'fytd', label: 'Yearly · YTD', group: 'Year' },
  { value: 'last_7d', label: 'Last 7d', group: 'Rolling' },
  { value: 'last_30d', label: 'Last 30d', group: 'Rolling' },
  { value: 'last_90d', label: 'Last 90d', group: 'Rolling' },
  { value: 'last_12m', label: 'Last 12 months', group: 'Rolling' },
  { value: 'all_time', label: 'All time', group: 'Other' },
  // custom dates are picked in the From/To boxes beside the dropdown, not from the list
  { value: 'custom', label: 'Custom dates', group: 'Other', hidden: true },
] as const;

export type Preset = (typeof PRESETS)[number]['value'];

export const SEGMENTS = [
  { value: 'new', label: 'New' },
  { value: 'retained', label: 'Retained' },
  { value: 'reactivated', label: 'Reactivated' },
  { value: 'inactive', label: 'Inactive' },
  { value: 'one_time', label: 'One-time' },
  { value: 'repeat', label: 'Repeat' },
];

/** Keys of the global filter bar — kept in the URL and carried to every page (and drill-down link). */
export const GLOBAL_KEYS = ['preset', 'date_from', 'date_to', 'region', 'rsm', 'state', 'asm', 'distributor', 'category'] as const;
/**
 * Module filters — URL params owned by one page's filter row. They are sent to the API with every request
 * from that page but are NOT carried when navigating, so another page never inherits them.
 */
export const MODULE_KEYS = [
  'segment', 'order_status', 'payment_status', 'platform', 'payment_mode', 'is_split', 'cat_l1', 'cat_l2', 'cat_l3', 'size', 'article', 'tier',
  'kyc_status', 'kyc_verified', 'event_type', 'stock_sync', 'settlement_status', 'pay_status', 'payout_date', 'date_basis',
] as const;
export type ModuleKey = (typeof MODULE_KEYS)[number];
export type GlobalKey = (typeof GLOBAL_KEYS)[number];
export const MULTI_KEYS = ['region', 'rsm', 'state', 'asm', 'distributor', 'category'] as const;
export type MultiKey = (typeof MULTI_KEYS)[number];

export interface GlobalFilters {
  preset: Preset;
  date_from?: string;
  date_to?: string;
  region: string[];
  rsm: string[];
  state: string[];
  asm: string[];
  distributor: string[];
  category: string[];
  segment?: string;
  payment_status?: string;
}

const split = (v: string | null) => (v ? v.split(',').filter(Boolean) : []);

export function parseFilters(sp: URLSearchParams): GlobalFilters {
  const p = (sp.get('preset') as Preset | null) ?? 'mtd';
  return {
    preset: PRESETS.some((x) => x.value === p) ? p : 'mtd',
    date_from: sp.get('date_from') ?? undefined,
    date_to: sp.get('date_to') ?? undefined,
    region: split(sp.get('region')),
    rsm: split(sp.get('rsm')),
    state: split(sp.get('state')),
    asm: split(sp.get('asm')),
    distributor: split(sp.get('distributor')),
    category: split(sp.get('category')),
    segment: sp.get('segment') ?? undefined,
    payment_status: sp.get('payment_status') ?? undefined,
  };
}

/** Query params sent to the API (contract: comma-separated ids): global filters + this page's module filters. */
export function toApiParams(f: GlobalFilters, sp?: URLSearchParams, opts: { includeSegment?: boolean } = {}): Params {
  const out: Params = { preset: f.preset };
  if (f.preset === 'custom') {
    out.date_from = f.date_from;
    out.date_to = f.date_to;
  }
  for (const k of MULTI_KEYS) if (f[k].length) out[k] = f[k].join(',');
  if (sp) {
    for (const k of MODULE_KEYS) {
      const v = sp.get(k);
      if (v) out[k] = v;
    }
  }
  if (opts.includeSegment === false) delete out.segment;
  return out;
}

export function useFilters() {
  const [sp, setSp] = useSearchParams();
  const filters = useMemo(() => parseFilters(sp), [sp]);
  const apiParams = useMemo(() => toApiParams(filters, sp), [filters, sp]);

  const update = useCallback(
    (patch: Partial<Record<GlobalKey | string, string | string[] | undefined | null>>) => {
      setSp(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            const val = Array.isArray(v) ? v.join(',') : v;
            if (val === undefined || val === null || val === '') next.delete(k);
            else next.set(k, val);
          }
          // Any filter change resets list paging.
          if (!('page' in patch)) next.delete('page');
          return next;
        },
        { replace: true },
      );
    },
    [setSp],
  );

  /** Clear the given keys (default: everything the filter bars own) and list paging. */
  const reset = useCallback(
    (keys: readonly string[] = [...GLOBAL_KEYS, ...MODULE_KEYS]) => {
      setSp(
        (prev) => {
          const next = new URLSearchParams(prev);
          keys.forEach((k) => next.delete(k));
          next.delete('page');
          return next;
        },
        { replace: true },
      );
    },
    [setSp],
  );

  return { filters, apiParams, update, reset, searchParams: sp };
}

/** Build a link to another page carrying the global filters plus extra params. */
export function linkWithFilters(path: string, current: URLSearchParams, extra: Record<string, string | number | undefined> = {}): string {
  const [base, qs] = path.split('?');
  const next = new URLSearchParams();
  for (const k of GLOBAL_KEYS) {
    const v = current.get(k);
    if (v) next.set(k, v);
  }
  // Params embedded in the target link (e.g. exceptions from the API) win over globals.
  if (qs) new URLSearchParams(qs).forEach((v, k) => next.set(k, v));
  for (const [k, v] of Object.entries(extra)) {
    if (v === undefined || v === '') next.delete(k);
    else next.set(k, String(v));
  }
  const s = next.toString();
  return s ? `${base}?${s}` : base;
}

/** Human description of the selected period (client-side approximation, IST). */
export function describePreset(f: GlobalFilters): string {
  const label = PRESETS.find((p) => p.value === f.preset)?.label ?? 'MTD';
  if (f.preset === 'custom' && f.date_from && f.date_to) {
    return `${dayjs(f.date_from).format('DD MMM YY')} – ${dayjs(f.date_to).format('DD MMM YY')}`;
  }
  return label;
}

/** Today's date in IST (the backend's calendar), whatever this browser's time zone. */
export function todayIst(now = new Date()): dayjs.Dayjs {
  const ist = new Date(now.getTime() + (330 + now.getTimezoneOffset()) * 60_000);
  return dayjs(new Date(ist.getFullYear(), ist.getMonth(), ist.getDate()));
}

const QUARTER_START_MONTH: Record<string, number> = { q1: 3, q2: 6, q3: 9, q4: 0 };
const ROLLING: Record<string, number> = { last_7d: 7, last_30d: 30, last_90d: 90 };

/**
 * The From/To dates a preset covers — mirrors analytics/filters.py resolve_period so the date boxes can show
 * them. `from` is null for All time (its start is the first order, known only to the server).
 */
export function presetRange(f: Pick<GlobalFilters, 'preset' | 'date_from' | 'date_to'>, today = todayIst()): { from: string | null; to: string } {
  const iso = (d: dayjs.Dayjs) => d.format('YYYY-MM-DD');
  const t = today;
  const fyStart = t.month() >= 3 ? t.year() : t.year() - 1;
  let s: dayjs.Dayjs | null = t;
  let e = t;
  switch (f.preset) {
    case 'yesterday': s = e = t.subtract(1, 'day'); break;
    case 'wtd': s = t.subtract((t.day() + 6) % 7, 'day'); break;
    case 'last_week': s = t.subtract(((t.day() + 6) % 7) + 7, 'day'); e = s.add(6, 'day'); break;
    case 'mtd': s = t.startOf('month'); break;
    case 'prev_month': s = t.subtract(1, 'month').startOf('month'); e = s.endOf('month').startOf('day'); break;
    case 'qtd': s = t.startOf('month').subtract(((t.month() - 3 + 12) % 12) % 3, 'month'); break;
    case 'fytd': s = dayjs(new Date(fyStart, 3, 1)); break;
    case 'q1': case 'q2': case 'q3': case 'q4': {
      const m = QUARTER_START_MONTH[f.preset];
      s = dayjs(new Date(m >= 3 ? fyStart : fyStart + 1, m, 1));
      const qEnd = s.add(2, 'month').endOf('month').startOf('day');
      e = s.isAfter(t) || qEnd.isBefore(t) ? qEnd : t;
      break;
    }
    case 'last_7d': case 'last_30d': case 'last_90d': s = t.subtract(ROLLING[f.preset] - 1, 'day'); break;
    case 'last_12m': s = t.startOf('month').subtract(11, 'month'); break;
    case 'all_time': s = null; break;
    case 'custom': return { from: f.date_from ?? null, to: f.date_to ?? iso(t) };
  }
  return { from: s ? iso(s) : null, to: iso(e) };
}

/** Financial year label (Apr–Mar): 2026-11-11 → "FY 2026-27" */
export function fyLabel(d = todayIst()): string {
  const y = d.month() >= 3 ? d.year() : d.year() - 1;
  return `FY ${y}-${String((y + 1) % 100).padStart(2, '0')}`;
}
