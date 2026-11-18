import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAnalytics } from '@/api/hooks';
import type { Growth, Retention as RetentionData } from '@/api/types';
import { GrowthJourney } from '@/components/GrowthJourney';
import { RetailerValue } from '@/components/RetailerValue';
import { cartesian, heatmap } from '@/charts/builders';
import { useChartTokens } from '@/charts/EChart';
import { ChartCard } from '@/components/ChartCard';
import { MiniStat } from '@/components/KpiTile';
import { PageHeader } from '@/components/PageHeader';
import { Card, ErrorState, Tabs } from '@/components/ui';
import { endsMidMonth } from '@/components/KpiTile';
import { asPct, inr, monthLabel, monthTick, num, pct } from '@/lib/format';

export default function Retention() {
  const q = useAnalytics<RetentionData>('/retention/');
  const g = useAnalytics<Growth>('/growth/');
  const [sp, setSp] = useSearchParams();
  type View = 'retention' | 'growth' | 'value';
  const view = (['growth', 'value'].includes(sp.get('view') ?? '') ? sp.get('view') : 'retention') as View;
  const setView = (v: View) => {
    const n = new URLSearchParams(sp);
    if (v === 'retention') n.delete('view');
    else n.set('view', v);
    setSp(n, { replace: true });
  };
  const t = useChartTokens();
  const d = q.data?.data;
  const basis = q.data?.meta?.sales_basis;
  // A month still in progress has an incomplete "lost" count (October buyers who may yet order in November), so the
  // headline uses the last complete month; charts label the running month "· MTD".
  const pto = q.data?.meta?.period?.to;
  const mv = d?.movement ?? [];
  const runningLast = mv.length > 1 && endsMidMonth(pto) && !!pto && mv[mv.length - 1].month.slice(0, 7) === pto.slice(0, 7);
  const last = runningLast ? mv[mv.length - 2] : mv[mv.length - 1];

  const movementOpt = useMemo(() => {
    const m = d?.movement ?? [];
    if (!m.length) return null;
    return cartesian(t, {
      x: m.map((r) => monthTick(r.month, pto)),
      series: [
        { name: 'Retained', data: m.map((r) => r.retained), stack: 'mv', color: t.series[0] },
        { name: 'New', data: m.map((r) => r.new), stack: 'mv', color: t.series[1] },
        { name: 'Reactivated', data: m.map((r) => r.reactivated), stack: 'mv', color: t.series[2] },
        { name: 'Lost', data: m.map((r) => -Math.abs(r.lost)), stack: 'mv', color: t.series[7] },
        { name: 'Net change', type: 'line', data: m.map((r) => r.net), color: t.target, ghost: true },
      ],
    });
  }, [d, t, pto]);

  const momOpt = useMemo(() => {
    const m = (d?.movement ?? []).filter((r) => r.mom_retention !== null);
    if (!m.length) return null;
    return cartesian(t, { x: m.map((r) => monthTick(r.month, pto)), format: 'pct', legend: false, series: [{ name: 'MoM retention', type: 'line', data: m.map((r) => asPct(r.mom_retention)), area: true, endLabel: true }] });
  }, [d, t, pto]);

  const qOpt = useMemo(() => {
    const qr = d?.quarterly_retention ?? [];
    if (!qr.length) return null;
    return cartesian(t, { x: qr.map((r) => r.quarter), format: 'pct', legend: false, showBarLabels: true, series: [{ name: 'Quarterly retention', data: qr.map((r) => Math.round((asPct(r.rate) ?? 0) * 10) / 10) }] });
  }, [d, t, pto]);

  const cohortOpt = useMemo(() => {
    const c = d?.cohorts ?? [];
    if (!c.length) return null;
    const maxLen = Math.max(...c.map((r) => r.values.length));
    const x = Array.from({ length: maxLen }, (_, i) => `M${i}`);
    const data: [number, number, number | null][] = [];
    c.forEach((r, yi) => r.values.forEach((v, xi) => data.push([xi, yi, v === null ? null : asPct(v)])));
    return heatmap(t, { x, y: c.map((r) => `${monthLabel(r.cohort)} (${num(r.size)})`), data, format: 'pct', min: 0, max: 100, labels: true });
  }, [d, t, pto]);

  const contribOpt = useMemo(() => {
    const c = d?.contribution ?? [];
    if (!c.length) return null;
    return cartesian(t, {
      x: c.map((r) => monthTick(r.month, pto)),
      format: 'inr',
      series: [
        { name: 'Repeat', data: c.map((r) => r.repeat_sales), stack: 'c', color: t.series[0] },
        { name: 'New', data: c.map((r) => r.new_sales), stack: 'c', color: t.series[1] },
        { name: 'Reactivated', data: c.map((r) => r.reactivated_sales), stack: 'c', color: t.series[2] },
      ],
    });
  }, [d, t, pto]);

  // gained vs lost (deck slide 41): net change as bars, lost and won-back as lines, one count axis
  const gainLossOpt = useMemo(() => {
    const m = (d?.movement ?? []).slice(1);
    if (!m.length) return null;
    return cartesian(t, {
      x: m.map((r) => monthTick(r.month, pto)),
      series: [
        { name: 'Net change', data: m.map((r) => r.net), colors: m.map((r) => (r.net >= 0 ? t.series[0] : t.series[7])) },
        { name: 'Lost vs previous month', type: 'line', data: m.map((r) => r.lost), color: t.series[7] },
        { name: 'Reactivated', type: 'line', data: m.map((r) => r.reactivated), color: t.series[2] },
      ],
    });
  }, [d, t, pto]);

  // month +1 retention by cohort (deck slide 43)
  const m1Opt = useMemo(() => {
    const c = (d?.cohorts ?? []).filter((r) => r.values.length > 1);
    if (!c.length) return null;
    return cartesian(t, { x: c.map((r) => monthLabel(r.cohort)), format: 'pct', legend: false, series: [{ name: 'Month +1 retention', data: c.map((r) => r.values[1]) }] });
  }, [d, t, pto]);

  // sales mix as % (deck slide 38): repeat / new / reactivated
  const mixPctOpt = useMemo(() => {
    const c = d?.contribution ?? [];
    if (!c.length) return null;
    const tot = c.map((r) => r.repeat_sales + r.new_sales + r.reactivated_sales);
    const p = (v: number, i: number) => (tot[i] ? Math.round((v / tot[i]) * 1000) / 10 : null);
    return cartesian(t, {
      x: c.map((r) => monthTick(r.month, pto)),
      format: 'pct',
      yMax: 100,
      series: [
        { name: 'Repeat', data: c.map((r, i) => p(r.repeat_sales, i)), stack: 'p', color: t.series[0] },
        { name: 'New', data: c.map((r, i) => p(r.new_sales, i)), stack: 'p', color: t.series[1] },
        { name: 'Reactivated', data: c.map((r, i) => p(r.reactivated_sales, i)), stack: 'p', color: t.series[2] },
      ],
    });
  }, [d, t, pto]);

  const bandsOpt = useMemo(() => {
    const b = d?.order_bands ?? [];
    if (!b.length) return null;
    const tr = b.reduce((s, x) => s + x.retailers, 0) || 1;
    const ts = b.reduce((s, x) => s + x.sales, 0) || 1;
    return cartesian(t, {
      x: b.map((x) => `${x.band} order${x.band === '1' ? '' : 's'}`),
      format: 'pct',
      series: [
        { name: 'Share of retailers', data: b.map((x) => Math.round((x.retailers / tr) * 1000) / 10), color: t.series[0] },
        { name: 'Share of sales', data: b.map((x) => Math.round((x.sales / ts) * 1000) / 10), color: t.series[1] },
      ],
    });
  }, [d, t, pto]);

  const paretoOpt = useMemo(() => {
    const p = d?.pareto ?? [];
    if (!p.some((x) => x.share > 0)) return null; // no sales in the period
    return cartesian(t, {
      x: p.map((x) => `Top ${num(x.top_n)}`),
      format: 'pct',
      legend: false,
      showBarLabels: true,
      yMax: 100,
      markLine: { value: 80, label: '80%' },
      series: [{ name: 'Cumulative share of sales', data: p.map((x) => Math.round((asPct(x.share) ?? 0) * 10) / 10) }],
    });
  }, [d, t, pto]);

  const opaOpt = useMemo(() => {
    const o = d?.orders_per_active_retailer ?? [];
    if (!o.length) return null;
    return cartesian(t, { x: o.map((r) => monthTick(r.month, pto)), format: 'dec', legend: false, series: [{ name: 'Orders per active retailer', type: 'line', data: o.map((r) => r.value), endLabel: true }] });
  }, [d, t, pto]);

  if (q.error && !q.data)
    return (
      <div>
        <PageHeader title="Retention & Growth" />
        <Card>
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        </Card>
      </div>
    );

  return (
    <div>
      <PageHeader title="Retention & Growth" subtitle="Who stays, who comes back, who drives sales" meta={(view === 'retention' ? q : g).data?.meta} />
      <div className="mb-4">
        <Tabs value={view} onChange={setView} tabs={[{ value: 'retention', label: 'Retention' }, { value: 'growth', label: 'Growth journey' }, { value: 'value', label: 'Retailer base & value' }]} />
      </div>
      {view === 'growth' && <GrowthJourney d={g.data?.data} loading={g.isLoading} />}
      {view === 'value' && <RetailerValue d={g.data?.data} loading={g.isLoading} />}
      {view === 'retention' && (<>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <MiniStat
          label={runningLast ? 'Active retailers (last full month)' : 'Active retailers (latest month)'}
          value={num(last?.active)}
          sub={last ? `${monthLabel(last.month)}${runningLast ? ` · ${monthLabel(mv[mv.length - 1].month)} still running` : ''}` : undefined}
        />
        <MiniStat label="Retained" value={num(last?.retained)} />
        <MiniStat label="New" value={num(last?.new)} />
        <MiniStat label="Reactivated" value={num(last?.reactivated)} />
        <MiniStat label="Lost" value={num(last?.lost)} tone={last?.lost ? 'bad' : undefined} />
        <MiniStat label="Avg days between orders" value={d?.avg_days_between_orders === null || d?.avg_days_between_orders === undefined ? '–' : `${num(d.avg_days_between_orders, 1)} d`} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ChartCard
          className="xl:col-span-2"
          title="Monthly retailer movement"
          subtitle="Retained + new + reactivated above the line, lost below · line = net change"
          option={movementOpt}
          loading={q.isLoading}
          height={300}
          table={
            d
              ? {
                  columns: ['Month', 'Active', 'Retained', 'New', 'Reactivated', 'Lost', 'Net', 'MoM retention'],
                  rows: d.movement.map((r) => [monthLabel(r.month), num(r.active), num(r.retained), num(r.new), num(r.reactivated), num(r.lost), num(r.net), pct(asPct(r.mom_retention))]),
                }
              : undefined
          }
        />
        <div className="grid grid-cols-1 gap-4">
          <ChartCard title="Month-on-month retention" subtitle="Share of last month's actives who ordered again" option={momOpt} loading={q.isLoading} height={120}
            table={d ? { columns: ['Month', 'Retention'], rows: d.movement.map((r) => [monthLabel(r.month), pct(asPct(r.mom_retention))]) } : undefined} />
          <ChartCard title="Quarterly retention" option={qOpt} loading={q.isLoading} height={120}
            table={d ? { columns: ['Quarter', 'Retention'], rows: d.quarterly_retention.map((r) => [r.quarter, pct(asPct(r.rate))]) } : undefined} />
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard
          title="Cohort retention"
          subtitle="% of each first-order cohort ordering again in month N"
          option={cohortOpt}
          loading={q.isLoading}
          height={Math.max(260, (d?.cohorts.length ?? 8) * 26 + 80)}
          table={
            d
              ? {
                  columns: ['Cohort', 'Size', ...Array.from({ length: Math.max(0, ...d.cohorts.map((c) => c.values.length)) }, (_, i) => `M${i}`)],
                  rows: d.cohorts.map((c) => [monthLabel(c.cohort), num(c.size), ...c.values.map((v) => (v === null ? '–' : pct(asPct(v), 0)))]),
                }
              : undefined
          }
        />
        <ChartCard
          title="Sales contribution"
          subtitle={basis ? `By retailer type · ${basis}` : 'By retailer type'}
          option={contribOpt}
          loading={q.isLoading}
          height={Math.max(260, (d?.cohorts.length ?? 8) * 26 + 80)}
          table={d ? { columns: ['Month', 'Repeat', 'New', 'Reactivated'], rows: d.contribution.map((r) => [monthLabel(r.month), inr(r.repeat_sales), inr(r.new_sales), inr(r.reactivated_sales)]) } : undefined}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ChartCard
          title="Order-count bands"
          subtitle="Retailers by lifetime orders vs their share of sales"
          option={bandsOpt}
          loading={q.isLoading}
          table={d ? { columns: ['Band', 'Retailers', 'Sales'], rows: d.order_bands.map((b) => [b.band, num(b.retailers), inr(b.sales)]) } : undefined}
        />
        <ChartCard
          title="Retailer Pareto"
          subtitle="Cumulative share of sales from the top N retailers"
          option={paretoOpt}
          loading={q.isLoading}
          table={d ? { columns: ['Top N', 'Share'], rows: d.pareto.map((p) => [num(p.top_n), pct(asPct(p.share))]) } : undefined}
        />
        <ChartCard
          title="Orders per active retailer"
          subtitle="Monthly purchase frequency"
          option={opaOpt}
          loading={q.isLoading}
          table={d ? { columns: ['Month', 'Orders / retailer'], rows: d.orders_per_active_retailer.map((r) => [monthLabel(r.month), num(r.value, 2)]) } : undefined}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ChartCard title="Gained vs lost" subtitle="Bars = net change in active retailers · lines = lost and won back" option={gainLossOpt} loading={q.isLoading}
          table={d ? { columns: ['Month', 'Net', 'Lost', 'Reactivated'], rows: d.movement.map((r) => [monthLabel(r.month), num(r.net), num(r.lost), num(r.reactivated)]) } : undefined} />
        <ChartCard title="Month +1 retention by cohort" subtitle="Share of each first-order cohort that ordered again the next month" option={m1Opt} loading={q.isLoading}
          table={d ? { columns: ['Cohort', 'Size', 'Month +1'], rows: d.cohorts.map((c) => [monthLabel(c.cohort), num(c.size), c.values[1] == null ? '–' : pct(c.values[1], 0)]) } : undefined} />
        <ChartCard title="Sales mix by retailer type" subtitle="Share of monthly sales: repeat, new, reactivated" option={mixPctOpt} loading={q.isLoading} />
      </div>
      </>)}
    </div>
  );
}
