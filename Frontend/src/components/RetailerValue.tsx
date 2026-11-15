import { useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type { Growth } from '@/api/types';
import { cartesian } from '@/charts/builders';
import { useChartTokens } from '@/charts/EChart';
import { ChartCard } from './ChartCard';
import { MiniStat } from './KpiTile';
import { Card } from './ui';
import { linkWithFilters } from '@/lib/filters';
import { inr, monthLabel, num, pct } from '@/lib/format';

/**
 * Retailer base & value (TD_DataDeck slides 36-39, 44, 56): how the base was built, how much of it is active,
 * what a transacting retailer is worth, how deep the relationships go, and who the biggest accounts are.
 */
export function RetailerValue({ d, loading }: { d: Growth | undefined; loading?: boolean }) {
  const t = useChartTokens();
  const [sp] = useSearchParams();
  const rv = d?.retailer_value;
  const months = useMemo(() => {
    const m = d?.monthly ?? [];
    const first = m.findIndex((r) => r.cum_retailers > 0);
    return first < 0 ? [] : m.slice(first);
  }, [d]);
  const x = months.map((r) => monthLabel(r.month));

  const baseOpt = useMemo(
    () =>
      months.length
        ? cartesian(t, {
            x,
            series: [
              { name: 'Cumulative acquired', type: 'line', data: months.map((r) => r.cum_retailers), color: t.series[0], endLabel: true },
              { name: 'Active in month', type: 'line', data: months.map((r) => r.active_retailers), color: t.series[1], endLabel: true },
              { name: 'New in month', data: months.map((r) => r.new_retailers), color: t.series[2] },
            ],
          })
        : null,
    [months, t], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const activePctOpt = useMemo(
    () => (months.length ? cartesian(t, { x, format: 'pct', legend: false, series: [{ name: 'Active as % of base', data: months.map((r) => r.active_pct_of_base) }] }) : null),
    [months, t], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const mixOpt = useMemo(
    () =>
      months.length
        ? cartesian(t, {
            x,
            format: 'pct',
            yMax: 100,
            series: [
              { name: 'Repeat retailers', data: months.map((r) => r.repeat_share), stack: 'mix', color: t.series[0] },
              { name: 'New retailers', data: months.map((r) => (r.repeat_share === null ? null : Math.round((100 - r.repeat_share) * 10) / 10)), stack: 'mix', color: t.series[1] },
            ],
          })
        : null,
    [months, t], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const sprOpt = useMemo(
    () => (months.length ? cartesian(t, { x, format: 'inr', legend: false, series: [{ name: 'Sales per active retailer', type: 'line', area: true, endLabel: true, data: months.map((r) => r.sales_per_retailer) }] }) : null),
    [months, t], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const histOpt = useMemo(
    () => (rv?.histogram.length ? cartesian(t, { x: rv.histogram.map((h) => h.bucket), legend: false, showBarLabels: true, series: [{ name: 'Retailers', data: rv.histogram.map((h) => h.retailers) }] }) : null),
    [rv, t],
  );
  const monthsOpt = useMemo(
    () => (rv?.months_active.length ? cartesian(t, { x: rv.months_active.map((m) => String(m.months)), legend: false, showBarLabels: true, series: [{ name: 'Retailers', data: rv.months_active.map((m) => m.retailers) }] }) : null),
    [rv, t],
  );

  const lt = rv?.lifetime;
  const fr = rv?.first_vs_repeat_aov;
  return (
    <div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <MiniStat label="Retailers with 2+ orders" value={num(lt?.repeat_retailers)} sub={lt ? `${pct(lt.repeat_pct)} of ${num(lt.acquired)} acquired` : undefined} />
        <MiniStat label="Their share of sales" value={pct(lt?.repeat_sales_share)} sub="Lifetime" />
        <MiniStat label="Avg lifetime orders" value={num(lt?.avg_orders, 1)} sub="Per retailer acquired" />
        <MiniStat label="One-order retailers" value={num(lt?.one_order)} sub={lt ? `${inr(lt.one_order_sales)} lifetime` : undefined} tone={lt?.one_order ? 'warn' : undefined} />
        <MiniStat label="First-order AOV" value={inr(fr?.first_aov)} sub={fr ? `${num(fr.first_orders)} first orders this period` : undefined} />
        <MiniStat label="Repeat-order AOV" value={inr(fr?.repeat_aov)} sub={fr ? `${num(fr.repeat_orders)} repeat orders this period` : undefined} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ChartCard className="xl:col-span-2" title="Retailer base" subtitle="Cumulative acquired vs active and new each month" option={baseOpt} loading={loading} height={260}
          table={{ columns: ['Month', 'Cumulative', 'Active', 'New', 'Active % of base'], rows: months.map((r) => [monthLabel(r.month), num(r.cum_retailers), num(r.active_retailers), num(r.new_retailers), pct(r.active_pct_of_base)]) }} />
        <ChartCard title="Active as % of the base" subtitle="Share of all retailers ever acquired who ordered in the month" option={activePctOpt} loading={loading} height={260} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard title="Sales mix: repeat vs new retailers" subtitle="New = the retailer's first order month" option={mixOpt} loading={loading} height={240}
          table={{ columns: ['Month', 'Repeat', 'New', 'Repeat %'], rows: months.map((r) => [monthLabel(r.month), inr(r.repeat_sales), inr(r.new_sales), pct(r.repeat_share)]) }} />
        <ChartCard title="Spend per active retailer" subtitle="Monthly sales ÷ retailers who ordered" option={sprOpt} loading={loading} height={240} />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <MiniStat label="Transacting retailers" value={num(rv?.transacting)} sub="Last 12 months" />
        <MiniStat label="Average annual spend" value={inr(rv?.avg_spend)} />
        <MiniStat label="Median annual spend" value={inr(rv?.median_spend)} sub="Half spend less than this" />
        <MiniStat label="Top-quartile average" value={inr(rv?.top_quartile.avg_spend)} sub={rv ? `${num(rv.top_quartile.retailers)} retailers = ${pct(rv.top_quartile.share, 0)} of sales` : undefined} />
        <MiniStat label="Months active (of 12)" value={num(rv?.avg_months_active, 1)} sub="Average per retailer" />
        <MiniStat label="Ordered in just one month" value={num(rv?.single_month)} tone={rv?.single_month ? 'warn' : undefined} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ChartCard title="Annual spend per retailer" subtitle="Retailers by last-12-month spend" option={histOpt} loading={loading} height={240}
          table={rv ? { columns: ['Spend', 'Retailers'], rows: rv.histogram.map((h) => [h.bucket, num(h.retailers)]) } : undefined} />
        <ChartCard title="Months active in the last 12" subtitle="How regularly transacting retailers order" option={monthsOpt} loading={loading} height={240}
          table={rv ? { columns: ['Months', 'Retailers'], rows: rv.months_active.map((m) => [m.months, num(m.retailers)]) } : undefined} />
        <Card title="Top retailers by lifetime value" subtitle="Click a name for the retailer page">
          <table className="w-full text-xs">
            <thead className="text-left text-muted">
              <tr className="border-b border-line"><th className="py-1 font-medium">Retailer</th><th className="text-right font-medium">Orders</th><th className="text-right font-medium">Sales</th><th className="text-right font-medium">Months</th></tr>
            </thead>
            <tbody>
              {(rv?.top_retailers ?? []).slice(0, 10).map((r) => (
                <tr key={r.id} className="border-b border-line/60 last:border-0">
                  <td className="max-w-[10rem] truncate py-1.5"><Link className="hover:underline" to={linkWithFilters(`/retailers/${r.id}`, sp)}>{r.name}</Link></td>
                  <td className="text-right tabular-nums">{num(r.orders)}</td>
                  <td className="text-right tabular-nums font-medium">{inr(r.sales)}</td>
                  <td className="text-right tabular-nums">{num(r.months_active)}</td>
                </tr>
              ))}
              {!rv?.top_retailers.length && <tr><td colSpan={4} className="py-6 text-center text-muted">{loading ? 'Loading…' : 'No retailers yet'}</td></tr>}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}
