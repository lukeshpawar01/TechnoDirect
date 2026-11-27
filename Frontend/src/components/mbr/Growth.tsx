import { useMemo, useState } from 'react';
import { inr, monthLabel, num, pct } from '@/lib/format';
import { useChartTokens } from '@/charts/EChart';
import { cartesian } from '@/charts/builders';
import { ChartCard } from '@/components/ChartCard';
import { Badge, Card, Field, InlineError, Meter, cx } from '@/components/ui';
import { IconEdit, IconPlus } from '@/components/Icons';
import { ITEM_TONE, ItemEditor, SectionTitle, Verdict, dmy, useSaveReview } from './shared';
import type { MbrItem, MbrNotes, Scorecard } from './types';
import { SupportMatrix } from './Support';
import { GrowthDrivers } from './Drivers';


export function Growth({ s, notes }: { s: Scorecard; notes: MbrNotes }) {
  const p = s.path;
  const [edit, setEdit] = useState<{ item?: MbrItem; kind?: string; preset?: Partial<MbrItem> } | null>(null);
  const growth = notes.items.filter((i) => i.section === 'growth');
  const actions = growth.filter((i) => i.kind === 'action');
  const blockers = growth.filter((i) => i.kind === 'bottleneck');
  // the goal is shown from the Nov 2026 review on (it applies from Dec 2026); earlier reviews show no goal
  const on = p.goal_active;
  const tone = (p.goal_pct ?? 0) >= 90 ? 'good' : (p.goal_pct ?? 0) >= 60 ? 'warn' : 'bad';

  return (
    <>
      {on ? (
      <Verdict
        tone={tone}
        label={`Goal ${inr(p.goal)} every month · ${p.base_label} made ${pct(p.goal_pct, 0)} of it`}
        aside={notes.can_edit ? <GoalEditor s={s} notes={notes} /> : undefined}
      >
        {p.territory_share_pct !== null && (
          <>This territory made {pct(p.territory_share_pct, 1)} of TD's sales over the last 3 months, so its share of the {inr(p.national_goal)} goal is {inr(p.goal)}.{' '}</>
        )}
        Our aim is <b className="font-semibold">{inr(p.goal)} of sales every month</b>. {p.base_label}, the last full month, made {inr(p.base_sales)}:{' '}
        <b className="font-semibold">{inr(p.gap_sales)} short</b>
        {p.avg_goal_pct_3m !== null && <>, and the last 3 months averaged {pct(p.avg_goal_pct_3m, 0)} of the goal</>}.
        Below is the route that closes the gap, lever by lever, and the plan that delivers it.
      </Verdict>
      ) : (
        <MonthTarget s={s} />
      )}

      {!on && <TargetHistory s={s} />}

      {on && <RouteToGoal s={s} />}

      <GrowthDrivers s={s} />

      {on && (
        <div className="grid gap-4 xl:grid-cols-5">
          <PathChart s={s} className="xl:col-span-3" />
          <AdoptionMath s={s} className="xl:col-span-2" />
        </div>
      )}

      <div className={cx('mt-4 grid gap-4', on && 'xl:grid-cols-2')}>
        <AdoptionTrend s={s} />
        {on && <Scenarios s={s} />}
      </div>

      <SectionTitle n="3.1" title="Plan for next month" sub="Growth actions and the support each needs" />
      <div className="grid gap-4 xl:grid-cols-3">
        <SupportMatrix s={s} notes={notes} className="xl:col-span-3" onAdd={(preset) => setEdit({ kind: 'action', preset })} onEdit={(item) => setEdit({ item })} />
      </div>

      <ItemList
        title="Critical growth actions"
        sub="What we will do next month to raise adoption"
        items={actions}
        notes={notes}
        empty="No actions yet. Add the 3–5 actions that move adoption most."
        onAdd={() => setEdit({ kind: 'action' })}
        onEdit={(item) => setEdit({ item })}
      />
      <ItemList
        title="Bottlenecks"
        sub="What is in the way, and who has to help"
        items={blockers}
        notes={notes}
        empty="No bottlenecks recorded."
        onAdd={() => setEdit({ kind: 'bottleneck' })}
        onEdit={(item) => setEdit({ item })}
      />

      {edit && <ItemEditor notes={notes} month={s.month} section="growth" item={edit.item} kind={edit.kind} preset={edit.preset} onClose={() => setEdit(null)} />}
    </>
  );
}

/** Reviews before the ₹10 Cr goal started: the month is judged against its own sales target. */
function MonthTarget({ s }: { s: Scorecard }) {
  const h = s.headline;
  if (!h.target) {
    return (
      <Verdict tone="neutral" label={`${s.label}: no sales target set`}>
        {s.label} made <b className="font-semibold">{inr(h.sales)}</b>. What drove it, and the actions, bottlenecks and support recorded for the month, are below.
      </Verdict>
    );
  }
  const a = h.achievement_pct ?? 0;
  const diff = h.sales - h.target;
  return (
    <Verdict tone={a >= 100 ? 'good' : a >= 90 ? 'warn' : 'bad'} label={`${s.label}: ${pct(a, 0)} of target achieved`}>
      Target <b className="font-semibold">{inr(h.target)}</b>, achieved <b className="font-semibold">{inr(h.sales)}</b>:{' '}
      <b className={cx('font-semibold', diff >= 0 ? 'text-good' : 'text-bad')}>{diff >= 0 ? `+${inr(diff)} above` : `${inr(-diff)} short`}</b>.
      What drove it, and the actions, bottlenecks and support recorded for the month, are below.
    </Verdict>
  );
}

/** Target vs achieved for the months up to the reviewed one (past reviews only). */
function TargetHistory({ s }: { s: Scorecard }) {
  const rows = s.trend.filter((t) => t.month <= s.month && t.target_sales).slice(-6).reverse();
  if (!rows.length) return null;
  return (
    <Card className="mb-4" title="Target vs achieved" subtitle={`The last ${rows.length} months with a sales target, up to ${s.label}`} bodyClass="p-0">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th className="px-4 py-2 font-medium">Month</th>
              <th className="px-3 py-2 text-right font-medium">Target</th>
              <th className="px-3 py-2 text-right font-medium">Achieved</th>
              <th className="px-3 py-2 text-right font-medium">Difference</th>
              <th className="w-48 px-4 py-2 font-medium">% of target</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => {
              const tg = t.target_sales ?? 0;
              const a = tg ? (t.sales / tg) * 100 : 0;
              const d = t.sales - tg;
              const tone = a >= 100 ? 'good' : a >= 90 ? 'warn' : 'bad';
              return (
                <tr key={t.month} className={cx('border-b border-line/60 last:border-0', t.month === s.month && 'bg-brand/5')}>
                  <td className="px-4 py-2 font-medium text-ink">{monthLabel(t.month)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-ink2">{inr(tg)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-ink">{inr(t.sales)}</td>
                  <td className={cx('px-3 py-2 text-right tabular-nums font-semibold', d >= 0 ? 'text-good' : 'text-bad')}>{d >= 0 ? '+' : '−'}{inr(Math.abs(d))}</td>
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-2">
                      <div className="flex-1"><Meter value={a} tone={tone} /></div>
                      <span className="w-10 text-right text-xs tabular-nums text-ink2">{pct(a, 0)}</span>
                    </div>
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

/**
 * The approach to the monthly goal: start from the last full month and add each lever's ₹ a month, in the order they
 * are easiest to pull: win back lapsed retailers, raise spend per retailer, then activate new ones for what is left.
 * The two assumptions are adjustable in the meeting; the last lever always closes the gap.
 */
function RouteToGoal({ s }: { s: Scorecard }) {
  const p = s.path;
  const [winBack, setWinBack] = useState(50);
  const [uplift, setUplift] = useState(15);
  const S = p.spend_per_retailer;
  const A = p.active_retailers;
  const back = Math.round((p.lapsed * winBack) / 100);
  const backV = back * S;
  const upV = (A + back) * S * (uplift / 100);
  const left = Math.max(p.goal - p.base_sales - backV - upV, 0);
  const newS = S * (1 + uplift / 100);
  const newN = newS ? Math.ceil(left / newS) : 0;
  const warm = s.sales_asks?.warm_total ?? 0;
  const over = p.base_sales + backV + upV >= p.goal;
  const steps = [
    { label: `Where we are: ${p.base_label}`, value: p.base_sales, how: `${num(A)} retailers bought, ${inr(S)} each on average`, who: '', tone: 'bg-ink2/40' },
    { label: `Win back ${num(back)} lapsed retailers`, value: backV, how: `${num(p.lapsed)} bought in the 3 months before ${p.base_label} but not in it; bring back ${winBack}% with ASM calls and schemes`, who: 'ASMs + sales executives', tone: 'bg-brand/60' },
    { label: `Raise spend per retailer by ${uplift}%`, value: upV, how: `${inr(S)} → ${inr(newS)} a month: wider range per store, new launches, stock at the distributor`, who: 'Product + distributors', tone: 'bg-brand/80' },
    { label: over ? 'No new retailers needed' : `Activate ${num(newN)} new retailers every month`, value: left, how: over ? 'The first two levers already reach the goal.' : `${pct(p.ants ? (newN / p.ants) * 100 : null, 0)} of the ${num(p.ants)} KYC-done retailers who never ordered${warm ? `; start with the ${num(warm)} warm ones who already buy TechnoSport offline` : ''}`, who: 'Sales + Growth', tone: 'bg-brand' },
  ];
  let run = 0;
  return (
    <Card
      className="mb-4"
      title={`The route to ${inr(p.goal)} a month`}
      subtitle="How the gap closes, lever by lever. Change the two assumptions to test the plan; the last lever covers whatever is left."
      actions={
        <div className="flex flex-wrap items-center gap-3 text-xs text-ink2">
          <label className="flex items-center gap-1.5">Win back
            <input type="range" min={0} max={100} step={5} value={winBack} onChange={(e) => setWinBack(Number(e.target.value))} className="w-20 accent-brand" />
            <span className="w-8 tabular-nums">{winBack}%</span>
          </label>
          <label className="flex items-center gap-1.5">Spend uplift
            <input type="range" min={0} max={50} step={5} value={uplift} onChange={(e) => setUplift(Number(e.target.value))} className="w-20 accent-brand" />
            <span className="w-8 tabular-nums">{uplift}%</span>
          </label>
        </div>
      }
    >
      <ol className="space-y-3">
        {steps.map((x, i) => {
          const start = run;
          run += x.value;
          return (
            <li key={i} className="grid gap-x-4 gap-y-1 md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)_7rem]">
              <div>
                <div className="text-sm font-medium text-ink">{x.label}</div>
                {x.who && <div className="text-2xs text-muted">{x.who}</div>}
              </div>
              <div>
                <div className="relative h-4 rounded bg-line/50">
                  <div className={cx('absolute inset-y-0 rounded', x.tone)} style={{ left: `${(start / p.goal) * 100}%`, width: `${Math.min((x.value / p.goal) * 100, 100 - (start / p.goal) * 100)}%` }} />
                </div>
                <div className="mt-0.5 text-2xs text-ink2">{x.how}</div>
              </div>
              <div className="text-right text-sm font-semibold tabular-nums text-ink">{i === 0 ? inr(x.value) : `+${inr(x.value)}`}</div>
            </li>
          );
        })}
        <li className="grid gap-x-4 border-t border-line pt-2 md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)_7rem]">
          <div className="text-sm font-semibold text-ink">Every month</div>
          <div className="text-2xs text-ink2">{num(A + back + newN)} retailers buying at {inr(newS)} each. The new and won-back retailers have to keep buying every month, not once.</div>
          <div className="text-right text-sm font-semibold tabular-nums text-ink">{inr(Math.max(run, p.goal))}</div>
        </li>
      </ol>
    </Card>
  );
}

function GoalEditor({ s }: { s: Scorecard; notes?: MbrNotes }) {
  const [open, setOpen] = useState(false);
  const [goal, setGoal] = useState(String(s.path.national_goal / 1e7));
  const save = useSaveReview(s.month);
  if (!open) return <button className="btn btn-sm" onClick={() => setOpen(true)}><IconEdit size={13} /> Goal</button>;
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate({ goal_monthly_sales: Number(goal) * 1e7 }, { onSuccess: () => setOpen(false) }); }}>
      <Field label="All-TD goal, ₹ Cr every month"><input className="input w-24 tabular-nums" inputMode="decimal" value={goal} onChange={(e) => setGoal(e.target.value)} /></Field>
      <button className="btn btn-sm btn-primary" disabled={save.isPending}>Save</button>
      <button type="button" className="btn btn-sm" onClick={() => setOpen(false)}>Cancel</button>
      {save.error ? <InlineError error={save.error} /> : null}
    </form>
  );
}

function PathChart({ s, className }: { s: Scorecard; className?: string }) {
  const t = useChartTokens();
  const p = s.path;
  const option = useMemo(() => {
    const months = p.months;
    return cartesian(t, {
      x: months.map((m) => monthLabel(m.month) + (m.partial ? ' (MTD)' : '')),
      format: 'inr',
      legend: true,
      markLine: { value: p.goal, label: `Goal ${inr(p.goal)}` },
      yMax: Math.ceil((p.goal * 1.1) / 1e7) * 1e7,
      series: [
        { name: 'Sales', data: months.map((m) => m.sales), type: 'bar', stack: 'goal', color: t.series[0] },
        { name: 'Short of the goal', data: months.map((m) => (m.partial ? null : m.short)), type: 'bar', stack: 'goal', color: t.deemph },
      ],
    });
  }, [t, p]);
  const hit = p.months_at_goal;
  return (
    <ChartCard
      className={className}
      title={`Every month against the ${inr(p.goal)} goal`}
      subtitle={`Each bar is a month's sales; the grey part is how far it fell short of ${inr(p.goal)}. ${hit ? `${hit} month${hit === 1 ? '' : 's'} reached it.` : 'No month has reached it yet.'}`}
      option={option}
      height={280}
    />
  );
}

function AdoptionMath({ s, className }: { s: Scorecard; className?: string }) {
  const p = s.path;
  const steps = [
    { label: 'Sales per transacting retailer', value: inr(p.spend_per_retailer), sub: 'last 3 complete months' },
    { label: 'Transacting retailers needed', value: num(p.retailers_needed), sub: `${inr(p.goal)} ÷ ${inr(p.spend_per_retailer)}` },
    { label: 'Transacting today', value: num(p.active_retailers), sub: p.base_label },
    { label: 'Gap', value: `+${num(p.retailers_gap)}`, sub: 'more retailers ordering every month', strong: true },
  ];
  const pools = [
    { label: 'KYC done, never ordered', n: p.ants, note: p.ants_share_of_gap_pct !== null ? `activating ${pct(p.ants_share_of_gap_pct, 0)} of them closes the gap` : '' },
    { label: 'TechnoSport retailers not transacting on TD', n: p.techno_not_transacting, note: `${pct(p.techno_adoption_pct, 1)} of ${num(p.techno_universe)} buy on TD today` },
  ];
  const max = Math.max(p.retailers_gap, ...pools.map((x) => x.n), 1);
  return (
    <Card className={className} title="The adoption maths" subtitle="What the goal means in retailers, at today's spend">
      <ol className="grid grid-cols-2 gap-3">
        {steps.map((x) => (
          <li key={x.label} className={cx('rounded-md border border-line p-3', x.strong && 'border-bad/40 bg-bad-bg')}>
            <div className="text-2xs text-muted">{x.label}</div>
            <div className={cx('text-lg font-semibold tabular-nums', x.strong ? 'text-bad' : 'text-ink')}>{x.value}</div>
            <div className="text-2xs text-muted">{x.sub}</div>
          </li>
        ))}
      </ol>
      <div className="mt-4 text-xs font-semibold text-ink2">Where the extra retailers can come from</div>
      <ul className="mt-2 space-y-2">
        <li>
          <div className="flex justify-between text-xs"><span className="text-ink">Needed</span><span className="tabular-nums text-ink">{num(p.retailers_gap)}</span></div>
          <div className="mt-1 h-2 rounded-full bg-sunken"><div className="h-2 rounded-full bg-bad" style={{ width: `${(p.retailers_gap / max) * 100}%` }} /></div>
        </li>
        {pools.map((x) => (
          <li key={x.label}>
            <div className="flex justify-between gap-2 text-xs"><span className="text-ink">{x.label}</span><span className="tabular-nums text-ink">{num(x.n)}</span></div>
            <div className="mt-1 h-2 rounded-full bg-sunken"><div className="h-2 rounded-full bg-brand" style={{ width: `${(x.n / max) * 100}%` }} /></div>
            {x.note && <div className="mt-0.5 text-2xs text-muted">{x.note}</div>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function AdoptionTrend({ s }: { s: Scorecard }) {
  const t = useChartTokens();
  const p = s.path;
  const option = useMemo(
    () =>
      cartesian(t, {
        x: p.adoption_trend.map((x) => monthLabel(x.month)),
        format: 'pct',
        legend: false,
        markLine: p.goal_active && p.adoption_needed_pct ? { value: p.adoption_needed_pct, label: `Needed ${pct(p.adoption_needed_pct, 1)}` } : undefined,
        yMax: p.goal_active && p.adoption_needed_pct ? Math.ceil((p.adoption_needed_pct * 1.2) / 2) * 2 : undefined,
        series: [{ name: 'Adoption: KYC base transacting', data: p.adoption_trend.map((x) => x.adoption_pct), type: 'line', area: true, color: t.series[0] }],
      }),
    [t, p],
  );
  return (
    <ChartCard
      title="Adoption, month by month"
      subtitle="Transacting retailers as a % of all KYC-approved retailers at month end; the rule is the adoption the goal needs"
      option={option}
      height={240}
      table={{
        columns: ['Month', 'Transacting', 'KYC base', 'Adoption'],
        rows: p.adoption_trend.map((x) => [monthLabel(x.month), num(x.active_retailers), num(x.kyc_base), pct(x.adoption_pct, 1)]),
      }}
    />
  );
}

function Scenarios({ s }: { s: Scorecard }) {
  const p = s.path;
  return (
    <Card title="Retailers vs spend: ways to the goal" subtitle="Raising spend per retailer lowers how many more retailers are needed" bodyClass="p-0">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-muted">
            <th className="px-4 py-2 font-medium">Spend per retailer</th>
            <th className="px-3 py-2 text-right font-medium">Retailers needed</th>
            <th className="px-3 py-2 text-right font-medium">More than today</th>
            <th className="px-4 py-2 text-right font-medium">Adoption needed</th>
          </tr>
        </thead>
        <tbody>
          {p.scenarios.map((x) => (
            <tr key={x.spend_uplift_pct} className={cx('border-b border-line/60 last:border-0', x.spend_uplift_pct === 0 && 'bg-sunken/50')}>
              <td className="px-4 py-2 text-ink">
                {inr(x.spend)} <span className="text-xs text-muted">{x.spend_uplift_pct ? `+${x.spend_uplift_pct}%` : 'today'}</span>
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-ink">{num(x.retailers_needed)}</td>
              <td className="px-3 py-2 text-right tabular-nums text-ink2">+{num(x.extra_retailers)}</td>
              <td className="px-4 py-2 text-right tabular-nums text-ink2">{pct(x.adoption_needed_pct, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="px-4 py-2 text-2xs text-muted">Adoption = transacting retailers ÷ the {num(p.kyc_base)} KYC-approved retailers today.</p>
    </Card>
  );
}

export function ItemList({ title, sub, items, notes, empty, onAdd, onEdit }: {
  title: string; sub: string; items: MbrItem[]; notes: MbrNotes; empty: string; onAdd: () => void; onEdit: (i: MbrItem) => void;
}) {
  const order = { blocked: 0, in_progress: 1, planned: 2, done: 3, dropped: 4 } as const;
  const prio = { high: 0, medium: 1, low: 2 } as const;
  const sorted = [...items].sort((a, b) => order[a.status] - order[b.status] || prio[a.priority] - prio[b.priority] || a.sort - b.sort);
  return (
    <Card
      className="mt-4"
      title={title}
      subtitle={sub}
      bodyClass="p-0"
      actions={notes.can_edit ? <button className="btn btn-sm" onClick={onAdd}><IconPlus size={13} /> Add</button> : undefined}
    >
      {sorted.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted">{empty}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-muted">
                <th className="px-4 py-2 font-medium">What</th>
                <th className="px-3 py-2 font-medium">Lever</th>
                <th className="px-3 py-2 font-medium">Support from</th>
                <th className="px-3 py-2 font-medium">Owner</th>
                <th className="px-3 py-2 font-medium">Due</th>
                <th className="px-3 py-2 text-right font-medium">Impact / month</th>
                <th className="px-4 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((i) => (
                <tr
                  key={i.id}
                  className={cx('border-b border-line/60 align-top last:border-0', notes.can_edit && 'cursor-pointer hover:bg-sunken/40', i.status === 'dropped' && 'opacity-60')}
                  onClick={notes.can_edit ? () => onEdit(i) : undefined}
                >
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-1.5 font-medium text-ink">
                      {i.priority === 'high' && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-bad" title="High priority" />}
                      {i.title}
                    </div>
                    {i.detail && <div className="mt-0.5 whitespace-pre-line text-xs text-ink2">{i.detail}</div>}
                    {i.blocker && <div className="mt-1 text-xs text-bad">Blocker: {i.blocker}</div>}
                    {i.carried_from && <div className="mt-0.5 text-2xs text-muted">Carried from last month</div>}
                  </td>
                  <td className="px-3 py-2 text-xs text-ink2">{i.lever_label || '–'}</td>
                  <td className="px-3 py-2 text-xs text-ink2">{i.team_label || '–'}</td>
                  <td className="px-3 py-2 text-xs text-ink2">{i.owner || '–'}</td>
                  <td className="px-3 py-2 text-xs tabular-nums text-ink2">{dmy(i.planned_date)}</td>
                  <td className="px-3 py-2 text-right text-xs tabular-nums text-ink2">{i.expected_impact ? inr(i.expected_impact) : '–'}</td>
                  <td className="px-4 py-2"><Badge tone={ITEM_TONE[i.status]}>{i.status_label}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
