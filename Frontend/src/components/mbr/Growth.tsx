import { useMemo, useState } from 'react';
import { inr, monthLabel, num, pct } from '@/lib/format';
import { useChartTokens } from '@/charts/EChart';
import { cartesian } from '@/charts/builders';
import { ChartCard } from '@/components/ChartCard';
import { Badge, Card, Field, InlineError, Meter, cx } from '@/components/ui';
import { IconEdit, IconPlus } from '@/components/Icons';
import { ITEM_TONE, ItemEditor, SectionTitle, Verdict, dmy, useSaveReview } from './shared';
import type { MbrItem, MbrNotes, Scorecard } from './types';
import { Takeaways } from './Summary';
import { SupportMatrix } from './Support';

const addMonths = (ym: string, n: number) => {
  const [y, m] = ym.split('-').map(Number);
  const d = new Date(y, m - 1 + n, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
};
const monthsBetween = (a: string, b: string) => {
  const [ya, ma] = a.split('-').map(Number);
  const [yb, mb] = b.split('-').map(Number);
  return (yb - ya) * 12 + (mb - ma);
};

export function Growth({ s, notes }: { s: Scorecard; notes: MbrNotes }) {
  const p = s.path;
  const [edit, setEdit] = useState<{ item?: MbrItem; kind?: string; preset?: Partial<MbrItem> } | null>(null);
  const growth = notes.items.filter((i) => i.section === 'growth');
  const actions = growth.filter((i) => i.kind === 'action');
  const blockers = growth.filter((i) => i.kind === 'bottleneck');
  const planned = actions.filter((i) => i.status !== 'dropped').reduce((a, i) => a + (i.expected_impact ?? 0), 0);
  const tone = (p.goal_pct ?? 0) >= 90 ? 'good' : (p.goal_pct ?? 0) >= 60 ? 'warn' : 'bad';

  return (
    <>
      <Verdict
        tone={tone}
        label={`${pct(p.goal_pct, 0)} of the ${inr(p.goal)}/month goal`}
        aside={notes.can_edit ? <GoalEditor s={s} notes={notes} /> : undefined}
      >
        {p.territory_share_pct !== null && (
          <>This territory made {pct(p.territory_share_pct, 1)} of TD's sales over the last 3 months, so its share of the {inr(p.national_goal)} goal is {inr(p.goal)}.{' '}</>
        )}
        To reach <b className="font-semibold">{inr(p.goal)} a month by {p.goal_by_label}</b>, {p.territory_share_pct !== null ? 'it' : 'TD'} has to grow{' '}
        <b className="font-semibold">{p.monthly_growth_needed_pct ?? '–'}% every month</b> for {p.months_left} months from {p.base_label}'s {inr(p.base_sales)}.
        At today's {inr(p.spend_per_retailer)} per transacting retailer that takes <b className="font-semibold">{num(p.retailers_needed)} transacting retailers</b>,{' '}
        {num(p.retailers_gap)} more than now. Adoption of the KYC base has to go from {pct(p.adoption_pct, 1)} to {pct(p.adoption_needed_pct, 1)}.
      </Verdict>

      <Takeaways s={s} areas={['goal', 'adoption']} />

      <div className="grid gap-4 xl:grid-cols-5">
        <PathChart s={s} className="xl:col-span-3" />
        <AdoptionMath s={s} className="xl:col-span-2" />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <AdoptionTrend s={s} />
        <Scenarios s={s} />
      </div>

      <SectionTitle n="3.1" title="Plan for next month" sub="Growth actions, the support each needs, and how much of the gap they cover" />
      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="How much of the gap the plan covers" subtitle={`Expected extra sales from the actions listed vs the ${inr(p.gap_sales)}/month gap`}>
          <div className="text-2xl font-semibold tabular-nums text-ink">{inr(planned)}</div>
          <div className="mb-2 text-xs text-muted">{pct(p.gap_sales ? (planned / p.gap_sales) * 100 : null, 0)} of the gap covered</div>
          <Meter value={p.gap_sales ? (planned / p.gap_sales) * 100 : 0} tone={planned >= p.gap_sales ? 'good' : planned >= p.gap_sales * 0.6 ? 'warn' : 'bad'} />
          <p className="mt-3 text-xs text-ink2">
            {planned >= p.gap_sales
              ? 'The plan, if delivered, closes the gap.'
              : `${inr(p.gap_sales - planned)} a month has no action against it yet.`}{' '}
            Add an expected impact to each action to keep this honest.
          </p>
        </Card>
        <SupportMatrix s={s} notes={notes} className="xl:col-span-2" onAdd={(preset) => setEdit({ kind: 'action', preset })} onEdit={(item) => setEdit({ item })} />
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

function GoalEditor({ s, notes }: { s: Scorecard; notes: MbrNotes }) {
  const [open, setOpen] = useState(false);
  const [goal, setGoal] = useState(String(s.path.national_goal / 1e7));
  const [by, setBy] = useState(s.path.goal_by);
  const save = useSaveReview(s.month);
  if (!open) return <button className="btn btn-sm" onClick={() => setOpen(true)}><IconEdit size={13} /> Goal</button>;
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate({ goal_monthly_sales: Number(goal) * 1e7, goal_by: by }, { onSuccess: () => setOpen(false) }); }}>
      <Field label="All-TD goal, ₹ Cr per month"><input className="input w-24 tabular-nums" inputMode="decimal" value={goal} onChange={(e) => setGoal(e.target.value)} /></Field>
      <Field label="By"><input type="month" className="input w-36" value={by} min={notes.month} onChange={(e) => setBy(e.target.value)} /></Field>
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
    const first = s.trend[0].month;
    const n = monthsBetween(first, p.goal_by);
    const months = Array.from({ length: n + 1 }, (_, i) => addMonths(first, i));
    const actual = new Map(s.trend.map((x) => [x.month, x.sales]));
    const g = (p.monthly_growth_needed_pct ?? 0) / 100;
    const path = months.map((m) => {
      const k = monthsBetween(p.base_month, m);
      return k < 0 ? null : Math.round(p.base_sales * (1 + g) ** k);
    });
    return cartesian(t, {
      x: months.map((m) => monthLabel(m) + (s.partial && m === s.month ? ' (MTD)' : '')),
      format: 'inr',
      legend: true,
      markLine: { value: p.goal, label: `Goal ${inr(p.goal)}` },
      yMax: Math.ceil((p.goal * 1.1) / 1e7) * 1e7,
      series: [
        { name: 'Actual sales', data: months.map((m) => actual.get(m) ?? null), type: 'bar', color: t.series[0] },
        { name: 'Path needed', data: path, type: 'line', dashed: true, color: t.series[1] },
      ],
    });
  }, [t, s, p]);
  return (
    <ChartCard
      className={className}
      title={`The path to ${inr(p.goal)} a month`}
      subtitle={`Actual sales, and the ${p.monthly_growth_needed_pct ?? '–'}% a month compound path from ${p.base_label} that reaches the goal in ${p.goal_by_label}`}
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
        markLine: p.adoption_needed_pct ? { value: p.adoption_needed_pct, label: `Needed ${pct(p.adoption_needed_pct, 1)}` } : undefined,
        yMax: p.adoption_needed_pct ? Math.ceil((p.adoption_needed_pct * 1.2) / 2) * 2 : undefined,
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
