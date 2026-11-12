import { useMemo, useState, type ReactNode } from 'react';
import { useAuth } from '@/auth/AuthContext';
import { download, errorMessage, type Params } from '@/lib/api';
import { downloadCsv } from '@/lib/csv';
import { num } from '@/lib/format';
import { EmptyState, ErrorState, LoadingBlock, Spinner, cx } from './ui';
import { IconArrowDown, IconArrowUp, IconChevron, IconDownload } from './Icons';

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** Plain text header for CSV export (defaults to header if it's a string). */
  exportHeader?: string;
  render?: (row: T) => ReactNode;
  /** Raw value used for sorting and client CSV export. */
  value?: (row: T) => unknown;
  align?: 'left' | 'right' | 'center';
  sortable?: boolean;
  /** Server ordering field (defaults to key). */
  sortField?: string;
  className?: string;
  /** Hide from export. */
  noExport?: boolean;
}

export interface ServerPaging {
  count: number;
  page: number;
  pageSize: number;
  onPage: (p: number) => void;
  ordering?: string;
  onOrdering?: (o: string) => void;
}

interface Props<T> {
  columns: Column<T>[];
  rows: T[] | undefined;
  rowKey: (row: T, i: number) => string | number;
  loading?: boolean;
  fetching?: boolean;
  error?: unknown;
  onRetry?: () => void;
  onRowClick?: (row: T) => void;
  emptyTitle?: string;
  emptyHint?: string;
  /** Server-side paging/sorting. Omit for client-side. */
  server?: ServerPaging;
  pageSize?: number;
  initialSort?: { key: string; dir: 'asc' | 'desc' };
  /** Server export: GET {exportPath}?export=csv|xlsx with these params. */
  exportPath?: string;
  exportParams?: Params;
  exportName: string;
  title?: ReactNode;
  toolbar?: ReactNode;
  dense?: boolean;
  maxHeight?: number;
  footer?: ReactNode;
}

function cmp(a: unknown, b: unknown): number {
  if (a === b) return 0;
  if (a === null || a === undefined || a === '') return 1;
  if (b === null || b === undefined || b === '') return -1;
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b), 'en-IN', { numeric: true });
}

export function DataTable<T>(p: Props<T>) {
  const { can } = useAuth();
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' } | null>(p.initialSort ?? null);
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState<string | null>(null);
  const [exportErr, setExportErr] = useState<string | null>(null);
  const pageSize = p.server?.pageSize ?? p.pageSize ?? 25;

  const colValue = (c: Column<T>, r: T) => (c.value ? c.value(r) : (r as Record<string, unknown>)[c.key]);

  const sorted = useMemo(() => {
    const rows = p.rows ?? [];
    if (p.server || !sort) return rows;
    const c = p.columns.find((x) => x.key === sort.key);
    if (!c) return rows;
    const out = [...rows].sort((a, b) => cmp(colValue(c, a), colValue(c, b)));
    return sort.dir === 'desc' ? out.reverse() : out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.rows, sort, p.server, p.columns]);

  const total = p.server ? p.server.count : sorted.length;
  const curPage = p.server ? p.server.page : Math.min(page, Math.max(1, Math.ceil(total / pageSize)));
  const visible = p.server ? sorted : sorted.slice((curPage - 1) * pageSize, curPage * pageSize);
  const pages = Math.max(1, Math.ceil(total / pageSize));

  const serverOrdering = p.server?.ordering;
  const activeSort = p.server
    ? serverOrdering
      ? { key: p.columns.find((c) => (c.sortField ?? c.key) === serverOrdering.replace(/^-/, ''))?.key ?? '', dir: serverOrdering.startsWith('-') ? 'desc' : 'asc' }
      : null
    : sort;

  function toggleSort(c: Column<T>) {
    if (c.sortable === false) return;
    const isActive = activeSort?.key === c.key;
    const dir: 'asc' | 'desc' = isActive && activeSort?.dir === 'desc' ? 'asc' : 'desc';
    if (p.server?.onOrdering) {
      const field = c.sortField ?? c.key;
      p.server.onOrdering(dir === 'desc' ? `-${field}` : field);
    } else {
      setSort({ key: c.key, dir });
      setPage(1);
    }
  }

  const canExport = can('export_data');

  async function doExport(fmt: 'csv' | 'xlsx') {
    setExportErr(null);
    if (p.exportPath) {
      setExporting(fmt);
      try {
        await download(p.exportPath, { ...(p.exportParams ?? {}), export: fmt, ordering: serverOrdering }, `${p.exportName}.${fmt}`);
      } catch (e) {
        setExportErr(errorMessage(e));
      } finally {
        setExporting(null);
      }
      return;
    }
    const cols = p.columns.filter((c) => !c.noExport);
    downloadCsv(
      p.exportName,
      cols.map((c) => c.exportHeader ?? (typeof c.header === 'string' ? c.header : c.key)),
      sorted.map((r) => cols.map((c) => colValue(c, r))),
    );
  }

  return (
    <div className="flex min-w-0 flex-col">
      {(p.title || p.toolbar || canExport) && (
        <div className="flex flex-wrap items-center justify-between gap-2 pb-2">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            {p.title && <h3 className="text-sm font-semibold">{p.title}</h3>}
            {p.toolbar}
          </div>
          {canExport && (
            <div className="flex items-center gap-1.5">
              {p.fetching && !p.loading && <Spinner size={12} />}
              <button className="btn btn-sm" onClick={() => doExport('csv')} disabled={!!exporting || total === 0} title="Export CSV">
                {exporting === 'csv' ? <Spinner size={12} /> : <IconDownload size={13} />} CSV
              </button>
              {p.exportPath && (
                <button className="btn btn-sm" onClick={() => doExport('xlsx')} disabled={!!exporting || total === 0} title="Export Excel">
                  {exporting === 'xlsx' ? <Spinner size={12} /> : <IconDownload size={13} />} XLSX
                </button>
              )}
            </div>
          )}
        </div>
      )}
      {exportErr && <div className="pb-2 text-xs text-bad">Export failed: {exportErr}</div>}
      <div className="overflow-auto rounded-md border border-line" style={p.maxHeight ? { maxHeight: p.maxHeight } : undefined}>
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-[1] bg-sunken">
            <tr>
              {p.columns.map((c) => {
                const active = activeSort?.key === c.key;
                const sortable = c.sortable !== false && !(p.server && !p.server.onOrdering);
                return (
                  <th
                    key={c.key}
                    scope="col"
                    aria-sort={active ? (activeSort!.dir === 'asc' ? 'ascending' : 'descending') : undefined}
                    className={cx('th', c.align === 'right' && 'text-right', c.align === 'center' && 'text-center', c.className)}
                  >
                    {sortable ? (
                      <button className={cx('inline-flex items-center gap-1 hover:text-ink', active && 'text-ink')} onClick={() => toggleSort(c)}>
                        {c.header}
                        {active ? activeSort!.dir === 'asc' ? <IconArrowUp size={11} /> : <IconArrowDown size={11} /> : null}
                      </button>
                    ) : (
                      c.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className={cx('tabular transition-opacity', p.fetching && !p.loading && 'opacity-60')}>
            {p.loading ? (
              <tr>
                <td colSpan={p.columns.length}>
                  <LoadingBlock height={160} />
                </td>
              </tr>
            ) : p.error && !p.rows ? (
              <tr>
                <td colSpan={p.columns.length}>
                  <ErrorState error={p.error} onRetry={p.onRetry} compact />
                </td>
              </tr>
            ) : visible.length === 0 ? (
              <tr>
                <td colSpan={p.columns.length}>
                  <EmptyState title={p.emptyTitle ?? 'No rows'} hint={p.emptyHint} height={120} />
                </td>
              </tr>
            ) : (
              visible.map((r, i) => (
                <tr
                  key={p.rowKey(r, i)}
                  onClick={p.onRowClick ? () => p.onRowClick!(r) : undefined}
                  className={cx('border-t border-line', p.onRowClick && 'cursor-pointer hover:bg-sunken/70')}
                >
                  {p.columns.map((c) => (
                    <td key={c.key} className={cx('td', p.dense && 'py-1.5', c.align === 'right' && 'text-right', c.align === 'center' && 'text-center', c.className)}>
                      {c.render ? c.render(r) : String(colValue(c, r) ?? '–')}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
          {p.footer}
        </table>
      </div>
      {total > pageSize && (
        <div className="flex items-center justify-between gap-2 pt-2 text-xs text-muted">
          <span>
            {num((curPage - 1) * pageSize + 1)}–{num(Math.min(curPage * pageSize, total))} of {num(total)}
          </span>
          <div className="flex items-center gap-1">
            <button
              className="btn btn-sm"
              disabled={curPage <= 1}
              onClick={() => (p.server ? p.server.onPage(curPage - 1) : setPage(curPage - 1))}
              aria-label="Previous page"
            >
              <IconChevron size={12} className="rotate-180" />
            </button>
            <span className="px-1">
              Page {curPage} / {pages}
            </span>
            <button
              className="btn btn-sm"
              disabled={curPage >= pages}
              onClick={() => (p.server ? p.server.onPage(curPage + 1) : setPage(curPage + 1))}
              aria-label="Next page"
            >
              <IconChevron size={12} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
