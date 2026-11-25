import { useState } from 'react';
import { Card, cx } from '@/components/ui';
import { IconPlus } from '@/components/Icons';
import { ItemEditor, Verdict, dmy } from './shared';
import type { MbrItem, MbrNotes } from './types';

const LANE_STYLE: Record<string, string> = { win: 'border-t-good', risk: 'border-t-bad' };

export function Developments({ notes, month }: { notes: MbrNotes; month: string }) {
  const [edit, setEdit] = useState<{ item?: MbrItem; kind?: string } | null>(null);
  const items = notes.items.filter((i) => i.section === 'other');
  const kinds = notes.choices.kinds.other;
  const count = (k: string) => items.filter((i) => i.kind === k).length;
  // wins and risks always shown; other kinds only when they have something
  const lanes = kinds.filter((k) => k.value === 'win' || k.value === 'risk' || count(k.value) > 0);
  const empty = kinds.filter((k) => !lanes.includes(k));

  return (
    <>
      <Verdict
        tone={count('risk') ? 'warn' : 'brand'}
        label={`${items.length} development${items.length === 1 ? '' : 's'}`}
        aside={notes.can_edit ? <button className="btn btn-sm" onClick={() => setEdit({})}><IconPlus size={13} /> Add development</button> : undefined}
      >
        {items.length ? (
          <>
            {count('win')} win{count('win') === 1 ? '' : 's'} and {count('risk')} risk{count('risk') === 1 ? '' : 's'} this month
            {items.length - count('win') - count('risk') > 0 ? <>, plus {items.length - count('win') - count('risk')} other updates on people, partners, policy and the market</> : null}.
          </>
        ) : (
          <>Anything leadership should know that is not in the numbers: wins, risks, people changes, partnerships, policy and compliance, competitors.</>
        )}
      </Verdict>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {lanes.map((k) => {
          const mine = items.filter((i) => i.kind === k.value).sort((a, b) => (b.event_date ?? '').localeCompare(a.event_date ?? ''));
          return (
            <Card
              key={k.value}
              className={cx('border-t-2', LANE_STYLE[k.value] ?? 'border-t-brand')}
              title={`${k.label}${mine.length ? ` · ${mine.length}` : ''}`}
              actions={notes.can_edit ? <button className="rounded p-1 text-muted hover:bg-sunken hover:text-ink" title={`Add ${k.label.toLowerCase()}`} aria-label={`Add ${k.label.toLowerCase()}`} onClick={() => setEdit({ kind: k.value })}><IconPlus size={14} /></button> : undefined}
            >
              {mine.length === 0 ? (
                <p className="text-sm text-muted">None recorded.</p>
              ) : (
                <ul className="space-y-3">
                  {mine.map((i) => (
                    <li key={i.id} className={cx('rounded-md', notes.can_edit && '-m-1.5 cursor-pointer p-1.5 hover:bg-sunken/50')} onClick={notes.can_edit ? () => setEdit({ item: i }) : undefined}>
                      <div className="text-sm font-medium text-ink">{i.title}</div>
                      {i.detail && <p className="mt-0.5 whitespace-pre-line text-xs leading-relaxed text-ink2">{i.detail}</p>}
                      <div className="mt-1 text-2xs text-muted">{[i.event_date ? dmy(i.event_date) : null, i.owner].filter(Boolean).join(' · ')}</div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          );
        })}
      </div>
      {notes.can_edit && empty.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
          Also add:
          {empty.map((k) => <button key={k.value} className="btn btn-sm" onClick={() => setEdit({ kind: k.value })}><IconPlus size={12} /> {k.label}</button>)}
        </div>
      )}

      {edit && <ItemEditor notes={notes} month={month} section="other" item={edit.item} kind={edit.kind} onClose={() => setEdit(null)} />}
    </>
  );
}
