import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useAnalytics } from '@/api/hooks';
import type { DistributorDetail as DD } from '@/api/types';
import { cartesian } from '@/charts/builders';
import { useChartTokens } from '@/charts/EChart';
import { ChartCard } from '@/components/ChartCard';
import { DataTable } from '@/components/DataTable';
import { KpiTile, endsMidMonth } from '@/components/KpiTile';
import { RfmDot } from '@/components/RfmPanel';
import { PageHeader } from '@/components/PageHeader';
import { OrdersDrill, type OrdersDrillSpec } from '@/components/OrdersDrill';
import { Card, ErrorState, LoadingBlock, Segmented, Stat } from '@/components/ui';
import { linkWithFilters, useFilters } from '@/lib/filters';
import { asPct, date, inr, monthLabel, num, pct, sharePct, titleCase } from '@/lib/format';
import { StalenessBadge, type SyncInfo } from './Distributors';
import { OrderDrawer } from './Orders';

const KPI_FMT: Record<string, { label: string; fmt: (n: number | null | undefined) => string; money?: boolean }> = {
  sales: { label: 'Sales', fmt: (n) => inr(n), money: true },
  orders: { label: 'Orders', fmt: (n) => num(n) },
  aov: { label: 'Avg order value', fmt: (n) => inr(n), money: true },
  active_retailers: { label: 'Active retailers', fmt: (n) => num(n) },
  new_retailers: { label: 'New retailers', fmt: (n) => num(n) },
  repeat_retailers: { label: 'Repeat retailers', fmt: (n) => num(n) },
  units_per_order: { label: 'Units per order', fmt: (n) => num(n, 1) },
  dispatch_pct: { label: 'Orders dispatched', fmt: (n) => pct(n) },
  achievement_pct: { label: 'Target achieved (month to date)', fmt: (n) => pct(n) },
};

// profile fields shown as-is from the API: readable labels, and numbers with separators
const PROFILE_LABELS: Record<string, string> = { gstin: 'GSTIN', mapped_retailers: 'Mapped retailers', pan: 'PAN' };
const profileValue = (v: string | number) => (typeof v === 'number' ? num(v) : v);

export default function DistributorDetail() {
  const { id } = useParams();
  const { searchParams } = useFilters();
  const nav = useNavigate();
  const t = useChartTokens();
  const q = useAnalytics<DD>(`/distributors/${id}/`);
  const d = q.data?.data;
  const basis = q.data?.meta?.sales_basis;

  const [grain, setGrain] = useState<'day' | 'week' | 'month'>('month');
  const [drill, setDrill] = useState<OrdersDrillSpec | null>(null);
  const [openId, setOpenId] = useState<string | number | null>(null);
  // sales trend by day (selected period) / week (26 weeks) / month (12 months) - requirements 4.3
  const trend = useMemo(() => {
    if (!d) return [] as { label: string; sales: number; orders: number | null }[];
    if (grain === 'day') return (d.daily ?? []).map((x) => ({ label: date(x.date, 'DD MMM'), sales: x.sales, orders: x.orders }));
    if (grain === 'week') return (d.weekly ?? []).map((x) => ({ label: `w/c ${date(x.week, 'DD MMM')}`, sales: x.sales, orders: x.orders }));
    return d.monthly.map((m) => ({ label: monthLabel(m.month), sales: m.sales, orders: m.orders ?? null }));
  }, [d, grain]);
  const opt = useMemo(
    () =>
      trend.length
        ? cartesian(t, { x: trend.map((m) => m.label), format: 'inr', legend: false, series: [{ name: 'Sales', data: trend.map((m) => m.sales) }] })
        : null,
    [trend, t],
  );

  if (q.isLoading) return <LoadingBlock height={400} />;
  if (q.error || !d)
    return (
      <Card>
        <ErrorState error={q.error ?? new Error('Distributor not found')} onRetry={() => q.refetch()} />
      </Card>
    );

  const p = d.profile;
  const extraProfile = Object.entries(p).filter(([k, v]) => !['id', 'name', 'state', 'region', 'asm', 'code', 'city', 'onboarded_on', 'last_stock_sync', 'inventory_status', 'stock_upload_mode', 'stock_update_frequency'].includes(k) && (typeof v === 'string' || typeof v === 'number'));

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
          <Stat
            label="Stock sync"
            value={<StalenessBadge at={p.last_stock_sync} info={p as SyncInfo} />}
            sub={[p.stock_upload_mode ? `Updated ${String(p.stock_upload_mode).toLowerCase() === 'manually' ? 'manually' : 'via ' + p.stock_upload_mode}` : null, p.stock_update_frequency as string | null].filter(Boolean).join(' · ') || undefined}
          />
          {extraProfile.slice(0, 3).map(([k, v]) => (
            <Stat key={k} label={PROFILE_LABELS[k] ?? titleCase(k)} value={String(profileValue(v as string | number))} />
          ))}
        </div>
      </Card>

      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {Object.entries(d.kpis).map(([k, v]) => {
          const def = KPI_FMT[k] ?? { label: titleCase(k), fmt: (n: number | null | undefined) => num(n) };
          return <KpiTile key={k} label={def.label} kpi={v} format={def.fmt} basis={def.money ? basis : undefined} partialMonth={endsMidMonth(q.data?.meta?.period?.to)} />;
        })}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard
          title={grain === 'day' ? 'Daily sales' : grain === 'week' ? 'Weekly sales' : 'Monthly sales'}
          subtitle={grain === 'day' ? `Every day of the selected period · ${basis ?? ''}` : grain === 'week' ? `26 weeks to the end of the period · ${basis ?? ''}` : basis}
          actions={<Segmented value={grain} onChange={setGrain} options={[{ value: 'day', label: 'Day' }, { value: 'week', label: 'Week' }, { value: 'month', label: 'Month' }]} />}
          option={opt}
          empty={!trend.length}
          table={{ columns: [grain === 'day' ? 'Day' : grain === 'week' ? 'Week' : 'Month', 'Sales', 'Orders'], rows: trend.map((m) => [m.label, inr(m.sales), num(m.orders)]) }}
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
              { key: 'category', header: 'Category', render: (r) => (r.category ? titleCase(r.category) : '–') },
              { key: 'units', header: 'Units', align: 'right', render: (r) => num(r.units) },
              { key: 'sales', header: 'Sales', align: 'right', render: (r) => inr(r.sales) },
              { key: 'share', header: 'Share', align: 'right', render: (r) => sharePct(asPct(r.share)) },
            ]}
          />
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card
          title="Stock on the app"
          subtitle={`Latest stock this distributor shows on TechnoDirect · low = ${d.stock?.low_threshold ?? 5} or fewer`}
          actions={<Link to={linkWithFilters('/inventory', searchParams, { distributor: String(p.id) })} className="text-xs text-ink2 hover:text-ink">Inventory →</Link>}
        >
          {d.stock && d.stock.skus ? (
            <div className="grid grid-cols-2 gap-3">
              <Stat label="Live styles" value={num(d.stock.live_styles)} />
              <Stat label="Units in stock" value={num(d.stock.units)} />
              <Stat label="SKUs in stock" value={`${num(d.stock.in_stock)} of ${num(d.stock.skus)}`} sub={pct((d.stock.in_stock / d.stock.skus) * 100, 0)} />
              <Stat label="Out of stock / low" value={`${num(d.stock.oos)} / ${num(d.stock.low)}`} sub="SKUs" />
            </div>
          ) : (
            <p className="py-6 text-sm text-ink2">No stock uploaded on the app for this distributor.</p>
          )}
        </Card>
        <Card
          className="xl:col-span-2"
          title="Orders"
          subtitle="Every order of this distributor in the selected period, with status, dispatch and delivery"
        >
          <p className="text-sm text-ink2">
            {num(d.kpis.orders?.value ?? null)} orders in the selected period.{' '}
            <button
              type="button"
              className="font-medium text-ink underline decoration-dotted underline-offset-4 hover:text-brand"
              onClick={() => setDrill({ title: `Orders · ${p.name}`, params: { distributor: String(p.id) } })}
            >
              Open the order list
            </button>{' '}
            to see each order, filter by retailer or open an order's details.
          </p>
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
            { key: 'rfm_label', header: 'RFM segment', render: (r) => (r.rfm_label ? <span className="flex items-center gap-1.5 whitespace-nowrap"><RfmDot segment={r.segment} />{r.rfm_label}</span> : '–') },
            { key: 'orders', header: 'Orders', align: 'right', render: (r) => num(r.orders) },
            { key: 'sales', header: 'Sales', align: 'right', render: (r) => inr(r.sales) },
            { key: 'last_order_date', header: 'Last order', render: (r) => date(r.last_order_date ?? null) },
            { key: 'days_since_last_order', header: 'Days since', align: 'right', render: (r) => num(r.days_since_last_order ?? null) },
          ]}
        />
      </Card>
      <OrdersDrill spec={drill} onClose={() => setDrill(null)} onOpenOrder={setOpenId} />
      <OrderDrawer id={openId} onClose={() => setOpenId(null)} />
    </div>
  );
}
