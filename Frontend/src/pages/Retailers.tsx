import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useAnalytics, usePagedList } from '@/api/hooks';
import type { RetailerRow, RfmData } from '@/api/types';
import { TierChip } from '@/components/TierChip';
import { RfmDot, RfmPanel } from '@/components/RfmPanel';
import { SegmentTrend } from '@/components/SegmentTrend';
import { DataTable } from '@/components/DataTable';
import { PageHeader } from '@/components/PageHeader';
import { Badge, Card, StatusBadge, Tabs } from '@/components/ui';
import { IconSearch } from '@/components/Icons';
import { linkWithFilters, useFilters } from '@/lib/filters';
import { date, inr, num, titleCase } from '@/lib/format';
import { ACTION_HINT, SEGMENT_TABS } from '@/lib/lifecycle';

export default function Retailers() {
  const { filters, update, searchParams, apiParams } = useFilters();
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const loc = useLocation();
  const segment = filters.segment ?? '';
  const warm = sp.get('warm') ?? undefined;
  // Page, sort and search live in the URL, so coming back from a retailer restores the same list view.
  // (Any filter change through update() drops `page`, i.e. goes back to page 1.)
  const debounced = sp.get('search') ?? '';
  const page = Math.max(1, Number(sp.get('page')) || 1);
  const ordering = sp.get('ordering') || '-sales';
  const setPage = (p: number) => update({ page: p > 1 ? String(p) : undefined });
  const setOrdering = (o: string) => update({ ordering: o === '-sales' ? undefined : o });
  const [search, setSearch] = useState(debounced);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (search === debounced) return;
    const h = setTimeout(() => update({ search: search.trim() || undefined }), 350);
    return () => clearTimeout(h);
  }, [search, debounced, update]);

  const params = {
    page,
    page_size: 50,
    ordering,
    search: debounced || undefined,
    warm,
  };
  const q = usePagedList<RetailerRow>('/retailers/', params);
  const rfmQ = useAnalytics<RfmData>('/retailers/rfm/', {}, { includeSegment: false });
  const rfmSeg = rfmQ.data?.data.segments.find((s) => s.segment === segment);
  const isLifecycle = SEGMENT_TABS.some((t) => t.value === segment);
  const segLabel = rfmSeg?.label ?? SEGMENT_TABS.find((t) => t.value === segment)?.label ?? 'All';

  return (
    <div>
      <PageHeader title="Retailers" subtitle="RFM segments, lifecycle groups and downloadable action lists" />
      <RfmPanel
        selected={segment}
        onSelect={(s) => {
          const off = s === segment;
          update({ segment: off ? undefined : s, warm: undefined });
          // jump to the list of those retailers (it sits below the panel, off-screen)
          if (!off) {
            const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            requestAnimationFrame(() =>
              listRef.current?.scrollIntoView({
                behavior: smooth ? 'smooth' : 'auto',
                block: 'start',
              }),
            );
          }
        }}
      />
      <SegmentTrend selected={segment} />
      <div ref={listRef} className="scroll-mt-4">
        <Card bodyClass="p-0">
          <div className="px-4 pt-2">
            {/* an RFM segment selection leaves no lifecycle tab highlighted */}
            <Tabs value={isLifecycle ? segment : '__rfm'} onChange={(v) => update({ segment: v || undefined, warm: undefined })} tabs={SEGMENT_TABS} />
          </div>
          <div className="p-4">
            {segment && !isLifecycle && (
              <div className="mb-3 flex flex-wrap items-start gap-x-3 gap-y-1 rounded-md border border-brand/30 bg-brand/5 px-3 py-2 text-xs text-ink2">
                <span className="flex items-center gap-1.5 font-semibold text-ink">
                  <RfmDot segment={segment} />
                  RFM: {segLabel}
                </span>
                {rfmSeg && (
                  <span>
                    {rfmSeg.meaning} <span className="font-medium text-ink">Action:</span> {rfmSeg.action}
                  </span>
                )}
                <button type="button" className="ml-auto text-ink underline decoration-dotted underline-offset-2" onClick={() => update({ segment: undefined })}>
                  Clear
                </button>
              </div>
            )}
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
              onRowClick={(r) =>
                nav(linkWithFilters(`/retailers/${r.id}`, searchParams), {
                  state: {
                    from: loc.pathname + loc.search,
                    fromLabel: `Retailers · ${segLabel}`,
                  },
                })
              }
              exportName={`retailers_${segment || 'all'}`}
              exportPath="/retailers/"
              exportParams={{
                ...apiParams,
                ordering,
                search: debounced || undefined,
                warm,
              }}
              server={{
                count: q.data?.count ?? 0,
                page,
                pageSize: 50,
                onPage: setPage,
                ordering,
                onOrdering: setOrdering,
              }}
              emptyTitle="No retailers in this segment"
              toolbar={
                <div className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1">
                  <IconSearch size={13} className="text-muted" />
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search name, phone, city…"
                    className="w-56 bg-transparent text-xs outline-none placeholder:text-muted"
                    aria-label="Search retailers"
                  />
                </div>
              }
              columns={[
                {
                  key: 'name',
                  header: 'Retailer',
                  render: (r) => <span className="font-medium">{r.name}</span>,
                },
                { key: 'phone', header: 'Phone', sortable: false },
                { key: 'state', header: 'State' },
                { key: 'distributor', header: 'Distributor' },
                { key: 'asm', header: 'ASM' },
                { key: 'rsm', header: 'RSM', sortable: false },
                {
                  key: 'kyc_status',
                  header: 'KYC',
                  render: (r) => <StatusBadge status={r.kyc_status} />,
                },
                {
                  key: 'tier',
                  header: 'Tier',
                  sortable: false,
                  render: (r) => (r.tier ? <TierChip tier={r.tier} /> : <span className="text-xs text-muted" title="Not found in the BlueOrigin sheets">–</span>),
                },
                {
                  key: 'rfm_label',
                  header: 'RFM segment',
                  sortable: false,
                  render: (r) =>
                    r.rfm_label ? (
                      <span className="flex items-center gap-1.5 whitespace-nowrap text-xs">
                        <RfmDot segment={r.rfm_segment} />
                        {r.rfm_label}
                      </span>
                    ) : (
                      '–'
                    ),
                },
                {
                  key: 'segment',
                  header: 'Status',
                  sortable: false,
                  render: (r) => <span className="text-xs text-ink2">{titleCase(r.segment)}</span>,
                },
                {
                  key: 'warm_match',
                  header: 'Warm',
                  align: 'center',
                  render: (r) => (r.warm_match ? <Badge tone="brand">Warm</Badge> : <span className="text-muted">–</span>),
                  value: (r) => (r.warm_match ? 'Yes' : 'No'),
                },
                {
                  key: 'first_order_date',
                  header: 'First order',
                  render: (r) => date(r.first_order_date),
                },
                {
                  key: 'last_order_date',
                  header: 'Last order',
                  render: (r) => date(r.last_order_date),
                },
                {
                  key: 'days_since_last_order',
                  header: 'Days since',
                  align: 'right',
                  render: (r) =>
                    r.days_since_last_order === null ? (
                      '–'
                    ) : (
                      <span className={r.days_since_last_order >= 90 ? 'font-semibold text-bad' : r.days_since_last_order >= 30 ? 'text-warn' : ''}>
                        {num(r.days_since_last_order)}
                      </span>
                    ),
                },
                {
                  key: 'orders',
                  header: 'Orders',
                  align: 'right',
                  render: (r) => num(r.orders),
                },
                {
                  key: 'sales',
                  header: 'Sales',
                  align: 'right',
                  render: (r) => inr(r.sales),
                },
              ]}
            />
          </div>
        </Card>
      </div>
    </div>
  );
}
