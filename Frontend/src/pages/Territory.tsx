import { useMemo } from 'react';
import { useAnalytics } from '@/api/hooks';
import type { Territory as TerritoryData } from '@/api/types';
import { cartesian } from '@/charts/builders';
import { useChartTokens } from '@/charts/EChart';
import { colorFor } from '@/charts/palette';
import { AsmTrackerActions } from '@/components/AsmTracker';
import { ChartCard } from '@/components/ChartCard';
import { DataTable } from '@/components/DataTable';
import { PageHeader } from '@/components/PageHeader';
import { Card, Delta, Meter, Segmented } from '@/components/ui';
import { useFilters } from '@/lib/filters';
import { asPct, inr, monthLabel, num, pct } from '@/lib/format';

type GroupBy = 'region' | 'state' | 'asm';

export default function Territory() {
  const { searchParams, update, apiParams } = useFilters();
  const groupBy = (['region', 'state', 'asm'].includes(searchParams.get('group_by') ?? '') ? searchParams.get('group_by') : 'region') as GroupBy;
  const q = useAnalytics<TerritoryData>('/territory/', { group_by: groupBy });
  const t = useChartTokens();
  const d = q.data?.data;
  const basis = q.data?.meta?.sales_basis;
  const groupLabel = groupBy === 'asm' ? 'ASM' : groupBy === 'region' ? 'Region' : 'State';

  const achOpt = useMemo(() => {
    const rows = (d?.rows ?? []).filter((r) => r.achievement_pct !== null).sort((a, b) => (asPct(b.achievement_pct) ?? 0) - (asPct(a.achievement_pct) ?? 0));
    if (!rows.length) return null;
    return cartesian(t, {
      x: rows.map((r) => r.name),
      horizontal: true,
      format: 'pct',
      legend: false,
      showBarLabels: true,
      markLine: { value: 100, label: 'Target' },
      series: [{ name: 'Achievement', data: rows.map((r) => Math.round((asPct(r.achievement_pct) ?? 0) * 10) / 10) }],
    });
  }, [d, t]);

  const trendOpt = useMemo(() => {
    const mb = d?.monthly_by_group ?? [];
    if (!mb.length) return null;
    const months = [...new Set(mb.map((m) => m.month))].sort();
    const totals = new Map<string, number>();
    mb.forEach((m) => totals.set(m.group, (totals.get(m.group) ?? 0) + m.sales));
    // At most 5 named lines (legible end labels); the rest fold into "Other".
    const top = [...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([g]) => g);
    const groups = [...top, ...(totals.size > top.length ? ['Other'] : [])];
    const colors = colorFor(groups, t);
    const val = (g: string, m: string) =>
      g === 'Other' ? mb.filter((x) => x.month === m && !top.includes(x.group)).reduce((s, x) => s + x.sales, 0) : (mb.find((x) => x.month === m && x.group === g)?.sales ?? null);
    return cartesian(t, {
      x: months.map(monthLabel),
      format: 'inr',
      series: groups.map((g) => ({ name: g, type: 'line' as const, data: months.map((m) => val(g, m)), color: colors[g], endLabel: groups.length <= 4 })),
    });
  }, [d, t]);

  return (
    <div>
      <PageHeader
        title="Territory"
        subtitle="Target achievement and adoption by geography"
        meta={q.data?.meta}
        actions={
          <Segmented<GroupBy>
            value={groupBy}
            onChange={(v) => update({ group_by: v })}
            options={[
              { value: 'region', label: 'Region' },
              { value: 'state', label: 'State' },
              { value: 'asm', label: 'ASM' },
            ]}
          />
        }
      />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard
          title={`Target achievement by ${groupLabel.toLowerCase()}`}
          subtitle="Sales ÷ target for the selected period · line = 100%"
          option={achOpt}
          loading={q.isLoading}
          error={q.error && !q.data ? q.error : undefined}
          onRetry={() => q.refetch()}
          emptyHint="No targets set for this grouping. Add them in Admin → Targets."
          height={Math.max(240, (d?.rows.length ?? 6) * 28 + 40)}
          table={d ? { columns: [groupLabel, 'Sales', 'Target', 'Achieved'], rows: d.rows.map((r) => [r.name, inr(r.sales), inr(r.target), pct(asPct(r.achievement_pct))]) } : undefined}
        />
        <ChartCard
          title={`Monthly sales by ${groupLabel.toLowerCase()}`}
          subtitle={basis ? `Top 5, rest as Other · ${basis}` : 'Top 5, rest as Other'}
          option={trendOpt}
          loading={q.isLoading}
          height={Math.max(240, (d?.rows.length ?? 6) * 28 + 40)}
          table={
            d
              ? {
                  columns: ['Month', groupLabel, 'Sales'],
                  rows: d.monthly_by_group.map((m) => [monthLabel(m.month), m.group, inr(m.sales)]),
                }
              : undefined
          }
        />
      </div>
      <Card
        title={`${groupLabel} scorecard`}
        className="mt-4"
        // ASM targets are maintained by the team in Excel: export / upload / edit the monthly tracker here
        actions={<AsmTrackerActions month={q.data?.meta?.period?.to?.slice(0, 7)} />}
      >
        <DataTable
          rows={d?.rows}
          loading={q.isLoading}
          fetching={q.isFetching}
          error={q.error}
          onRetry={() => q.refetch()}
          rowKey={(r) => r.id}
          exportName={`territory_by_${groupBy}`}
          exportPath="/territory/"
          exportParams={{ ...apiParams, group_by: groupBy }}
          initialSort={{ key: 'sales', dir: 'desc' }}
          onRowClick={(r) => update({ [groupBy]: String(r.id) })}
          columns={[
            { key: 'name', header: groupLabel, render: (r) => <span className="font-medium">{r.name}</span> },
            { key: 'sales', header: 'Sales', align: 'right', render: (r) => inr(r.sales) },
            { key: 'target', header: 'Target', align: 'right', render: (r) => inr(r.target) },
            {
              key: 'achievement_pct',
              header: 'Achieved',
              align: 'right',
              render: (r) => {
                const a = asPct(r.achievement_pct);
                return (
                  <div className="flex items-center justify-end gap-2">
                    <div className="w-20"><Meter value={a} tone={a === null ? 'brand' : a >= 100 ? 'good' : a >= 80 ? 'warn' : 'bad'} /></div>
                    <span className="w-12">{pct(a, 0)}</span>
                  </div>
                );
              },
            },
            { key: 'growth_pct', header: 'Growth', align: 'right', render: (r) => <Delta value={r.growth_pct} suffix="" /> },
            { key: 'orders', header: 'Orders', align: 'right', render: (r) => num(r.orders) },
            { key: 'active_retailers', header: 'Active retailers', align: 'right', render: (r) => num(r.active_retailers) },
            { key: 'new_retailers', header: 'New', align: 'right', render: (r) => num(r.new_retailers) },
            { key: 'kyc_base', header: 'KYC base', align: 'right', render: (r) => num(r.kyc_base) },
            { key: 'adoption_pct', header: 'Adoption', align: 'right', render: (r) => pct(asPct(r.adoption_pct), 0) },
            { key: 'distributors', header: 'Distributors', align: 'right', render: (r) => num(r.distributors) },
          ]}
        />
        <p className="mt-2 text-2xs text-muted">Click a row to filter the whole dashboard to that {groupLabel.toLowerCase()}.</p>
      </Card>
    </div>
  );
}
