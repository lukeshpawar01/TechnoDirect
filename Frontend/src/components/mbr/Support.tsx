import { Fragment, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { inr, num } from '@/lib/format';
import { Badge, Card, Drawer, cx } from '@/components/ui';
import { IconPlus } from '@/components/Icons';
import { ITEM_TONE } from './shared';
import type { MbrItem, MbrNotes, SalesAsk, SalesAskKind, Scorecard } from './types';

/**
 * MBR page 3, "Support required": one card per team. Click a card for what we need from that team.
 * The Sales card also carries asks built from data for RSMs / ASMs / executives (stretch targets, distributors
 * stalled or slow distributors, stock problems, new warehouses).
 */
const TEAMS = ['sales', 'tech', 'finance', 'data', 'marketing'] as const;
type Team = (typeof TEAMS)[number] | 'operations' | 'other';

const KIND: Record<SalesAskKind, { label: string; hint: string; lever: string }> = {
  stretch: { label: 'Stretch targets for next month', hint: 'The biggest distributor in each region, sized against its own best month', lever: 'distributors' },
  stalled: { label: 'Distributors that stopped ordering', hint: 'Sold in the last 3 months, nothing this month', lever: 'retention' },
  no_asm: { label: 'Distributors with no ASM: RSM to decide', hint: 'No ASM, or only a placeholder named after the distributor', lever: 'distributors' },
  warm: { label: 'Warm retailers to activate, by ASM', hint: 'KYC done, buy TechnoSport offline (BlueOrigin), never ordered on TD. Targets split the monthly activation goal by ASM', lever: 'activation' },
  stock: { label: 'Stock problems at distributors', hint: '30-day demand on items now at zero stock (month in progress only)', lever: 'other' },
  slow: { label: 'Slow growth', hint: 'A real base but growing slower than TD (last 3 months vs the 3 before)', lever: 'retention' },
  new: { label: 'New warehouses to launch', hint: 'On TD but no orders yet; retailers in the same district are served from elsewhere', lever: 'distributors' },
  reassign: { label: 'Territory changes to consider', hint: 'A near-dead distributor next to a working one in the same state', lever: 'distributors' },
};
const KIND_ORDER: SalesAskKind[] = ['stretch', 'stalled', 'stock', 'slow', 'new'];

export function SupportMatrix({ s, notes, className, onAdd, onEdit }: {
  s: Scorecard; notes: MbrNotes; className?: string;
  onAdd: (preset: Partial<MbrItem>) => void; onEdit: (i: MbrItem) => void;
}) {
  const [open, setOpen] = useState<Team | null>(null);
  const asks = notes.items.filter((i) => i.section === 'growth' && ['planned', 'in_progress', 'blocked'].includes(i.status));
  const label = (t: string) => notes.choices.teams.find((x) => x.value === t)?.label ?? t;
  const extra = (['operations', 'other'] as const).filter((t) => asks.some((i) => i.team === t));
  const suggested = s.sales_asks?.asks ?? [];
  const autoFor = (t: Team) => (t === 'sales' ? suggested.length : t === 'tech' ? techAuto(notes).length : t === 'marketing' ? marketingAuto(s).length : t === 'finance' ? financeAuto(s).length : 0);

  return (
    <Card className={className} title="Support required" subtitle="What we need from each team to grow. Click a card for the asks; Sales includes suggestions from the data.">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        {[...TEAMS, ...extra].map((t) => {
          const mine = asks.filter((i) => i.team === t);
          const blocked = mine.filter((i) => i.status === 'blocked').length;
          const auto = autoFor(t);
          const high = t === 'sales' ? suggested.filter((a) => a.priority === 'high').length : 0;
          return (
            <button
              key={t}
              onClick={() => setOpen(t)}
              className={cx('rounded-md border p-3 text-left transition-colors hover:border-brand hover:bg-sunken/40',
                blocked ? 'border-bad/40 bg-bad-bg' : t === 'sales' ? 'border-brand/50 bg-brand/5' : 'border-line')}
            >
              <div className="text-xs font-medium text-ink2">{label(t)}</div>
              <div className="text-xl font-semibold tabular-nums text-ink">{mine.length + auto}</div>
              <div className={cx('text-2xs', blocked ? 'font-medium text-bad' : 'text-muted')}>
                {blocked ? `${blocked} blocked · ` : ''}
                {t === 'sales' ? `${auto} suggested${high ? `, ${high} high` : ''} · ${mine.length} in plan` : mine.length || auto ? `${mine.length} asked${auto ? ` · ${auto} flagged` : ''}` : 'nothing asked'}
              </div>
            </button>
          );
        })}
      </div>
      {open && (
        <TeamDrawer
          team={open} label={label(open)} s={s} notes={notes} asks={asks.filter((i) => i.team === open)}
          onClose={() => setOpen(null)}
          onAdd={(p) => { setOpen(null); onAdd({ team: open, ...p }); }}
          onEdit={(i) => { setOpen(null); onEdit(i); }}
        />
      )}
    </Card>
  );
}

type Auto = { title: string; detail: string; link?: string; value?: number | null; value_label?: string; high?: boolean; facts?: [string, string][] };
function techAuto(notes: MbrNotes): Auto[] {
  return notes.items
    .filter((i) => i.section === 'tech' && i.status !== 'done' && i.status !== 'dropped' && (i.status === 'blocked' || i.blocker || i.adherence?.state === 'overdue'))
    .map((i) => ({ title: i.title, detail: i.blocker ? `Blocked: ${i.blocker}` : 'Past its go-live date', link: 'tech' }));
}
function financeAuto(s: Scorecard): Auto[] {
  return (s.finance_asks?.asks ?? []).map((a) => ({ title: a.title, detail: a.detail, value: a.value, value_label: a.value_label, high: a.priority === 'high' }));
}
/** TD promotion campaigns, sized from the data (backend analytics/mbr_marketing.py). */
function marketingAuto(s: Scorecard): Auto[] {
  return (s.marketing_asks?.asks ?? []).map((a) => ({
    title: a.title, detail: a.detail, value: a.value,
    value_label: a.rate_pct ? `${a.value_label} (assumes ${a.rate_pct}% respond)` : a.value_label,
    high: a.priority === 'high',
    facts: [['Audience', `${num(a.audience)} retailers`], ['Channel', a.channel], ['Offer', a.offer]],
  }));
}

function TeamDrawer({ team, label, s, notes, asks, onClose, onAdd, onEdit }: {
  team: Team; label: string; s: Scorecard; notes: MbrNotes; asks: MbrItem[];
  onClose: () => void; onAdd: (p: Partial<MbrItem>) => void; onEdit: (i: MbrItem) => void;
}) {
  const sales = team === 'sales' ? s.sales_asks : null;
  // region filter for the Sales suggestions ('' = all regions: then only the top few of each kind, the rest per region)
  const [region, setRegion] = useState('');
  const regions = useMemo(() => {
    const c = new Map<string, number>();
    for (const a of sales?.asks ?? []) if (a.region) c.set(a.region, (c.get(a.region) ?? 0) + 1);
    return [...c.entries()].sort((a, b) => b[1] - a[1]);
  }, [sales]);
  const ALL_CAP = 4;
  const auto = team === 'tech' ? techAuto(notes) : team === 'marketing' ? marketingAuto(s) : team === 'finance' ? financeAuto(s) : [];
  const inPlan = new Set(notes.items.map((i) => i.title.trim().toLowerCase()));
  const toPlan = (a: SalesAsk): Partial<MbrItem> => ({
    title: a.title.slice(0, 200), detail: a.detail, owner: a.owner, priority: a.priority === 'high' ? 'high' : 'medium',
    lever: KIND[a.kind].lever, expected_impact: a.value && a.value > 0 && a.kind !== 'no_asm' ? Math.round(a.value) : null,
  });

  return (
    <Drawer open onClose={onClose} title={`${label}: what we need`} width={760}>
      {sales && (
        <>
          <p className="mb-3 text-sm text-ink2">
            Suggestions from the data for RSMs, ASMs and sales executives for {s.label}'s plan. TD grew {sales.td_growth_3m_pct ?? '–'}% over
            the last 3 months{s.path.goal_active ? <>; the {inr(s.path.goal)} monthly goal needs <b className="text-ink">{num(sales.activation_per_month)} more retailers buying every month</b> than today</> : null}.
            {notes.can_edit ? ' Use “Add to plan” to make one a growth action with an owner and a due date.' : ''}
          </p>
          <div className="sticky top-0 z-10 -mx-1 mb-3 flex flex-wrap items-center gap-1.5 bg-surface px-1 py-1.5">
            <span className="mr-1 text-xs text-muted">Region</span>
            {[['', sales.asks.length] as [string, number], ...regions].map(([r, n]) => (
              <button
                key={r || 'all'}
                className={cx('chip text-xs', region === r ? 'border-brand bg-brand/10 text-ink' : 'text-ink2')}
                onClick={() => setRegion(r)}
                aria-pressed={region === r}
              >
                {r || 'All regions'} <span className="tabular-nums text-muted">{n}</span>
              </button>
            ))}
          </div>
          {KIND_ORDER.map((k) => {
            const all = sales.asks.filter((a) => a.kind === k && (!region || a.region === region));
            if (!all.length) return null;
            // all regions: the strongest few of each kind; pick a region for its full list
            const rows = region ? all : [...all].sort((a, b) => (a.priority === b.priority ? (b.value ?? 0) - (a.value ?? 0) : a.priority === 'high' ? -1 : 1)).slice(0, ALL_CAP);
            const more = all.length - rows.length;
            return (
              <section key={k} className="mb-4">
                <h3 className="text-sm font-semibold text-ink">{KIND[k].label}</h3>
                <p className="mb-1.5 text-2xs text-muted">{KIND[k].hint}</p>
                <ul className="divide-y divide-line rounded-md border border-line">
                  {rows.map((a) => {
                    const added = inPlan.has(a.title.trim().toLowerCase());
                    return (
                      <li key={a.title} className="grid gap-2 px-3 py-2.5 sm:grid-cols-[minmax(0,1fr)_auto]">
                        <div className="min-w-0">
                          <div className="text-sm font-medium text-ink">
                            {a.priority === 'high' && <span className="mb-0.5 mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-bad align-middle" title="High priority" />}
                            {a.title}
                          </div>
                          <p className="mt-0.5 text-xs leading-relaxed text-ink2">{a.detail}</p>
                          <div className="mt-1 text-2xs text-muted">{[a.owner, a.region].filter(Boolean).join(' · ')}</div>
                        </div>
                        <div className="flex items-start gap-3 sm:flex-col sm:items-end">
                          {a.value ? (
                            <div className="text-right">
                              <div className="text-sm font-semibold tabular-nums text-ink">{inr(a.value)}</div>
                              <div className="max-w-[11rem] text-2xs text-muted">{a.value_label}</div>
                            </div>
                          ) : null}
                          {notes.can_edit && (added
                            ? <span className="text-2xs text-good">In the plan</span>
                            : <button className="btn btn-sm" onClick={() => onAdd(toPlan(a))}><IconPlus size={12} /> Add to plan</button>)}
                        </div>
                      </li>
                    );
                  })}
                </ul>
                {more > 0 && <p className="mt-1 text-2xs text-muted">+{more} more in the regions: pick a region above to see them.</p>}
              </section>
            );
          })}
        </>
      )}

      {auto.length > 0 && (
        <section className="mb-4">
          <h3 className="mb-1.5 text-sm font-semibold text-ink">{team === 'tech' ? 'Blocked or overdue tech work' : team === 'finance' ? 'What we need from Finance' : team === 'marketing' ? 'Campaigns to promote TD' : 'Flagged from the data'}</h3>
          <ul className="divide-y divide-line rounded-md border border-line">
            {auto.map((a) => (
              <li key={a.title} className="grid gap-2 px-3 py-2.5 sm:grid-cols-[minmax(0,1fr)_auto]">
                <div className="min-w-0">
                  <div className="text-sm font-medium text-ink">
                    {a.high && <span className="mb-0.5 mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-bad align-middle" title="High priority" />}
                    {a.title}
                  </div>
                  <p className="mt-0.5 text-xs leading-relaxed text-ink2">{a.detail}</p>
                  {a.facts && (
                    <dl className="mt-1.5 grid grid-cols-[4.5rem_minmax(0,1fr)] gap-x-2 gap-y-0.5 text-2xs">
                      {a.facts.map(([k, v]) => <Fragment key={k}><dt className="text-muted">{k}</dt><dd className="text-ink2">{v}</dd></Fragment>)}
                    </dl>
                  )}
                </div>
                <div className="flex items-start gap-3 sm:flex-col sm:items-end">
                  {a.value ? (
                    <div className="text-right">
                      <div className="text-sm font-semibold tabular-nums text-ink">{inr(a.value)}</div>
                      <div className="max-w-[11rem] text-2xs text-muted">{a.value_label}</div>
                    </div>
                  ) : null}
                  {a.link ? <Link to={`/mbr/${a.link}?month=${s.month}`} className="text-2xs text-brand hover:underline" onClick={onClose}>Open</Link>
                    : notes.can_edit ? (inPlan.has(a.title.trim().toLowerCase())
                      ? <span className="text-2xs text-good">In the plan</span>
                      : <button className="btn btn-sm" onClick={() => onAdd({ title: a.title.slice(0, 200), detail: [a.detail, ...(a.facts ?? []).map(([k, v]) => `${k}: ${v}`)].join('\n'), priority: a.high ? 'high' : 'medium', owner: team === 'finance' ? 'Finance' : team === 'marketing' ? 'Marketing' : '', expected_impact: a.value && team === 'marketing' ? Math.round(a.value) : null })}><IconPlus size={12} /> Add to plan</button>) : null}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <div className="mb-1.5 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ink">Asks in the plan ({asks.length})</h3>
          {notes.can_edit && <button className="btn btn-sm" onClick={() => onAdd({})}><IconPlus size={12} /> New ask for {label}</button>}
        </div>
        {asks.length === 0 ? (
          <p className="rounded-md border border-dashed border-line px-3 py-4 text-sm text-muted">
            Nothing asked of {label} yet.{team === 'sales' ? ' Add the suggestions above, or your own (e.g. "Pune warehouse is live: push West sales there").' : ''}
          </p>
        ) : (
          <ul className="divide-y divide-line rounded-md border border-line">
            {asks.map((i) => (
              <li key={i.id} className={cx('flex items-start justify-between gap-3 px-3 py-2.5', notes.can_edit && 'cursor-pointer hover:bg-sunken/40')}
                onClick={notes.can_edit ? () => onEdit(i) : undefined}>
                <div className="min-w-0">
                  <div className="text-sm font-medium text-ink">{i.title}</div>
                  {i.detail && <p className="mt-0.5 line-clamp-2 text-xs text-ink2">{i.detail}</p>}
                  <div className="mt-1 text-2xs text-muted">{[i.owner, i.expected_impact ? `${inr(i.expected_impact)}/month` : null].filter(Boolean).join(' · ')}</div>
                </div>
                <Badge tone={ITEM_TONE[i.status]}>{i.status_label}</Badge>
              </li>
            ))}
          </ul>
        )}
      </section>
    </Drawer>
  );
}
