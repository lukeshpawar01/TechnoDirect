import { useMemo, useState } from 'react';
import type { EChartsOption } from 'echarts';
import type { Growth, GrowthMonth } from '@/api/types';
import { cartesian, waterfall, type ValueFormat } from '@/charts/builders';
import { EChart, useChartTokens } from '@/charts/EChart';
import { STATUS } from '@/charts/palette';
import { ChartCard } from './ChartCard';
import { MiniStat } from './KpiTile';
import { Card, Segmented, cx } from './ui';
import { inr, monthLabel, num, pct, signedPct } from '@/lib/format';

/**
 * Growth journey — the board-review story (TD_DataDeck slides 28-35, 59-60) computed live:
 * since-launch headline, monthly sales with MoM / YoY, quarters & FYs, the basket small multiples,
 * cumulative sales with milestones, the growth decomposition and the like-for-like bridge.
 */
type Range = '12' | '24' | 'all';
const GROUP = 'growth-multiples';
const xl = (r: GrowthMonth) => (r.is_partial ? `${monthLabel(r.month)} · MTD` : monthLabel(r.month));
const fmtDate = (s: string) => new Date(s).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: '2-digit', timeZone: 'Asia/Kolkata' });

export function GrowthJourney({ d, loading }: { d: Growth | undefined; loading?: boolean }) {
  const t = useChartTokens();
  const [range, setRange] = useState<Range>('24');

  const all = useMemo(() => {
    const m = d?.monthly ?? [];
    const first = m.findIndex((r) => r.sales > 0);
    return first < 0 ? [] : m.slice(first);
  }, [d]);
  const rows = useMemo(() => (range === 'all' ? all : all.slice(-Number(range))), [all, range]);
  const x = rows.map(xl);

  const salesOpt = useMemo(
    () =>
      rows.length
        ? cartesian(t, {
            x,
            format: 'inr',
            legend: false,
            series: [{ name: 'Sales', data: rows.map((r) => r.sales), colors: rows.map((r) => (r.is_partial ? t.deemph : t.series[0])) }],
          })
        : null,
    [rows, t], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const growthBars = (vals: (number | null)[], name: string) =>
    cartesian(t, { x, format: 'pct', legend: false, series: [{ name, data: vals, colors: vals.map((v) => ((v ?? 0) >= 0 ? t.series[0] : STATUS.critical)) }] });
  const momOpt = useMemo(() => (rows.some((r) => r.mom_pct !== null) ? growthBars(rows.map((r) => r.mom_pct), 'MoM growth') : null), [rows, t]); // eslint-disable-line react-hooks/exhaustive-deps
  const yoyRows = rows.filter((r) => r.prev_year_sales);
  const yoyOpt = useMemo(
    () => (yoyRows.length ? cartesian(t, { x: yoyRows.map(xl), format: 'pct', legend: false, series: [{ name: 'YoY growth', data: yoyRows.map((r) => r.yoy_pct), colors: yoyRows.map((r) => ((r.yoy_pct ?? 0) >= 0 ? t.series[0] : STATUS.critical)) }] }) : null),
    [yoyRows, t], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const tyLyOpt = useMemo(
    () =>
      yoyRows.length
        ? cartesian(t, {
            x: yoyRows.map(xl),
            format: 'inr',
            series: [
              { name: 'This year', data: yoyRows.map((r) => r.sales), color: t.series[0] },
              { name: 'Same month, prior year', data: yoyRows.map((r) => r.prev_year_sales), color: t.deemph },
            ],
          })
        : null,
    [yoyRows, t], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const fyOpt = useMemo(
    () =>
      d?.fy.length
        ? cartesian(t, { x: d.fy.map((y) => (y.is_partial ? `${y.label} (YTD)` : y.label)), format: 'inr', legend: false, showBarLabels: true, series: [{ name: 'FY sales', data: d.fy.map((y) => y.sales), colors: d.fy.map((y) => (y.is_partial ? t.deemph : t.series[0])) }] })
        : null,
    [d, t],
  );

  // small multiples: one measure each, shared months, linked crosshair
  const multiples: { title: string; fmt: ValueFormat; v: (r: GrowthMonth) => number | null }[] = [
    { title: 'Orders', fmt: 'num', v: (r) => r.orders },
    { title: 'Pieces sold', fmt: 'num', v: (r) => r.units },
    { title: 'Average order value', fmt: 'inr', v: (r) => r.aov },
    { title: 'Units per order', fmt: 'dec', v: (r) => r.units_per_order },
    { title: 'Realisation per piece', fmt: 'inr', v: (r) => r.realisation_per_unit },
    { title: 'Sales per active retailer', fmt: 'inr', v: (r) => r.sales_per_retailer },
    { title: 'Distinct articles per order', fmt: 'dec', v: (r) => r.articles_per_order },
    { title: 'Articles sold in the month', fmt: 'num', v: (r) => r.articles_sold },
  ];

  const cumOpt = useMemo(() => {
    if (!all.length) return null;
    const opt = cartesian(t, { x: all.map(xl), format: 'inr', legend: false, series: [{ name: 'Cumulative sales', type: 'line', area: true, data: all.map((r) => r.cum_sales), endLabel: true }] }) as EChartsOption & { series: { markPoint?: unknown }[] };
    const idx = new Map(all.map((r, i) => [r.month, i]));
    const byMonth = { has: (m: string) => idx.has(m), get: (m: string) => all[idx.get(m)!] };
    opt.series[0].markPoint = {
      symbol: 'circle',
      symbolSize: 9,
      itemStyle: { color: t.surface, borderColor: t.series[1], borderWidth: 2 },
      label: { show: false },
      data: (d?.milestones ?? []).filter((m) => byMonth.has(m.month)).map((m) => ({ name: m.label, coord: [idx.get(m.month)!, byMonth.get(m.month).cum_sales] })),
      tooltip: { formatter: (p: { name: string }) => p.name },
    };
    return opt;
  }, [all, d, t]);

  const dec = d?.decomposition;
  const decOpt = useMemo(() => {
    if (!dec?.available) return null;
    return waterfall(t, [
      { label: `Same period LY`, value: dec.prev_sales, total: true },
      ...dec.factors.map((f) => ({ label: f.label, value: f.contribution ?? 0 })),
      { label: 'This period', value: dec.cur_sales, total: true },
    ]);
  }, [dec, t]);

  const b = d?.bridge;
  const bridgeOpt = useMemo(() => {
    if (!b || (!b.prev_total && !b.cur_total)) return null;
    return waterfall(t, [
      { label: 'Same 6 months LY', value: b.prev_total, total: true },
      { label: `Lapsed (${num(b.lapsed.retailers)})`, value: -b.lapsed.sales },
      { label: `Like-for-like (${num(b.like_for_like.retailers)})`, value: b.like_for_like.change },
      { label: `New to window (${num(b.new.retailers)})`, value: b.new.sales },
      { label: 'Last 6 months', value: b.cur_total, total: true },
    ]);
  }, [b, t]);

  const h = d?.headline;
  return (
    <div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <MiniStat label="Cumulative sales" value={inr(h?.cum_sales)} sub={h ? `Since ${monthLabel(h.since.slice(0, 7))}` : undefined} />
        <MiniStat label="Orders" value={num(h?.cum_orders)} sub="Cart-level, since launch" />
        <MiniStat label="Retailers transacted" value={num(h?.retailers)} />
        <MiniStat label="Distributors" value={num(h?.distributors)} sub="With at least one order" />
        <MiniStat label="Sales from repeat retailers" value={pct(h?.repeat_share_last_month)} sub={h?.last_month ? monthLabel(h.last_month) : undefined} />
        <MiniStat label="Record month" value={h?.record_month ? monthLabel(h.record_month) : '–'} sub={h?.record_month ? inr(all.find((r) => r.month === h.record_month)?.sales) : undefined} />
      </div>

      <ChartCard
        className="mt-4"
        title="Monthly sales"
        subtitle="Grey = month in progress"
        option={salesOpt}
        loading={loading}
        height={260}
        actions={<Segmented value={range} onChange={setRange} size="xs" options={[{ value: '12', label: '12 m' }, { value: '24', label: '24 m' }, { value: 'all', label: 'Since launch' }]} />}
        table={{ columns: ['Month', 'Sales', 'Orders', 'MoM', 'YoY'], rows: rows.map((r) => [xl(r), inr(r.sales), num(r.orders), signedPct(r.mom_pct), signedPct(r.yoy_pct)]) }}
      />
      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ChartCard title="Month-on-month growth" subtitle="Sales vs the previous month" option={momOpt} loading={loading} height={220} empty={!momOpt} emptyHint="Needs two months of sales" />
        <ChartCard title="Year-on-year growth" subtitle="Sales vs the same month last year" option={yoyOpt} loading={loading} height={220} empty={!yoyOpt} emptyHint="Available once a month has a prior-year month to compare" />
        <ChartCard title="This year vs same month last year" option={tyLyOpt} loading={loading} height={220} empty={!tyLyOpt} emptyHint="Available once a month has a prior-year month to compare" />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="Quarterly performance" subtitle="Financial-year quarters · growth vs the previous quarter">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted">
                <tr className="border-b border-line">
                  {['Quarter', 'Sales', 'QoQ', 'Orders', 'AOV', 'Active retailers'].map((c, i) => (
                    <th key={c} className={cx('py-2 pr-3 font-medium', i ? 'text-right' : '')}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(d?.quarters ?? []).map((q) => (
                  <tr key={q.label} className="border-b border-line/60 last:border-0">
                    <td className="py-1.5 pr-3">{q.label}{q.is_partial && <span className="ml-1 text-2xs text-muted">(to date)</span>}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums font-medium">{inr(q.sales)}</td>
                    <td className={cx('py-1.5 pr-3 text-right tabular-nums', (q.growth_pct ?? 0) < 0 ? 'text-bad' : 'text-good')}>{q.growth_pct === null ? '—' : signedPct(q.growth_pct)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{num(q.orders)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{inr(q.aov)}</td>
                    <td className="py-1.5 text-right tabular-nums">{num(q.active_retailers)}</td>
                  </tr>
                ))}
                {!d?.quarters.length && (
                  <tr><td colSpan={6} className="py-6 text-center text-xs text-muted">{loading ? 'Loading…' : 'No sales yet'}</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-2xs text-muted">A quarter still running is compared with the whole previous quarter, so its growth reads low until it closes.</p>
        </Card>
        <ChartCard title="Sales by financial year" subtitle="April–March · grey = year to date" option={fyOpt} loading={loading} height={260}
          table={d ? { columns: ['FY', 'Sales', 'Growth', 'Orders', 'Active retailers'], rows: d.fy.map((y) => [y.label, inr(y.sales), signedPct(y.growth_pct), num(y.orders), num(y.active_retailers)]) } : undefined} />
      </div>

      <Card className="mt-4" title="What makes up each month" subtitle="Order count, basket size and price, one measure per panel · hover one to read all">
        <div className="grid grid-cols-1 gap-x-6 gap-y-2 md:grid-cols-2 xl:grid-cols-4">
          {multiples.map((m) => {
            const vals = rows.map(m.v);
            const opt = rows.length ? cartesian(t, { x, format: m.fmt, legend: false, series: [{ name: m.title, type: 'line', data: vals, area: true, endLabel: true }] }) : null;
            return (
              <div key={m.title}>
                <div className="text-xs font-medium text-ink2">{m.title}</div>
                {opt ? <EChart option={opt} height={140} group={GROUP} ariaLabel={`${m.title} per month`} /> : <div className="h-[140px]" />}
              </div>
            );
          })}
        </div>
      </Card>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ChartCard className="xl:col-span-2" title="Cumulative sales since launch" subtitle="Dots mark milestones — hover for the detail" option={cumOpt} loading={loading} height={280}
          table={d ? { columns: ['Month', 'Milestone'], rows: d.milestones.map((m) => [monthLabel(m.month), m.label]) } : undefined} />
        <Card title="Milestones">
          <ol className="space-y-2">
            {(d?.milestones ?? []).map((m, i) => (
              <li key={i} className="flex gap-3 text-sm">
                <span className="w-16 shrink-0 text-xs tabular-nums text-muted">{monthLabel(m.month)}</span>
                <span className={cx(m.kind === 'record' ? 'font-semibold text-ink' : 'text-ink2')}>{m.label}</span>
              </li>
            ))}
            {!d?.milestones.length && <li className="text-xs text-muted">{loading ? 'Loading…' : 'None yet'}</li>}
          </ol>
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard
          title="What drove growth vs last year"
          subtitle={dec ? `${fmtDate(dec.period.start)}–${fmtDate(dec.period.end)} vs ${fmtDate(dec.compare.start)}–${fmtDate(dec.compare.end)} · sales = active retailers × orders per retailer × AOV` : undefined}
          option={decOpt}
          loading={loading}
          height={280}
          empty={!decOpt}
          emptyHint="Needs sales in the same period last year — pick a period with a prior-year base"
          footer={
            dec?.available ? (
              <table className="mt-2 w-full text-xs">
                <thead className="text-left text-muted">
                  <tr><th className="py-1 font-medium">Driver</th><th className="text-right font-medium">Last year</th><th className="text-right font-medium">This period</th><th className="text-right font-medium">Change</th><th className="text-right font-medium">Share of growth</th></tr>
                </thead>
                <tbody>
                  {[...dec.factors, ...dec.aov_factors].map((f, i) => (
                    <tr key={f.key} className={cx('border-t border-line/60', i >= dec.factors.length && 'text-ink2')}>
                      <td className="py-1">{i >= dec.factors.length ? `↳ ${f.label}` : f.label}</td>
                      <td className="text-right tabular-nums">{f.key.includes('aov') || f.key.includes('realisation') ? inr(f.prev) : num(f.prev, f.key === 'active_retailers' ? 0 : 2)}</td>
                      <td className="text-right tabular-nums">{f.key.includes('aov') || f.key.includes('realisation') ? inr(f.cur) : num(f.cur, f.key === 'active_retailers' ? 0 : 2)}</td>
                      <td className="text-right tabular-nums">{signedPct(f.change_pct)}</td>
                      <td className="text-right tabular-nums font-medium">{pct(f.share_pct, 0)}{i >= dec.factors.length ? ' of AOV' : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : undefined
          }
        />
        <ChartCard
          title="Like-for-like bridge"
          subtitle={b ? `${fmtDate(b.window.start)}–${fmtDate(b.window.end)} vs the same window a year earlier` : undefined}
          option={bridgeOpt}
          loading={loading}
          height={280}
          empty={!bridgeOpt}
          footer={
            b ? (
              <p className="mt-2 text-xs text-ink2">
                Like-for-like: {num(b.like_for_like.retailers)} retailers active in both windows, {inr(b.like_for_like.prev)} → {inr(b.like_for_like.cur)} ({signedPct(b.like_for_like.change_pct)}). Lapsed retailers bought last year but not this window; new includes first orders and win-backs.
              </p>
            ) : undefined
          }
        />
      </div>
    </div>
  );
}
