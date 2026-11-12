import { useEffect, useState } from 'react';
import { useAnalytics, usePagedList } from '@/api/hooks';
import type { Inventory as InventoryData, InventoryItem } from '@/api/types';
import { DataTable } from '@/components/DataTable';
import { MiniStat } from '@/components/KpiTile';
import { PageHeader } from '@/components/PageHeader';
import { Card, ErrorState, Meter, StatusBadge } from '@/components/ui';
import { IconSearch } from '@/components/Icons';
import { useFilters } from '@/lib/filters';
import { date, num, pct } from '@/lib/format';
import { StalenessBadge } from './Distributors';

export default function Inventory() {
  const q = useAnalytics<InventoryData>('/inventory/');
  const { apiParams } = useFilters();
  const d = q.data?.data;
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [page, setPage] = useState(1);
  const [ordering, setOrdering] = useState('qty');
  const [stock, setStock] = useState('');

  useEffect(() => {
    const h = setTimeout(() => setDebounced(search), 350);
    return () => clearTimeout(h);
  }, [search]);
  useEffect(() => setPage(1), [debounced, stock, apiParams]);

  const items = usePagedList<InventoryItem>('/inventory/items/', { page, page_size: 50, ordering, search: debounced || undefined, stock_status: stock || undefined });
  const staleCount = (d?.sync ?? []).filter((s) => !s.last_sync_at || Date.now() - new Date(s.last_sync_at).getTime() > 24 * 36e5).length;

  return (
    <div>
      <PageHeader title="Inventory" subtitle="Channel Konnect stock by distributor" meta={q.data?.meta} showBasis={false} />
      {q.error && !q.data ? (
        <Card>
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <MiniStat label="Live styles" value={num(d?.summary.live_styles)} />
            <MiniStat label="Out-of-stock SKUs" value={num(d?.summary.oos_skus)} tone={d?.summary.oos_skus ? 'bad' : undefined} />
            <MiniStat label="Low-stock SKUs" value={num(d?.summary.low_stock_skus)} tone={d?.summary.low_stock_skus ? 'warn' : undefined} />
            <MiniStat label="Distributors with stale stock" value={num(staleCount)} sub="No sync in 24 h" tone={staleCount ? 'warn' : 'good'} />
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Card title="Stock sync by distributor" subtitle="Green ≤ 24 h · amber ≤ 72 h · red older or never">
              <DataTable
                rows={d?.sync}
                loading={q.isLoading}
                rowKey={(r) => r.distributor_id}
                exportName="inventory_sync_status"
                initialSort={{ key: 'last_sync_at', dir: 'asc' }}
                dense
                columns={[
                  { key: 'distributor', header: 'Distributor', render: (r) => <span className="font-medium">{r.distributor}</span> },
                  { key: 'last_sync_at', header: 'Last sync', render: (r) => <StalenessBadge at={r.last_sync_at} />, value: (r) => r.last_sync_at },
                  { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
                  { key: 'skus', header: 'SKUs', align: 'right', render: (r) => num(r.skus) },
                  {
                    key: 'in_stock_skus',
                    header: 'In stock',
                    align: 'right',
                    render: (r) => {
                      const p = r.skus ? (r.in_stock_skus / r.skus) * 100 : null;
                      return (
                        <div className="flex items-center justify-end gap-2">
                          <div className="w-16"><Meter value={p} tone={p !== null && p < 70 ? 'warn' : 'brand'} /></div>
                          <span className="w-20">{num(r.in_stock_skus)} · {pct(p, 0)}</span>
                        </div>
                      );
                    },
                  },
                ]}
              />
            </Card>
            <Card title="Out-of-stock top sellers" subtitle="SKUs with sales in the last 30 days and zero stock">
              <DataTable
                rows={d?.oos_top_sellers}
                loading={q.isLoading}
                rowKey={(r, i) => `${r.style}-${r.size}-${r.distributor}-${i}`}
                exportName="oos_top_sellers"
                initialSort={{ key: 'last_30d_units', dir: 'desc' }}
                dense
                emptyTitle="No top sellers are out of stock"
                columns={[
                  { key: 'style', header: 'Style', render: (r) => <span className="font-medium">{r.style}</span> },
                  { key: 'size', header: 'Size' },
                  { key: 'distributor', header: 'Distributor' },
                  { key: 'last_30d_units', header: 'Units sold (30 d)', align: 'right', render: (r) => num(r.last_30d_units) },
                ]}
              />
            </Card>
          </div>
        </>
      )}

      <Card title="Stock items" className="mt-4">
        <DataTable
          rows={items.data?.results}
          loading={items.isLoading}
          fetching={items.isFetching}
          error={items.error}
          onRetry={() => items.refetch()}
          rowKey={(r, i) => `${r.distributor}-${r.sku}-${i}`}
          exportName="inventory_items"
          exportPath="/inventory/items/"
          exportParams={{ ...apiParams, search: debounced || undefined, stock_status: stock || undefined }}
          server={{ count: items.data?.count ?? 0, page, pageSize: 50, onPage: setPage, ordering, onOrdering: setOrdering }}
          toolbar={
            <>
              <div className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1">
                <IconSearch size={13} className="text-muted" />
                <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="SKU or style…" className="w-40 bg-transparent text-xs outline-none placeholder:text-muted" aria-label="Search stock" />
              </div>
              <select className="rounded-md border border-line bg-surface px-2 py-1 text-xs" value={stock} onChange={(e) => setStock(e.target.value)} aria-label="Stock status">
                <option value="">All stock</option>
                <option value="oos">Out of stock</option>
                <option value="low_stock">Low stock</option>
                <option value="in_stock">In stock</option>
              </select>
            </>
          }
          columns={[
            { key: 'distributor', header: 'Distributor' },
            { key: 'sku', header: 'SKU', render: (r) => <span className="font-mono text-xs">{r.sku}</span> },
            { key: 'style', header: 'Style' },
            { key: 'name', header: 'Article', render: (r) => r.name ?? '–' },
            { key: 'size', header: 'Size' },
            { key: 'category', header: 'Category', render: (r) => r.category ?? '–' },
            { key: 'qty', header: 'Qty', align: 'right', render: (r) => <span className={r.qty <= 0 ? 'font-semibold text-bad' : ''}>{num(r.qty)}</span> },
            { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status ?? (r.qty <= 0 ? 'oos' : 'in_stock')} /> },
            { key: 'snapshot_date', header: 'Snapshot', render: (r) => date(r.snapshot_date ?? null) },
          ]}
        />
      </Card>
    </div>
  );
}
