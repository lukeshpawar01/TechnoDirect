import { useMemo } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAnalytics } from '@/api/hooks';
import type { KpiKey, Overview as OverviewData } from '@/api/types';
import { cartesian } from '@/charts/builders';
import { useChartTokens } from '@/charts/EChart';
import { STATUS } from '@/charts/palette';
import { ChartCard } from '@/components/ChartCard';
import { MomTrend } from '@/components/MomTrend';
import { KpiTile } from '@/components/KpiTile';
import { PageHeader } from '@/components/PageHeader';
import { TargetBullet } from '@/components/TargetBullet';
import { TodayStrip } from '@/components/TodayStrip';
import { Badge, Card, Delta, EmptyState, ErrorState, Meter, Skeleton } from '@/components/ui';
import { IconCheck, IconChevron } from '@/components/Icons';
import { date, inr, monthLabel, num, pct, asPct } from '@/lib/format';
import { linkWithFilters } from '@/lib/filters';

const KPI_DEFS: { key: KpiKey; label: string; fmt: (n: number | null | undefined) => string; money?: boolean; to: string; extra?: Record<string, string> }[] = [
  { key: 'sales', label: 'Sales', fmt: (n) => inr(n), money: true, to: '/orders' },
  { key: 'orders', label: 'Orders', fmt: (n) => num(n), to: '/orders' },
  { key: 'aov', label: 'Avg order value', fmt: (n) => inr(n), money: true, to: '/orders' },
  { key: 'units_per_order', label: 'Units per order', fmt: (n) => num(n, 1), to: '/products' },
  { key: 'realisation_per_unit', label: 'Realisation per unit', fmt: (n) => inr(n, { compact: false }), money: true, to: '/products' },
  { key: 'active_retailers', label: 'Active retailers', fmt: (n) => num(n), to: '/retailers' },
  { key: 'new_retailers', label: 'New retailers', fmt: (n) => num(n), to: '/retailers', extra: { segment: 'new' } },
  { key: 'repeat_retailers', label: 'Repeat retailers', fmt: (n) => num(n), to: '/retailers', extra: { segment: 'repeat' } },
  { key: 'active_distributors', label: 'Active distributors', fmt: (n) => num(n), to: '/distributors' },
];

const FUNNEL_ORDER = ['received', 'confirmed', 'shipped', 'delivered', 'cancelled'];

export default function Overview() {
  const q = useAnalytics<OverviewData>('/overview/');
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const t = useChartTokens();
  const d = q.data?.data;
  const meta = q.data?.meta;
  const basis = meta?.sales_basis;
  const dim = q.isFetching && q.isPlaceholderData;

  const dailyOpt = useMemo(() => {
    if (!d?.daily_trend?.length) return null;
    const hasTarget = d.daily_trend.some((x) => x.cum_target !== null);
    return cartesian(t, {
      x: d.daily_trend.map((x) => date(x.date, 'DD MMM')),
      format: 'inr',
      series: [
        { name: 'Cumulative sales', type: 'line', data: d.daily_trend.map((x) => x.cum_sales), color: t.series[0], area: true, endLabel: true },
        ...(hasTarget ? [{ name: 'Cumulative target', type: 'line' as const, data: d.daily_trend.map((x) => x.cum_target), color: t.target, ghost: true, dashed: true, endLabel: true }] : []),
      ],
    });
  }, [d, t]);

  const monthlyOpt = useMemo(() => {
    if (!d?.monthly?.length) return null;
    const hasPy = d.monthly.some((m) => m.prev_year_sales !== null);
    return cartesian(t, {
      x: d.monthly.map((m) => monthLabel(m.month)),
      format: 'inr',
      series: [
        { name: 'Sales', type: 'bar', data: d.monthly.map((m) => m.sales), color: t.series[0] },
        ...(hasPy ? [{ name: 'Same month last year', type: 'line' as const, data: d.monthly.map((m) => m.prev_year_sales), color: t.target, ghost: true }] : []),
      ],
    });
  }, [d, t]);

  const funnelRows = useMemo(() => {
    if (!d?.order_funnel) return [];
    return [...d.order_funnel].sort((a, b) => FUNNEL_ORDER.indexOf(a.status) - FUNNEL_ORDER.indexOf(b.status));
  }, [d]);

  const funnelOpt = useMemo(() => {
    if (!funnelRows.length) return null;
    return cartesian(t, {
      x: funnelRows.map((r) => r.status[0].toUpperCase() + r.status.slice(1)),
      horizontal: true,
      format: 'num',
      legend: false,
      showBarLabels: true,
      series: [
        {
          name: 'Orders',
          data: funnelRows.map((r) => r.count),
          // ordered stages → ordinal ramp; cancelled is a status (critical), labelled in the axis
          colors: funnelRows.map((r, i) => (r.status === 'cancelled' ? STATUS.critical : t.ordinal[Math.min(i + 1, t.ordinal.length - 1)])),
        },
      ],
    });
  }, [funnelRows, t]);

  return (
    <div>
      <PageHeader title="Executive Overview" meta={meta} />
      <TodayStrip />

      {q.error && !q.data ? (
        <Card>
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        </Card>
      ) : (
        <div className={dim ? 'opacity-70 transition-opacity' : 'transition-opacity'}>
          {/* KPI tiles */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5 2xl:grid-cols-9">
            {KPI_DEFS.map((k) => (
              <KpiTile
                key={k.key}
                label={k.label}
                kpi={d?.kpis?.[k.key]}
                format={k.fmt}
                loading={q.isLoading}
                basis={k.money ? basis : undefined}
                to={linkWithFilters(k.to, sp, k.extra)}
              />
            ))}
          </div>

          <div className="mt-4">
            <MomTrend />
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-5">
            <Card title="Month target" subtitle="Required vs current daily run-rate and month-end projection" className="xl:col-span-2">
              {q.isLoading ? (
                <Skeleton className="h-40" />
              ) : d?.target ? (
                <TargetBullet t={d.target} basis={basis} />
              ) : (
                <EmptyState title="No target set for this scope" hint="Add one in Admin → Targets." height={160} />
              )}
            </Card>
            <ChartCard
              className="xl:col-span-3"
              title="Daily cumulative sales vs target"
              subtitle={basis ? `${basis} · cumulative within period` : 'Cumulative within period'}
              option={dailyOpt}
              loading={q.isLoading}
              height={260}
              table={
                d
                  ? {
                      columns: ['Date', 'Sales', 'Orders', 'Cumulative', 'Cum. target'],
                      rows: d.daily_trend.map((x) => [date(x.date), inr(x.sales), num(x.orders), inr(x.cum_sales), x.cum_target === null ? '–' : inr(x.cum_target)]),
                    }
                  : undefined
              }
            />
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
            <ChartCard
              className="xl:col-span-2"
              title="Monthly sales"
              subtitle={`Last 21 months (current month to date), prior-year same month overlaid · click a bar for that month's orders${basis ? ` · ${basis}` : ''}`}
              option={monthlyOpt}
              loading={q.isLoading}
              height={280}
              onClick={(p) => {
                const m = d?.monthly[p.dataIndex];
                if (!m) return;
                const from = `${m.month}-01`;
                const end = new Date(Number(m.month.slice(0, 4)), Number(m.month.slice(5, 7)), 0);
                const to = `${m.month}-${String(end.getDate()).padStart(2, '0')}`;
                nav(linkWithFilters('/orders', sp, { preset: 'custom', date_from: from, date_to: to }));
              }}
              table={
                d
                  ? {
                      columns: ['Month', 'Sales', 'Orders', 'AOV', 'Active retailers', 'Prior year'],
                      rows: d.monthly.map((m) => [monthLabel(m.month), inr(m.sales), num(m.orders), inr(m.aov), num(m.active_retailers), m.prev_year_sales === null ? '–' : inr(m.prev_year_sales)]),
                    }
                  : undefined
              }
            />
            <ChartCard
              title="Order status"
              subtitle="Orders in period by current status"
              option={funnelOpt}
              loading={q.isLoading}
              height={280}
              onClick={(p) => {
                const r = funnelRows[p.dataIndex];
                if (r) nav(linkWithFilters('/orders', sp, { order_status: r.status }));
              }}
              table={{ columns: ['Status', 'Orders', 'Value'], rows: funnelRows.map((r) => [r.status, num(r.count), inr(r.value)]) }}
            />
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-4">
            <Card title="Concentration" subtitle="Dependency on a few accounts">
              {q.isLoading ? (
                <Skeleton className="h-32" />
              ) : d?.concentration ? (
                <ul className="space-y-3">
                  {[
                    { label: 'Top 3 distributors', v: asPct(d.concentration.top3_distributor_share), to: '/distributors' },
                    { label: `Top state${d.concentration.top_state ? ` · ${d.concentration.top_state.name}` : ''}`, v: asPct(d.concentration.top_state?.share), to: '/territory?group_by=state' },
                    { label: 'Top 10 retailers', v: asPct(d.concentration.top10_retailer_share), to: '/retailers' },
                  ].map((c) => (
                    <li key={c.label}>
                      <Link to={linkWithFilters(c.to, sp)} className="group block">
                        <div className="flex justify-between text-xs">
                          <span className="text-ink2 group-hover:text-ink">{c.label}</span>
                          <span className="font-semibold">{pct(c.v)} of sales</span>
                        </div>
                        <div className="mt-1">
                          <Meter value={c.v} tone={c.v !== null && c.v >= 50 ? 'warn' : 'brand'} />
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState height={120} />
              )}
            </Card>

            <Card title="Top distributors" subtitle="Share of sales · growth vs compare period" actions={<Link to={linkWithFilters('/distributors', sp)} className="text-xs text-ink2 hover:text-ink">All →</Link>}>
              {q.isLoading ? (
                <Skeleton className="h-32" />
              ) : d?.top_distributors?.length ? (
                <ul className="space-y-2.5">
                  {d.top_distributors.slice(0, 6).map((x) => (
                    <li key={x.id}>
                      <Link to={linkWithFilters(`/distributors/${x.id}`, sp)} className="group block">
                        <div className="flex items-baseline justify-between gap-2 text-xs">
                          <span className="truncate font-medium group-hover:underline">{x.name}</span>
                          <span className="shrink-0 tabular">
                            {inr(x.sales)} <span className="text-muted">· {pct(asPct(x.share), 0)}</span>
                          </span>
                        </div>
                        <div className="mt-1 flex items-center gap-2">
                          <Meter value={asPct(x.share)} />
                          <Delta value={x.growth_pct} suffix="" className="w-14 shrink-0 justify-end" />
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState height={120} />
              )}
            </Card>

            <Card title="Top states" subtitle="Share of sales" actions={<Link to={linkWithFilters('/territory', sp, { group_by: 'state' })} className="text-xs text-ink2 hover:text-ink">Territory →</Link>}>
              {q.isLoading ? (
                <Skeleton className="h-32" />
              ) : d?.top_states?.length ? (
                <ul className="space-y-2.5">
                  {d.top_states.slice(0, 6).map((x) => (
                    <li key={x.id}>
                      <Link to={linkWithFilters('/territory', sp, { state: String(x.id), group_by: 'state' })} className="group block">
                        <div className="flex items-baseline justify-between text-xs">
                          <span className="truncate font-medium group-hover:underline">{x.name}</span>
                          <span className="tabular">
                            {inr(x.sales)} <span className="text-muted">· {pct(asPct(x.share), 0)}</span>
                          </span>
                        </div>
                        <div className="mt-1">
                          <Meter value={asPct(x.share)} />
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState height={120} />
              )}
            </Card>

            <Card title="Exceptions" subtitle="Needs attention — click to open the filtered list">
              {q.isLoading ? (
                <Skeleton className="h-32" />
              ) : d?.exceptions?.length ? (
                <ul className="divide-y divide-line">
                  {[...d.exceptions]
                    .sort((a, b) => ['high', 'medium', 'low'].indexOf(a.severity) - ['high', 'medium', 'low'].indexOf(b.severity))
                    .map((e) => (
                      <li key={e.code}>
                        <Link to={linkWithFilters(e.link, sp)} className="group flex items-start gap-2 py-2">
                          <Badge tone={e.severity === 'high' ? 'bad' : e.severity === 'medium' ? 'warn' : 'neutral'} icon>
                            {e.severity}
                          </Badge>
                          <span className="min-w-0 flex-1 text-xs text-ink2 group-hover:text-ink">
                            <span className="font-semibold text-ink">{num(e.count)}</span> {e.message}
                          </span>
                          <IconChevron size={14} className="mt-0.5 shrink-0 text-muted" />
                        </Link>
                      </li>
                    ))}
                </ul>
              ) : (
                <div className="flex items-center gap-2 py-6 text-xs text-good">
                  <IconCheck size={14} /> No exceptions right now.
                </div>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
