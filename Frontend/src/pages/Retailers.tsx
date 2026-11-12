import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { usePagedList } from '@/api/hooks';
import type { RetailerRow } from '@/api/types';
import { DataTable } from '@/components/DataTable';
import { PageHeader } from '@/components/PageHeader';
import { Badge, Card, StatusBadge, Tabs } from '@/components/ui';
import { IconSearch } from '@/components/Icons';
import { linkWithFilters, useFilters } from '@/lib/filters';
import { date, inr, num, titleCase } from '@/lib/format';

const SEGMENT_TABS = [
  { value: '', label: 'All' },
  { value: 'new', label: 'New' },
  { value: 'repeat', label: 'Repeat' },
  { value: 'one_time', label: 'One-time' },
  { value: 'retained', label: 'Retained' },
  { value: 'reactivated', label: 'Reactivated' },
  { value: 'never_ordered', label: 'Never ordered' },
  { value: 'inactive_30', label: 'Inactive 30+' },
  { value: 'inactive_60', label: 'Inactive 60+' },
  { value: 'inactive_90', label: 'Inactive 90+' },
];

const ACTION_HINT: Record<string, string> = {
  never_ordered: 'Action list: KYC-approved retailers who have never ordered — call warm (ledger-matched) ones first.',
  inactive_30: 'Action list: retailers with no order for 30+ days — reactivation calls.',
  inactive_60: 'Action list: 60+ days since last order — at risk of churn.',
  inactive_90: 'Action list: 90+ days since last order — treat as lost; win-back offers.',
};

export default function Retailers() {
  const { filters, update, searchParams, apiParams } = useFilters();
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const segment = filters.segment ?? '';
  const warm = sp.get('warm') ?? undefined;
  const [search, setSearch] = useState(sp.get('search') ?? '');
  const [debounced, setDebounced] = useState(search);
  const [page, setPage] = useState(1);
  const [ordering, setOrdering] = useState('-sales');

  useEffect(() => {
    const h = setTimeout(() => setDebounced(search), 350);
    return () => clearTimeout(h);
  }, [search]);
  useEffect(() => setPage(1), [debounced, segment, warm, filters]);

  const params = { page, page_size: 50, ordering, search: debounced || undefined, warm };
  const q = usePagedList<RetailerRow>('/retailers/', params);

  return (
    <div>
      <PageHeader title="Retailers" subtitle="Segments and downloadable action lists" />
      <Card bodyClass="p-0">
        <div className="px-4 pt-2">
          <Tabs value={segment} onChange={(v) => update({ segment: v || undefined, warm: undefined })} tabs={SEGMENT_TABS} />
        </div>
        <div className="p-4">
          {ACTION_HINT[segment] && (
            <div className="mb-3 rounded-md border border-line bg-sunken px-3 py-2 text-xs text-ink2">
              {ACTION_HINT[segment]}
              {warm && <Badge tone="brand">{warm === 'true' ? 'Warm only' : 'Cold only'}</Badge>}
            </div>
          )}
          <DataTable
            rows={q.data?.results}
            loading={q.isLoading}
            fetching={q.isFetching}
            error={q.error}
            onRetry={() => q.refetch()}
            rowKey={(r) => r.id}
            onRowClick={(r) => nav(linkWithFilters(`/retailers/${r.id}`, searchParams))}
            exportName={`retailers_${segment || 'all'}`}
            exportPath="/retailers/"
            exportParams={{ ...apiParams, ordering, search: debounced || undefined, warm }}
            server={{ count: q.data?.count ?? 0, page, pageSize: 50, onPage: setPage, ordering, onOrdering: setOrdering }}
            emptyTitle="No retailers in this segment"
            toolbar={
              <div className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1">
                <IconSearch size={13} className="text-muted" />
                <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search name, phone, city…" className="w-56 bg-transparent text-xs outline-none placeholder:text-muted" aria-label="Search retailers" />
              </div>
            }
            columns={[
              { key: 'name', header: 'Retailer', render: (r) => <span className="font-medium">{r.name}</span> },
              { key: 'phone', header: 'Phone', sortable: false },
              { key: 'state', header: 'State' },
              { key: 'distributor', header: 'Distributor' },
              { key: 'asm', header: 'ASM' },
              { key: 'kyc_status', header: 'KYC', render: (r) => <StatusBadge status={r.kyc_status} /> },
              { key: 'segment', header: 'Segment', render: (r) => <span className="text-xs text-ink2">{titleCase(r.segment)}</span> },
              { key: 'warm_match', header: 'Warm', align: 'center', render: (r) => (r.warm_match ? <Badge tone="brand">Warm</Badge> : <span className="text-muted">–</span>), value: (r) => (r.warm_match ? 'Yes' : 'No') },
              { key: 'first_order_date', header: 'First order', render: (r) => date(r.first_order_date) },
              { key: 'last_order_date', header: 'Last order', render: (r) => date(r.last_order_date) },
              {
                key: 'days_since_last_order',
                header: 'Days since',
                align: 'right',
                render: (r) =>
                  r.days_since_last_order === null ? '–' : <span className={r.days_since_last_order >= 90 ? 'font-semibold text-bad' : r.days_since_last_order >= 30 ? 'text-warn' : ''}>{num(r.days_since_last_order)}</span>,
              },
              { key: 'orders', header: 'Orders', align: 'right', render: (r) => num(r.orders) },
              { key: 'sales', header: 'Sales', align: 'right', render: (r) => inr(r.sales) },
            ]}
          />
        </div>
      </Card>
    </div>
  );
}
