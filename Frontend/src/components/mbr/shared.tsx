import { useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, del, getEnvelope, get, patch, post } from '@/lib/api';
import { inr, num, pct } from '@/lib/format';
import { Badge, Drawer, Field, InlineError, cx, type Tone } from '@/components/ui';
import { IconTrash } from '@/components/Icons';
import type { Fmt, ItemStatus, MbrItem, MbrNotes, RowStatus, Scorecard, Section } from './types';

// ---------------------------------------------------------------- data
export function useScorecard(month: string) {
  return useQuery({
    queryKey: ['mbr', 'scorecard', month],
    queryFn: () => getEnvelope<Scorecard>('/mbr/', { month }),
    placeholderData: (p) => p,
  });
}

export function useNotes(month: string) {
  return useQuery({ queryKey: ['mbr', 'notes', month], queryFn: () => get<MbrNotes>('/masters/mbr/', { month }) });
}

export function useSaveReview(month: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api.put<MbrNotes>('/masters/mbr/', body, { params: { month } }).then((r) => r.data),
    onSuccess: (d) => {
      qc.setQueryData(['mbr', 'notes', month], d);
      void qc.invalidateQueries({ queryKey: ['mbr', 'scorecard', month] });
    },
  });
}

// ---------------------------------------------------------------- formatting
export function fmt(v: number | null | undefined, f: Fmt): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '–';
  if (f === 'inr') return inr(v);
  if (f === 'pct') return pct(v, 1);
  if (f === 'dec') return num(v, 2);
  return num(v);
}

/** Change column: % for values, percentage points for rates. Coloured by whether it is good news. */
export function Change({ v, f, up = true }: { v: number | null | undefined; f: Fmt; up?: boolean }) {
  if (v === null || v === undefined || !Number.isFinite(v)) return <span className="text-muted">–</span>;
  const flat = Math.abs(v) < 0.05;
  const good = flat ? null : (v > 0) === up;
  const sign = flat ? '±' : v > 0 ? '+' : '−';
  const text = `${sign}${Math.abs(v).toFixed(1)}${f === 'pct' ? ' pp' : '%'}`;
  return <span className={cx('tabular-nums font-medium', good === null ? 'text-muted' : good ? 'text-good' : 'text-bad')}>{text}</span>;
}

export const STATUS_TONE: Record<string, Tone> = { good: 'good', warn: 'warn', bad: 'bad', in_progress: 'neutral' };
export function statusText(s: RowStatus): string {
  return s === 'good' ? 'On target' : s === 'warn' ? 'Close (90%+)' : s === 'bad' ? 'Below target' : s === 'in_progress' ? 'Month in progress' : '';
}

export const ITEM_TONE: Record<ItemStatus, Tone> = { planned: 'neutral', in_progress: 'brand', blocked: 'bad', done: 'good', dropped: 'neutral' };

/** Tiny inline trend line (no chart instance per table row). The last point is hollow when the month is partial. */
export function MiniTrend({ data, partial, width = 96, height = 26 }: { data: (number | null)[]; partial?: boolean; width?: number; height?: number }) {
  const vals = data.map((v) => (typeof v === 'number' && Number.isFinite(v) ? v : null));
  const nums = vals.filter((v): v is number => v !== null);
  if (nums.length < 2) return <span className="text-2xs text-muted">–</span>;
  const lo = Math.min(...nums);
  const hi = Math.max(...nums);
  const span = hi - lo || 1;
  const x = (i: number) => 2 + (i * (width - 4)) / (vals.length - 1);
  const y = (v: number) => height - 3 - ((v - lo) / span) * (height - 6);
  let d = '';
  vals.forEach((v, i) => {
    if (v === null) return;
    d += `${d && vals[i - 1] !== null ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
  });
  const li = vals.length - 1;
  const last = vals[li];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" className="overflow-visible">
      <path d={d} fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinejoin="round" strokeLinecap="round" className="text-brand dark:text-[#86b6ef]" />
      {last !== null && (
        <circle cx={x(li)} cy={y(last)} r={2.6} className={partial ? 'fill-surface stroke-brand dark:stroke-[#86b6ef]' : 'fill-brand dark:fill-[#86b6ef]'} strokeWidth={1.4} />
      )}
    </svg>
  );
}

/** The one-sentence answer at the top of every MBR page. */
export function Verdict({ tone, label, children, aside }: { tone: Tone; label: string; children: ReactNode; aside?: ReactNode }) {
  const bar = { good: 'bg-good', warn: 'bg-warn', bad: 'bg-bad', neutral: 'bg-muted', brand: 'bg-brand' }[tone];
  return (
    <div className="card relative mb-4 overflow-hidden p-4 pl-5">
      <span className={cx('absolute inset-y-0 left-0 w-1', bar)} aria-hidden="true" />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-w-4xl">
          <Badge tone={tone} icon>{label}</Badge>
          <p className="mt-2 text-[15px] leading-relaxed text-ink">{children}</p>
        </div>
        {aside}
      </div>
    </div>
  );
}

export function SectionTitle({ n, title, sub }: { n?: string; title: string; sub?: ReactNode }) {
  return (
    <div className="mb-2 mt-6 flex flex-wrap items-baseline gap-x-2">
      {n && <span className="text-xs font-semibold tabular-nums text-muted">{n}</span>}
      <h2 className="text-base font-semibold text-ink">{title}</h2>
      {sub && <span className="text-xs text-muted">{sub}</span>}
    </div>
  );
}

export function dmy(d: string | null | undefined) {
  if (!d) return '–';
  const [y, m, day] = d.split('-');
  return `${day} ${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][Number(m) - 1]} ${y.slice(2)}`;
}

// ---------------------------------------------------------------- add / edit a line (pages 2-4)
type Draft = Partial<Record<keyof MbrItem, string>>;
const toDraft = (i: Partial<MbrItem>): Draft =>
  Object.fromEntries(Object.entries(i).map(([k, v]) => [k, v === null || v === undefined ? '' : String(v)])) as Draft;

export function ItemEditor({ notes, month, item, section, kind, preset, onClose }: {
  notes: MbrNotes;
  month: string;
  item?: MbrItem | null;
  section: Section;
  kind?: string;
  /** prefill for a new line (e.g. a suggested sales ask) */
  preset?: Partial<MbrItem>;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const c = notes.choices;
  const [d, setD] = useState<Draft>(() =>
    toDraft(item ?? { section, kind: kind ?? c.kinds[section][0].value, status: 'planned', priority: 'medium', ...preset }),
  );
  const set = (k: keyof MbrItem) => (e: { target: { value: string } }) => setD((x) => ({ ...x, [k]: e.target.value }));
  const done = () => {
    void qc.invalidateQueries({ queryKey: ['mbr', 'notes', month] });
    onClose();
  };
  const body = () => {
    const keys: (keyof MbrItem)[] = ['section', 'kind', 'title', 'detail', 'owner', 'status', 'priority', 'team', 'blocker'];
    if (section === 'growth') keys.push('lever', 'expected_impact', 'planned_date');
    if (section === 'tech') keys.push('planned_date', 'revised_date', 'done_date');
    if (section === 'other') keys.push('event_date');
    return Object.fromEntries(keys.map((k) => [k, d[k] ?? '']));
  };
  const save = useMutation({
    mutationFn: () => (item ? patch(`/masters/mbr/items/${item.id}/`, body()) : post(`/masters/mbr/items/?month=${month}`, body())),
    onSuccess: done,
  });
  const remove = useMutation({ mutationFn: () => del(`/masters/mbr/items/${item!.id}/`), onSuccess: done });
  const sel = (k: keyof MbrItem, opts: { value: string; label: string }[], blank?: string) => (
    <select className="input" value={d[k] ?? ''} onChange={set(k)}>
      {blank !== undefined && <option value="">{blank}</option>}
      {opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
  const heading = { growth: 'growth action', tech: 'tech update', other: 'development' }[section];
  return (
    <Drawer open onClose={onClose} title={item ? `Edit ${heading}` : `Add ${heading}`} width={520}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Type">{sel('kind', c.kinds[section])}</Field>
          <Field label="Status">{sel('status', c.statuses)}</Field>
        </div>
        <Field label="Title">
          <input className="input" value={d.title ?? ''} onChange={set('title')} maxLength={200} required autoFocus placeholder={section === 'growth' ? 'e.g. Activate 300 KYC-done retailers in Karnataka' : section === 'tech' ? 'e.g. Credit (pay later) at checkout' : 'e.g. New distributor signed in Pune'} />
        </Field>
        <Field label="Details">
          <textarea className="input min-h-[72px]" value={d.detail ?? ''} onChange={set('detail')} />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Owner"><input className="input" value={d.owner ?? ''} onChange={set('owner')} /></Field>
          {section !== 'other' && <Field label="Priority">{sel('priority', c.priorities)}</Field>}
        </div>
        {section !== 'other' && (
          <Field label={section === 'growth' ? 'Support required from' : 'Delivering team'}>{sel('team', c.teams, '— none —')}</Field>
        )}
        {section === 'growth' && (
          <>
            <Field label="Growth lever">{sel('lever', c.levers, '— choose —')}</Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Expected extra sales / month (₹)" hint="Used to see how much of the gap the plan covers">
                <input className="input tabular-nums" inputMode="decimal" value={d.expected_impact ?? ''} onChange={set('expected_impact')} placeholder="e.g. 50,00,000" />
              </Field>
              <Field label="Due date"><input type="date" className="input" value={d.planned_date ?? ''} onChange={set('planned_date')} /></Field>
            </div>
          </>
        )}
        {section === 'tech' && (
          <div className="grid grid-cols-3 gap-2">
            <Field label="Planned go-live"><input type="date" className="input" value={d.planned_date ?? ''} onChange={set('planned_date')} /></Field>
            <Field label="Revised date"><input type="date" className="input" value={d.revised_date ?? ''} onChange={set('revised_date')} /></Field>
            <Field label="Went live"><input type="date" className="input" value={d.done_date ?? ''} onChange={set('done_date')} /></Field>
          </div>
        )}
        {section === 'other' && (
          <Field label="Date"><input type="date" className="input" value={d.event_date ?? ''} onChange={set('event_date')} /></Field>
        )}
        {section !== 'other' && (
          <Field label="Blocker" hint="What is stopping it, and what is needed to unblock">
            <textarea className="input min-h-[56px]" value={d.blocker ?? ''} onChange={set('blocker')} />
          </Field>
        )}
        {save.error ? <InlineError error={save.error} /> : null}
        {remove.error ? <InlineError error={remove.error} /> : null}
        <div className="flex items-center justify-between gap-2 pt-2">
          {item ? (
            <button type="button" className="btn text-bad" disabled={remove.isPending} onClick={() => { if (window.confirm(`Delete "${item.title}"?`)) remove.mutate(); }}>
              <IconTrash size={14} /> Delete
            </button>
          ) : <span />}
          <div className="flex gap-2">
            <button type="button" className="btn" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={save.isPending}>{save.isPending ? 'Saving…' : item ? 'Save changes' : 'Add'}</button>
          </div>
        </div>
        {item?.updated_by && <p className="text-[11px] text-muted">Last changed by {item.updated_by}</p>}
      </form>
    </Drawer>
  );
}

/** Commentary box (page 1 "went well / needs attention"). Saves on blur-free explicit Save. */
export function NoteBox({ title, value, canEdit, onSave, saving, placeholder, tone }: {
  title: string; value: string; canEdit: boolean; onSave: (v: string) => void; saving: boolean; placeholder: string; tone: 'good' | 'bad';
}) {
  const [editing, setEditing] = useState(false);
  const [v, setV] = useState(value);
  return (
    <div className="card flex min-w-0 flex-col p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className={cx('text-sm font-semibold', tone === 'good' ? 'text-good' : 'text-bad')}>{title}</h3>
        {canEdit && !editing && <button className="btn btn-sm" onClick={() => { setV(value); setEditing(true); }}>Edit</button>}
      </div>
      {editing ? (
        <>
          <textarea className="input min-h-[120px] flex-1" value={v} onChange={(e) => setV(e.target.value)} placeholder={placeholder} autoFocus />
          <div className="mt-2 flex justify-end gap-2">
            <button className="btn btn-sm" onClick={() => setEditing(false)}>Cancel</button>
            <button className="btn btn-sm btn-primary" disabled={saving} onClick={() => { onSave(v); setEditing(false); }}>Save</button>
          </div>
        </>
      ) : value ? (
        <ul className="list-disc space-y-1 pl-4 text-sm leading-relaxed text-ink">
          {value.split('\n').filter((l) => l.trim()).map((l, i) => <li key={i}>{l.replace(/^[-•*]\s*/, '')}</li>)}
        </ul>
      ) : (
        <p className="text-sm text-muted">{canEdit ? 'Nothing written yet. One point per line.' : 'Nothing written for this month yet.'}</p>
      )}
    </div>
  );
}
