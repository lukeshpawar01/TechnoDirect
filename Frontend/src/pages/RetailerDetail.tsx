import { useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useAnalytics } from '@/api/hooks';
import type { RetailerDetail as RD } from '@/api/types';
import { cartesian } from '@/charts/builders';
import { useChartTokens } from '@/charts/EChart';
import { ChartCard } from '@/components/ChartCard';
import { DataTable } from '@/components/DataTable';
import { PageHeader } from '@/components/PageHeader';
import { Badge, Card, ErrorState, LoadingBlock, Stat, StatusBadge } from '@/components/ui';
import { linkWithFilters } from '@/lib/filters';
import { date, dateTime, inr, monthLabel, num, titleCase } from '@/lib/format';
import { OrderDrawer } from './Orders';

export default function RetailerDetail() {
  const { id } = useParams();
  const [sp] = useSearchParams();
  const t = useChartTokens();
  const q = useAnalytics<RD>(`/retailers/${id}/`, {}, { includeSegment: false });
  const r = q.data?.data;
  const [order, setOrder] = useState<string | number | null>(null);

  const opt = useMemo(
    () =>
      r?.monthly?.length
        ? cartesian(t, { x: r.monthly.map((m) => monthLabel(m.month)), format: 'inr', legend: false, series: [{ name: 'Sales', data: r.monthly.map((m) => m.sales) }] })
        : null,
    [r, t],
  );

  if (q.isLoading) return <LoadingBlock height={400} />;
  if (q.error || !r)
    return (
      <Card>
        <ErrorState error={q.error ?? new Error('Retailer not found')} onRetry={() => q.refetch()} />
      </Card>
    );

  return (
    <div>
      <div className="mb-2 text-xs text-muted">
        <Link to={linkWithFilters('/retailers', sp)} className="hover:text-ink">
          Retailers
        </Link>{' '}
        / {r.name}
      </div>
      <PageHeader title={r.name} subtitle={[r.city, r.state].filter(Boolean).join(', ')} meta={q.data?.meta} />

      <Card>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4 xl:grid-cols-8">
          <Stat label="KYC" value={<StatusBadge status={r.kyc_status} />} sub={r.kyc_approved_at ? `Approved ${date(r.kyc_approved_at)}` : undefined} />
          <Stat label="Segment" value={titleCase(r.segment)} sub={r.warm_match ? <Badge tone="brand">Warm ledger match</Badge> : undefined} />
          <Stat label="Phone" value={r.phone || '–'} />
          <Stat label="Distributor" value={r.distributor} />
          <Stat label="ASM" value={r.asm} />
          <Stat label="Pincode" value={r.pincode ?? '–'} />
          <Stat label="First / last order" value={`${date(r.first_order_date, 'DD MMM YY')} → ${date(r.last_order_date, 'DD MMM YY')}`} sub={r.days_since_last_order !== null ? `${num(r.days_since_last_order)} days since last order` : undefined} />
          <Stat label="Lifetime" value={`${inr(r.sales)} · ${num(r.orders)} orders`} sub={r.aov ? `AOV ${inr(r.aov)}` : undefined} />
        </div>
      </Card>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-5">
        <ChartCard
          className="xl:col-span-2"
          title="Monthly sales"
          subtitle={q.data?.meta?.sales_basis}
          option={opt}
          empty={!r.monthly?.length}
          table={{ columns: ['Month', 'Sales', 'Orders'], rows: (r.monthly ?? []).map((m) => [monthLabel(m.month), inr(m.sales), num(m.orders)]) }}
        />
        <Card title="Recent orders" className="xl:col-span-3">
          <DataTable
            rows={r.recent_orders}
            rowKey={(o) => o.id}
            exportName={`retailer_${r.id}_orders`}
            onRowClick={(o) => setOrder(o.id)}
            dense
            columns={[
              { key: 'display_id', header: 'Order' },
              { key: 'placed_at', header: 'Placed', render: (o) => dateTime(o.placed_at) },
              { key: 'distributor', header: 'Distributor' },
              { key: 'status', header: 'Status', render: (o) => <StatusBadge status={o.status} /> },
              { key: 'units', header: 'Units', align: 'right', render: (o) => num(o.units) },
              { key: 'value', header: 'Value', align: 'right', render: (o) => inr(o.value) },
            ]}
          />
        </Card>
      </div>
      <OrderDrawer id={order} onClose={() => setOrder(null)} />
    </div>
  );
}
