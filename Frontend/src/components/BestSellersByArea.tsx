import { useEffect, useMemo, useState } from 'react';
import { useAnalytics } from '@/api/hooks';
import type { BestSellerArea, BestSellerItem, BestSellers } from '@/api/types';
import { DataTable, type Column } from '@/components/DataTable';
import { Card, ErrorState, Segmented } from '@/components/ui';
import { useFilters } from '@/lib/filters';
import { inr, num, pct } from '@/lib/format';

type Level = 'region' | 'state';
type Dim = 'style' | 'category';

/** Ranks this many places higher in the area than nationally: a local favourite. */
const LOCAL_GAP = 3;

function NationalRank({ r, rank }: { r: BestSellerItem; rank: number }) {
  if (r.national_rank == null) return <span className="text-muted">–</span>;
  const local = r.national_rank - rank >= LOCAL_GAP;
  return (
    <span className="inline-flex items-center justify-end gap-1.5 whitespace-nowrap">
      {local && (
        <span className="rounded bg-accent/15 px-1.5 py-0.5 text-2xs font-medium text-accent" title={`#${rank} here, #${r.national_rank} across India`}>
          local favourite
        </span>
      )}
      <span className={local ? 'font-medium' : 'text-muted'}>#{r.national_rank}</span>
    </span>
  );
}

function ShareBar({ v }: { v: number | null }) {
  const w = Math.max(0, Math.min(100, v ?? 0));
  return (
    <span className="inline-flex items-center justify-end gap-2">
      <span className="hidden h-1.5 w-12 overflow-hidden rounded-full bg-sunken 2xl:block" aria-hidden>
        <span className="block h-full rounded-full bg-brand" style={{ width: `${Math.min(100, w * 2.5)}%` }} />
      </span>
      <span className="text-right">{pct(v, 1)}</span>
    </span>
  );
}

/** Products page: which styles / categories sell best in each region or state. */
export function BestSellersByArea() {
  const q = useAnalytics<BestSellers>('/products/best-sellers/');
  const { update } = useFilters();
  const [level, setLevel] = useState<Level>('region');
  const [dim, setDim] = useState<Dim>('style');
  const [pick, setPick] = useState<string | null>(null);
  const d = q.data?.data;
  const areas: BestSellerArea[] = useMemo(() => d?.[level]?.[dim] ?? [], [d, level, dim]);

  // keep the picked area when switching style / category; otherwise the biggest area
  useEffect(() => {
    if (!areas.length) return;
    if (!pick || !areas.some((a) => a.area === pick)) setPick(areas[0].area);
  }, [areas, pick]);
  const area = areas.find((a) => a.area === pick) ?? areas[0];
  const rows = useMemo(() => (area?.top ?? []).map((r, i) => ({ ...r, rank: i + 1 })), [area]);
  type Row = (typeof rows)[number];

  const columns: Column<Row>[] = [
    { key: 'rank', header: '#', render: (r) => <span className="text-muted">{r.rank}</span> },
    dim === 'style'
      ? {
          key: 'key',
          header: 'Style',
          render: (r) => (
            <div className="min-w-0">
              <div className="font-medium">{r.key}</div>
              <div className="max-w-[200px] truncate text-xs text-muted" title={r.name}>{r.name}</div>
            </div>
          ),
        }
      : { key: 'name', header: 'Category', render: (r) => <span className="font-medium">{r.name}</span> },
    dim === 'style'
      ? { key: 'category', header: 'Category', render: (r) => r.category ?? '–' }
      : {
          key: 'top_style',
          header: 'Best style here',
          render: (r) => (
            <div className="min-w-0">
              <div className="font-medium">{r.top_style ?? '–'}</div>
              <div className="max-w-[220px] truncate text-xs text-muted" title={r.top_style_name ?? ''}>
                {r.styles ? `of ${num(r.styles)} styles sold` : ''}
              </div>
            </div>
          ),
        },
    { key: 'sales', header: 'Sales', align: 'right', render: (r) => inr(r.sales) },
    { key: 'share', header: `Share of ${level}`, align: 'right', value: (r) => r.share ?? null, render: (r) => <ShareBar v={r.share} /> },
    { key: 'units', header: 'Units', align: 'right', render: (r) => num(r.units) },
    { key: 'retailers', header: 'Retailers', align: 'right', render: (r) => num(r.retailers) },
    { key: 'national_rank', header: 'Rank in India', align: 'right', value: (r) => r.national_rank ?? null, render: (r) => <NationalRank r={r} rank={r.rank} /> },
  ];

  return (
    <Card
      className="mt-4"
      title="Best sellers by area"
      subtitle={`Top ${d?.top_n ?? 10} ${dim === 'style' ? 'styles (all colours together)' : 'categories (Category III)'} in each ${level} this period · "local favourite" = ranks ${LOCAL_GAP}+ places higher here than across India`}
      actions={
        <div className="flex flex-wrap gap-2">
          <Segmented value={level} onChange={setLevel} options={[{ value: 'region', label: 'Region' }, { value: 'state', label: 'State' }]} />
          <Segmented value={dim} onChange={setDim} options={[{ value: 'style', label: 'Style' }, { value: 'category', label: 'Category' }]} />
        </div>
      }
    >
      {q.error && !q.data ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
          <div role="tablist" aria-label={`Pick a ${level}`} className="flex max-h-[520px] flex-col gap-1 overflow-y-auto pr-1">
            {q.isLoading && !areas.length && <p className="p-2 text-sm text-muted">Loading…</p>}
            {!q.isLoading && !areas.length && <p className="p-2 text-sm text-muted">No sales in this period.</p>}
            {areas.map((a) => {
              const on = a.area === area?.area;
              const first = a.top[0];
              return (
                <button
                  key={a.area}
                  role="tab"
                  aria-selected={on}
                  onClick={() => setPick(a.area)}
                  className={`rounded-md border px-3 py-2 text-left transition-colors ${on ? 'border-brand bg-brand/10' : 'border-line hover:bg-sunken'}`}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-sm font-medium">{a.area}</span>
                    <span className="whitespace-nowrap text-xs text-muted">{inr(a.sales)}</span>
                  </div>
                  <div className="mt-0.5 truncate text-xs text-muted">
                    {level === 'state' && a.region ? `${a.region} · ` : ''}#1 {first ? (dim === 'style' ? `${first.key} (${first.category ?? '–'})` : first.name) : '–'}
                  </div>
                </button>
              );
            })}
          </div>
          <div className="min-w-0">
            {area && (
              <p className="mb-2 text-sm">
                <span className="font-medium">{area.area}</span>
                <span className="text-muted">
                  {' '}
                  · {inr(area.sales)} from {num(area.items)} {dim === 'style' ? 'styles' : 'categories'} · top {rows.length} make{' '}
                  {pct(rows.reduce((s, r) => s + (r.share ?? 0), 0), 0)} of it
                </span>
              </p>
            )}
            <DataTable
              rows={rows}
              loading={q.isLoading}
              rowKey={(r) => r.key}
              exportName={`best_${dim === 'style' ? 'styles' : 'categories'}_${(area?.area ?? level).toLowerCase().replace(/\W+/g, '_')}`}
              initialSort={{ key: 'rank', dir: 'asc' }}
              pageSize={10}
              dense
              columns={columns}
              onRowClick={dim === 'style' ? (r) => update({ article: [r.key] }) : undefined}
            />
            {dim === 'style' && <p className="mt-2 text-2xs text-muted">Click a style to filter the whole page to it.</p>}
          </div>
        </div>
      )}
    </Card>
  );
}
