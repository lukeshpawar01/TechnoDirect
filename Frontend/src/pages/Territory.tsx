import { useMemo } from 'react';
import { useAnalytics } from '@/api/hooks';
import type { Territory as TerritoryData } from '@/api/types';
import { cartesian } from '@/charts/builders';
import { useChartTokens } from '@/charts/EChart';
import { colorFor } from '@/charts/palette';
import { AsmTrackerActions } from '@/components/AsmTracker';
import { ChartCard } from '@/components/ChartCard';
import { ExecutivePerformance } from '@/components/ExecutivePerformance';
import { IncentiveSheet } from '@/components/IncentiveSheet';
import { PageHeader } from '@/components/PageHeader';
import { SalesTeam } from '@/components/SalesTeam';
import { Segmented } from '@/components/ui';
import { useFilters } from '@/lib/filters';
import { asPct, inr, monthLabel, monthTick, pct } from '@/lib/format';

type GroupBy = 'region' | 'rsm' | 'state' | 'asm';

export default function Territory() {
  const { searchParams, update } = useFilters();
  const groupBy = (['region', 'rsm', 'state', 'asm'].includes(searchParams.get('group_by') ?? '') ? searchParams.get('group_by') : 'region') as GroupBy;
  const q = useAnalytics<TerritoryData>('/territory/', { group_by: groupBy });
  const t = useChartTokens();
  const d = q.data?.data;
  const basis = q.data?.meta?.sales_basis;
  const groupLabel = groupBy === 'asm' ? 'ASM' : groupBy === 'rsm' ? 'RSM' : groupBy === 'region' ? 'Region' : 'State';
  const byLabel = groupBy === 'asm' || groupBy === 'rsm' ? groupLabel : groupLabel.toLowerCase();

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
      x: months.map((m) => monthTick(m, q.data?.meta?.period?.to)),
      format: 'inr',
      series: groups.map((g) => ({ name: g, type: 'line' as const, data: months.map((m) => val(g, m)), color: colors[g], endLabel: groups.length <= 4 })),
    });
  }, [d, t]);

  return (
    <div>
      <PageHeader
        title="Region & ASM Performance"
        subtitle="Target achievement and adoption by geography and sales team (RSM → ASM)"
        meta={q.data?.meta}
        actions={
          <Segmented<GroupBy>
            value={groupBy}
            onChange={(v) => update({ group_by: v })}
            options={[
              { value: 'region', label: 'Region' },
              { value: 'rsm', label: 'RSM' },
              { value: 'state', label: 'State' },
              { value: 'asm', label: 'ASM' },
            ]}
          />
        }
      />
      {groupBy === 'rsm' && <SalesTeam rsms={d?.rows.filter((r) => r.id) ?? []} team={d?.breakdown ?? []} loading={q.isLoading} periodStart={q.data?.meta?.period?.from} />}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard
          title={`Target achievement by ${byLabel}`}
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
          title={`Monthly sales by ${byLabel}`}
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
      {/* the team's incentive sheet, row for row (replaces the region scorecard, 2026-11-23); ASM tracker
          export / upload / edit stays on it */}
      <IncentiveSheet month={q.data?.meta?.period?.to?.slice(0, 7)} actions={<AsmTrackerActions month={q.data?.meta?.period?.to?.slice(0, 7)} />} />
      <ExecutivePerformance month={q.data?.meta?.period?.to?.slice(0, 7)} />
    </div>
  );
}
