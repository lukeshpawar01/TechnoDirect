import { useMemo } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useAnalytics } from '@/api/hooks';
import type { DistributorDetail as DD } from '@/api/types';
import { cartesian } from '@/charts/builders';
import { useChartTokens } from '@/charts/EChart';
import { ChartCard } from '@/components/ChartCard';
import { DataTable } from '@/components/DataTable';
import { KpiTile } from '@/components/KpiTile';
import { PageHeader } from '@/components/PageHeader';
import { Card, ErrorState, LoadingBlock, Stat } from '@/components/ui';
import { linkWithFilters, useFilters } from '@/lib/filters';
import { asPct, date, inr, monthLabel, num, pct, titleCase } from '@/lib/format';
import { StalenessBadge } from './Distributors';

const KPI_FMT: Record<string, { label: string; fmt: (n: number | null | undefined) => string; money?: boolean }> = {
  sales: { label: 'Sales', fmt: (n) => inr(n), money: true },
  orders: { label: 'Orders', fmt: (n) => num(n) },
  aov: { label: 'Avg order value', fmt: (n) => inr(n), money: true },
  active_retailers: { label: 'Active retailers', fmt: (n) => num(n) },
  new_retailers: { label: 'New retailers', fmt: (n) => num(n) },
  repeat_retailers: { label: 'Repeat retailers', fmt: (n) => num(n) },
  units_per_order: { label: 'Units per order', fmt: (n) => num(n, 1) },
};

export default function DistributorDetail() {
  const { id } = useParams();
  const { searchParams } = useFilters();
  const nav = useNavigate();
  const t = useChartTokens();
  const q = useAnalytics<DD>(`/distributors/${id}/`);
  const d = q.data?.data;
  const basis = q.data?.meta?.sales_basis;

  const opt = useMemo(
    () =>
      d?.monthly?.length
        ? cartesian(t, { x: d.monthly.map((m) => monthLabel(m.month)), format: 'inr', legend: false, series: [{ name: 'Sales', data: d.monthly.map((m) => m.sales) }] })
        : null,
    [d, t],
  );

  if (q.isLoading) return <LoadingBlock height={400} />;
  if (q.error || !d)
    return (
      <Card>
        <ErrorState error={q.error ?? new Error('Distributor not found')} onRetry={() => q.refetch()} />
      </Card>
    );

  const p = d.profile;
  const extraProfile = Object.entries(p).filter(([k, v]) => !['id', 'name', 'state', 'region', 'asm', 'code', 'city', 'onboarded_on', 'last_stock_sync'].includes(k) && (typeof v === 'string' || typeof v === 'number'));

  return (
    <div>
      <div className="mb-2 text-xs text-muted">
        <Link to={linkWithFilters('/distributors', searchParams)} className="hover:text-ink">
          Distributors
        </Link>{' '}
        / {p.name}
      </div>
      <PageHeader title={p.name} subtitle={[p.code, p.city, p.state, p.region].filter(Boolean).join(' · ')} meta={q.data?.meta} />

      <Card>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4 xl:grid-cols-6">
          <Stat label="ASM" value={p.asm ?? '–'} />
          <Stat label="Onboarded" value={date(p.onboarded_on ?? null)} />
          <Stat label="Stock sync" value={<StalenessBadge at={p.last_stock_sync} />} />
          {extraProfile.slice(0, 3).map(([k, v]) => (
            <Stat key={k} label={titleCase(k)} value={String(v)} />
          ))}
        </div>
      </Card>

      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {Object.entries(d.kpis).map(([k, v]) => {
          const def = KPI_FMT[k] ?? { label: titleCase(k), fmt: (n: number | null | undefined) => num(n) };
          return <KpiTile key={k} label={def.label} kpi={v} format={def.fmt} basis={def.money ? basis : undefined} />;
        })}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard
          title="Monthly sales"
          subtitle={basis}
          option={opt}
          empty={!d.monthly?.length}
          table={{ columns: ['Month', 'Sales', 'Orders'], rows: d.monthly.map((m) => [monthLabel(m.month), inr(m.sales), num(m.orders ?? null)]) }}
        />
        <Card title="Top articles">
          <DataTable
            rows={d.top_articles}
            rowKey={(r) => r.style}
            exportName={`distributor_${p.id}_top_articles`}
            initialSort={{ key: 'sales', dir: 'desc' }}
            pageSize={10}
            dense
            columns={[
              { key: 'style', header: 'Style' },
              { key: 'name', header: 'Article' },
              { key: 'category', header: 'Category' },
              { key: 'units', header: 'Units', align: 'right', render: (r) => num(r.units) },
              { key: 'sales', header: 'Sales', align: 'right', render: (r) => inr(r.sales) },
              { key: 'share', header: 'Share', align: 'right', render: (r) => pct(asPct(r.share)) },
            ]}
          />
        </Card>
      </div>

      <Card title="Retailers" subtitle="Top 50 by sales" className="mt-4">
        <DataTable
          rows={d.retailers}
          rowKey={(r) => r.id}
          exportName={`distributor_${p.id}_retailers`}
          onRowClick={(r) => nav(linkWithFilters(`/retailers/${r.id}`, searchParams))}
          initialSort={{ key: 'sales', dir: 'desc' }}
          dense
          columns={[
            { key: 'name', header: 'Retailer', render: (r) => <span className="font-medium">{r.name}</span> },
            { key: 'state', header: 'State' },
            { key: 'segment', header: 'Segment', render: (r) => titleCase(r.segment) },
            { key: 'orders', header: 'Orders', align: 'right', render: (r) => num(r.orders) },
            { key: 'sales', header: 'Sales', align: 'right', render: (r) => inr(r.sales) },
            { key: 'last_order_date', header: 'Last order', render: (r) => date(r.last_order_date ?? null) },
            { key: 'days_since_last_order', header: 'Days since', align: 'right', render: (r) => num(r.days_since_last_order ?? null) },
          ]}
        />
      </Card>
    </div>
  );
}
