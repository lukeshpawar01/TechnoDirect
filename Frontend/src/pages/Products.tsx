import { useMemo, useState } from 'react';
import { useAnalytics } from '@/api/hooks';
import type { ArticleRow, Products as ProductsData, ProductTree } from '@/api/types';
import { DecompositionTree } from '@/components/DecompositionTree';
import { cartesian } from '@/charts/builders';
import { useChartTokens } from '@/charts/EChart';
import { colorFor } from '@/charts/palette';
import { ChartCard } from '@/components/ChartCard';
import { DataTable, type Column } from '@/components/DataTable';
import { MiniStat } from '@/components/KpiTile';
import { PageHeader } from '@/components/PageHeader';
import { StylePerformance } from '@/components/StylePerformance';
import { Card, ErrorState, Segmented } from '@/components/ui';
import { useFilters } from '@/lib/filters';
import { asPct, date, inr, monthLabel, num, pct } from '@/lib/format';

const articleCols: Column<ArticleRow>[] = [
  { key: 'style', header: 'Style' },
  { key: 'name', header: 'Article', render: (r) => <span className="font-medium">{r.name}</span> },
  { key: 'category', header: 'Category' },
  { key: 'sales', header: 'Sales', align: 'right', render: (r) => inr(r.sales) },
  { key: 'units', header: 'Units', align: 'right', render: (r) => num(r.units) },
  { key: 'orders', header: 'Orders', align: 'right', render: (r) => num(r.orders) },
  { key: 'retailers', header: 'Retailers', align: 'right', render: (r) => num(r.retailers) },
  { key: 'share', header: 'Share', align: 'right', render: (r) => pct(asPct(r.share)) },
  { key: 'units_per_order', header: 'Units / order', align: 'right', value: (r) => r.units_per_order ?? null, render: (r) => num(r.units_per_order, 1) },
  { key: 'realisation', header: 'Realisation / unit', align: 'right', value: (r) => r.realisation ?? null, render: (r) => inr(r.realisation, { compact: false }) },
];

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export default function Products() {
  const q = useAnalytics<ProductsData>('/products/');
  const tree = useAnalytics<ProductTree>('/products/tree/');
  const t = useChartTokens();
  const { apiParams, update } = useFilters();
  // click an article row: look at that style alone (all its colours / batches)
  const pickStyle = (code: string | undefined) => code && update({ article: [code] });
  const d = q.data?.data;
  const basis = q.data?.meta?.sales_basis;
  const [list, setList] = useState<'top' | 'bottom'>('top');

  // Category I (men / women / kids / unisex) stacked by Category II (topwear / bottomwear / ...)
  const catOpt = useMemo(() => {
    const c = d?.category_mix ?? [];
    if (!c.length) return null;
    const l1Tot = new Map<string, number>();
    const l2Tot = new Map<string, number>();
    c.forEach((x) => {
      l1Tot.set(x.l1, (l1Tot.get(x.l1) ?? 0) + x.sales);
      l2Tot.set(x.l2, (l2Tot.get(x.l2) ?? 0) + x.sales);
    });
    const l1s = [...l1Tot.entries()].sort((a, b) => a[1] - b[1]).map(([k]) => k);
    const l2top = [...l2Tot.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([k]) => k);
    const l2s = [...l2top, ...(l2Tot.size > l2top.length ? ['Other'] : [])];
    const colors = colorFor(l2s, t);
    const val = (l1: string, l2: string) => c.filter((x) => x.l1 === l1 && (l2 === 'Other' ? !l2top.includes(x.l2) : x.l2 === l2)).reduce((s, x) => s + x.sales, 0);
    return cartesian(t, { x: l1s.map(cap), horizontal: true, format: 'inr', series: l2s.map((l2) => ({ name: cap(l2), data: l1s.map((l1) => val(l1, l2)), stack: 'cat', color: colors[l2] })) });
  }, [d, t]);

  const mixOpt = useMemo(() => {
    const m = (d?.category_mix_monthly_l1l2 ?? []).map((x) => ({ month: x.month, category: `${cap(x.l1)} · ${x.l2}`, sales: x.sales }));
    if (!m.length) return null;
    const months = [...new Set(m.map((x) => x.month))].sort();
    const totals = new Map<string, number>();
    m.forEach((x) => totals.set(x.category, (totals.get(x.category) ?? 0) + x.sales));
    const top = [...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([c]) => c);
    const cats = [...top, ...(totals.size > top.length ? ['Other'] : [])];
    const colors = colorFor(cats, t);
    const val = (c: string, mo: string) => (c === 'Other' ? m.filter((x) => x.month === mo && !top.includes(x.category)) : m.filter((x) => x.month === mo && x.category === c)).reduce((s, x) => s + x.sales, 0);
    return cartesian(t, { x: months.map(monthLabel), format: 'inr', series: cats.map((c) => ({ name: c, data: months.map((mo) => val(c, mo)), stack: 'mix', color: colors[c] })) });
  }, [d, t]);

  const sizeOpt = useMemo(() => {
    const s = d?.size_mix ?? [];
    if (!s.length) return null;
    // ~20 sizes: horizontal bars so every size is named; the long tail folds into "Other sizes"
    const sorted = [...s].sort((a, b) => (b.share ?? 0) - (a.share ?? 0));
    const top = sorted.slice(0, 9);
    const rest = sorted.slice(9).reduce((acc, x) => acc + (asPct(x.share) ?? 0), 0);
    const rows = top.map((x) => ({ label: x.size, v: asPct(x.share) ?? 0 }));
    if (rest > 0) rows.push({ label: `Other sizes (${sorted.length - 9})`, v: rest });
    return cartesian(t, { x: rows.map((r) => r.label), horizontal: true, format: 'pct', legend: false, showBarLabels: true, series: [{ name: 'Share of units', data: rows.map((r) => Math.round(r.v * 10) / 10) }] });
  }, [d, t]);

  if (q.error && !q.data)
    return (
      <div>
        <PageHeader title="Products" />
        <Card>
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        </Card>
      </div>
    );

  return (
    <div>
      <PageHeader title="Products" subtitle="Category mix, articles, sizes and launches" meta={q.data?.meta} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <MiniStat label="Distinct articles sold" value={num(d?.concentration.distinct_articles)} />
        <MiniStat label="Top 4 articles' share" value={pct(asPct(d?.concentration.top4_share))} sub="of sales" />
        <MiniStat label="Top 12 articles' share" value={pct(asPct(d?.concentration.top12_share))} sub="of sales" />
        <MiniStat
          label="New articles, last 6 months"
          value={num(d?.new_articles_6m?.articles)}
          sub={d?.new_articles_6m ? `${inr(d.new_articles_6m.sales)} · ${pct(d.new_articles_6m.share)} of those months' sales` : undefined}
        />
      </div>

      <StylePerformance data={d} period={q.data?.meta?.period} loading={q.isFetching} />

      <Card
        className="mt-4"
        title="Product decomposition"
        subtitle={`Category I → Category II → Category III → Style · click a node to drill, × to remove a level · ${tree.data?.meta?.sales_basis ?? basis ?? ''}`}
      >
        {tree.error && !tree.data ? <ErrorState error={tree.error} onRetry={() => tree.refetch()} /> : <DecompositionTree data={tree.data?.data} loading={tree.isLoading} />}
      </Card>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ChartCard
          title="Category mix"
          subtitle="Category I, split by Category II · table has share and realisation"
          option={catOpt}
          loading={q.isLoading}
          table={d?.category_mix ? { columns: ['Category I', 'Category II', 'Sales', 'Units', 'Share', 'Realisation/unit', 'Units/order'], rows: d.category_mix.map((c) => [cap(c.l1), c.l2, inr(c.sales), num(c.units), pct(c.share), inr(c.realisation, { compact: false }), num(c.units_per_order, 1)]) } : undefined}
        />
        <ChartCard
          className="xl:col-span-2"
          title="Category mix by month"
          subtitle="Category I · Category II, top 6 with the rest as Other"
          option={mixOpt}
          loading={q.isLoading}
          table={d?.category_mix_monthly_l1l2 ? { columns: ['Month', 'Category I', 'Category II', 'Sales'], rows: d.category_mix_monthly_l1l2.map((m) => [monthLabel(m.month), cap(m.l1), m.l2, inr(m.sales)]) } : undefined}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card
          className="xl:col-span-2"
          title={list === 'top' ? 'Top articles' : 'Bottom articles'}
          subtitle="Click a row to see that style on its own"
          actions={<Segmented value={list} onChange={setList} options={[{ value: 'top', label: 'Top' }, { value: 'bottom', label: 'Bottom' }]} />}
        >
          <DataTable
            rows={list === 'top' ? d?.top_articles : d?.bottom_articles}
            loading={q.isLoading}
            rowKey={(r) => `${r.style}·${r.name}·${r.category}`}
            exportName={`${list}_articles`}
            exportPath="/products/"
            exportParams={{ ...apiParams, table: `${list}_articles` }}
            initialSort={{ key: 'sales', dir: list === 'top' ? 'desc' : 'asc' }}
            pageSize={15}
            dense
            columns={articleCols}
            onRowClick={(r) => pickStyle(r.code)}
          />
        </Card>
        <ChartCard
          title="Size mix"
          subtitle="Share of units sold · top 9 sizes"
          option={sizeOpt}
          loading={q.isLoading}
          table={d ? { columns: ['Size', 'Units', 'Share'], rows: d.size_mix.map((s) => [s.size, num(s.units), pct(asPct(s.share))]) } : undefined}
        />
      </div>

      <Card title="New launches" className="mt-4">
        <DataTable
          rows={d?.new_launches}
          loading={q.isLoading}
          rowKey={(r) => r.style}
          exportName="new_launches"
          initialSort={{ key: 'launched_on', dir: 'desc' }}
          dense
          columns={[
            { key: 'style', header: 'Style', render: (r) => <span className="font-medium">{r.style}</span> },
            { key: 'name', header: 'Article', render: (r) => r.name ?? '–' },
            { key: 'launched_on', header: 'Launched', render: (r) => date(r.launched_on) },
            { key: 'sales', header: 'Sales', align: 'right', render: (r) => inr(r.sales) },
            { key: 'units', header: 'Units', align: 'right', render: (r) => num(r.units) },
            { key: 'retailers', header: 'Retailers', align: 'right', render: (r) => num(r.retailers) },
          ]}
        />
      </Card>
    </div>
  );
}
