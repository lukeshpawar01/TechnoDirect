import { Fragment, useEffect, useState } from 'react';
import { useAnalytics } from '@/api/hooks';
import { DataTable } from '@/components/DataTable';
import { Card, ErrorState, Segmented, cx } from '@/components/ui';
import { IconSearch } from '@/components/Icons';
import { download, errorMessage } from '@/lib/api';
import { useFilters } from '@/lib/filters';
import { date, inr, num } from '@/lib/format';

/**
 * Inventory → the Power BI "Inventory" tab (TD_Analytics.pbix), on live stock:
 *  - "Current Stock with Each Distributor": Style → Size rows × distributor columns (stock units)
 *  - "Full Sets with Each Distributor": full sets per style × distributor, over each style's own sizes
 *  - "Stockwise Run Rate" + "Quantity sold in last 30, 60, 90 days" per style
 * Backend: analytics/views/inventory_matrix.py. Follows the page filters (territory, Category I/II/III).
 */
type Cells = Record<string, number>;
interface MatrixStyle { style: string; name: string | null; category: string | null; stock: number; by_dist: Cells; full_sets: Cells | null; full_total: number | null; set_sizes?: string | null; sizes: { size: string; stock: number; by_dist: Cells }[] }
interface MatrixData {
  distributors: { id: number; name: string; stock: number }[];
  grand_total: number; count: number; page: number; page_size: number; styles: MatrixStyle[];
  full_sets_total: number; full_sets_by_dist: Cells; snapshot_date: string | null; core_sizes: string[];
}
interface RunRow { style: string; name: string | null; category: string | null; stock: number; sold_30: number; sold_60: number; sold_90: number; sales_90: number; qty_sold: number; active_days: number | null; drr: number | null; mrr: number | null; days_of_stock: number | null }
interface RunData { count: number; page: number; page_size: number; rows: RunRow[]; totals: Record<string, number> }

const PAGE = 20;

function useDebounced(v: string, ms = 350) {
  const [d, setD] = useState(v);
  useEffect(() => {
    const h = setTimeout(() => setD(v), ms);
    return () => clearTimeout(h);
  }, [v, ms]);
  return d;
}

function Search({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1">
      <IconSearch size={13} className="text-muted" />
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder="Style code or name…" aria-label="Search style"
        className="w-40 bg-transparent text-xs outline-none placeholder:text-muted" />
    </div>
  );
}

export function StockMatrix() {
  const { apiParams } = useFilters();
  const [view, setView] = useState<'stock' | 'full'>('stock');
  const [search, setSearch] = useState('');
  const q = useDebounced(search);
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [exportErr, setExportErr] = useState<string | null>(null);
  const ordering = view === 'full' ? '-full_sets' : '-stock';
  useEffect(() => setPage(1), [q, view, apiParams]);
  const r = useAnalytics<MatrixData>('/inventory/matrix/', { page, page_size: PAGE, q: q || undefined, ordering });
  const d = r.data?.data;
  const pages = d ? Math.max(Math.ceil(d.count / d.page_size), 1) : 1;
  const dists = d?.distributors ?? [];
  const full = view === 'full';

  const toggle = (s: string) => setOpen((o) => {
    const n = new Set(o);
    if (n.has(s)) n.delete(s); else n.add(s);
    return n;
  });
  const cell = (v: number | undefined, strong = false) =>
    v ? <span className={cx('tabular-nums', strong ? 'font-semibold text-ink' : 'text-ink2')}>{num(v)}</span> : <span className="text-muted/50">·</span>;

  async function exportCsv() {
    setExportErr(null);
    try {
      await download('/inventory/matrix/', { ...apiParams, q: q || undefined, export: 'csv' }, 'stock_by_distributor_size.csv');
    } catch (e) {
      setExportErr(errorMessage(e));
    }
  }

  return (
    <Card
      className="mt-4"
      title={full ? 'Full sets with each distributor' : 'Current stock with each distributor'}
      subtitle={full
        ? 'A full set = one piece in every size the style comes in (the sizes listed for it in the stock data, even at 0: M–2XL, S–2XL, kids or plus sizes); full sets = the smallest stock across them. “–” = a single-size style.'
        : `Stock units by style and size at every distributor (latest sync${d?.snapshot_date ? `, ${date(d.snapshot_date)}` : ''}). Click a style for its sizes.`}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Segmented value={view} onChange={setView} size="xs" options={[{ value: 'stock', label: 'Stock' }, { value: 'full', label: 'Full sets' }]} />
          <Search value={search} onChange={setSearch} />
          {!full && <button type="button" className="btn btn-sm" onClick={exportCsv}>CSV</button>}
        </div>
      }
      bodyClass="p-0"
    >
      {r.error && !r.data ? (
        <ErrorState error={r.error} onRetry={() => r.refetch()} />
      ) : (
        <>
          <div className={cx('max-h-[34rem] overflow-auto', r.isFetching && 'opacity-70 transition-opacity')}>
            <table className="w-max min-w-full border-separate border-spacing-0 text-xs">
              <thead className="sticky top-0 z-20 bg-surface">
                <tr className="text-left text-muted">
                  <th className="sticky left-0 z-30 min-w-[13rem] border-b border-line bg-surface px-3 py-2 font-medium">Style {full ? '' : '/ Size'}</th>
                  <th className="border-b border-l border-line bg-surface px-3 py-2 text-right font-medium text-ink">Total</th>
                  {dists.map((x) => (
                    <th key={x.id} title={x.name} className="max-w-[6.5rem] border-b border-line px-2 py-2 text-right align-bottom font-medium">
                      <span className="line-clamp-2 break-words leading-tight">{x.name}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(d?.styles ?? []).map((s) => {
                  const isOpen = !full && open.has(s.style);
                  const vals = full ? s.full_sets : s.by_dist;
                  return (
                    <Fragment key={s.style}>
                      <tr className="group hover:bg-sunken/60">
                        <td className="sticky left-0 z-10 border-b border-line/60 bg-surface px-3 py-1.5 group-hover:bg-sunken">
                          <button type="button" disabled={full} onClick={() => toggle(s.style)} className="flex items-center gap-1.5 text-left">
                            {!full && <span className={cx('inline-block w-3 text-muted transition-transform', isOpen && 'rotate-90')}>▸</span>}
                            <span className="font-semibold text-ink">{s.style}</span>
                            {s.category && <span className="text-2xs text-muted">{s.category}</span>}
                            {full && s.set_sizes && <span className="whitespace-nowrap rounded bg-sunken px-1 text-2xs text-muted" title="Sizes in this style's set">{s.set_sizes}</span>}
                          </button>
                        </td>
                        <td className="border-b border-l border-line/60 px-3 py-1.5 text-right">
                          {full ? (s.full_total === null ? <span className="text-muted">–</span> : cell(s.full_total, true)) : cell(s.stock, true)}
                        </td>
                        {dists.map((x) => (
                          <td key={x.id} className="border-b border-line/60 px-2 py-1.5 text-right">
                            {vals === null ? <span className="text-muted/50">–</span> : cell(vals[x.id])}
                          </td>
                        ))}
                      </tr>
                      {isOpen && s.sizes.map((z) => (
                        <tr key={z.size} className="bg-sunken/30 hover:bg-sunken/60">
                          <td className="sticky left-0 z-10 border-b border-line/40 bg-sunken px-3 py-1 pl-8 text-ink2">{z.size}</td>
                          <td className="border-b border-l border-line/40 px-3 py-1 text-right">{cell(z.stock)}</td>
                          {dists.map((x) => <td key={x.id} className="border-b border-line/40 px-2 py-1 text-right">{cell(z.by_dist[x.id])}</td>)}
                        </tr>
                      ))}
                    </Fragment>
                  );
                })}
                {d && !d.styles.length && (
                  <tr><td colSpan={dists.length + 2} className="px-4 py-8 text-center text-sm text-muted">No stock for these filters.</td></tr>
                )}
              </tbody>
              {d && d.styles.length > 0 && (
                <tfoot className="sticky bottom-0 z-20 bg-surface">
                  <tr className="font-semibold text-ink">
                    <td className="sticky left-0 z-30 border-t border-line bg-surface px-3 py-2">All {num(d.count)} styles</td>
                    <td className="border-l border-t border-line px-3 py-2 text-right tabular-nums">{num(full ? d.full_sets_total : d.grand_total)}</td>
                    {dists.map((x) => (
                      <td key={x.id} className="border-t border-line px-2 py-2 text-right tabular-nums">{num(full ? d.full_sets_by_dist[x.id] ?? 0 : x.stock)}</td>
                    ))}
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-2 text-xs text-muted">
            <span>
              {d ? `Styles ${num((page - 1) * PAGE + 1)}–${num(Math.min(page * PAGE, d.count))} of ${num(d.count)}, ${full ? 'most full sets' : 'most stock'} first · ${dists.length} distributors` : 'Loading…'}
              {exportErr && <span className="ml-2 text-bad">{exportErr}</span>}
            </span>
            <span className="flex items-center gap-1">
              <button type="button" className="btn btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
              <span className="px-1 tabular-nums">{page} / {pages}</span>
              <button type="button" className="btn btn-sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button>
            </span>
          </div>
        </>
      )}
    </Card>
  );
}

export function StyleRunRate() {
  const { apiParams } = useFilters();
  const [search, setSearch] = useState('');
  const q = useDebounced(search);
  const [page, setPage] = useState(1);
  const [ordering, setOrdering] = useState('-sold_30');
  useEffect(() => setPage(1), [q, ordering, apiParams]);
  const r = useAnalytics<RunData>('/inventory/run-rate/', { page, page_size: 25, q: q || undefined, ordering });
  const d = r.data?.data;
  const t = d?.totals;
  return (
    <Card
      className="mt-4"
      title="Stockwise run rate"
      subtitle={`Per style: stock now, units sold in the last 30 / 60 / 90 days, and the run rate since its first sale (DRR = units sold ÷ active days, MRR = DRR × 30). Days of stock = stock ÷ the last 30 days' daily sales.${t ? ` All styles: ${num(t.stock)} in stock, ${num(t.sold_30)} sold in 30 days, ${inr(t.sales_90)} in 90 days.` : ''}`}
    >
      <DataTable
        rows={d?.rows}
        loading={r.isLoading}
        fetching={r.isFetching}
        error={r.error}
        onRetry={() => r.refetch()}
        rowKey={(x) => x.style}
        exportName="stockwise_run_rate"
        exportPath="/inventory/run-rate/"
        exportParams={{ q: q || undefined }}
        server={{ count: d?.count ?? 0, page, pageSize: 25, onPage: setPage, ordering, onOrdering: setOrdering }}
        dense
        toolbar={<Search value={search} onChange={setSearch} />}
        columns={[
          { key: 'style', header: 'Style', render: (x) => <span className="font-semibold">{x.style}</span> },
          { key: 'category', header: 'Category', sortable: false, render: (x) => x.category ?? '–' },
          { key: 'stock', header: 'Stock', align: 'right', render: (x) => num(x.stock) },
          { key: 'sold_30', header: 'Sold 30 d', align: 'right', render: (x) => num(x.sold_30) },
          { key: 'sold_60', header: 'Sold 60 d', align: 'right', render: (x) => num(x.sold_60) },
          { key: 'sold_90', header: 'Sold 90 d', align: 'right', render: (x) => num(x.sold_90) },
          { key: 'sales_90', header: 'Sales 90 d', align: 'right', render: (x) => inr(x.sales_90) },
          { key: 'qty_sold', header: 'Qty sold (all)', align: 'right', render: (x) => num(x.qty_sold) },
          { key: 'active_days', header: 'Active days', align: 'right', render: (x) => (x.active_days === null ? '–' : num(x.active_days)) },
          { key: 'drr', header: 'Units DRR', align: 'right', render: (x) => (x.drr === null ? '–' : x.drr.toFixed(1)) },
          { key: 'mrr', header: 'Units MRR', align: 'right', render: (x) => (x.mrr === null ? '–' : num(Math.round(x.mrr))) },
          {
            key: 'days_of_stock', header: 'Days of stock', align: 'right',
            render: (x) => x.days_of_stock === null ? <span className="text-muted">–</span> : (
              <span className={cx('font-semibold tabular-nums', x.days_of_stock < 15 ? 'text-bad' : x.days_of_stock < 30 ? 'text-warn' : 'text-ink')}>{num(x.days_of_stock)}</span>
            ),
          },
        ]}
      />
    </Card>
  );
}
