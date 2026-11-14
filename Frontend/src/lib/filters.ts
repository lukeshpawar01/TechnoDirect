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
  { value: 'custom', label: 'Custom range', group: 'Other' },
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
export const GLOBAL_KEYS = ['preset', 'date_from', 'date_to', 'region', 'state', 'asm', 'distributor', 'category'] as const;
/**
 * Module filters — URL params owned by one page's filter row. They are sent to the API with every request
 * from that page but are NOT carried when navigating, so another page never inherits them.
 */
export const MODULE_KEYS = [
  'segment', 'payment_status', 'platform', 'payment_mode', 'is_split', 'cat_l1', 'cat_l2', 'cat_l3', 'size',
  'kyc_status', 'kyc_verified', 'event_type', 'stock_sync',
] as const;
export type ModuleKey = (typeof MODULE_KEYS)[number];
export type GlobalKey = (typeof GLOBAL_KEYS)[number];
export const MULTI_KEYS = ['region', 'state', 'asm', 'distributor', 'category'] as const;
export type MultiKey = (typeof MULTI_KEYS)[number];

export interface GlobalFilters {
  preset: Preset;
  date_from?: string;
  date_to?: string;
  region: string[];
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

/** Financial year label (Apr–Mar): 2026-11-11 → "FY 2026-27" */
export function fyLabel(d = dayjs()): string {
  const y = d.month() >= 3 ? d.year() : d.year() - 1;
  return `FY ${y}-${String((y + 1) % 100).padStart(2, '0')}`;
}
