import { useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { IconChevron } from '@/components/Icons';
import { RfmDot } from '@/components/RfmPanel';
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
  const d = q.data?.data;
  const r = d?.profile;
  const rf = d?.rfm;
  const monthly = d?.monthly ?? [];
  const [order, setOrder] = useState<string | number | null>(null);
  const loc = useLocation();
  const nav = useNavigate();
  const from = loc.state as { from?: string; fromLabel?: string } | null;
  // Back to the exact list the user came from (segment, search, page, sort); opened directly -> the Retailers list.
  const goBack = () => {
    if (from?.from) nav(from.from);
    else if (loc.key !== 'default') nav(-1);
    else nav(linkWithFilters('/retailers', sp));
  };

  const opt = useMemo(
    () =>
      monthly.length
        ? cartesian(t, { x: monthly.map((m) => monthLabel(m.month)), format: 'inr', legend: false, series: [{ name: 'Sales', data: monthly.map((m) => m.sales) }] })
        : null,
    [monthly, t],
  );

  if (q.isLoading) return <LoadingBlock height={400} />;
  if (q.error || !d || !r)
    return (
      <Card>
        <ErrorState error={q.error ?? new Error('Retailer not found')} onRetry={() => q.refetch()} />
      </Card>
    );

  return (
    <div>
      <div className="mb-2 flex items-center gap-3 text-xs text-muted">
        <button
          type="button"
          onClick={goBack}
          className="inline-flex items-center gap-1 rounded-md border border-line bg-surface px-2 py-1 font-medium text-ink2 hover:bg-sunken hover:text-ink"
        >
          <IconChevron size={12} className="rotate-180" aria-hidden />
          Back{from?.fromLabel ? ` to ${from.fromLabel}` : ''}
        </button>
        <span>
          <Link to={from?.from?.startsWith('/retailers') ? from.from : linkWithFilters('/retailers', sp)} className="hover:text-ink">
            {from?.from?.startsWith('/retailers') && from.fromLabel ? from.fromLabel : 'Retailers'}
          </Link>{' '}
          / {r.name}
        </span>
      </div>
      <PageHeader
        title={r.name}
        subtitle={[r.owner_name && r.owner_name !== r.name ? r.owner_name : null, [r.city, r.state].filter(Boolean).join(', ')].filter(Boolean).join(' · ')}
        meta={q.data?.meta}
      />

      <Card>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4 xl:grid-cols-8">
          <Stat
            label="KYC"
            value={<StatusBadge status={r.kyc_status} />}
            sub={r.kyc_approved_at ? `Approved ${date(r.kyc_approved_at)}` : r.kyc_submitted_at ? `Submitted ${date(r.kyc_submitted_at)}` : undefined}
          />
          <Stat
            label="RFM segment"
            value={
              rf ? (
                <span className="flex items-center gap-1.5" title={rf.meaning}>
                  <RfmDot segment={rf.segment} />
                  {rf.label}
                </span>
              ) : (
                titleCase(r.segment)
              )
            }
            sub={r.warm_match ? <Badge tone="brand">Warm ledger match</Badge> : titleCase(r.segment)}
          />
          <Stat
            label="Last order"
            value={r.last_order_date ? `${date(r.last_order_date, 'DD MMM YY')}${r.days_since_last_order !== null ? ` · ${num(r.days_since_last_order)}d ago` : ''}` : '–'}
            sub={r.first_order_date ? `First ${date(r.first_order_date, 'DD MMM YY')}` : undefined}
          />
          <Stat label="Lifetime" value={`${inr(r.sales)} · ${num(r.orders)} orders`} sub={r.aov ? `AOV ${inr(r.aov)}` : undefined} />
          <Stat label="Distributor" value={r.distributor || '–'} />
          <Stat label="ASM" value={r.asm || '–'} sub={r.rsm ? `RSM ${r.rsm}` : undefined} />
          <Stat label="Region" value={r.region || '–'} sub={r.state || undefined} />
          <Stat label="Signed up" value={date(r.signed_up_at)} sub={r.tier ? `Tier ${r.tier}` : undefined} />
        </div>
        <div className="mt-4 grid grid-cols-2 gap-4 border-t border-line pt-4 md:grid-cols-4 xl:grid-cols-8">
          <Stat label="Owner" value={r.owner_name || '–'} />
          <Stat label="Phone" value={r.phone || '–'} />
          <div className="col-span-2">
            <Stat label="Email" value={<span title={r.email ?? undefined}>{r.email || '–'}</span>} />
          </div>
          <Stat label="GSTIN" value={r.gstin || '–'} />
          <Stat label="Udyam no." value={r.udyam_number || '–'} />
          <Stat label="City" value={r.city || '–'} />
          <Stat label="Pincode" value={r.pincode || '–'} />
        </div>
        {rf && rf.segment !== 'prospect' && (
          <div className="mt-4 grid grid-cols-2 gap-4 border-t border-line pt-4 md:grid-cols-4 xl:grid-cols-8">
            <Stat
              label="Silent vs usual gap"
              value={rf.days_since !== undefined ? `${num(rf.days_since)}d vs ${num(rf.expected_gap ?? 0)}d` : '–'}
              sub={rf.recency_ratio !== undefined ? `${rf.recency_ratio.toFixed(2)}× their rhythm` : undefined}
            />
            <Stat label="R · F · M scores" value={rf.r_score ? `${rf.r_score} · ${rf.f_score} · ${rf.m_score}` : '–'} sub={rf.r_score ? `FM ${rf.fm} (1 low – 5 high)` : titleCase(rf.lifecycle ?? '')} />
            <Stat label="Orders / month" value={rf.f !== undefined ? rf.f.toFixed(2) : '–'} sub={rf.tenure_months ? `over ${rf.tenure_months.toFixed(1)} months` : undefined} />
            <Stat label="Value / month" value={rf.m !== undefined ? inr(rf.m) : '–'} sub={rf.window_start ? `since ${date(rf.window_start, 'MMM YY')}` : undefined} />
            <div className="col-span-2 md:col-span-4">
              <Stat
                label={`What to do · as of ${date(rf.as_of)}`}
                value={<span className="whitespace-normal font-medium">{rf.action}</span>}
                sub={<span className="whitespace-normal">{rf.meaning}</span>}
              />
            </div>
          </div>
        )}
      </Card>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-5">
        <ChartCard
          className="xl:col-span-2"
          title="Monthly sales"
          subtitle={q.data?.meta?.sales_basis}
          option={opt}
          empty={!monthly.length}
          table={{ columns: ['Month', 'Sales', 'Orders'], rows: monthly.map((m) => [monthLabel(m.month), inr(m.sales), num(m.orders)]) }}
        />
        <Card title="Recent orders" className="xl:col-span-3">
          <DataTable
            rows={d.recent_orders}
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
