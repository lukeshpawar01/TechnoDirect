import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '@/auth/AuthContext';
import type { AsmTrackerData, AsmTrackerRow } from '@/api/types';
import { download, errorMessage, get, post } from '@/lib/api';
import { inr, num, pct } from '@/lib/format';
import { IconDownload, IconEdit, IconUpload } from './Icons';
import { Badge, InlineError, Modal, Spinner, cx } from './ui';

/*
 * ASM tracker — the targets the team maintains in Excel.
 *  Export  : tracker for a month as .xlsx (same layout the team uses) + ASM summary sheet
 *  Upload  : the edited .xlsx / .csv back (sets ASMs, distributor ASM + region, month targets)
 *  Edit    : the same on screen, with a live per-ASM summary
 */

type Draft = { distributor_id: number; distributor: string; region: string; asm: string; target: string; sales: number; orders: number };

const monthNow = () => new Date().toISOString().slice(0, 7);

function useTracker(month: string, enabled: boolean) {
  return useQuery({
    queryKey: ['asm-tracker', month],
    queryFn: () => get<AsmTrackerData>('/masters/asm-tracker/', { month }),
    enabled,
    staleTime: 60_000,
  });
}

function toDraft(r: AsmTrackerRow): Draft {
  return {
    distributor_id: r.distributor_id,
    distributor: r.distributor,
    region: r.region,
    asm: r.asm,
    target: r.target === null ? '' : String(Math.round(r.target)),
    sales: r.sales,
    orders: r.orders,
  };
}

function Editor({ open, onClose, initialMonth }: { open: boolean; onClose: () => void; initialMonth: string }) {
  const qc = useQueryClient();
  const [month, setMonth] = useState(initialMonth);
  const [rows, setRows] = useState<Draft[]>([]);
  const [filter, setFilter] = useState('');
  const [dirty, setDirty] = useState(false);
  const q = useTracker(month, open);

  useEffect(() => setMonth(initialMonth), [initialMonth, open]);
  useEffect(() => {
    if (q.data) {
      setRows(q.data.rows.map(toDraft));
      setDirty(false);
    }
  }, [q.data]);

  const save = useMutation({
    mutationFn: () =>
      post('/masters/asm-tracker/', {
        month,
        rows: rows.map((r) => ({ distributor_id: r.distributor_id, region: r.region, asm: r.asm.trim(), target: r.target.trim() === '' ? null : Number(r.target) })),
      }),
    onSuccess: () => {
      void qc.invalidateQueries();
      onClose();
    },
  });

  const set = (id: number, patch: Partial<Draft>) => {
    setRows((rs) => rs.map((r) => (r.distributor_id === id ? { ...r, ...patch } : r)));
    setDirty(true);
  };

  // live per-ASM roll-up of what is on screen
  const summary = useMemo(() => {
    const m = new Map<string, { asm: string; target: number; sales: number; distributors: number }>();
    for (const r of rows) {
      const key = r.asm.trim() || '—';
      const cur = m.get(key) ?? { asm: key, target: 0, sales: 0, distributors: 0 };
      cur.target += Number(r.target) || 0;
      cur.sales += r.sales;
      cur.distributors += 1;
      m.set(key, cur);
    }
    return [...m.values()].sort((a, b) => b.target - a.target);
  }, [rows]);
  const totalTarget = rows.reduce((s, r) => s + (Number(r.target) || 0), 0);
  const badTarget = rows.some((r) => r.target.trim() !== '' && (!Number.isFinite(Number(r.target)) || Number(r.target) < 0));
  const shown = rows.filter((r) => !filter || `${r.distributor} ${r.asm} ${r.region}`.toLowerCase().includes(filter.toLowerCase()));
  const asmNames = useMemo(() => [...new Set([...(q.data?.asms ?? []), ...rows.map((r) => r.asm.trim()).filter(Boolean)])].sort(), [q.data, rows]);

  return (
    <Modal
      open={open}
      onClose={() => (!dirty || window.confirm('Discard your changes?')) && onClose()}
      xl
      title={
        <span className="flex items-center gap-3">
          Edit ASM &amp; targets
          <input type="month" className="input w-40 py-1 text-xs" value={month} onChange={(e) => setMonth(e.target.value || monthNow())} aria-label="Target month" />
        </span>
      }
      footer={
        <>
          <span className="mr-auto text-xs text-muted">
            Total target {inr(totalTarget, { compact: true })} · type a new name in ASM to add an ASM · blank target = covered by the ASM's target
          </span>
          <button className="btn btn-sm" onClick={onClose} disabled={save.isPending}>
            Cancel
          </button>
          <button className="btn-primary btn-sm" onClick={() => save.mutate()} disabled={save.isPending || !rows.length || badTarget}>
            {save.isPending && <Spinner size={12} />} Save for {month}
          </button>
        </>
      }
    >
      {q.isLoading ? (
        <div className="py-10 text-center text-sm text-muted">Loading…</div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
          <div>
            <input className="input mb-2 py-1.5 text-xs" placeholder="Search distributor, ASM or region…" value={filter} onChange={(e) => setFilter(e.target.value)} />
            <datalist id="asm-names">
              {asmNames.map((n) => (
                <option key={n} value={n} />
              ))}
            </datalist>
            <div className="overflow-x-auto rounded-md border border-line">
              <table className="w-full text-xs">
                <thead className="bg-sunken text-left text-muted">
                  <tr>
                    <th className="px-2 py-2 font-medium">Distributor</th>
                    <th className="px-2 py-2 font-medium">Region</th>
                    <th className="px-2 py-2 font-medium">ASM</th>
                    <th className="px-2 py-2 text-right font-medium">Target (₹)</th>
                    <th className="px-2 py-2 text-right font-medium">Sales {month}</th>
                    <th className="px-2 py-2 text-right font-medium">Achieved</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r) => {
                    const t = Number(r.target) || 0;
                    const invalid = r.target.trim() !== '' && (!Number.isFinite(Number(r.target)) || Number(r.target) < 0);
                    return (
                      <tr key={r.distributor_id} className="border-t border-line">
                        <td className="px-2 py-1.5 font-medium text-ink">{r.distributor}</td>
                        <td className="px-2 py-1.5">
                          <select className="input w-28 py-1 text-xs" value={r.region} onChange={(e) => set(r.distributor_id, { region: e.target.value })}>
                            <option value="">—</option>
                            {(q.data?.regions ?? []).map((g) => (
                              <option key={g} value={g}>
                                {g}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="px-2 py-1.5">
                          <input className="input w-36 py-1 text-xs" list="asm-names" value={r.asm} placeholder="No ASM" onChange={(e) => set(r.distributor_id, { asm: e.target.value })} />
                        </td>
                        <td className="px-2 py-1.5 text-right">
                          <input
                            className={cx('input w-32 py-1 text-right text-xs', invalid && 'border-bad')}
                            inputMode="numeric"
                            value={r.target}
                            placeholder="—"
                            onChange={(e) => set(r.distributor_id, { target: e.target.value.replace(/[^\d.]/g, '') })}
                            aria-label={`Target for ${r.distributor}`}
                          />
                        </td>
                        <td className="px-2 py-1.5 text-right text-ink2">{inr(r.sales, { compact: true })}</td>
                        <td className="px-2 py-1.5 text-right">{t ? pct((r.sales / t) * 100, 0) : <span className="text-muted">–</span>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
          <aside>
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">ASM summary (live)</div>
            <div className="space-y-1.5">
              {summary.map((s) => (
                <div key={s.asm} className="rounded-md border border-line px-2.5 py-1.5 text-xs">
                  <div className="flex justify-between font-medium text-ink">
                    <span className="truncate">{s.asm}</span>
                    <span>{s.target ? pct((s.sales / s.target) * 100, 0) : '–'}</span>
                  </div>
                  <div className="text-muted">
                    {num(s.distributors)} dist · {inr(s.sales, { compact: true })} / {s.target ? inr(s.target, { compact: true }) : 'no target'}
                  </div>
                </div>
              ))}
            </div>
          </aside>
        </div>
      )}
      <InlineError error={q.error ?? save.error} />
    </Modal>
  );
}

/** Buttons for the Territory page: Export / Upload / Edit the monthly ASM tracker. */
export function AsmTrackerActions({ month }: { month?: string }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const m = month || monthNow();
  const [editing, setEditing] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const canEdit = can('manage_targets') && can('manage_mappings');
  const canExport = can('export_data');

  const exp = useMutation({ mutationFn: () => download('/masters/asm-tracker/', { month: m, download: 'xlsx' }, `ASM_tracker_${m}.xlsx`) });
  const upload = useMutation({
    mutationFn: (f: File) => {
      const fd = new FormData();
      fd.append('file', f);
      fd.append('month', m);
      return post<{ saved: number; result: { targets?: Record<string, number> } }>('/masters/asm-tracker/upload/', fd);
    },
    onSuccess: (r) => {
      setResult(`Uploaded ${num(r.saved)} distributors for ${m}.`);
      void qc.invalidateQueries();
    },
  });

  if (!canExport && !canEdit) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {canExport && (
        <button className="btn btn-sm" onClick={() => exp.mutate()} disabled={exp.isPending} title={`Download the ASM tracker for ${m} as Excel`}>
          {exp.isPending ? <Spinner size={12} /> : <IconDownload size={13} />} Export ASM tracker
        </button>
      )}
      {canEdit && (
        <>
          <button className="btn btn-sm" onClick={() => fileRef.current?.click()} disabled={upload.isPending} title={`Upload the edited tracker for ${m}`}>
            {upload.isPending ? <Spinner size={12} /> : <IconUpload size={13} />} Upload tracker
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.csv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = '';
              if (f && window.confirm(`Replace the ASM tracker for ${m} with "${f.name}"?`)) upload.mutate(f);
            }}
          />
          <button className="btn-primary btn-sm" onClick={() => setEditing(true)}>
            <IconEdit size={13} /> Edit ASM &amp; targets
          </button>
          <Editor open={editing} onClose={() => setEditing(false)} initialMonth={m} />
        </>
      )}
      {result && (
        <Badge tone="good" icon>
          {result}
        </Badge>
      )}
      {(exp.error || upload.error) && <span className="text-xs text-bad">{errorMessage(exp.error ?? upload.error)}</span>}
    </div>
  );
}
