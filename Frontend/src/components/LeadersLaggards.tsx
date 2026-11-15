import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { DistributorRow } from '@/api/types';
import { linkWithFilters } from '@/lib/filters';
import { inr, num, pct, signedPct } from '@/lib/format';
import { Card, Meter, Segmented, cx } from './ui';

/**
 * Leaders & laggards: top 5 / bottom 5 distributors for ONE metric at a time.
 *
 * Ranking rules (so the list says something real instead of rewarding size or tiny bases):
 *  - sales:       absolute value; distributors with no sales are counted, not listed (they would all tie at 0)
 *  - growth:      vs the comparison period, only where that period had >= MIN_GROWTH_BASE in sales
 *  - target:      achievement %, only distributors with a target
 *  - activation:  % of mapped retailers that ordered in the period (rate, so big networks don't always win),
 *                 only distributors with >= MIN_RETAILERS mapped retailers
 *  - fulfilment:  % of orders dispatched, >= MIN_ORDERS orders; ties broken by faster median dispatch
 * When fewer than 10 qualify, the two lists split the field instead of repeating the same names.
 */
type MetricKey = 'sales' | 'growth' | 'growth_l3m' | 'target' | 'activation' | 'repeat' | 'fulfilment';

const MIN_GROWTH_BASE = 50_000;
const MIN_RETAILERS = 20;
const MIN_ORDERS = 5;
const N = 5;

interface Metric {
  label: string;
  /** what qualifies a distributor for this ranking (shown under the lists) */
  rule: string;
  eligible: (r: DistributorRow) => boolean;
  value: (r: DistributorRow) => number;
  /** secondary sort key, higher = better */
  tiebreak?: (r: DistributorRow) => number;
  display: (r: DistributorRow) => string;
  context: (r: DistributorRow) => string;
  /** meter scale */
  max: (rows: DistributorRow[]) => number;
  signed?: boolean;
}

const activation = (r: DistributorRow) => (r.retailers ? (r.active_retailers / r.retailers) * 100 : 0);
const maxOf = (rows: DistributorRow[], f: (r: DistributorRow) => number) => Math.max(1, ...rows.map((r) => Math.abs(f(r))));

const METRICS: Record<MetricKey, Metric> = {
  sales: {
    label: 'Sales',
    rule: 'Distributors with at least one paid order in the period',
    eligible: (r) => r.sales > 0,
    value: (r) => r.sales,
    display: (r) => inr(r.sales),
    context: (r) => `${num(r.orders)} orders · ${pct(r.share, 1)} share`,
    max: (rows) => maxOf(rows, (r) => r.sales),
  },
  growth: {
    label: 'Growth',
    rule: `Sales vs the comparison period · base of at least ${inr(MIN_GROWTH_BASE)}`,
    eligible: (r) => r.growth_pct !== null && (r.prev_sales ?? 0) >= MIN_GROWTH_BASE,
    value: (r) => r.growth_pct ?? 0,
    tiebreak: (r) => r.sales,
    display: (r) => signedPct(r.growth_pct ?? 0),
    context: (r) => `${inr(r.prev_sales)} → ${inr(r.sales)}`,
    max: (rows) => maxOf(rows, (r) => r.growth_pct ?? 0),
    signed: true,
  },
  growth_l3m: {
    label: 'Growth L3M',
    rule: 'Last 3 months vs the 3 months before · base of at least ₹50,000',
    eligible: (r) => r.l3m_growth_pct != null,
    value: (r) => r.l3m_growth_pct ?? 0,
    tiebreak: (r) => r.l3m_sales,
    display: (r) => signedPct(r.l3m_growth_pct ?? 0),
    context: (r) => `${inr(r.p3m_sales)} → ${inr(r.l3m_sales)}`,
    max: (rows) => maxOf(rows, (r) => r.l3m_growth_pct ?? 0),
    signed: true,
  },
  target: {
    label: 'Target',
    rule: 'Distributors with a sales target for the period',
    eligible: (r) => !!r.target,
    value: (r) => r.achievement_pct ?? 0,
    // equal % -> the bigger rupee gap to target ranks lower
    tiebreak: (r) => -((r.target ?? 0) - r.sales),
    display: (r) => pct(r.achievement_pct, 0),
    context: (r) => `${inr(r.sales)} of ${inr(r.target)}`,
    max: (rows) => Math.max(100, maxOf(rows, (r) => r.achievement_pct ?? 0)),
  },
  activation: {
    label: 'Activation',
    rule: `Share of mapped retailers who ordered · at least ${MIN_RETAILERS} mapped retailers`,
    eligible: (r) => r.retailers >= MIN_RETAILERS,
    value: activation,
    tiebreak: (r) => r.new_retailers,
    display: (r) => pct(activation(r), 1),
    context: (r) => `${num(r.active_retailers)} of ${num(r.retailers)} active · ${num(r.new_retailers)} new`,
    max: (rows) => maxOf(rows, activation),
  },
  repeat: {
    label: 'Repeat %',
    rule: `Share of the period's ordering retailers who had ordered before · at least ${MIN_ORDERS} orders`,
    eligible: (r) => r.orders >= MIN_ORDERS && r.active_retailers > 0,
    value: (r) => r.repeat_pct ?? 0,
    tiebreak: (r) => r.active_retailers,
    display: (r) => pct(r.repeat_pct, 0),
    context: (r) => `${num(r.active_retailers - r.new_retailers)} of ${num(r.active_retailers)} retailers`,
    max: () => 100,
  },
  fulfilment: {
    label: 'Fulfilment',
    rule: `Orders dispatched · at least ${MIN_ORDERS} orders; ties go to faster median dispatch`,
    eligible: (r) => r.orders >= MIN_ORDERS && r.dispatch_pct !== null,
    value: (r) => r.dispatch_pct ?? 0,
    tiebreak: (r) => -(r.median_dispatch_days ?? 1e9),
    display: (r) => pct(r.dispatch_pct, 0),
    context: (r) => `${num(r.orders)} orders${r.median_dispatch_days == null ? '' : ` · ${num(r.median_dispatch_days, 1)} d median`}`,
    max: () => 100,
  },
};

const ORDER: MetricKey[] = ['sales', 'growth', 'growth_l3m', 'target', 'activation', 'repeat', 'fulfilment'];
const KEY = 'td.distributors.rank';

function initial(): MetricKey {
  try {
    const v = localStorage.getItem(KEY) as MetricKey | null;
    return v && v in METRICS ? v : 'sales';
  } catch {
    return 'sales';
  }
}

export function LeadersLaggards({ rows, loading, searchParams }: { rows: DistributorRow[] | undefined; loading?: boolean; searchParams: URLSearchParams }) {
  const [metric, setMetric] = useState<MetricKey>(initial);
  const m = METRICS[metric];
  const nav = useNavigate();

  const { top, bottom, eligible, noSales, scale } = useMemo(() => {
    const all = rows ?? [];
    const el = all.filter(m.eligible);
    const sorted = [...el].sort((a, b) => m.value(b) - m.value(a) || (m.tiebreak?.(b) ?? 0) - (m.tiebreak?.(a) ?? 0) || a.name.localeCompare(b.name));
    // fewer than 2N qualify -> split the field so nobody is both a leader and a laggard
    const nTop = Math.min(N, Math.ceil(sorted.length / 2));
    const nBottom = Math.min(N, sorted.length - nTop);
    return {
      top: sorted.slice(0, nTop),
      bottom: nBottom ? sorted.slice(-nBottom).reverse() : [],
      eligible: el.length,
      noSales: all.filter((r) => r.sales <= 0).length,
      scale: m.max(el),
    };
  }, [rows, m]);

  const choose = (v: MetricKey) => {
    setMetric(v);
    try {
      localStorage.setItem(KEY, v);
    } catch {
      /* per-viewer preference only */
    }
  };

  const List = ({ title, items, start, lagging }: { title: string; items: DistributorRow[]; start: (i: number) => number; lagging?: boolean }) => (
    <div className="min-w-0">
      <div className="mb-1.5 flex items-baseline justify-between">
        <h4 className={cx('text-xs font-semibold uppercase tracking-wider', lagging ? 'text-bad' : 'text-good')}>{title}</h4>
      </div>
      {items.length ? (
        <ol className="divide-y divide-line">
          {items.map((r, i) => {
            const v = m.value(r);
            return (
              <li key={r.id}>
                <button
                  className="grid w-full grid-cols-[1.25rem_minmax(0,1fr)_5.5rem] items-center gap-x-2 rounded px-1 py-1.5 text-left hover:bg-sunken focus-visible:bg-sunken"
                  onClick={() => nav(linkWithFilters(`/distributors/${r.id}`, searchParams))}
                  title={`Open ${r.name}`}
                >
                  <span className="text-xs tabular-nums text-muted">{start(i)}</span>
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-ink">{r.name}</span>
                    <span className="block truncate text-2xs text-muted">{m.context(r)}</span>
                  </span>
                  <span className="text-right">
                    <span className={cx('block text-sm font-semibold tabular-nums', m.signed ? (v > 0 ? 'text-good' : v < 0 ? 'text-bad' : 'text-ink') : 'text-ink')}>{m.display(r)}</span>
                    <span className="mt-1 block">
                      <Meter value={Math.abs(v)} max={scale} tone={m.signed ? (v < 0 ? 'bad' : 'good') : 'brand'} />
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="py-6 text-center text-xs text-muted">{loading ? 'Loading…' : 'No distributor qualifies'}</p>
      )}
    </div>
  );

  return (
    <Card
      title="Leaders & laggards"
      subtitle="Top and bottom distributors for the selected measure. Click a name for the detail page"
      actions={<Segmented value={metric} onChange={choose} options={ORDER.map((k) => ({ value: k, label: METRICS[k].label }))} size="xs" />}
      className="mb-4"
    >
      {!loading && eligible === 0 ? (
        <p className="py-6 text-center text-sm text-muted">
          {metric === 'growth'
            ? 'No comparison period, or no distributor had enough sales in it. Try "Last month" or a quarter preset.'
            : metric === 'target'
              ? 'No distributor targets for this period. Targets are set in the ASM tracker on Region & ASM Performance.'
              : 'No distributor qualifies for this ranking with the current filters.'}
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-x-8 gap-y-4 md:grid-cols-2">
          <List title="Leading" items={top} start={(i) => i + 1} />
          <List title="Lagging" items={bottom} start={(i) => eligible - i} lagging />
        </div>
      )}
      <p className="mt-3 border-t border-line pt-2 text-2xs text-muted">
        Ranked: {m.rule} ({num(eligible)} qualify)
        {metric === 'sales' && noSales > 0 ? ` · ${num(noSales)} distributors had no sales in this period` : ''}
      </p>
    </Card>
  );
}
