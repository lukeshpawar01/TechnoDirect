import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import type { EChartsOption } from 'echarts';
import { inr, num, pct } from '@/lib/format';
import { baseOption, useChartTokens } from '@/charts/EChart';
import { STATUS } from '@/charts/palette';
import { ChartCard } from '@/components/ChartCard';
import { Card, cx, type Tone } from '@/components/ui';
import { SectionTitle, Verdict } from './shared';
import type { ExecDecision, ExecInsight, InsightArea, MbrNotes, Scorecard } from './types';

/**
 * MBR page 1 - the executive summary for founders / CEO / directors.
 * The month in one line, five numbers, what drove the change, the conclusions, and the decisions to take.
 * Everything else in the MBR is the evidence behind this page.
 */
export const AREA: Record<InsightArea, { label: string; page?: string }> = {
  sales: { label: 'Sales', page: 'performance' },
  drivers: { label: 'Drivers', page: 'performance' },
  retailers: { label: 'Retailers', page: 'performance' },
  territory: { label: 'Territory', page: 'performance' },
  product: { label: 'Product', page: 'performance' },
  operations: { label: 'Operations', page: 'performance' },
  goal: { label: 'Goal', page: 'growth' },
  adoption: { label: 'Adoption', page: 'growth' },
  growth: { label: 'Growth plan', page: 'growth' },
  tech: { label: 'Tech', page: 'tech' },
  risk: { label: 'Risk', page: 'developments' },
};
const DOT = { good: 'bg-good', bad: 'bg-bad', warn: 'bg-warn', neutral: 'bg-muted' };
const signed = (v: number) => `${v >= 0 ? '+' : '−'}${inr(Math.abs(v))}`;

/** Decisions that come from the team's own MBR lines (pages 3-5), next to the ones computed from data. */
function noteDecisions(s: Scorecard, notes?: MbrNotes): ExecDecision[] {
  if (!notes) return [];
  const out: ExecDecision[] = [];
  const growth = notes.items.filter((i) => i.section === 'growth' && i.kind === 'action' && i.status !== 'dropped');
  const planned = growth.reduce((a, i) => a + (i.expected_impact ?? 0), 0);
  const gap = s.path.gap_sales;
  if (gap > 0 && planned < gap) {
    out.push({
      area: 'growth', owner: 'Business Head', title: growth.length ? 'Fill the growth plan' : 'Write the growth plan',
      value: gap - planned, value_label: 'monthly gap with no action against it',
      reason: growth.length
        ? `${growth.length} growth action${growth.length === 1 ? '' : 's'} cover ${inr(planned)} of the ${inr(gap)}/month gap to the goal (${pct((planned / gap) * 100, 0)}).`
        : `No growth actions are listed for the ${inr(gap)}/month gap to the goal. Add 3–5 actions with an expected ₹ impact.`,
      link: 'growth',
    });
  }
  const t = notes.tech_summary;
  if (t.overdue || t.blocked) {
    const blocked = notes.items.filter((i) => i.section === 'tech' && (i.status === 'blocked' || (i.blocker && i.status !== 'done' && i.status !== 'dropped')));
    out.push({
      area: 'tech', owner: 'Tech', title: `Unblock tech: ${t.blocked} blocked, ${t.overdue} overdue`, value: null, value_label: '',
      reason: blocked.length ? blocked.slice(0, 2).map((i) => `${i.title}${i.blocker ? ` (${i.blocker})` : ''}`).join('; ') + '.' : 'Overdue items have passed their go-live date.',
      link: 'tech',
    });
  }
  const risks = notes.items.filter((i) => i.section === 'other' && i.kind === 'risk');
  if (risks.length) {
    out.push({
      area: 'risk', owner: 'Leadership', title: `${risks.length} open risk${risks.length === 1 ? '' : 's'} to decide on`, value: null, value_label: '',
      reason: risks.slice(0, 2).map((r) => r.title).join('; ') + '.', link: 'developments',
    });
  }
  return out;
}

function noteInsights(notes?: MbrNotes): ExecInsight[] {
  if (!notes) return [];
  const t = notes.tech_summary;
  const out: ExecInsight[] = [];
  if (t.total) {
    out.push({
      area: 'tech', tone: t.adherence_pct === null ? 'neutral' : t.adherence_pct >= 80 ? 'good' : t.adherence_pct >= 60 ? 'warn' : 'bad', title: 'Tech',
      text: `${t.done} of ${t.total} tech items live${t.adherence_pct !== null ? `, ${t.adherence_pct.toFixed(0)}% on time` : ''}${t.blocked ? `; ${t.blocked} blocked` : ''}.`,
    });
  }
  return out;
}

export function Summary({ s, notes }: { s: Scorecard; notes?: MbrNotes }) {
  const x = s.summary;
  const h = s.headline;
  const rows = useMemo(() => Object.fromEntries(s.rows.map((r) => [r.key, r])), [s.rows]);
  const insights = [...x.insights, ...noteInsights(notes)];
  const decisions = [...x.decisions, ...noteDecisions(s, notes)];
  const best = s.partial ? h.projected_pct : h.achievement_pct;
  const tone: Tone = best === null ? 'neutral' : best >= 100 ? 'good' : best >= 90 ? 'warn' : 'bad';
  const m = x.momentum;
  const pace: Tone = m.avg_growth_3m_pct === null || m.needed_pct === null ? 'neutral' : m.avg_growth_3m_pct >= m.needed_pct ? 'good' : 'bad';

  return (
    <>
      <Verdict
        tone={tone}
        label={h.target ? `${s.partial ? 'Projected' : 'Closed at'} ${pct(best, 0)} of target` : 'No sales target set'}
      >
        {insights[0]?.text}{' '}
        {m.needed_pct !== null && m.avg_growth_3m_pct !== null && (
          <>
            For {inr(s.path.goal)} a month by {s.path.goal_by_label}, TD has to grow <b className="font-semibold">{m.needed_pct.toFixed(1)}% a month</b>; it has
            been growing <b className={cx('font-semibold', pace === 'bad' && 'text-bad')}>{m.avg_growth_3m_pct.toFixed(1)}%</b>.
          </>
        )}{' '}
        {decisions.length > 0 && <>{decisions.length} decisions below.</>}
      </Verdict>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <Tile label={s.partial ? 'Sales, projected' : 'Sales'} value={inr(s.partial ? h.projected : h.sales)}
          sub={h.target ? `${pct(best, 0)} of ${inr(h.target)} target` : `${signed(x.bridge.change)} vs ${s.compare.prev}`} tone={tone} />
        <Tile label="Growth" value={`${(h.mom_pct ?? 0) >= 0 ? '+' : ''}${(h.mom_pct ?? 0).toFixed(1)}%`}
          sub={`MoM like for like${h.yoy_pct !== null ? ` · ${h.yoy_pct >= 0 ? '+' : ''}${h.yoy_pct.toFixed(0)}% YoY` : ''}`} tone={(h.mom_pct ?? 0) >= 0 ? 'good' : 'bad'} />
        <Tile label="Transacting retailers" value={num(rows.active_retailers?.value)}
          sub={`${num(rows.new_retailers?.value)} new · retention ${pct(rows.retention_pct?.value, 0)}`} />
        <Tile label="Spend per retailer" value={inr(rows.spend_per_retailer?.value)}
          sub={`was ${inr(rows.spend_per_retailer?.prev)}`} tone={(rows.spend_per_retailer?.value ?? 0) >= (rows.spend_per_retailer?.prev ?? 0) ? 'good' : 'warn'} />
        <Tile label="Pace to the goal" value={m.avg_growth_3m_pct === null ? '–' : `${m.avg_growth_3m_pct.toFixed(1)}%`}
          sub={`a month, vs ${m.needed_pct === null ? '–' : `${m.needed_pct.toFixed(1)}%`} needed`} tone={pace} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-5">
        <Bridge s={s} className="xl:col-span-2" />
        <Card className="xl:col-span-3" title="What the month tells us" subtitle="One line per area, worst news not hidden">
          <ul className="divide-y divide-line/60">
            {insights.map((i) => (
              <li key={i.area + i.text} className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-3 py-2">
                <span className="flex items-center gap-1.5 text-xs font-medium text-ink2">
                  <span className={cx('h-2 w-2 shrink-0 rounded-full', DOT[i.tone])} aria-hidden />
                  {AREA[i.area].label}
                </span>
                <span className="text-sm leading-snug text-ink">{i.text}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <SectionTitle n="1.1" title="Decisions for leadership" sub="Each with the ₹ at stake and the team that owns it; the pages after this one are the evidence" />
      <DecisionTable items={decisions} month={s.month} />
    </>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: Tone }) {
  const cls = tone === 'good' ? 'text-good' : tone === 'bad' ? 'text-bad' : tone === 'warn' ? 'text-warn' : 'text-ink';
  return (
    <div className="card p-3.5">
      <div className="text-xs text-muted">{label}</div>
      <div className={cx('mt-0.5 text-2xl font-semibold tabular-nums', cls)}>{value}</div>
      <div className="mt-0.5 text-2xs text-muted">{sub}</div>
    </div>
  );
}

/** Last month's sales -> this month's: new retailers, repeat base, spend per retailer. */
function Bridge({ s, className }: { s: Scorecard; className?: string }) {
  const t = useChartTokens();
  const b = s.summary.bridge;
  const option = useMemo<EChartsOption>(() => {
    const base = baseOption(t);
    const names = ['Last month', ...b.steps.map((x) => x.label), 'This month'];
    let run = b.prev;
    const invisible: number[] = [b.prev * 0];
    const bars: { value: number; itemStyle: { color: string }; label: { formatter: string } }[] = [
      { value: b.prev, itemStyle: { color: t.deemph }, label: { formatter: inr(b.prev) } },
    ];
    for (const st of b.steps) {
      const lo = Math.min(run, run + st.value);
      invisible.push(lo);
      bars.push({ value: Math.abs(st.value), itemStyle: { color: st.value >= 0 ? STATUS.good : STATUS.critical }, label: { formatter: signed(st.value) } });
      run += st.value;
    }
    invisible.push(0);
    bars.push({ value: b.current, itemStyle: { color: t.series[0] }, label: { formatter: inr(b.current) } });
    return {
      ...base,
      legend: { show: false },
      grid: { left: 8, right: 8, top: 24, bottom: 8, containLabel: true },
      tooltip: {
        ...(base.tooltip as object),
        trigger: 'item',
        formatter: (p: unknown) => {
          const i = (p as { dataIndex: number }).dataIndex;
          if (i === 0) return `<b>${s.compare.prev}</b><br/>${inr(b.prev)}`;
          if (i === names.length - 1) return `<b>${s.compare.current}</b><br/>${inr(b.current)} (${signed(b.change)})`;
          const st = b.steps[i - 1];
          return `<b>${st.label}</b> ${signed(st.value)}<br/><span style="opacity:.75">${st.note}</span>`;
        },
      },
      xAxis: { type: 'category', data: names, axisLabel: { color: t.ink2, fontSize: 11, interval: 0, width: 70, overflow: 'break', lineHeight: 13 }, axisLine: { lineStyle: { color: t.axis } }, axisTick: { show: false } },
      yAxis: { type: 'value', axisLabel: { color: t.muted, fontSize: 11, formatter: (v: number) => inr(v) }, splitLine: { lineStyle: { color: t.grid } } },
      series: [
        { type: 'bar', stack: 'w', silent: true, itemStyle: { color: 'transparent' }, data: invisible, tooltip: { show: false } },
        {
          type: 'bar', stack: 'w', barMaxWidth: 42,
          itemStyle: { borderRadius: 4 },
          label: { show: true, position: 'top', color: t.ink2, fontSize: 11 },
          data: bars,
        },
      ],
    } as EChartsOption;
  }, [b, t, s.compare]);
  return (
    <ChartCard
      className={className}
      title="What drove the change"
      subtitle={`${s.compare.prev} → ${s.compare.current}: ${signed(b.change)}`}
      option={option}
      height={300}
      table={{ columns: ['Step', 'Value', 'How'], rows: [['Last month', inr(b.prev), ''], ...b.steps.map((x) => [x.label, signed(x.value), x.note]), ['This month', inr(b.current), '']] }}
      footer={<p className="text-2xs text-muted">New retailers and the repeat base are valued at last month's spend per retailer; the rest is the change in spend per retailer. The three steps add up to the change.</p>}
    />
  );
}

function DecisionTable({ items, month }: { items: ExecDecision[]; month: string }) {
  if (!items.length) return <Card><p className="text-sm text-muted">No decisions flagged this month.</p></Card>;
  return (
    <Card bodyClass="p-0">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[820px] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th className="w-10 px-4 py-2 font-medium">#</th>
              <th className="px-3 py-2 font-medium">Decision</th>
              <th className="px-3 py-2 font-medium">Owner</th>
              <th className="px-4 py-2 text-right font-medium">₹ at stake</th>
            </tr>
          </thead>
          <tbody>
            {items.map((d, i) => {
              const page = d.link && !d.link.startsWith('/') ? `/mbr/${d.link}?month=${month}` : d.link || (AREA[d.area].page ? `/mbr/${AREA[d.area].page}?month=${month}` : null);
              return (
                <tr key={d.title} className="border-b border-line/60 align-top last:border-0">
                  <td className="px-4 py-3 text-xs font-semibold tabular-nums text-muted">{i + 1}</td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded bg-sunken px-1.5 py-0.5 text-2xs font-medium text-ink2">{AREA[d.area].label}</span>
                      <span className="font-semibold text-ink">{d.title}</span>
                      {page && <Link to={page} className="text-2xs text-brand hover:underline">Evidence</Link>}
                    </div>
                    <p className="mt-1 max-w-3xl text-xs leading-relaxed text-ink2">{d.reason}</p>
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-xs text-ink2">{d.owner}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-right">
                    {d.value === null ? <span className="text-muted">–</span> : (
                      <>
                        <div className="font-semibold tabular-nums text-ink">{inr(d.value)}</div>
                        <div className="text-2xs text-muted">{d.value_label}</div>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/** A slim "so what" strip for the evidence pages: the summary lines for these areas. */
export function Takeaways({ s, areas }: { s: Scorecard; areas: InsightArea[] }) {
  const items = s.summary.insights.filter((i) => areas.includes(i.area));
  if (!items.length) return null;
  return (
    <div className="card mb-4 p-4">
      <div className="mb-2 text-xs font-medium text-muted">So what</div>
      <ul className="grid gap-x-6 gap-y-1.5 lg:grid-cols-2">
        {items.map((i) => (
          <li key={i.text} className="flex gap-2 text-sm text-ink">
            <span className={cx('mt-1.5 h-2 w-2 shrink-0 rounded-full', DOT[i.tone])} aria-hidden />
            <span><b className="font-semibold">{AREA[i.area].label}.</b> {i.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
