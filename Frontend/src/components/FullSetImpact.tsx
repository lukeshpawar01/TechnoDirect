import { useState } from 'react';
import { useAnalytics } from '@/api/hooks';
import { DataTable } from '@/components/DataTable';
import { Card, ErrorState, Segmented, cx } from '@/components/ui';
import { date, inr, num, pct } from '@/lib/format';

/**
 * Inventory → "Full sets vs sales" (backend: analytics/views/fullset.py). Stock on a past day, sales in the days
 * after it: how much a full set (every size the style comes in) sells compared with broken sets, which sizes break sets, and the sales the
 * missing sizes cost.
 */
interface Group { key: 'full' | 'broken' | 'badly' | 'out'; label: string; combos: number; sold_pct: number | null; units_per_combo: number | null; value_per_combo: number | null; units: number; value: number }
interface Dist { id: number; name: string; styles: number; full_pct: number | null; units: number; units_per_style: number | null; lost_value: number; lost_value_month: number }
interface Data {
  available: boolean; reason?: string; snapshot_date: string; from: string; to: string; days: number; lookback: number;
  groups: Group[]; full_vs_broken: number | null;
  size_curve: { size: string; sales_share_pct: number; broken_sets_missing: number }[];
  lost: { units: number; value: number; value_month: number };
  distributors: Dist[];
  top_lost: { style: string; distributor: string; missing: string[]; sold: number; lost_value: number }[];
}

const TONE: Record<Group['key'], string> = { full: 'bg-good', broken: 'bg-warn', badly: 'bg-bad/70', out: 'bg-muted/40' };

export function FullSetImpact() {
  const [lookback, setLookback] = useState('10');
  const q = useAnalytics<Data>('/inventory/fullset-impact/', { lookback });
  const d = q.data?.data;
  const max = Math.max(...(d?.groups ?? []).map((g) => g.units_per_combo ?? 0), 1);
  const full = d?.groups.find((g) => g.key === 'full');
  const broken = d?.groups.find((g) => g.key === 'broken');
  const worstSize = d ? [...d.size_curve].sort((a, b) => b.broken_sets_missing * b.sales_share_pct - a.broken_sets_missing * a.sales_share_pct)[0] : null;

  return (
    <Card
      className="mt-4"
      title="Full sets vs sales"
      subtitle={d?.available
        ? `Each distributor's stock on ${date(d.snapshot_date)}, and what it sold of each style from ${date(d.from)} to ${date(d.to)} (${d.days} days). A full set = every size the style comes in (M–2XL, S–2XL, kids or plus sizes, as listed in the stock data).`
        : 'Stock on a past day against the sales in the days after it'}
      actions={<Segmented value={lookback} onChange={setLookback} size="xs" options={[{ value: '7', label: '7 d' }, { value: '10', label: '10 d' }, { value: '14', label: '14 d' }]} />}
    >
      {q.error && !q.data ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !d ? (
        <p className="py-6 text-center text-sm text-muted">Loading…</p>
      ) : !d.available ? (
        <p className="py-6 text-center text-sm text-muted">{d.reason}</p>
      ) : (
        <div className={cx('space-y-5', q.isFetching && 'opacity-70 transition-opacity')}>
          {full && broken && (
            <p className="text-sm text-ink2">
              A <b className="text-ink">full set sold {d.full_vs_broken ?? '–'}× a broken one</b>: {full.units_per_combo} vs {broken.units_per_combo} units per style
              in {d.days} days, and {pct(full.sold_pct, 0)} of full sets sold at all against {pct(broken.sold_pct, 0)} of broken ones.
              With 3 or more of its sizes missing a style practically stops selling.
              {worstSize && <> The costliest gap is <b className="text-ink">{worstSize.size}</b>: it is missing in {num(worstSize.broken_sets_missing)} broken sets and is {pct(worstSize.sales_share_pct, 0)} of units sold.</>}
            </p>
          )}

          <div className="grid gap-5 lg:grid-cols-5">
            <div className="lg:col-span-3">
              <h4 className="mb-2 text-xs font-medium text-muted">Units sold per style after the stock day</h4>
              <ul className="space-y-2.5">
                {d.groups.map((g) => (
                  <li key={g.key}>
                    <div className="flex items-baseline justify-between gap-2 text-sm">
                      <span className="text-ink2">{g.label}</span>
                      <span className="whitespace-nowrap tabular-nums">
                        <b className="text-ink">{g.units_per_combo ?? '–'}</b>
                        <span className="text-xs text-muted"> units · {inr(g.value_per_combo ?? 0)} · {pct(g.sold_pct, 0)} sold · {num(g.combos)} styles</span>
                      </span>
                    </div>
                    <div className="mt-1 h-2.5 rounded bg-line/50">
                      <div className={cx('h-full rounded', TONE[g.key])} style={{ width: `${((g.units_per_combo ?? 0) / max) * 100}%` }} />
                    </div>
                  </li>
                ))}
              </ul>
            </div>
            <div className="lg:col-span-2">
              <h4 className="mb-2 text-xs font-medium text-muted">Which sizes break sets</h4>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted">
                    <th className="py-1 font-medium">Size</th>
                    <th className="py-1 text-right font-medium">Share of sales</th>
                    <th className="py-1 text-right font-medium">Broken sets missing it</th>
                  </tr>
                </thead>
                <tbody>
                  {d.size_curve.map((z) => (
                    <tr key={z.size} className="border-t border-line/60">
                      <td className="py-1 font-medium text-ink">{z.size}</td>
                      <td className="py-1 text-right tabular-nums">{pct(z.sales_share_pct, 0)}</td>
                      <td className={cx('py-1 text-right tabular-nums', z.sales_share_pct >= 15 && z.broken_sets_missing ? 'font-semibold text-bad' : 'text-ink2')}>{num(z.broken_sets_missing)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="mt-3 rounded-md bg-sunken px-3 py-2">
                <div className="text-xs text-muted">Sales lost to missing sizes</div>
                <div className="text-xl font-semibold tabular-nums text-ink">≈ {inr(d.lost.value_month)} a month</div>
                <div className="text-2xs text-muted">{inr(d.lost.value)} ({num(d.lost.units)} units) in these {d.days} days: what the missing sizes would have sold at each distributor's pace for the style, capped at double its actual sales.</div>
              </div>
            </div>
          </div>

          <div>
            <h4 className="mb-2 text-xs font-medium text-muted">Distributors: full-set rate, sales and what broken sets cost</h4>
            <DataTable
              rows={d.distributors}
              rowKey={(r) => r.id}
              exportName="fullsets_vs_sales_by_distributor"
              initialSort={{ key: 'lost_value_month', dir: 'desc' }}
              pageSize={10}
              dense
              columns={[
                { key: 'name', header: 'Distributor', render: (r) => <span className="font-medium">{r.name}</span> },
                { key: 'full_pct', header: 'Styles in full sets', align: 'right', render: (r) => pct(r.full_pct, 1) },
                { key: 'units', header: `Units sold (${d.days} d)`, align: 'right', render: (r) => num(r.units) },
                { key: 'units_per_style', header: 'Units / style', align: 'right', render: (r) => (r.units_per_style ?? 0).toFixed(1) },
                { key: 'lost_value_month', header: 'Lost to missing sizes / month', align: 'right', render: (r) => (r.lost_value_month ? <span className="font-semibold text-bad">{inr(r.lost_value_month)}</span> : <span className="text-muted">–</span>) },
              ]}
            />
          </div>

          {d.top_lost.length > 0 && (
            <div>
              <h4 className="mb-2 text-xs font-medium text-muted">Refill first: broken sets that were selling</h4>
              <ul className="divide-y divide-line/60 text-sm">
                {d.top_lost.slice(0, 8).map((x) => (
                  <li key={`${x.style}-${x.distributor}`} className="flex flex-wrap items-baseline justify-between gap-2 py-1.5">
                    <span><b className="text-ink">{x.style}</b> <span className="text-ink2">at {x.distributor}</span> <span className="text-xs text-muted">· missing {x.missing.join(', ')} · sold {num(x.sold)}</span></span>
                    <span className="tabular-nums text-bad">{inr(x.lost_value)} lost</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
