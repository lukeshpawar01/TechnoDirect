import { useMemo, useState } from 'react';
import { useAnalytics, usePagedList } from '@/api/hooks';
import type { BoHierarchy, BoRetailerRow, BoSummary } from '@/api/types';
import { cartesian } from '@/charts/builders';
import { useChartTokens } from '@/charts/EChart';
import { ChartCard } from '@/components/ChartCard';
import { DataTable } from '@/components/DataTable';
import { IconInfo, IconSearch } from '@/components/Icons';
import { MiniStat } from '@/components/KpiTile';
import { PageHeader } from '@/components/PageHeader';
import { TierChip } from '@/components/TierChip';
import { Card, Delta, ErrorState, Segmented, cx } from '@/components/ui';
import { useFilters } from '@/lib/filters';
import { inr, monthLabel, num } from '@/lib/format';
import { TIERS, tierColor } from '@/lib/tiers';

type Group = 'region' | 'rsm' | 'asm' | 'state' | 'distributor';
const GROUPS: { value: Group; label: string }[] = [
  { value: 'region', label: 'Region' },
  { value: 'rsm', label: 'RSM' },
  { value: 'asm', label: 'ASM' },
  { value: 'state', label: 'State' },
  { value: 'distributor', label: 'Distributor' },
];
/** clicking a row filters the page to it and goes one level down */
const NEXT: Record<Group, Group> = { region: 'rsm', rsm: 'asm', asm: 'distributor', state: 'distributor', distributor: 'distributor' };
const TIERED = TIERS.filter((t) => t !== 'Untiered');

export default function BlueOrigin() {
  const t = useChartTokens();
  const { update } = useFilters();
  const s = useAnalytics<BoSummary>('/blueorigin/summary/');
  const [group, setGroup] = useState<Group>('asm');
  const h = useAnalytics<BoHierarchy>('/blueorigin/hierarchy/', { group_by: group });
  const [mixBy, setMixBy] = useState<'retailers' | 'purchase'>('retailers');
  const d = s.data?.data;
  const w = d?.window;
  const k = d?.kpis;

  // list
  const [page, setPage] = useState(1);
  const [ordering, setOrdering] = useState('-purchase');
  const [search, setSearch] = useState('');
  const listParams = { page, page_size: 50, ordering, search: search.trim() || undefined };
  const list = usePagedList<BoRetailerRow>('/blueorigin/retailers/', listParams);

  const mixOpt = useMemo(() => {
    if (!d?.tier_mix.length) return null;
    return cartesian(t, {
      x: d.tier_mix.map((q) => q.label),
      format: mixBy === 'purchase' ? 'inr' : 'num',
      legend: true,
      series: (mixBy === 'retailers' ? TIERED : TIERS).map((tier) => ({
        name: tier,
        stack: 'tier',
        color: tierColor(tier, t),
        data: d.tier_mix.map((q) => q.tiers[tier]?.[mixBy] ?? 0),
      })),
    });
  }, [d, t, mixBy]);

  const monthlyOpt = useMemo(() => {
    if (!d?.monthly.length) return null;
    return cartesian(t, {
      x: d.monthly.map((m) => monthLabel(m.month)),
      format: 'inr',
      series: [
        { name: 'Distributor purchase (BlueOrigin)', data: d.monthly.map((m) => m.offline), color: t.series[0] },
      ],
    });
  }, [d, t]);

  const moveCell = (from: string, to: string) => d?.movement.cells.find((c) => c.from === from && c.to === to)?.retailers ?? 0;
  const moveRows = ['Not listed', ...TIERS];
  const maxMove = Math.max(1, ...(d?.movement.cells.filter((c) => c.from !== c.to).map((c) => c.retailers) ?? [1]));

  if (s.error && !s.data)
    return (
      <div>
        <PageHeader title="BlueOrigin (Offline)" />
        <Card>
          <ErrorState error={s.error} onRetry={() => s.refetch()} />
        </Card>
      </div>
    );

  return (
    <div>
      <PageHeader
        title="BlueOrigin (Offline)"
        subtitle="What distributors sold to each retailer (BlueOrigin sheets) and retailer tiers, on TechnoDirect's regions, RSMs, ASMs and distributors"
        meta={s.data?.meta}
      />

      {d && !d.available && (
        <Card>
          <div className="p-6 text-sm text-ink2">No BlueOrigin data has been loaded yet. It is imported from the quarterly sheets (FY27_qtr2.csv …) on the next refresh.</div>
        </Card>
      )}

      {w && (
        <div className="mb-4 flex items-start gap-2 rounded-lg border border-line bg-sunken/40 px-3 py-2 text-xs text-ink2">
          <IconInfo size={14} className="mt-0.5 shrink-0 text-muted" />
          <span>
            {w.shifted ? (
              <>
                The selected period is after the latest BlueOrigin data, so the latest quarter is shown: <b className="text-ink">{w.label}</b>.{' '}
              </>
            ) : (
              <>
                Showing <b className="text-ink">{w.label}</b>
                {w.clipped ? ' (the period runs past the BlueOrigin data, so it stops at its last month)' : ''}.{' '}
              </>
            )}
            BlueOrigin data runs {monthLabel(w.data_from)} to {monthLabel(w.data_until)}. Tiers are the distributor sheets' "New Tier" for {w.tier_quarter}.
          </span>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <MiniStat
          label="Distributor purchase"
          value={inr(k?.purchase)}
          sub={
            k && w?.prev_label ? (
              <span className="inline-flex items-center gap-1">
                <Delta value={k.delta_pct} suffix="" /> vs {w.prev_label}
              </span>
            ) : undefined
          }
        />
        <MiniStat label="Buying retailers" value={num(k?.active)} sub={k ? `of ${num(k.retailers)} in BlueOrigin` : undefined} />
        <MiniStat
          label={`Tiered retailers (${w?.tier_quarter ?? ''})`}
          value={num(k?.tiered)}
          sub={k ? `Platinum ${num(k.tiers.Platinum)} · Gold ${num(k.tiers.Gold)}` : undefined}
        />
        <MiniStat label="Avg purchase per buying retailer" value={inr(k?.active ? k.purchase / k.active : null)} sub={w ? `in ${w.label}` : undefined} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-5">
        <ChartCard
          className="xl:col-span-3"
          title="Tier mix by quarter"
          subtitle={mixBy === 'retailers' ? 'Tiered retailers per quarter (sheet "New Tier"); Untiered left out' : 'Quarter purchase by tier, Untiered included'}
          actions={
            <Segmented
              size="xs"
              value={mixBy}
              onChange={setMixBy}
              options={[
                { value: 'retailers', label: 'Retailers' },
                { value: 'purchase', label: 'Purchase' },
              ]}
            />
          }
          option={mixOpt}
          loading={s.isLoading}
          table={
            d
              ? {
                  columns: ['Quarter', ...TIERS],
                  rows: d.tier_mix.map((q) => [q.label, ...TIERS.map((tr) => (mixBy === 'purchase' ? inr(q.tiers[tr]?.purchase) : num(q.tiers[tr]?.retailers)))]),
                }
              : undefined
          }
        />
        <Card className="xl:col-span-2" title={`Tiers in ${w?.tier_quarter ?? '…'}`} subtitle={`Purchase in ${w?.label ?? 'the period'}`}>
          <div className="overflow-x-auto px-4 pb-4">
            <table className="w-full text-sm tabular">
              <thead>
                <tr className="border-b border-line text-xs text-muted">
                  <th className="py-2 pr-2 text-left font-medium">Tier</th>
                  <th className="px-2 py-2 text-right font-medium">Retailers</th>
                  <th className="px-2 py-2 text-right font-medium">Purchase</th>
                  <th className="py-2 pl-2 text-right font-medium">Avg</th>
                </tr>
              </thead>
              <tbody>
                {(d?.by_tier ?? []).map((r) => (
                  <tr key={r.tier} className="border-t border-line/60">
                    <td className="py-1.5 pr-2">
                      <TierChip tier={r.tier} />
                    </td>
                    <td className="px-2 py-1.5 text-right">{num(r.tier === 'Untiered' ? r.active : r.retailers)}</td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-right font-semibold text-ink">{inr(r.purchase)}</td>
                    <td className="whitespace-nowrap py-1.5 pl-2 text-right text-ink2">{inr(r.avg_purchase)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-2xs text-muted">Untiered counts only retailers who bought in the period. Avg = purchase per buying retailer.</p>
          </div>
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-5">
        <Card
          className="xl:col-span-2"
          title="Tier movement"
          subtitle={d?.movement.from_quarter ? `${d.movement.from_quarter} → ${d.movement.to_quarter} · rows = before, columns = after` : 'Needs two quarters'}
        >
          {d?.movement.from_quarter && (
            <div className="px-4 pb-4">
              <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink2">
                <span>
                  <b className="text-good">{num(d.movement.upgraded)}</b> moved up
                </span>
                <span>
                  <b className="text-bad">{num(d.movement.downgraded)}</b> moved down
                </span>
                <span>
                  <b className="text-ink">{num(d.movement.new)}</b> new in the sheet
                </span>
                <span>
                  <b className="text-ink">{num(d.movement.dropped)}</b> missing from the latest sheet
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs tabular">
                  <thead>
                    <tr className="text-muted">
                      <th className="py-1 pr-2 text-left font-medium">Before ↓ / After →</th>
                      {moveRows.map((c) => (
                        <th key={c} className="px-1 py-1 text-right font-medium">
                          {c === 'Not listed' ? 'Gone' : c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {moveRows.map((r) => (
                      <tr key={r} className="border-t border-line/60">
                        <td className="py-1 pr-2 text-ink2">{r === 'Not listed' ? 'New' : r}</td>
                        {moveRows.map((c) => {
                          const n = moveCell(r, c);
                          const ri = moveRows.indexOf(r);
                          const ci = moveRows.indexOf(c);
                          const tone = r === c ? '' : r === 'Not listed' || c === 'Not listed' ? '' : ci < ri ? 'text-good' : 'text-bad';
                          return (
                            <td
                              key={c}
                              className={cx('px-1 py-1 text-right', tone, r === c && 'font-semibold text-ink')}
                              style={r !== c && n ? { background: `color-mix(in srgb, ${t.ordinal[3]} ${Math.round((n / maxMove) * 28)}%, transparent)` } : undefined}
                            >
                              {n ? num(n) : <span className="text-muted">·</span>}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-2xs text-muted">Green = moved to a higher tier, red = lower. "Gone" = in the earlier sheet but not in the latest one.</p>
            </div>
          )}
        </Card>
        <ChartCard
          className="xl:col-span-3"
          title="Distributor purchase by month"
          subtitle="Last 12 BlueOrigin months"
          option={monthlyOpt}
          loading={s.isLoading}
          table={
            d
              ? {
                  columns: ['Month', 'Distributor purchase'],
                  rows: d.monthly.map((m) => [monthLabel(m.month), inr(m.offline)]),
                }
              : undefined
          }
        />
      </div>

      <Card
        className="mt-4"
        title="By hierarchy"
        subtitle={`${w?.label ?? ''} · click a row to filter to it and go one level down · tiers as of ${w?.tier_quarter ?? ''}`}
        actions={<Segmented size="xs" value={group} onChange={setGroup} options={GROUPS} />}
      >
        <DataTable
          rows={h.data?.data.rows}
          loading={h.isLoading}
          error={h.error}
          onRetry={() => h.refetch()}
          rowKey={(r) => `${group}-${r.id ?? 'none'}`}
          exportName={`blueorigin_by_${group}`}
          exportPath="/blueorigin/hierarchy/"
          exportParams={{ group_by: group }}
          initialSort={{ key: 'purchase', dir: 'desc' }}
          pageSize={25}
          dense
          onRowClick={(r) => {
            if (r.id === null || group === 'distributor') return;
            update({ [group]: [String(r.id)] });
            setGroup(NEXT[group]);
          }}
          footer={
            h.data?.data.total ? (
              <tfoot>
                <tr className="border-t-2 border-line font-semibold text-ink">
                  <td className="px-3 py-2">Total</td>
                  <td className="px-3 py-2 text-right">{inr(h.data.data.total.purchase)}</td>
                  <td className="px-3 py-2 text-right" />
                  <td className="px-3 py-2 text-right">{num(h.data.data.total.active)}</td>
                  {TIERED.map((tr) => (
                    <td key={tr} className="px-3 py-2 text-right">
                      {num(h.data!.data.total.tiers[tr])}
                    </td>
                  ))}
                </tr>
              </tfoot>
            ) : undefined
          }
          columns={[
            {
              key: 'name',
              header: GROUPS.find((g) => g.value === group)?.label,
              render: (r) => (
                <span className={cx('font-medium', r.id === null && 'text-warn')}>
                  {r.name}
                  {r.offline_only && <span className="ml-1.5 text-2xs font-normal text-muted">offline only</span>}
                </span>
              ),
            },
            { key: 'purchase', header: 'Distributor purchase', align: 'right', render: (r) => <span className="whitespace-nowrap font-semibold">{inr(r.purchase)}</span> },
            {
              key: 'delta_pct',
              header: `vs ${w?.prev_label ?? 'previous'}`,
              align: 'right',
              value: (r) => r.delta_pct,
              render: (r) => <Delta value={r.delta_pct} suffix="" className="justify-end" />,
            },
            { key: 'active', header: 'Buying', align: 'right', render: (r) => num(r.active) },
            ...TIERED.map((tr) => ({
              key: `tier_${tr}`,
              header: tr,
              align: 'right' as const,
              value: (r: BoHierarchy['rows'][number]) => r.tiers[tr],
              render: (r: BoHierarchy['rows'][number]) => (r.tiers[tr] ? num(r.tiers[tr]) : <span className="text-muted">·</span>),
            })),
          ]}
        />
      </Card>

      <Card className="mt-4" title="Offline retailers" subtitle={`Purchase in ${w?.label ?? 'the period'} · tier history = the last 4 quarterly sheets`}>
        <DataTable
          rows={list.data?.results}
          loading={list.isLoading}
          fetching={list.isFetching}
          error={list.error}
          onRetry={() => list.refetch()}
          rowKey={(r) => r.id}
          exportName="blueorigin_retailers"
          exportPath="/blueorigin/retailers/"
          exportParams={listParams}
          server={{ count: list.data?.count ?? 0, page, pageSize: 50, onPage: setPage, ordering, onOrdering: setOrdering }}
          dense
          toolbar={
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1">
                <IconSearch size={13} className="text-muted" />
                <input
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value);
                    setPage(1);
                  }}
                  placeholder="Search name, BO ID, phone…"
                  className="w-52 bg-transparent text-xs outline-none placeholder:text-muted"
                  aria-label="Search offline retailers"
                />
              </div>
            </div>
          }
          columns={[
            {
              key: 'name',
              sortField: 'name',
              header: 'Retailer',
              render: (r) => (
                <div>
                  <div className="font-medium text-ink">{r.retailer}</div>
                  <div className="text-2xs text-muted">
                    {r.bo_id}
                    {r.phone ? ` · ${r.phone}` : ''}
                  </div>
                </div>
              ),
            },
            {
              key: 'distributor',
              header: 'Distributor',
              render: (r) => (
                <span>
                  {r.distributor ?? '–'}
                  {r.offline_only_distributor && <span className="ml-1 text-2xs text-muted">offline only</span>}
                </span>
              ),
            },
            {
              key: 'asm',
              header: 'ASM / RSM',
              sortable: false,
              render: (r) =>
                r.asm ? (
                  <span>
                    {r.asm}
                    {r.rsm ? <span className="text-xs text-muted"> · {r.rsm}</span> : null}
                  </span>
                ) : (
                  <span className="text-warn">Unassigned</span>
                ),
            },
            { key: 'state', header: 'Place', sortable: false, render: (r) => [r.district, r.state].filter(Boolean).join(', ') || '–' },
            { key: 'tier', header: 'Tier', render: (r) => <TierChip tier={r.tier} /> },
            {
              key: 'tier_history',
              header: 'History',
              sortable: false,
              noExport: true,
              render: (r) => (
                <span className="inline-flex gap-1" title={r.tier_history.map((x) => `${x.quarter}: ${x.tier}`).join('\n')}>
                  {r.tier_history.map((x) => (
                    <span key={x.quarter} className="h-2.5 w-4 rounded-sm" style={{ background: tierColor(x.tier, t) }} aria-label={`${x.quarter}: ${x.tier}`} />
                  ))}
                </span>
              ),
            },
            { key: 'purchase', header: 'Purchase', align: 'right', render: (r) => <span className="whitespace-nowrap font-semibold">{inr(r.purchase)}</span> },
          ]}
        />
      </Card>
    </div>
  );
}
