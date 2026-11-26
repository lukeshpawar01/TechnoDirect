import { useState } from 'react';
import { pct } from '@/lib/format';
import { Badge, Card, cx, type Tone } from '@/components/ui';
import { IconPlus } from '@/components/Icons';
import { ITEM_TONE, ItemEditor, SectionTitle, Verdict, dmy } from './shared';
import type { MbrItem, MbrNotes } from './types';

type State = NonNullable<MbrItem['adherence']>['state'];
const STATE: Record<State, { label: string; tone: Tone; bar: string }> = {
  on_time: { label: 'Live on time', tone: 'good', bar: 'bg-good' },
  late: { label: 'Live, late', tone: 'warn', bar: 'bg-warn' },
  overdue: { label: 'Overdue', tone: 'bad', bar: 'bg-bad' },
  slipping: { label: 'Date moved', tone: 'warn', bar: 'bg-warn' },
  on_track: { label: 'On track', tone: 'brand', bar: 'bg-brand' },
  dropped: { label: 'Dropped', tone: 'neutral', bar: 'bg-muted' },
  undated: { label: 'No date', tone: 'neutral', bar: 'bg-muted' },
};
const day = (s: string) => new Date(`${s}T00:00:00`).getTime();

export function Tech({ notes, month, today }: { notes: MbrNotes; month: string; today: string }) {
  const [edit, setEdit] = useState<{ item?: MbrItem } | null>(null);
  const items = notes.items.filter((i) => i.section === 'tech');
  const s = notes.tech_summary;
  // a past month is judged at its month end (as the backend does), not today
  const [yy, mm] = month.split('-').map(Number);
  const monthEnd = `${month}-${String(new Date(yy, mm, 0).getDate()).padStart(2, '0')}`;
  const asOf = monthEnd < today ? monthEnd : today;
  const tone: Tone = s.adherence_pct === null ? 'neutral' : s.adherence_pct >= 80 ? 'good' : s.adherence_pct >= 60 ? 'warn' : 'bad';
  const blocked = items.filter((i) => i.status === 'blocked' || (i.blocker && i.status !== 'done' && i.status !== 'dropped'));

  return (
    <>
      <Verdict
        tone={tone}
        label={s.adherence_pct === null ? 'No dated tech items yet' : `${pct(s.adherence_pct, 0)} on time`}
        aside={notes.can_edit ? <button className="btn btn-sm" onClick={() => setEdit({})}><IconPlus size={13} /> Add tech item</button> : undefined}
      >
        {items.length === 0 ? (
          <>Add each tech item with its planned go-live date. The page then tracks what went live, what slipped and what is blocking it.</>
        ) : (
          <>
            {s.done} of {s.total} tech items are live
            {s.adherence_pct !== null && <>; {s.on_time} of the {s.on_time + s.late + s.overdue} due by month end went live on time</>}.
            {s.overdue ? <> <b className="font-semibold text-bad">{s.overdue} overdue</b>.</> : null}
            {s.blocked ? <> <b className="font-semibold text-bad">{s.blocked} blocked</b>.</> : null}
            {s.avg_slip_days ? <> Items that slipped moved {s.avg_slip_days} days on average.</> : null}
          </>
        )}
      </Verdict>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {[
          { label: 'On-time adherence', v: pct(s.adherence_pct, 0), sub: 'live on time ÷ due', cls: tone === 'good' ? 'text-good' : tone === 'bad' ? 'text-bad' : 'text-ink' },
          { label: 'Live', v: String(s.done), sub: `of ${s.total} items` },
          { label: 'In progress', v: String(s.in_progress), sub: 'being built' },
          { label: 'Overdue', v: String(s.overdue), sub: 'date passed, not live', cls: s.overdue ? 'text-bad' : 'text-ink' },
          { label: 'Blocked', v: String(s.blocked), sub: 'need a decision or help', cls: s.blocked ? 'text-bad' : 'text-ink' },
        ].map((x) => (
          <div key={x.label} className="card p-4">
            <div className="text-xs text-muted">{x.label}</div>
            <div className={cx('mt-1 text-2xl font-semibold tabular-nums', x.cls ?? 'text-ink')}>{x.v}</div>
            <div className="text-2xs text-muted">{x.sub}</div>
          </div>
        ))}
      </div>

      <SectionTitle n="4.1" title="Timeline" sub="Planned go-live vs where it is now" />
      <Timeline items={items} today={asOf} label={asOf === today ? 'Today' : 'Month end'} canEdit={notes.can_edit} onEdit={(item) => setEdit({ item })} />

      <SectionTitle n="4.2" title="Blockers" sub="What needs a decision or help this month" />
      <Card bodyClass="p-0">
        {blocked.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted">Nothing blocked.</p>
        ) : (
          <ul className="divide-y divide-line">
            {blocked.map((i) => (
              <li key={i.id} className={cx('grid gap-1 px-4 py-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,3fr)_auto] sm:gap-4', notes.can_edit && 'cursor-pointer hover:bg-sunken/40')} onClick={notes.can_edit ? () => setEdit({ item: i }) : undefined}>
                <div>
                  <div className="font-medium text-ink">{i.title}</div>
                  <div className="text-xs text-muted">{[i.team_label, i.owner].filter(Boolean).join(' · ') || '–'}</div>
                </div>
                <div className="text-sm text-bad">{i.blocker || 'Blocked: no reason written'}</div>
                <Badge tone={ITEM_TONE[i.status]}>{i.status_label}</Badge>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {edit && <ItemEditor notes={notes} month={month} section="tech" item={edit.item} onClose={() => setEdit(null)} />}
    </>
  );
}

function Timeline({ items, today, label, canEdit, onEdit }: { items: MbrItem[]; today: string; label: string; canEdit: boolean; onEdit: (i: MbrItem) => void }) {
  if (items.length === 0) return <Card><p className="text-sm text-muted">No tech items for this month.</p></Card>;
  const order: Record<State, number> = { overdue: 0, slipping: 1, on_track: 2, late: 3, on_time: 4, undated: 5, dropped: 6 };
  const rows = [...items].sort((a, b) => order[a.adherence!.state] - order[b.adherence!.state] || (a.planned_date ?? '').localeCompare(b.planned_date ?? ''));
  const dates = rows.flatMap((i) => [i.planned_date, i.revised_date, i.done_date].filter(Boolean) as string[]).concat(today);
  const lo = Math.min(...dates.map(day)) - 3 * 864e5;
  const hi = Math.max(...dates.map(day)) + 3 * 864e5;
  const x = (d: string) => `${((day(d) - lo) / (hi - lo)) * 100}%`;
  const ticks: string[] = [];
  const t0 = new Date(lo);
  for (let d = new Date(t0.getFullYear(), t0.getMonth() + 1, 1); d.getTime() <= hi; d = new Date(d.getFullYear(), d.getMonth() + 1, 1)) {
    ticks.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`);
  }
  const every = Math.ceil(ticks.length / 8); // keep month labels from colliding
  return (
    <Card bodyClass="p-0">
      <div className="overflow-x-auto">
        <div className="min-w-[760px]">
          <div className="grid grid-cols-[minmax(0,15rem)_minmax(0,1fr)_7.5rem] border-b border-line text-2xs text-muted">
            <div className="px-4 py-2">Item</div>
            <div className="relative h-8">
              {ticks.filter((_, k) => k % every === 0).map((t) => (
                <span key={t} className="absolute top-2 -translate-x-1/2 whitespace-nowrap" style={{ left: x(t) }}>{dmy(t).slice(3)}</span>
              ))}
              <span className="absolute bottom-0 top-0 w-px bg-accent" style={{ left: x(today) }} />
              <span className="absolute bottom-0 -translate-x-1/2 rounded bg-accent px-1 text-[10px] font-medium text-white" style={{ left: x(today) }}>{label}</span>
            </div>
            <div className="px-3 py-2">State</div>
          </div>
          {rows.map((i) => {
            const a = i.adherence!;
            const st = STATE[a.state];
            const end = i.done_date ?? i.revised_date ?? (a.state === 'overdue' ? today : i.planned_date);
            return (
              <div
                key={i.id}
                className={cx('grid grid-cols-[minmax(0,15rem)_minmax(0,1fr)_7.5rem] items-center border-b border-line/60 last:border-0', canEdit && 'cursor-pointer hover:bg-sunken/40')}
                onClick={canEdit ? () => onEdit(i) : undefined}
              >
                <div className="px-4 py-2">
                  <div className="truncate text-sm font-medium text-ink" title={i.title}>{i.title}</div>
                  <div className="truncate text-2xs text-muted">{[i.kind_label, i.team_label, i.owner].filter(Boolean).join(' · ')}</div>
                </div>
                <div className="relative h-10">
                  {ticks.map((t) => <span key={t} className="absolute inset-y-0 w-px bg-line/60" style={{ left: x(t) }} />)}
                  <span className="absolute inset-y-0 w-px bg-accent/60" style={{ left: x(today) }} />
                  {i.planned_date && end && (
                    <>
                      {end !== i.planned_date && (
                        <span
                          className={cx('absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full', st.bar, day(end) < day(i.planned_date) && 'opacity-60')}
                          style={{ left: x(day(end) < day(i.planned_date) ? end : i.planned_date), width: `calc(${x(day(end) < day(i.planned_date) ? i.planned_date : end)} - ${x(day(end) < day(i.planned_date) ? end : i.planned_date)})` }}
                          title={a.slip_days ? `${a.slip_days} days late` : undefined}
                        />
                      )}
                      <span className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rotate-45 border-2 border-ink2 bg-surface" style={{ left: x(i.planned_date) }} title={`Planned ${dmy(i.planned_date)}`} />
                      {i.done_date ? (
                        <span className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface bg-good" style={{ left: x(i.done_date) }} title={`Live ${dmy(i.done_date)}`} />
                      ) : i.revised_date ? (
                        <span className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rotate-45 bg-warn" style={{ left: x(i.revised_date) }} title={`Revised ${dmy(i.revised_date)}`} />
                      ) : null}
                    </>
                  )}
                </div>
                <div className="px-3 py-2">
                  <Badge tone={st.tone}>{st.label}</Badge>
                  {a.slip_days ? <div className="mt-0.5 text-2xs tabular-nums text-muted">{a.slip_days} days</div> : null}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-line px-4 py-2 text-2xs text-ink2">
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rotate-45 border-2 border-ink2 bg-surface" /> Planned</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rotate-45 bg-warn" /> Revised date</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-good" /> Went live</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-4 rounded-full bg-bad" /> Delay so far</span>
      </div>
    </Card>
  );
}
