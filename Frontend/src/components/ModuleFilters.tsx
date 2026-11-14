import { useMemo } from 'react';
import { useFilterOptions } from '@/api/hooks';
import type { FilterOptions } from '@/api/types';
import { SEGMENTS, useFilters, type ModuleKey } from '@/lib/filters';
import { navItemFor } from '@/nav';
import { MultiSelect } from './MultiSelect';
import { IconX } from './Icons';

type Opt = { value: string; label: string };
interface FieldDef {
  /** usually a module key; 'category' (Category I) is shared with the top bar so the choice carries across pages */
  key: ModuleKey | 'category';
  label: string;
  single?: boolean;
  width?: string;
  /** static options, or derived from /meta/filters/ and the current URL (for cascades) */
  options: Opt[] | ((o: FilterOptions | undefined, sp: URLSearchParams) => Opt[]);
}

const title = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace(/[_-]/g, ' ');
const csv = (v: string | null) => (v ? v.split(',') : []);

/** Category I → II → III cascade from the product catalogue. */
function catLevel(level: 1 | 2 | 3) {
  return (o: FilterOptions | undefined, sp: URLSearchParams): Opt[] => {
    // Category I is the top-bar "Category" filter
    const l1 = new Set(csv(sp.get('category')));
    const l2 = new Set(csv(sp.get('cat_l2')));
    const rows = (o?.category_tree ?? []).filter((r) => (level < 2 || !l1.size || l1.has(r.l1)) && (level < 3 || !l2.size || l2.has(r.l2)));
    const vals = [...new Set(rows.map((r) => (level === 1 ? r.l1 : level === 2 ? r.l2 : r.l3)).filter(Boolean))].sort();
    return vals.map((v) => ({ value: v, label: title(v) }));
  };
}

const SEGMENT: FieldDef = { key: 'segment', label: 'Segment', single: true, options: SEGMENTS };
// Category I uses the global `category` key (hidden from the top bar on pages that show it here)
const CAT_L1: FieldDef = { key: 'category', label: 'Category I', options: catLevel(1), width: 'w-36' };
const CAT_L2: FieldDef = { key: 'cat_l2', label: 'Category II', options: catLevel(2), width: 'w-36' };
const CAT_L3: FieldDef = { key: 'cat_l3', label: 'Category III', options: catLevel(3), width: 'w-40' };

/** Page-specific filters, keyed by the nav path that owns them. Sent to the API only from that page. */
const MODULES: Record<string, FieldDef[]> = {
  '/overview': [SEGMENT],
  '/retailers': [
    { key: 'kyc_status', label: 'KYC status', options: ['approved', 'pending', 'rejected', 'not_submitted'].map((v) => ({ value: v, label: title(v) })) },
    // segment has its own tabs on the Retailers page
  ],
  '/distributors': [
    {
      key: 'stock_sync',
      label: 'Stock sync',
      single: true,
      options: [
        { value: 'fresh', label: 'Fresh (< 24 h)' },
        { value: 'stale', label: 'Stale (> 24 h)' },
        { value: 'never', label: 'Never synced' },
      ],
    },
  ],
  '/orders': [
    { key: 'payment_status', label: 'Payment status', single: true, options: (o) => (o?.payment_statuses ?? []).map((s) => ({ value: s, label: title(s) })) },
    { key: 'payment_mode', label: 'Payment mode', options: (o) => (o?.payment_modes ?? []).map((s) => ({ value: s, label: s })) },
    { key: 'platform', label: 'Platform', options: (o) => (o?.platforms ?? []).map((s) => ({ value: s, label: title(s) })) },
    { key: 'is_split', label: 'Split orders', single: true, options: [{ value: 'true', label: 'Split only' }] },
  ],
  '/products': [CAT_L1, CAT_L2, CAT_L3],
  '/inventory': [CAT_L1, CAT_L2, CAT_L3, { key: 'size', label: 'Size', options: (o) => (o?.sizes ?? []).map((s) => ({ value: s, label: s })), width: 'w-32' }],
  '/retention': [SEGMENT],
  '/loyalty': [
    {
      key: 'event_type',
      label: 'Event type',
      options: [
        { value: 'new_customer', label: 'Welcome bonus' },
        { value: 'earned', label: 'Points earned' },
        { value: 'redeemed', label: 'Points redeemed' },
      ],
    },
  ],
};

/** Second filter row: filters that only make sense on the current module. */
export function ModuleFilters({ pathname }: { pathname: string }) {
  const item = navItemFor(pathname);
  const isDetail = !!item && pathname !== item.to; // detail pages (e.g. /orders/12) keep a clean header
  const fields = item && !isDetail ? MODULES[item.to] : undefined;
  const { update, reset, searchParams: sp } = useFilters();
  const opts = useFilterOptions();

  const resolved = useMemo(
    () => (fields ?? []).map((f) => ({ ...f, opts: typeof f.options === 'function' ? f.options(opts.data, sp) : f.options })),
    [fields, opts.data, sp],
  );
  if (!item || !resolved.length) return null;
  const active = resolved.some((f) => sp.get(f.key));

  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-line bg-sunken/40 px-3 py-2" aria-label={`${item.label} filters`}>
      <span className="mr-1 text-2xs font-semibold uppercase tracking-wider text-muted">{item.label} filters</span>
      {resolved.map((f) => (
        <MultiSelect
          key={f.key}
          label={f.label}
          single={f.single}
          options={f.opts}
          value={csv(sp.get(f.key))}
          onChange={(v) => {
            const patch: Record<string, string[] | undefined> = { [f.key]: v.length ? v : undefined };
            // narrowing a parent category clears child selections that may no longer exist
            if (f.key === 'category') Object.assign(patch, { cat_l2: undefined, cat_l3: undefined });
            if (f.key === 'cat_l2') patch.cat_l3 = undefined;
            update(patch);
          }}
          disabled={opts.isLoading && typeof f.options === 'function'}
          width={f.width ?? 'w-36'}
        />
      ))}
      {active && (
        <button
          className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs text-ink2 hover:bg-sunken hover:text-ink"
          onClick={() => reset(resolved.map((f) => f.key))}
        >
          <IconX size={12} /> Clear
        </button>
      )}
    </div>
  );
}
