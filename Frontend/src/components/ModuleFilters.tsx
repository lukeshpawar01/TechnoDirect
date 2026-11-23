import { useMemo } from 'react';
import { SEGMENT_TABS } from '@/lib/lifecycle';
import { useFilterOptions } from '@/api/hooks';
import type { FilterOptions } from '@/api/types';
import { SEGMENTS, useFilters, type ModuleKey } from '@/lib/filters';
import { MODE_LABELS, date as fmtDate } from '@/lib/format';
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


const PLATFORM_LABELS: Record<string, string> = { android: 'Android app', ios: 'iOS app', web: 'Website' };

const SEGMENT: FieldDef = { key: 'segment', label: 'Segment', single: true, options: SEGMENTS };
/** Lifecycle group (same list as the Retailers page tabs); empty = all retailers. */
const RETAILER_GROUP: FieldDef = { key: 'segment', label: 'Retailer type', single: true, width: 'w-40', options: SEGMENT_TABS.filter((t) => t.value) };
// Category I uses the global `category` key (hidden from the top bar on pages that show it here)
// customer `kyc` column: TRUE = verified (KYC approved)
const KYC_STATUS: FieldDef = { key: 'kyc_status', label: 'KYC status', options: ['approved', 'pending', 'rejected', 'not_submitted'].map((v) => ({ value: v, label: title(v) })) };
const KYC_VERIFIED: FieldDef = { key: 'kyc_verified', label: 'KYC Verified', single: true, width: 'w-40', options: [{ value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }] };
const CAT_L1: FieldDef = { key: 'category', label: 'Category I', options: catLevel(1), width: 'w-36' };
const CAT_L2: FieldDef = { key: 'cat_l2', label: 'Category II', options: catLevel(2), width: 'w-36' };
const CAT_L3: FieldDef = { key: 'cat_l3', label: 'Category III', options: catLevel(3), width: 'w-40' };
/** Style (article) code, narrowed by the category choices; search matches code or name. */
const STYLE: FieldDef = {
  key: 'article',
  label: 'Style',
  width: 'w-40',
  options: (o, sp) => {
    const l1 = new Set(csv(sp.get('category')));
    const l2 = new Set(csv(sp.get('cat_l2')));
    const l3 = new Set(csv(sp.get('cat_l3')));
    return (o?.styles ?? [])
      .filter((s) => (!l1.size || l1.has(s.l1)) && (!l2.size || l2.has(s.l2)) && (!l3.size || l3.has(s.l3)))
      .map((s) => {
        // names usually repeat the code ("OR99 Solid woven ..."): show it once
        const name = s.name.replace(new RegExp(`^${s.code}[\\s-]+`, 'i'), '').trim();
        return { value: s.code, label: name ? `${s.code} · ${name}` : s.code };
      });
  },
};

/** BlueOrigin tier from the offline sheets (latest quarter). */
const TIER: FieldDef = { key: 'tier', label: 'Tier', width: 'w-36', options: (o) => (o?.tiers ?? []).map((t) => ({ value: t, label: t })) };
/** On the app's retailer pages a retailer can also be absent from BlueOrigin. */
const TIER_TD: FieldDef = { ...TIER, options: (o, sp) => [...(TIER.options as (o: FilterOptions | undefined, sp: URLSearchParams) => Opt[])(o, sp), { value: 'None', label: 'Not in BlueOrigin' }] };

/** Page-specific filters, keyed by the nav path that owns them. Sent to the API only from that page. */
const MODULES: Record<string, FieldDef[]> = {
  '/overview': [SEGMENT, TIER_TD],
  '/funnel': [RETAILER_GROUP, KYC_STATUS, KYC_VERIFIED, TIER_TD],
  '/retailers': [
    KYC_STATUS,
    KYC_VERIFIED,
    TIER_TD,
    // segment has its own tabs on the Retailers page
  ],
  '/distributors': [
    {
      key: 'stock_sync',
      label: 'Stock sync',
      single: true,
      options: [
        { value: 'fresh', label: 'Within 3 days' },
        { value: 'stale', label: 'More than 3 days' },
        { value: 'never', label: 'Never synced' },
      ],
    },
  ],
  // Fulfilment first; payment fields come straight from the order (no gateway / settlement data)
  '/orders': [
    { key: 'order_status', label: 'Order status', width: 'w-48', options: (o) => (o?.order_statuses ?? []).map((s) => ({ value: s, label: title(s) })) },
    { key: 'payment_mode', label: 'Payment mode', width: 'w-40', options: (o) => (o?.payment_modes ?? []).map((s) => ({ value: s, label: MODE_LABELS[s] ?? s })) },
    { key: 'platform', label: 'Platform', options: (o) => (o?.platforms ?? []).map((s) => ({ value: s, label: PLATFORM_LABELS[s] ?? title(s) })) },
    { key: 'is_split', label: 'Cart type', single: true, options: [{ value: 'false', label: 'Single distributor' }, { value: 'true', label: 'Split cart' }] },
  ],
  '/products': [CAT_L1, CAT_L2, CAT_L3, STYLE],
  '/inventory': [CAT_L1, CAT_L2, CAT_L3, STYLE, { key: 'size', label: 'Size', options: (o) => (o?.sizes ?? []).map((s) => ({ value: s, label: s })), width: 'w-32' }],
  '/retention': [SEGMENT],
  '/blueorigin': [TIER],
  // finance tracker: the period filters the order date, or the payout date when "Date basis" says so
  '/settlements': [
    { key: 'date_basis', label: 'Date basis', single: true, width: 'w-44', options: [{ value: 'order', label: 'Period = order date' }, { value: 'payout', label: 'Period = payout date' }] },
    // no "Payment status": in the finance tracker it is always the same as Settlement status (approved = settled ...)
    { key: 'settlement_status', label: 'Settlement status', width: 'w-44', options: [{ value: 'settled', label: 'Settled' }, { value: 'not_settled', label: 'Not settled' }, { value: 'pending', label: 'Not reviewed' }, { value: 'cancelled', label: 'Cancelled' }] },
    { key: 'payout_date', label: 'Distributor settlement date', width: 'w-56', options: (o) => (o?.payout_dates ?? []).map((d) => ({ value: d, label: fmtDate(d, 'ddd, DD MMM YYYY') })) },
    // no "Payment mode": how the retailer paid (UPI / card ...) does not change what the distributor is paid
    { key: 'is_split', label: 'Cart type', single: true, width: 'w-48', options: [{ value: 'false', label: 'Single distributor' }, { value: 'true', label: 'Split (multi-distributor)' }] },
  ],
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
