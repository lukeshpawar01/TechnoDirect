import { useState, type ReactNode } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { errorMessage, post } from '@/lib/api';
import { IconEdit } from './Icons';
import { Spinner, cx } from './ui';

/**
 * An Achieved cell of the incentive table that can be typed over (perm manage_targets).
 * `children` shows the value; the pencil opens a small input. Clearing the input (or "Use calculated") goes back to
 * the value calculated from data. Edited values carry a dot and show the calculated value on hover.
 */
export function AchievedEdit({
  id,
  kpi,
  value,
  calculated,
  edited,
  editedBy,
  canEdit,
  money,
  children,
}: {
  id: number;
  kpi: 'td' | 'new' | 'gps' | 'kyc';
  value: number;
  calculated?: number;
  edited?: boolean;
  editedBy?: string | null;
  canEdit: boolean;
  money?: boolean;
  children: ReactNode;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const save = useMutation({
    mutationFn: (v: string | null) => post('/masters/incentives/sheet/achieved/', { id, kpi, value: v }),
    onSuccess: () => {
      setOpen(false);
      void qc.invalidateQueries({ queryKey: ['incentive-sheet'] });
    },
  });
  const fmt = (v: number) => (money ? `₹${Math.round(v).toLocaleString('en-IN')}` : String(v));

  if (open) {
    return (
      <form
        className="inline-flex items-center justify-end gap-1"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(text.trim() === '' ? null : text.replace(/[,₹\s]/g, ''));
        }}
      >
        <input
          autoFocus
          className={cx('input w-24 px-1.5 py-0.5 text-right text-xs tabular-nums', save.error ? 'border-bad' : undefined)}
          inputMode="decimal"
          value={text}
          placeholder={calculated !== undefined ? fmt(calculated) : fmt(value)}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
          aria-label="Achieved value"
          title={save.error ? errorMessage(save.error) : 'Enter to save, Esc to cancel. Leave empty to use the calculated value.'}
        />
        <button type="submit" className="btn btn-sm px-1.5" disabled={save.isPending} title="Save">
          {save.isPending ? <Spinner size={11} /> : '✓'}
        </button>
        {edited && (
          <button type="button" className="btn btn-sm px-1.5 text-2xs" disabled={save.isPending} onClick={() => save.mutate(null)} title="Use the value calculated from data">
            Reset
          </button>
        )}
        <button type="button" className="btn btn-sm px-1.5" onClick={() => setOpen(false)} title="Cancel">
          ✕
        </button>
      </form>
    );
  }
  return (
    <span className="group inline-flex items-center justify-end gap-1">
      {edited && (
        <span
          className="h-1.5 w-1.5 rounded-full bg-warn"
          title={`Edited${editedBy ? ` by ${editedBy}` : ''}. Calculated from data: ${calculated !== undefined ? fmt(calculated) : '–'}`}
          aria-label="Edited value"
        />
      )}
      {children}
      {canEdit && (
        <button
          type="button"
          className="rounded p-0.5 text-muted opacity-40 hover:text-brand group-hover:opacity-100"
          onClick={() => {
            setText(edited ? String(value) : '');
            save.reset();
            setOpen(true);
          }}
          title="Edit the achieved value"
          aria-label="Edit the achieved value"
        >
          <IconEdit size={12} />
        </button>
      )}
    </span>
  );
}
