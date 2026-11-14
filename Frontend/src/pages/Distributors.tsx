import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAnalytics } from '@/api/hooks';
import type { DistributorRow } from '@/api/types';
import { cartesian } from '@/charts/builders';
import { useChartTokens } from '@/charts/EChart';
import { ChartCard } from '@/components/ChartCard';
import { DataTable } from '@/components/DataTable';
import { Sparkline } from '@/components/KpiTile';
import { PageHeader } from '@/components/PageHeader';
import { Badge, Card, Delta, Meter } from '@/components/ui';
import { linkWithFilters, useFilters } from '@/lib/filters';
import { asPct, inr, num, pct, relTime } from '@/lib/format';

export function StalenessBadge({ at }: { at: string | null | undefined }) {
  if (!at) return <Badge tone="bad" icon>Never synced</Badge>;
  const h = (Date.now() - new Date(at).getTime()) / 36e5;
  const tone = h <= 24 ? 'good' : h <= 72 ? 'warn' : 'bad';
  return (
    <Badge tone={tone} icon title={new Date(at).toLocaleString('en-IN')}>
      {relTime(at)}
    </Badge>
  );
}

export default function Distributors() {
  const q = useAnalytics<{ rows: DistributorRow[] }>('/distributors/');
  const nav = useNavigate();
  const t = useChartTokens();
  const { searchParams, apiParams } = useFilters();
  const rows = q.data?.data.rows;
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
                    <span className="w-10">{pct(asPct(r.share), 0)}</span>
                  </div>
                ),
              },
              { key: 'spark', header: '12-mo trend', sortable: false, noExport: true, render: (r) => <div className="w-24"><Sparkline data={r.spark} height={24} /></div> },
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
              { key: 'last_stock_sync', header: 'Stock sync', render: (r) => <StalenessBadge at={r.last_stock_sync} />, value: (r) => r.last_stock_sync },
            ]}
          />
        </Card>
      </div>
    </div>
  );
}
