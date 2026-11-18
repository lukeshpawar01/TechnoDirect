import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAnalytics } from '@/api/hooks';
import type { DistributorInsights, DistributorRow } from '@/api/types';
import { cartesian } from '@/charts/builders';
import { useChartTokens } from '@/charts/EChart';
import { ChartCard } from '@/components/ChartCard';
import { DataTable } from '@/components/DataTable';
import { LeadersLaggards } from '@/components/LeadersLaggards';
import { NetworkCoverage } from '@/components/NetworkCoverage';
import { Sparkline, endsMidMonth } from '@/components/KpiTile';
import { PageHeader } from '@/components/PageHeader';
import { Badge, Card, Delta, Meter } from '@/components/ui';
import { linkWithFilters, useFilters } from '@/lib/filters';
import { asPct, inr, monthLabel, num, pct, sharePct, monthTick } from '@/lib/format';
import { MiniStat } from '@/components/KpiTile';

/** stock counts as current when synced within this many days (Stock sync filter, badges, Inventory) */
export const STOCK_SYNC_DAYS = 3;

export interface SyncInfo {
  inventory_status?: string | null;
  stock_upload_mode?: string | null;
  stock_update_frequency?: string | null;
}

/** Calendar days since the stock was last updated (the sheet gives a date, not a time). */
export function syncDays(at: string | null | undefined): number | null {
  if (!at) return null;
  const a = new Date(at);
  const today = new Date();
  const d0 = Date.UTC(a.getFullYear(), a.getMonth(), a.getDate());
  const d1 = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.max(0, Math.round((d1 - d0) / 864e5));
}

/** Stock sync badge: green within STOCK_SYNC_DAYS days, amber older, red never (same rule as the Stock sync filter). */
export function StalenessBadge({ at, info }: { at: string | null | undefined; info?: SyncInfo }) {
  const how = [info?.inventory_status, info?.stock_upload_mode && `updated ${info.stock_upload_mode}`, info?.stock_update_frequency].filter(Boolean).join(' · ');
  if (!at)
    return (
      <Badge tone="bad" icon title={how || undefined}>
        {info?.inventory_status && info.inventory_status !== 'Inventory Live' ? info.inventory_status : 'Never synced'}
      </Badge>
    );
  const days = syncDays(at) ?? 0;
  const tone = days <= STOCK_SYNC_DAYS ? 'good' : 'warn';
  const label = days === 0 ? 'Today' : days === 1 ? 'Yesterday' : `${days} days ago`;
  const when = new Date(at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
  return (
    <Badge tone={tone} icon title={[`Stock updated ${when}`, how].filter(Boolean).join('\n')}>
      {label}
    </Badge>
  );
}

export default function Distributors() {
  const q = useAnalytics<{ rows: DistributorRow[] }>('/distributors/');
  const nav = useNavigate();
  const t = useChartTokens();
  const { searchParams, apiParams } = useFilters();
  const rows = q.data?.data.rows;
  const ins = useAnalytics<DistributorInsights>('/distributors/insights/');
  const di = ins.data?.data;

  // top-5 distributors over 12 months (deck slide 49): lines on one ₹ axis, the rest as a muted "Other"
  const trendOpt = useMemo(() => {
    if (!di?.trend.series.length) return null;
    return cartesian(t, {
      x: di.trend.months.map((m) => monthTick(m, ins.data?.meta?.period?.to)),
      format: 'inr',
      series: di.trend.series.map((s, i) => ({ name: s.name, type: 'line' as const, data: s.data, color: s.name === 'Other' ? t.deemph : t.series[i], endLabel: s.name !== 'Other' })),
    });
  }, [di, t, ins.data?.meta?.period?.to]);
  const transOpt = useMemo(
    () => (di?.transacting_monthly.length ? cartesian(t, { x: di.transacting_monthly.map((r) => monthTick(r.month, ins.data?.meta?.period?.to)), legend: false, showBarLabels: true, series: [{ name: 'Distributors transacting', data: di.transacting_monthly.map((r) => r.distributors) }] }) : null),
    [di, t],
  );
  const multiOpt = useMemo(
    () => (di?.multi_distributor.monthly.length ? cartesian(t, { x: di.multi_distributor.monthly.map((r) => monthLabel(r.month)), format: 'pct', legend: false, series: [{ name: 'Retailers buying from 2+ distributors', type: 'line', area: true, endLabel: true, data: di.multi_distributor.monthly.map((r) => r.multi_pct) }] }) : null),
    [di, t],
  );
  const md = di?.multi_distributor;
  const basis = q.data?.meta?.sales_basis;

  const shareOpt = useMemo(() => {
    if (!rows?.length) return null;
    const top = [...rows].sort((a, b) => b.sales - a.sales);
    const head = top.slice(0, 10);
    const rest = top.slice(10).reduce((s, r) => s + r.sales, 0);
    const x = [...head.map((r) => r.name), ...(rest > 0 ? ['Other'] : [])];
    const vals = [...head.map((r) => r.sales), ...(rest > 0 ? [rest] : [])];
    return cartesian(t, {
      x,
      horizontal: true,
      format: 'inr',
      legend: false,
      showBarLabels: true,
      series: [{ name: 'Sales', data: vals, colors: x.map((n) => (n === 'Other' ? t.deemph : t.series[0])) }],
    });
  }, [rows, t]);

  return (
    <div>
      <PageHeader title="Distributors" subtitle="Scorecard — click a row for the distributor detail" meta={q.data?.meta} />
      <LeadersLaggards rows={rows} loading={q.isLoading} searchParams={searchParams} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-4">
        <ChartCard
          title="Sales by distributor"
          subtitle={basis ?? 'Top 10, rest folded into Other'}
          option={shareOpt}
          loading={q.isLoading}
          error={q.error && !q.data ? q.error : undefined}
          height={360}
          onClick={(p) => {
            const r = rows?.find((x) => x.name === p.name);
            if (r) nav(linkWithFilters(`/distributors/${r.id}`, searchParams));
          }}
          table={rows ? { columns: ['Distributor', 'Sales', 'Share'], rows: [...rows].sort((a, b) => b.sales - a.sales).map((r) => [r.name, inr(r.sales), pct(asPct(r.share))]) } : undefined}
        />
        <Card className="xl:col-span-3" title="Distributor scorecard" subtitle={basis ? `Sales = ${basis}` : undefined}>
          <DataTable
            rows={rows}
            loading={q.isLoading}
            fetching={q.isFetching}
            error={q.error}
            onRetry={() => q.refetch()}
            rowKey={(r) => r.id}
            onRowClick={(r) => nav(linkWithFilters(`/distributors/${r.id}`, searchParams))}
            exportName="distributor_scorecard"
            exportPath="/distributors/"
            exportParams={apiParams}
            initialSort={{ key: 'sales', dir: 'desc' }}
            pageSize={50}
            dense
            columns={[
              { key: 'name', header: 'Distributor', render: (r) => <span className="font-medium">{r.name}</span> },
              { key: 'state', header: 'State' },
              { key: 'asm', header: 'ASM', render: (r) => r.asm ?? <span className="text-muted">–</span>, value: (r) => r.asm ?? '' },
              { key: 'sales', header: 'Sales', align: 'right', render: (r) => inr(r.sales) },
              {
                key: 'share',
                header: 'Share',
                align: 'right',
                value: (r) => r.share,
                render: (r) => (
                  <div className="flex items-center justify-end gap-1.5">
                    <div className="w-12"><Meter value={asPct(r.share)} /></div>
                    <span className="w-10">{sharePct(asPct(r.share))}</span>
                  </div>
                ),
              },
              { key: 'spark', header: '12-mo trend', sortable: false, noExport: true, render: (r) => <div className="w-24"><Sparkline data={r.spark} height={24} partialLast={endsMidMonth(q.data?.meta?.period?.to)} /></div> },
              { key: 'growth_pct', header: 'Growth', align: 'right', render: (r) => <Delta value={r.growth_pct} suffix="" /> },
              { key: 'orders', header: 'Orders', align: 'right', render: (r) => num(r.orders) },
              { key: 'aov', header: 'AOV', align: 'right', render: (r) => inr(r.aov) },
              { key: 'active_retailers', header: 'Active / total retailers', align: 'right', render: (r) => `${num(r.active_retailers)} / ${num(r.retailers)}` },
              { key: 'new_retailers', header: 'New', align: 'right', render: (r) => num(r.new_retailers) },
              { key: 'repeat_pct', header: 'Repeat %', align: 'right', render: (r) => pct(asPct(r.repeat_pct), 0) },
              { key: 'orders_per_retailer', header: 'Orders / retailer', align: 'right', render: (r) => num(r.orders_per_retailer, 1) },
              { key: 'dispatch_pct', header: 'Dispatched', align: 'right', render: (r) => <span className={(asPct(r.dispatch_pct) ?? 100) < 80 ? 'text-bad' : ''}>{pct(asPct(r.dispatch_pct), 0)}</span> },
              { key: 'median_dispatch_days', header: 'Median dispatch', align: 'right', render: (r) => (r.median_dispatch_days === null ? '–' : `${num(r.median_dispatch_days, 1)} d`) },
              { key: 'l3m_sales', header: 'L3M sales', align: 'right', render: (r) => inr(r.l3m_sales) },
              { key: 'l3m_growth_pct', header: 'L3M vs P3M', align: 'right', value: (r) => r.l3m_growth_pct ?? null, render: (r) => (r.l3m_growth_pct == null ? <span className="text-muted" title="Previous 3 months under ₹50K">–</span> : <Delta value={r.l3m_growth_pct} suffix="" />) },
              { key: 'sales_per_retailer', header: 'Sales / retailer', align: 'right', value: (r) => r.sales_per_retailer ?? null, render: (r) => inr(r.sales_per_retailer) },
              { key: 'target', header: 'Target', align: 'right', render: (r) => inr(r.target) },
              {
                key: 'achievement_pct',
                header: 'Achieved',
                align: 'right',
                render: (r) => {
                  const a = asPct(r.achievement_pct);
                  return a === null ? '–' : <span className={a >= 100 ? 'font-semibold text-good' : a < 70 ? 'text-bad' : ''}>{pct(a, 0)}</span>;
                },
              },
              { key: 'last_stock_sync', header: 'Stock sync', render: (r) => <StalenessBadge at={r.last_stock_sync} info={r} />, value: (r) => r.last_stock_sync },
            ]}
          />
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ChartCard className="xl:col-span-2" title="Top 5 distributors over time" subtitle="Monthly sales for this period's five largest · grey = everyone else" option={trendOpt} loading={ins.isLoading} height={280}
          table={di ? { columns: ['Distributor', ...di.trend.months.map(monthLabel)], rows: di.trend.series.map((s) => [s.name, ...s.data.map((v) => inr(v))]) } : undefined} />
        <ChartCard title="Distributors transacting" subtitle="With at least one paid order in the month" option={transOpt} loading={ins.isLoading} height={280}
          table={di ? { columns: ['Month', 'Distributors', 'Retailers'], rows: di.transacting_monthly.map((r) => [monthLabel(r.month), num(r.distributors), num(r.retailers)]) } : undefined} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="Top 3 articles by distributor" subtitle="This period, by line value · shows whether range depth travels across the network">
          <div className="max-h-[360px] overflow-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-surface text-left text-muted">
                <tr className="border-b border-line">
                  <th className="py-1.5 pr-2 font-medium">Distributor</th>
                  <th className="pr-2 text-right font-medium">Sales</th>
                  {['#1', '#2', '#3'].map((h) => <th key={h} className="pr-2 font-medium">{h} article</th>)}
                </tr>
              </thead>
              <tbody>
                {(di?.top_articles ?? []).map((r) => (
                  <tr key={r.id} className="border-b border-line/60 last:border-0">
                    <td className="max-w-[12rem] truncate py-1.5 pr-2 font-medium">{r.name}</td>
                    <td className="pr-2 text-right tabular-nums">{inr(r.sales)}</td>
                    {[0, 1, 2].map((i) => (
                      <td key={i} className="pr-2">
                        {r.articles[i] ? (<><span className="font-medium text-ink">{r.articles[i].style}</span> <span className="text-muted">{inr(r.articles[i].sales)}</span></>) : <span className="text-muted">–</span>}
                      </td>
                    ))}
                  </tr>
                ))}
                {!di?.top_articles.length && <tr><td colSpan={5} className="py-6 text-center text-muted">{ins.isLoading ? 'Loading…' : 'No line items in this period'}</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>
        <div className="grid grid-cols-1 gap-4">
          <div className="grid grid-cols-2 gap-3">
            <MiniStat label="Bought from 2+ distributors" value={pct(md?.multi_pct)} sub={md ? `${num(md.multi)} of ${num(md.retailers)} retailers` : undefined} />
            <MiniStat label="Lifetime orders" value={md?.avg_orders_multi == null ? '–' : `${num(md.avg_orders_multi, 1)} vs ${num(md.avg_orders_single, 1)}`} sub="Multi- vs single-distributor retailers" />
          </div>
          <ChartCard title="Multi-distributor retailers" subtitle="Share of each month's ordering retailers" option={multiOpt} loading={ins.isLoading} height={170} />
        </div>
      </div>

      <NetworkCoverage />
    </div>
  );
}
