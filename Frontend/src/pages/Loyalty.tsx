import { useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAnalytics } from '@/api/hooks';
import type { Loyalty as LoyaltyData, LoyaltyMember } from '@/api/types';
import { cartesian } from '@/charts/builders';
import { useChartTokens } from '@/charts/EChart';
import { ChartCard } from '@/components/ChartCard';
import { DataTable } from '@/components/DataTable';
import { MiniStat } from '@/components/KpiTile';
import { PageHeader } from '@/components/PageHeader';
import { Card, ErrorState } from '@/components/ui';
import { linkWithFilters, useFilters } from '@/lib/filters';
import { date, monthLabel, num, pct } from '@/lib/format';

export default function Loyalty() {
  const q = useAnalytics<LoyaltyData>('/loyalty/');
  const t = useChartTokens();
  const nav = useNavigate();
  const [searchParams] = useSearchParams();
  const { apiParams } = useFilters();
  const d = q.data?.data;
  const per = d?.period;
  const life = d?.lifetime;
  const range = d?.data_range;
  const periodEmpty = !!d && (per?.events ?? 0) === 0 && (life?.events ?? 0) > 0;

  const monthlyOpt = useMemo(() => {
    const m = d?.monthly ?? [];
    if (!m.length) return null;
    return cartesian(t, {
      x: m.map((r) => monthLabel(r.month)),
      format: 'num',
      series: [
        { name: 'Points issued', data: m.map((r) => r.issued), color: t.series[0] },
        { name: 'Points redeemed', data: m.map((r) => r.redeemed), color: t.series[1] },
      ],
    });
  }, [d, t]);

  const membersOpt = useMemo(() => {
    const m = d?.monthly ?? [];
    if (!m.length) return null;
    return cartesian(t, {
      x: m.map((r) => monthLabel(r.month)),
      format: 'num',
      series: [
        { name: 'New members', data: m.map((r) => r.new_members), color: t.series[0] },
        { name: 'Retailers earning points', data: m.map((r) => r.earners), color: t.series[2] },
      ],
    });
  }, [d, t]);

  const eventOpt = useMemo(() => {
    const e = d?.by_event ?? [];
    if (!e.length) return null;
    return cartesian(t, {
      x: e.map((r) => r.event),
      format: 'num',
      horizontal: true,
      legend: false,
      showBarLabels: true,
      series: [{ name: 'Points', data: e.map((r) => r.points) }],
    });
  }, [d, t]);

  const stateOpt = useMemo(() => {
    const s = (d?.by_state ?? []).slice(0, 12);
    if (!s.length) return null;
    return cartesian(t, {
      x: s.map((r) => r.state),
      format: 'num',
      horizontal: true,
      legend: false,
      series: [{ name: 'Points issued', data: s.map((r) => r.issued) }],
    });
  }, [d, t]);

  if (q.error && !q.data)
    return (
      <div>
        <PageHeader title="Loyalty Points" />
        <Card>
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        </Card>
      </div>
    );

  const rangeText = range?.first ? `Loyalty data covers ${date(range.first)} – ${date(range.last)}` : 'No loyalty data loaded yet';

  return (
    <div>
      <PageHeader title="Loyalty Points" subtitle="Points issued to retailers, redemptions and the most engaged members" meta={q.data?.meta} showBasis={false} />

      {periodEmpty && (
        <div className="mb-3 rounded-md border border-warn/30 bg-warn-bg px-3 py-2 text-xs text-ink2">
          No loyalty events in the selected period. {rangeText}; change the period to see them. Lifetime figures and trends below include all data.
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <MiniStat label="Points issued (period)" value={num(per?.points_issued)} sub={`${num(life?.points_issued)} lifetime`} />
        <MiniStat label="Points redeemed (period)" value={num(per?.points_redeemed)} sub={`${num(life?.points_redeemed)} lifetime`} />
        <MiniStat label="Redemption rate" value={pct(per?.redemption_rate)} sub={`${pct(life?.redemption_rate)} lifetime`} tone={(life?.redemption_rate ?? 0) < 5 && (life?.points_issued ?? 0) > 0 ? 'warn' : undefined} />
        <MiniStat label="Outstanding points" value={num(life?.net_points)} sub="Issued − redeemed, lifetime" />
        <MiniStat label="Members (period)" value={num(per?.members)} sub={`${num(per?.new_members)} new · ${num(life?.members)} lifetime`} />
        <MiniStat label="Retailers earning" value={num(per?.earning_retailers)} sub={`${num(per?.redeeming_retailers)} redeemed`} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <ChartCard
          title="Points issued vs redeemed"
          subtitle={`By month · ${rangeText.toLowerCase()}`}
          option={monthlyOpt}
          loading={q.isLoading}
          empty={!d?.monthly.length}
          table={d ? { columns: ['Month', 'Issued', 'Redeemed'], rows: d.monthly.map((r) => [monthLabel(r.month), r.issued, r.redeemed]) } : undefined}
        />
        <ChartCard
          title="New members and earners"
          subtitle="Welcome bonuses vs retailers earning points on orders"
          option={membersOpt}
          loading={q.isLoading}
          empty={!d?.monthly.length}
          table={d ? { columns: ['Month', 'New members', 'Earning retailers'], rows: d.monthly.map((r) => [monthLabel(r.month), r.new_members, r.earners]) } : undefined}
        />
        <ChartCard
          title="Points by event type"
          subtitle="Selected period"
          option={eventOpt}
          loading={q.isLoading}
          empty={!d?.by_event.length}
          height={220}
          table={d ? { columns: ['Event', 'Events', 'Points'], rows: d.by_event.map((r) => [r.event, r.events, r.points]) } : undefined}
        />
        <ChartCard
          title="Points issued by state"
          subtitle="Selected period · top 12"
          option={stateOpt}
          loading={q.isLoading}
          empty={!d?.by_state.length}
          height={220}
          table={d ? { columns: ['State', 'Members', 'Issued', 'Redeemed'], rows: d.by_state.map((r) => [r.state, r.members, r.issued, r.redeemed]) } : undefined}
        />
      </div>

      <div className="mt-4">
        <Card title="Top loyalty members" subtitle="Lifetime points, top 100 retailers by points earned">
          <DataTable<LoyaltyMember>
            rows={d?.top_members}
            loading={q.isLoading}
            fetching={q.isFetching}
            error={q.error}
            onRetry={() => q.refetch()}
            rowKey={(r) => r.retailer_id}
            onRowClick={(r) => nav(linkWithFilters(`/retailers/${r.retailer_id}`, searchParams))}
            exportName="loyalty_top_members"
            exportPath="/loyalty/"
            exportParams={apiParams}
            initialSort={{ key: 'earned', dir: 'desc' }}
            pageSize={25}
            columns={[
              { key: 'retailer', header: 'Retailer', render: (r) => <div><div className="font-medium">{r.retailer}</div>{r.owner && r.owner.toLowerCase() !== r.retailer.toLowerCase() && <div className="text-2xs text-muted">{r.owner}</div>}</div>, value: (r) => r.retailer },
              { key: 'state', header: 'State', render: (r) => r.state ?? '–' },
              { key: 'distributor', header: 'Distributor', render: (r) => r.distributor ?? '–' },
              { key: 'earned', header: 'Earned', align: 'right', render: (r) => num(r.earned) },
              { key: 'redeemed', header: 'Redeemed', align: 'right', render: (r) => num(r.redeemed) },
              { key: 'balance', header: 'Balance', align: 'right', render: (r) => <span className="font-semibold">{num(r.balance)}</span> },
              { key: 'orders', header: 'Orders with points', align: 'right', render: (r) => num(r.orders) },
              { key: 'last_event', header: 'Last activity', render: (r) => date(r.last_event), value: (r) => r.last_event },
            ]}
          />
        </Card>
      </div>
    </div>
  );
}
