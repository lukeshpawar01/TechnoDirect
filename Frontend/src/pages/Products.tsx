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
];

export default function Products() {
  const q = useAnalytics<ProductsData>('/products/');
  const tree = useAnalytics<ProductTree>('/products/tree/');
  const t = useChartTokens();
  const { apiParams } = useFilters();
  const d = q.data?.data;
  const basis = q.data?.meta?.sales_basis;
  const [list, setList] = useState<'top' | 'bottom'>('top');

  const catOpt = useMemo(() => {
    const c = [...(d?.categories ?? [])].sort((a, b) => b.sales - a.sales);
    if (!c.length) return null;
    return cartesian(t, { x: c.map((x) => x.name), horizontal: true, format: 'inr', legend: false, showBarLabels: true, series: [{ name: 'Sales', data: c.map((x) => x.sales) }] });
  }, [d, t]);

  const mixOpt = useMemo(() => {
    const m = d?.category_mix_monthly ?? [];
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
    return cartesian(t, { x: s.map((x) => x.size), format: 'pct', legend: false, showBarLabels: true, series: [{ name: 'Share of units', data: s.map((x) => Math.round((asPct(x.share) ?? 0) * 10) / 10) }] });
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
        <MiniStat label="New launches in period" value={num(d?.new_launches.length)} />
      </div>

      <Card
        className="mt-4"
        title="Product decomposition"
        subtitle={`Category I → Category II → Category III → Style · click a node to drill, × to remove a level · ${tree.data?.meta?.sales_basis ?? basis ?? ''}`}
      >
        {tree.error && !tree.data ? <ErrorState error={tree.error} onRetry={() => tree.refetch()} /> : <DecompositionTree data={tree.data?.data} loading={tree.isLoading} />}
      </Card>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ChartCard
          title="Sales by category"
          subtitle={basis}
          option={catOpt}
          loading={q.isLoading}
          table={d ? { columns: ['Category', 'Sales', 'Units', 'Share', 'Realisation/unit'], rows: d.categories.map((c) => [c.name, inr(c.sales), num(c.units), pct(asPct(c.share)), inr(c.realisation, { compact: false })]) } : undefined}
        />
        <ChartCard
          className="xl:col-span-2"
          title="Category mix by month"
          subtitle="Top 6 categories, rest as Other"
          option={mixOpt}
          loading={q.isLoading}
          table={d ? { columns: ['Month', 'Category', 'Sales'], rows: d.category_mix_monthly.map((m) => [monthLabel(m.month), m.category, inr(m.sales)]) } : undefined}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card
          className="xl:col-span-2"
          title={list === 'top' ? 'Top articles' : 'Bottom articles'}
          actions={<Segmented value={list} onChange={setList} options={[{ value: 'top', label: 'Top' }, { value: 'bottom', label: 'Bottom' }]} />}
        >
          <DataTable
            rows={list === 'top' ? d?.top_articles : d?.bottom_articles}
            loading={q.isLoading}
            rowKey={(r) => r.style}
            exportName={`${list}_articles`}
            exportPath="/products/"
            exportParams={{ ...apiParams, table: `${list}_articles` }}
            initialSort={{ key: 'sales', dir: list === 'top' ? 'desc' : 'asc' }}
            pageSize={15}
            dense
            columns={articleCols}
          />
        </Card>
        <ChartCard
          title="Size mix"
          subtitle="Share of units sold"
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
