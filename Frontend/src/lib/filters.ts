import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import dayjs from 'dayjs';
import type { Params } from './api';

export const PRESETS = [
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'wtd', label: 'This week' },
  { value: 'mtd', label: 'MTD' },
  { value: 'prev_month', label: 'Previous month' },
  { value: 'qtd', label: 'QTD' },
  { value: 'fytd', label: 'FYTD' },
  { value: 'last_12m', label: 'Last 12 months' },
  { value: 'custom', label: 'Custom range' },
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

/** Keys that make up the global filter bar — kept in the URL so links are shareable. */
export const GLOBAL_KEYS = ['preset', 'date_from', 'date_to', 'region', 'state', 'asm', 'distributor', 'category', 'segment', 'payment_status'] as const;
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

/** Query params sent to the API (contract: comma-separated ids). */
export function toApiParams(f: GlobalFilters, opts: { includeSegment?: boolean } = {}): Params {
  const out: Params = { preset: f.preset };
  if (f.preset === 'custom') {
    out.date_from = f.date_from;
    out.date_to = f.date_to;
  }
  for (const k of MULTI_KEYS) if (f[k].length) out[k] = f[k].join(',');
  if (opts.includeSegment !== false && f.segment) out.segment = f.segment;
  if (f.payment_status) out.payment_status = f.payment_status;
  return out;
}

export function useFilters() {
  const [sp, setSp] = useSearchParams();
  const filters = useMemo(() => parseFilters(sp), [sp]);
  const apiParams = useMemo(() => toApiParams(filters), [filters]);

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

  const reset = useCallback(() => {
    setSp(
      (prev) => {
        const next = new URLSearchParams(prev);
        GLOBAL_KEYS.forEach((k) => next.delete(k));
        next.delete('page');
        return next;
      },
      { replace: true },
    );
  }, [setSp]);

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
