import { useMemo } from 'react';
import type { DelayGroup, LeadStage, OrderFlow } from '@/api/types';
import { cartesian } from '@/charts/builders';
import { useChartTokens } from '@/charts/EChart';
import { STATUS } from '@/charts/palette';
import { ChartCard } from '@/components/ChartCard';
import { DataTable } from '@/components/DataTable';
import { MiniStat } from '@/components/KpiTile';
import type { OrdersDrillSpec } from '@/components/OrdersDrill';
import { Card, cx } from '@/components/ui';
import { date, num, pct, titleCase } from '@/lib/format';

type Drill = (spec: OrdersDrillSpec) => void;

export const days = (v: number | null | undefined) => (v === null || v === undefined ? '–' : `${Math.round(v * 10) / 10} ${v === 1 ? 'day' : 'days'}`);
const dayTick = (iso: string, weekly: boolean) => (weekly ? `w/c ${date(iso, 'DD MMM')}` : date(iso, 'DD MMM'));

const EVENTS = [
  { key: 'received', label: 'Received', verb: 'placed' },
  { key: 'shipped', label: 'Shipped', verb: 'shipped' },
  { key: 'delivered', label: 'Delivered', verb: 'delivered' },
] as const;

/**
 * Daily order flow: orders received (placed), shipped and delivered each day of the period. Shipped / delivered
 * count the day they happened, so they include orders placed before the period.
 */
export function DailyFlowCard({ d, loading, periodLabel, onDrill }: { d: OrderFlow | undefined; loading: boolean; periodLabel: string; onDrill: Drill }) {
  const t = useChartTokens();
  const weekly = d?.flow.granularity === 'week';
  const pts = d?.flow.points ?? [];
  const opt = useMemo(
    () =>
      pts.length
        ? cartesian(t, {
            x: pts.map((p) => dayTick(p.date, weekly)),
            series: [
              { name: 'Received', data: pts.map((p) => p.received) },
              { name: 'Shipped', type: 'line', data: pts.map((p) => p.shipped) },
              { name: 'Delivered', type: 'line', data: pts.map((p) => p.delivered), dashed: true },
            ],
          })
        : null,
    [pts, t, weekly],
  );
  const last = d?.latest_day?.today;
  const prev = d?.latest_day?.previous;
  const delta = (k: 'received' | 'shipped' | 'delivered') => (last && prev ? last[k] - prev[k] : null);
  const open = (iso: string, ev: (typeof EVENTS)[number]) =>
    onDrill({
      title: `${ev.label} ${weekly ? `in the week of ${date(iso, 'DD MMM')}` : `on ${date(iso, 'DD MMM YYYY')}`}`,
      subtitle: `Orders ${ev.verb} ${weekly ? 'that week' : 'that day'} · cancelled excluded`,
      params: { flow_day: iso, flow_event: ev.key, ...(weekly ? { flow_week: '1' } : {}) },
    });

  return (
    <ChartCard
      title={weekly ? 'Weekly order flow' : 'Daily order flow'}
      subtitle={
        last ? (
          <span>
            Latest data, {date(last.date, 'DD MMM')}:{' '}
            {EVENTS.map((ev, i) => {
              const dv = delta(ev.key);
              return (
                <span key={ev.key}>
                  {i ? <span className="text-muted"> · </span> : null}
                  <button type="button" className="font-medium text-ink hover:underline" onClick={() => open(last.date, ev)}>
                    {num(last[ev.key])} {ev.label.toLowerCase()}
                  </button>
                  {dv ? <span className={cx('ml-1 text-2xs', dv > 0 ? 'text-good' : 'text-muted')}>{dv > 0 ? '+' : ''}{dv} vs day before</span> : null}
                </span>
              );
            })}
            <span className="text-muted"> · click a point to list its orders</span>
          </span>
        ) : (
          `Orders placed, shipped and delivered ${weekly ? 'per week' : 'per day'} · ${periodLabel} · click a point to list them`
        )
      }
      option={opt}
      loading={loading}
      height={240}
      onClick={(p) => {
        const pt = pts[p.dataIndex];
        const ev = EVENTS.find((e) => e.label === p.seriesName);
        if (pt && ev) open(pt.date, ev);
      }}
      table={{ columns: [weekly ? 'Week of' : 'Day', 'Received', 'Shipped', 'Delivered'], rows: pts.map((p) => [date(p.date, 'DD MMM YYYY'), num(p.received), num(p.shipped), num(p.delivered)]) }}
    />
  );
}

function leadOption(t: ReturnType<typeof useChartTokens>, s: LeadStage) {
  const SHORT: Record<string, string> = { '0': 'Same day', '1': '1d', '2': '2d', '3': '3d', '4_6': '4–6d', '7p': '7d+' };
  const rows = [...s.buckets.map((b) => ({ label: SHORT[b.key] ?? b.label, n: b.orders, late: b.late, seven: b.key === '7p' })), { label: 'Waiting', n: s.waiting_late, late: true, seven: true }];
  const opt = cartesian(t, {
    x: rows.map((r) => r.label),
    legend: false,
    showBarLabels: true,
    series: [{ name: 'Orders', data: rows.map((r) => r.n), colors: rows.map((r) => (r.seven ? STATUS.critical : r.late ? STATUS.serious : t.series[0])) }],
  });
  // seven short labels always fit: show every one (the default skips alternate labels)
  const xa = opt.xAxis as { axisLabel?: Record<string, unknown> } | undefined;
  if (xa && !Array.isArray(xa)) xa.axisLabel = { ...(xa.axisLabel ?? {}), interval: 0, hideOverlap: false };
  return opt;
}

function LeadCard({ stage, s, sla, loading, periodLabel, onDrill }: { stage: 'dispatch' | 'transit'; s: LeadStage | undefined; sla: number; loading: boolean; periodLabel: string; onDrill: Drill }) {
  const t = useChartTokens();
  const opt = useMemo(() => (s && (s.done || s.waiting_late) ? leadOption(t, s) : null), [s, t]);
  const what = stage === 'dispatch' ? 'Placed → shipped' : 'Shipped → delivered';
  return (
    <ChartCard
      title={stage === 'dispatch' ? 'Days to dispatch' : 'Days in transit'}
      subtitle={
        s
          ? `${what} · ${pct(s.within_sla_pct, 0)} within the ${sla}-day SLA · median ${days(s.median_days)} · red = past SLA · click a bar`
          : what
      }
      option={opt}
      loading={loading}
      height={220}
      onClick={(p) => {
        if (!s) return;
        const b = s.buckets[p.dataIndex];
        if (b) {
          onDrill({ title: `${what}: ${b.label.toLowerCase()}`, subtitle: `${num(b.orders)} orders placed in ${periodLabel}${b.late ? ` · past the ${sla}-day SLA` : ''}`, params: { lead: stage, lead_bucket: b.key } });
        } else if (s.waiting_late) {
          onDrill({
            title: stage === 'dispatch' ? `Not shipped after ${sla}+ days` : `In transit for ${sla}+ days`,
            subtitle: `${num(s.waiting_late)} orders still waiting, past the SLA (placed in the last 30 days)`,
            params: { delay: stage, waiting: '1' },
          });
        }
      }}
      table={s ? { columns: ['Days', 'Orders'], rows: [...s.buckets.map((b) => [b.label, num(b.orders)]), ['Still waiting (past SLA)', num(s.waiting_late)]] } : undefined}
    />
  );
}

const share = (v: number | null) => (v ? pct(v, 0) : '–');

/**
 * Where orders get delayed: lead-time distributions against the SLA, plain-language findings and a hotspot table
 * ranked by how many late orders each group causes.
 */
export function DelaySection({
  d,
  loading,
  periodLabel,
  groupBy,
  onGroupBy,
  onDrill,
}: {
  d: OrderFlow | undefined;
  loading: boolean;
  periodLabel: string;
  groupBy: string;
  onGroupBy: (v: string) => void;
  onDrill: Drill;
}) {
  const sla = d?.sla ?? { dispatch_days: 2, transit_days: 3 };
  const hs = d?.hotspots;
  const minN = hs?.min_orders ?? 10;
  const groupLabel = (g: DelayGroup) => (hs?.group_by === 'platform' || hs?.group_by === 'payment_mode' ? titleCase(g.label) : g.label);
  const openGroup = (g: DelayGroup, delay: 'any' | 'dispatch' | 'transit' = 'any') =>
    onDrill({
      title: `${groupLabel(g)} · ${delay === 'any' ? 'late orders' : delay === 'dispatch' ? 'shipped late' : 'arrived late'}`,
      subtitle: `${hs?.label}: ${groupLabel(g)} · ${num(delay === 'any' ? g.late_orders : delay === 'dispatch' ? g.late_dispatch : g.late_transit)} of ${num(g.orders)} orders placed in ${periodLabel} · late = shipped after ${sla.dispatch_days} days or delivered ${sla.transit_days}+ days after shipping (including those still waiting)`,
      params: { delay, group_by: hs?.group_by ?? groupBy, group: g.key },
    });
  const lateLink = (g: DelayGroup, stage: 'dispatch' | 'transit') => {
    const n = stage === 'dispatch' ? g.late_dispatch : g.late_transit;
    const p = stage === 'dispatch' ? g.late_dispatch_pct : g.late_transit_pct;
    if (!n) return <span className="text-muted">0</span>;
    return (
      <button
        type="button"
        className={cx('tabular hover:underline', (p ?? 0) >= 25 && g.orders >= minN ? 'font-semibold text-bad' : 'text-ink')}
        onClick={(e) => {
          e.stopPropagation();
          openGroup(g, stage);
        }}
      >
        {pct(p, 0)} <span className="text-2xs font-normal text-muted">({num(n)})</span>
      </button>
    );
  };

  return (
    <section className="mt-6">
      <div className="mb-3">
        <h2 className="text-base font-semibold text-ink">Where orders get delayed</h2>
        <p className="text-xs text-ink2">
          Orders placed in {periodLabel}, cancelled excluded · SLA: shipped within {sla.dispatch_days} days of placing, delivered within {sla.transit_days} days of shipping · orders still waiting past the SLA count as late
          {d ? ` · data up to ${date(d.as_of, 'DD MMM YYYY')}` : ''}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MiniStat
          label={`Shipped within ${sla.dispatch_days} days`}
          value={pct(d?.dispatch.within_sla_pct, 0)}
          tone={d?.dispatch.within_sla_pct != null ? (d.dispatch.within_sla_pct >= 90 ? 'good' : d.dispatch.within_sla_pct < 80 ? 'bad' : 'warn') : undefined}
          sub={d ? `median ${days(d.dispatch.median_days)} · ${num(d.dispatch.waiting_late)} still not shipped past SLA` : undefined}
          onClick={d?.dispatch.waiting_late ? () => onDrill({ title: `Not shipped after ${sla.dispatch_days}+ days`, subtitle: 'Still waiting, past the dispatch SLA (placed in the last 30 days)', params: { delay: 'dispatch', waiting: '1' } }) : undefined}
        />
        <MiniStat
          label={`Delivered within ${sla.transit_days} days of shipping`}
          value={pct(d?.transit.within_sla_pct, 0)}
          tone={d?.transit.within_sla_pct != null ? (d.transit.within_sla_pct >= 90 ? 'good' : d.transit.within_sla_pct < 80 ? 'bad' : 'warn') : undefined}
          sub={d ? `median ${days(d.transit.median_days)} · ${num(d.transit.waiting_late)} in transit past SLA` : undefined}
          onClick={d?.transit.waiting_late ? () => onDrill({ title: `In transit for ${sla.transit_days}+ days`, subtitle: 'Shipped, not delivered, past the transit SLA', params: { delay: 'transit', waiting: '1' } }) : undefined}
        />
        <MiniStat label="Placed → delivered (median)" value={days(d?.end_to_end_median_days)} sub={d ? `${num(d.orders)} orders placed in the period` : undefined} />
        <MiniStat
          label="Late orders"
          value={num(d?.late_orders)}
          tone={d?.late_orders ? 'bad' : undefined}
          sub={d?.orders ? `${pct((d.late_orders / d.orders) * 100, 0)} of orders late at dispatch or in transit · click to list` : undefined}
          onClick={d?.late_orders ? () => onDrill({ title: 'Late orders', subtitle: `Shipped or delivered past the SLA, or still waiting past it · placed in ${periodLabel}`, params: { delay: 'any' } }) : undefined}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <LeadCard stage="dispatch" s={d?.dispatch} sla={sla.dispatch_days} loading={loading} periodLabel={periodLabel} onDrill={onDrill} />
        <LeadCard stage="transit" s={d?.transit} sla={sla.transit_days} loading={loading} periodLabel={periodLabel} onDrill={onDrill} />
        <Card title="What stands out" subtitle="Worst first · click a finding to list its orders">
          {loading && !d ? (
            <p className="text-xs text-muted">Loading…</p>
          ) : d?.insights.length ? (
            <ul className="space-y-2">
              {d.insights.map((i, k) => (
                <li key={k}>
                  <button
                    type="button"
                    disabled={!i.params}
                    onClick={() => i.params && onDrill({ title: i.title, subtitle: i.text, params: i.params })}
                    className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-xs text-ink hover:bg-sunken disabled:hover:bg-transparent"
                  >
                    <span className={cx('mt-1 h-2 w-2 shrink-0 rounded-full', i.tone === 'bad' ? 'bg-bad' : i.tone === 'warn' ? 'bg-warn' : 'bg-good')} aria-hidden />
                    <span>{i.text}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted">No orders in this period.</p>
          )}
        </Card>
      </div>

      <Card
        className="mt-4"
        title="Delay hotspots"
        subtitle={`Ranked by late orders caused · groups under ${minN} orders are greyed (too few to judge) · click a row to list its late orders`}
        actions={
          <label className="flex items-center gap-1.5 text-xs text-ink2">
            Group by
            <select className="rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink" value={groupBy} onChange={(e) => onGroupBy(e.target.value)}>
              {(d?.dimensions ?? [{ key: groupBy, label: groupBy }]).map((o) => (
                <option key={o.key} value={o.key}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
        }
      >
        <DataTable
          rows={hs?.rows}
          loading={loading}
          dense
          rowKey={(r) => r.key}
          onRowClick={(r) => r.late_orders && openGroup(r)}
          exportName={`delay_hotspots_${groupBy}`}
          emptyTitle="No orders in this period"
          columns={[
            { key: 'label', header: hs?.label ?? 'Group', render: (r) => <span className={cx('font-medium', r.orders < minN && 'text-muted')}>{groupLabel(r)}</span>, value: (r) => groupLabel(r) },
            { key: 'orders', header: 'Orders', align: 'right', render: (r) => num(r.orders) },
            { key: 'median_dispatch_days', header: 'Median to ship', align: 'right', render: (r) => days(r.median_dispatch_days) },
            { key: 'late_dispatch_pct', header: `Shipped late (>${sla.dispatch_days}d)`, align: 'right', render: (r) => lateLink(r, 'dispatch'), value: (r) => r.late_dispatch_pct },
            { key: 'median_transit_days', header: 'Median in transit', align: 'right', render: (r) => days(r.median_transit_days) },
            { key: 'late_transit_pct', header: `Arrived late (>${sla.transit_days}d)`, align: 'right', render: (r) => lateLink(r, 'transit'), value: (r) => r.late_transit_pct },
            { key: 'late_orders', header: 'Late orders', align: 'right', render: (r) => <span className={cx(r.late_orders && r.orders >= minN ? 'font-semibold' : 'text-muted')}>{num(r.late_orders)}</span> },
            { key: 'late_dispatch_share', header: 'Share of late dispatch', align: 'right', render: (r) => share(r.late_dispatch_share) },
            { key: 'late_transit_share', header: 'Share of late transit', align: 'right', render: (r) => share(r.late_transit_share) },
          ]}
        />
      </Card>
    </section>
  );
}
