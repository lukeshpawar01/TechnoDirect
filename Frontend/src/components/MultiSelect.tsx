import { useEffect, useMemo, useRef, useState } from 'react';
import { IconCheck, IconChevronDown, IconSearch } from './Icons';
import { cx } from './ui';

export interface Option {
  value: string;
  label: string;
}

export function MultiSelect({
  label,
  options,
  value,
  onChange,
  placeholder = 'All',
  disabled,
  single,
  width = 'w-40',
}: {
  label: string;
  options: Option[];
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  single?: boolean;
  width?: string;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const k = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', h);
    document.addEventListener('keydown', k);
    return () => {
      document.removeEventListener('mousedown', h);
      document.removeEventListener('keydown', k);
    };
  }, [open]);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    return s ? options.filter((o) => o.label.toLowerCase().includes(s)) : options;
  }, [options, q]);

  const selectedLabels = options.filter((o) => value.includes(o.value)).map((o) => o.label);
  const summary = value.length === 0 ? placeholder : value.length === 1 ? (selectedLabels[0] ?? '1 selected') : `${value.length} selected`;

  function toggle(v: string) {
    if (single) {
      onChange(value.includes(v) ? [] : [v]);
      setOpen(false);
      return;
    }
    onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  }

  return (
    <div className={cx('relative', width)} ref={ref}>
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={cx(
          'flex w-full items-center justify-between gap-1 rounded-md border bg-surface px-2.5 py-1.5 text-left text-xs disabled:opacity-50',
          value.length ? 'border-brand/50' : 'border-line',
        )}
      >
        <span className="min-w-0 truncate">
          <span className="text-muted">{label}: </span>
          <span className={cx('font-medium', value.length ? 'text-ink' : 'text-ink2')}>{summary}</span>
        </span>
        <IconChevronDown size={12} className="shrink-0 text-muted" />
      </button>
      {open && (
        <div className="absolute left-0 z-40 mt-1 w-64 rounded-md border border-line bg-surface shadow-lg" role="listbox" aria-multiselectable={!single}>
          {options.length > 8 && (
            <div className="flex items-center gap-1.5 border-b border-line px-2 py-1.5">
              <IconSearch size={13} className="text-muted" />
              <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search ${label.toLowerCase()}…`} className="w-full bg-transparent text-xs outline-none placeholder:text-muted" />
            </div>
          )}
          <div className="max-h-64 overflow-y-auto py-1">
            {filtered.length === 0 && <div className="px-3 py-2 text-xs text-muted">No matches</div>}
            {filtered.map((o) => {
              const sel = value.includes(o.value);
              return (
                <button
                  key={o.value}
                  type="button"
                  role="option"
                  aria-selected={sel}
                  onClick={() => toggle(o.value)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-sunken"
                >
                  <span className={cx('flex h-4 w-4 shrink-0 items-center justify-center rounded border', sel ? 'border-brand bg-brand text-white' : 'border-line')}>
                    {sel && <IconCheck size={11} strokeWidth={3} />}
                  </span>
                  <span className={cx('truncate', sel && 'font-semibold')}>{o.label}</span>
                </button>
              );
            })}
          </div>
          {value.length > 0 && (
            <div className="flex justify-between border-t border-line px-3 py-1.5">
              <button className="text-xs text-ink2 hover:text-ink" onClick={() => onChange([])}>
                Clear
              </button>
              <button className="text-xs font-medium text-brand dark:text-ink" onClick={() => setOpen(false)}>
                Done
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
