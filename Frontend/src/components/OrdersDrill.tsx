import { useEffect, useState, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { usePagedList } from '@/api/hooks';
import type { OrderRow } from '@/api/types';
import { DataTable } from '@/components/DataTable';
import { RfmDot } from '@/components/RfmPanel';
import { Drawer, Segmented, StatusBadge } from '@/components/ui';
import { linkWithFilters, useFilters } from '@/lib/filters';
import { date, dateTime, inr, num } from '@/lib/format';

/** What a chart mark stands for: a title for the panel and the /orders/ parameters that select its orders. */
export interface OrdersDrillSpec {
  title: string;
  subtitle?: string;
  params: Record<string, string>;
  /** extra buttons in the panel (e.g. "Filter the whole page by this status") */
  actions?: ReactNode;
}

interface OrderRetailerRow {
  id: number;
  retailer: string;
  phone: string | null;
  city: string | null;
  state: string | null;
  distributor: string | null;
  asm: string | null;
  rfm_segment: string;
  rfm_label: string;
  orders: number;
  value: number;
  last_order: string | null;
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');

/**
 * Drill-down from an Orders-page chart: the retailers (default) or orders behind one bar / cell / month,
 * each downloadable as CSV / XLSX with exactly the same selection.
 */
export function OrdersDrill({ spec, onClose, onOpenOrder }: { spec: OrdersDrillSpec | null; onClose: () => void; onOpenOrder: (id: number | string) => void }) {
  const [view, setView] = useState<'retailers' | 'orders'>('retailers');
  const [page, setPage] = useState(1);
  const [ordering, setOrdering] = useState('-value');
  const { apiParams, searchParams } = useFilters();
  const nav = useNavigate();
  const loc = useLocation();
  const key = spec ? JSON.stringify(spec.params) : '';

  useEffect(() => {
    setPage(1);
    setOrdering(view === 'retailers' ? '-value' : '-placed_at');
  }, [key, view]);
  useEffect(() => setView('retailers'), [key]);

  const open = !!spec;
  const params = { ...(spec?.params ?? {}), page, page_size: 25, ordering };
  const retailers = usePagedList<OrderRetailerRow>('/orders/retailers/', params, { enabled: open && view === 'retailers' });
  const orders = usePagedList<OrderRow>('/orders/', params, { enabled: open && view === 'orders' });
  const exportParams = { ...apiParams, ...(spec?.params ?? {}) };
  const name = spec ? slug(spec.title) : 'drill';

  return (
    <Drawer open={open} onClose={onClose} width={1100} title={spec?.title ?? ''}>
      {spec && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {spec.subtitle && <p className="text-xs text-ink2">{spec.subtitle}</p>}
            <div className="ml-auto flex items-center gap-2">
              {spec.actions}
              <Segmented
                value={view}
                onChange={setView}
                size="xs"
                options={[
                  { value: 'retailers', label: `Retailers${retailers.data ? ` · ${num(retailers.data.count)}` : ''}` },
                  { value: 'orders', label: `Orders${orders.data ? ` · ${num(orders.data.count)}` : ''}` },
                ]}
              />
            </div>
          </div>

          {view === 'retailers' ? (
            <DataTable
              rows={retailers.data?.results}
              loading={retailers.isLoading}
              fetching={retailers.isFetching}
              error={retailers.error}
              onRetry={() => retailers.refetch()}
              rowKey={(r) => r.id}
              dense
              onRowClick={(r) => nav(linkWithFilters(`/retailers/${r.id}`, searchParams), { state: { from: loc.pathname + loc.search, fromLabel: 'Orders & Fulfilment' } })}
              exportName={`retailers_${name}`}
              exportPath="/orders/retailers/"
              exportParams={exportParams}
              server={{ count: retailers.data?.count ?? 0, page, pageSize: 25, onPage: setPage, ordering, onOrdering: setOrdering }}
              emptyTitle="No retailers for this selection"
              columns={[
                { key: 'retailer', header: 'Retailer', sortable: false, render: (r) => <span className="font-medium">{r.retailer}</span> },
                { key: 'phone', header: 'Phone', sortable: false },
                { key: 'city', header: 'City', sortable: false, render: (r) => [r.city, r.state].filter(Boolean).join(', ') || '–', value: (r) => [r.city, r.state].filter(Boolean).join(', ') },
                { key: 'distributor', header: 'Distributor', sortable: false },
                { key: 'asm', header: 'ASM', sortable: false },
                {
                  key: 'rfm_label',
                  header: 'RFM segment',
                  sortable: false,
                  render: (r) => (
                    <span className="flex items-center gap-1.5 whitespace-nowrap text-xs">
                      <RfmDot segment={r.rfm_segment} />
                      {r.rfm_label}
                    </span>
                  ),
                },
                { key: 'orders', header: 'Orders', align: 'right', render: (r) => num(r.orders) },
                { key: 'value', header: 'Value', align: 'right', render: (r) => inr(r.value) },
                { key: 'last_order', header: 'Last order', render: (r) => date(r.last_order) },
              ]}
            />
          ) : (
            <DataTable
              rows={orders.data?.results}
              loading={orders.isLoading}
              fetching={orders.isFetching}
              error={orders.error}
              onRetry={() => orders.refetch()}
              rowKey={(r) => r.id}
              dense
              onRowClick={(r) => onOpenOrder(r.id)}
              exportName={`orders_${name}`}
              exportPath="/orders/"
              exportParams={exportParams}
              server={{ count: orders.data?.count ?? 0, page, pageSize: 25, onPage: setPage, ordering, onOrdering: setOrdering }}
              emptyTitle="No orders for this selection"
              columns={[
                { key: 'display_id', header: 'Order', render: (r) => <span className="font-medium">{r.display_id}</span> },
                { key: 'placed_at', header: 'Placed', render: (r) => dateTime(r.placed_at) },
                { key: 'retailer', header: 'Retailer' },
                { key: 'distributor', header: 'Distributor' },
                { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
                { key: 'shipped_on', header: 'Shipped', sortable: false, render: (r) => (r.shipped_on ? date(r.shipped_on, 'DD MMM') : '–') },
                { key: 'dispatch_days', header: 'Days to ship', sortable: false, align: 'right', render: (r) => (r.dispatch_days ?? '–') },
                { key: 'delivered_on', header: 'Delivered', sortable: false, render: (r) => (r.delivered_on ? date(r.delivered_on, 'DD MMM') : '–') },
                { key: 'transit_days', header: 'Days in transit', sortable: false, align: 'right', render: (r) => (r.transit_days ?? '–') },
                { key: 'payment_mode', header: 'Mode', render: (r) => r.payment_mode ?? '–' },
                { key: 'value', header: 'Value', align: 'right', render: (r) => inr(r.value, { compact: false }) },
              ]}
            />
          )}
        </>
      )}
    </Drawer>
  );
}
