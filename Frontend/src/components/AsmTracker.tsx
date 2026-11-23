import { todayIst } from '@/lib/filters';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '@/auth/AuthContext';
import type { AsmTrackerData, AsmTrackerRow } from '@/api/types';
import { download, errorMessage, get, post } from '@/lib/api';
import { date, inr, monthLabel, num, pct } from '@/lib/format';
import { IconDownload, IconEdit, IconPlus, IconUpload } from './Icons';
import { Badge, InlineError, Modal, Spinner, cx } from './ui';

/*
 * ASM tracker — the monthly targets the team maintains, in the layout of their sheet (Nov 26):
 *   Distributor · Region · ASM · Target · Order value · Orders · Share · Remaining · Achieved
 * ("Total Target Acheived" from the sheet is left out: it repeats Order value.)
 *  Export  : the month as .xlsx in that layout + an ASM summary sheet
 *  Upload  : the edited .xlsx / .csv back (ASMs, distributor ASM + region, distributor targets)
 *  Edit    : the same on screen. An ASM's target is the sum of its distributors' targets; an ASM with no
 *            distributor targets has one target for the whole ASM, edited in the ASM panel.
 * Managed from Jan 2026 (first_month).
 */

type Draft = {
  distributor_id: number;
  distributor: string;
  region: string;
  asm: string;
  target: string;
  sales: number;
  orders: number;
  suggested: number | null;
  /** as loaded: lets the server tell edited cells from untouched ones */
  asmOrig?: string;
  regionOrig?: string;
};

const monthNow = () => todayIst().format('YYYY-MM'); // India's month (toISOString is UTC: a day late until 5:30 AM IST)
const FIRST_MONTH = '2025-10'; // Oct 2025 targets were added on request; tracking otherwise starts Jan 2026

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
    asmOrig: r.asm,
    regionOrig: r.region,
    target: r.target === null ? '' : String(Math.round(r.target)),
    sales: r.sales,
    orders: r.orders,
    suggested: r.suggested ?? null,
  };
}

const money = (v: string) => (v.trim() === '' ? 0 : Number(v));
const isBad = (v: string) => v.trim() !== '' && (!Number.isFinite(Number(v)) || Number(v) < 0);
const achTone = (a: number | null) => (a === null ? 'text-muted' : a >= 100 ? 'text-good' : a >= 80 ? 'text-warn' : 'text-bad');

function Editor({ open, onClose, initialMonth }: { open: boolean; onClose: () => void; initialMonth: string }) {
  const qc = useQueryClient();
  const { can } = useAuth();
  const canAdd = can('manage_mappings');
  const clampMonth = (m: string) => (m < FIRST_MONTH ? FIRST_MONTH : m);
  const [month, setMonth] = useState(clampMonth(initialMonth));
  const [rows, setRows] = useState<Draft[]>([]);
  const [asmTargets, setAsmTargets] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState('');
  const [adding, setAdding] = useState<null | 'asm' | 'distributor'>(null);
  const [extraAsms, setExtraAsms] = useState<{ name: string; region: string }[]>([]);
  const [dirty, setDirty] = useState(false);
  const q = useTracker(month, open);
  const fc = q.data?.forecast ?? null;

  useEffect(() => setMonth(clampMonth(initialMonth)), [initialMonth, open]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (q.data) {
      setRows(q.data.rows.map(toDraft));
      setAsmTargets(Object.fromEntries(q.data.asm_summary.filter((a) => a.target_from === 'asm').map((a) => [a.asm, a.target === null ? '' : String(Math.round(a.target))])));
      setDirty(false);
    }
  }, [q.data]);

  // live per-ASM view of what is on screen
  const asms = useMemo(() => {
    const server = new Map((q.data?.asm_summary ?? []).map((a) => [a.asm, a]));
    const names = [...new Set([...rows.map((r) => r.asm.trim()).filter(Boolean), ...server.keys(), ...extraAsms.map((a) => a.name)])];
    return names
      .map((name) => {
        const mine = rows.filter((r) => r.asm.trim() === name);
        const fromDists = mine.some((r) => money(r.target) > 0);
        const target = fromDists ? mine.reduce((s, r) => s + money(r.target), 0) : asmTargets[name]?.trim() ? Number(asmTargets[name]) : null;
        const sales = mine.length ? mine.reduce((s, r) => s + r.sales, 0) : server.get(name)?.sales ?? 0;
        const withTarget = mine.filter((r) => money(r.target) > 0).length;
        const region = server.get(name)?.region ?? extraAsms.find((a) => a.name === name)?.region ?? mine[0]?.region ?? '';
        return { name, region, distributors: mine.length, withTarget, fromDists, target, sales };
      })
      .sort((a, b) => {
        const sug = q.data?.forecast?.asm ?? {};
        return (b.target ?? 0) - (a.target ?? 0) || b.sales - a.sales || (sug[b.name] ?? 0) - (sug[a.name] ?? 0);
      });
  }, [rows, asmTargets, q.data, extraAsms]);

  const totals = useMemo(() => {
    const sales = rows.reduce((s, r) => s + r.sales, 0);
    const orders = rows.reduce((s, r) => s + r.orders, 0);
    // company target = ASM targets + targets of distributors with no ASM (as saved by the server)
    const target = asms.reduce((s, a) => s + (a.target ?? 0), 0) + rows.filter((r) => !r.asm.trim()).reduce((s, r) => s + money(r.target), 0);
    return { sales, orders, target };
  }, [rows, asms]);

  const save = useMutation({
    mutationFn: () =>
      post('/masters/asm-tracker/', {
        month,
        rows: rows.map((r) => ({
          distributor_id: r.distributor_id,
          region: r.region,
          asm: r.asm.trim(),
          ...(r.asmOrig !== undefined ? { asm_orig: r.asmOrig, region_orig: r.regionOrig ?? '' } : {}),
          target: r.target.trim() === '' ? null : Number(r.target),
        })),
        asm_targets: asms.filter((a) => !a.fromDists).map((a) => ({ asm: a.name, target: asmTargets[a.name]?.trim() ? Number(asmTargets[a.name]) : null })),
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
  const bad = rows.some((r) => isBad(r.target)) || Object.values(asmTargets).some(isBad);
  const shown = rows.filter((r) => !filter || `${r.distributor} ${r.asm} ${r.region}`.toLowerCase().includes(filter.toLowerCase()));
  const asmNames = useMemo(() => [...new Set([...(q.data?.asms ?? []), ...extraAsms.map((a) => a.name), ...rows.map((r) => r.asm.trim()).filter(Boolean)])].sort(), [q.data, rows, extraAsms]);
  const ach = (sales: number, target: number | null) => (target ? (sales / target) * 100 : null);
  const splitOf = (id: number) => q.data?.rows.find((x) => x.distributor_id === id)?.split ?? [];

  return (
    <Modal
      open={open}
      onClose={() => (!dirty || window.confirm('Discard your changes?')) && onClose()}
      xl
      title={
        <span className="flex items-center gap-3">
          Edit ASM &amp; targets
          <input
            type="month"
            className="input w-40 py-1 text-xs"
            value={month}
            min={q.data?.first_month ?? FIRST_MONTH}
            onChange={(e) => setMonth(clampMonth(e.target.value || monthNow()))}
            aria-label="Target month"
          />
        </span>
      }
      footer={
        <>
          <span className="mr-auto text-xs text-muted">
            {q.data?.managed_by_sheet ? (
              <span className="font-medium text-warn">
                {monthLabel(month)} targets come from the incentive sheet (TD_ASM_Executive_Incentive_Tracker). Change them with "Edit incentive sheet" on this page.{' '}
              </span>
            ) : null}
            Targets in ₹ for {monthLabel(month)}. An ASM's target is the sum of its distributors' targets; for an ASM without distributor targets, set it in the ASM panel. Type a new name in ASM to add an ASM.
          </span>
          <button className="btn btn-sm" onClick={onClose} disabled={save.isPending}>
            Cancel
          </button>
          <button className="btn-primary btn-sm" onClick={() => save.mutate()} disabled={save.isPending || !rows.length || bad || !!q.data?.managed_by_sheet}>
            {save.isPending && <Spinner size={12} />} Save {monthLabel(month)}
          </button>
        </>
      }
    >
      {q.isLoading ? (
        <div className="py-10 text-center text-sm text-muted">Loading…</div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <input className="input min-w-[14rem] flex-1 py-1.5 text-xs" placeholder="Search distributor, ASM or region…" value={filter} onChange={(e) => setFilter(e.target.value)} />
              {canAdd && (
                <>
                  <button type="button" className={cx('btn btn-sm', adding === 'asm' && 'bg-sunken')} onClick={() => setAdding(adding === 'asm' ? null : 'asm')} aria-expanded={adding === 'asm'}>
                    <IconPlus size={13} /> Add ASM
                  </button>
                  <button type="button" className={cx('btn btn-sm', adding === 'distributor' && 'bg-sunken')} onClick={() => setAdding(adding === 'distributor' ? null : 'distributor')} aria-expanded={adding === 'distributor'}>
                    <IconPlus size={13} /> Add distributor
                  </button>
                </>
              )}
            </div>
            {fc && (
              <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-brand/25 bg-brand/5 px-3 py-2 text-xs text-ink2">
                <span>
                  <span className="font-semibold text-ink">Suggested target</span> by TD Target Forecaster, made on {date(fc.as_of)} from sales and targets up to then
                  {fc.overall ? <> · total {inr(fc.overall, { compact: true })}</> : null}.
                </span>
                {fc.wape_vs_set !== null && (
                  <span title="Weighted average gap between the suggested and the set ASM targets (WAPE)">
                    Off from the set targets by <span className="font-semibold text-ink">{pct(fc.wape_vs_set, 1)}</span>
                  </span>
                )}
                <button
                  type="button"
                  className="btn btn-sm ml-auto"
                  onClick={() => {
                    const fill = (r: Draft) => (r.target.trim() === '' && r.suggested ? { ...r, target: String(Math.round(r.suggested)) } : r);
                    setRows((rs) => rs.map(fill));
                    setAsmTargets((m) => {
                      const next = { ...m };
                      for (const a of asms) if (!a.fromDists && !(next[a.name] ?? '').trim() && fc.asm[a.name]) next[a.name] = String(Math.round(fc.asm[a.name]));
                      return next;
                    });
                    setDirty(true);
                  }}
                  title="Copy the suggestions into every empty target box (filled ones are kept)"
                >
                  Fill empty targets with suggestions
                </button>
              </div>
            )}
            {adding && q.data && (
              <AddForm
                key={adding}
                kind={adding}
                data={q.data}
                asmNames={asmNames}
                onCancel={() => setAdding(null)}
                onAdded={(item) => {
                  setAdding(null);
                  // keep unsaved edits: insert into the open editor instead of reloading it
                  if (item.kind === 'asm') setExtraAsms((xs) => [...xs, { name: item.name, region: item.region }]);
                  else {
                    setRows((rs) => [{ distributor_id: item.id, distributor: item.name, region: item.region, asm: item.asm, target: '', sales: 0, orders: 0, suggested: null }, ...rs]);
                    setFilter('');
                  }
                  void qc.invalidateQueries({ predicate: (x) => x.queryKey[0] !== 'asm-tracker' });
                }}
              />
            )}
            <datalist id="asm-names">
              {asmNames.map((n) => (
                <option key={n} value={n} />
              ))}
            </datalist>
            <div className="max-h-[60vh] overflow-auto rounded-md border border-line">
              <table className="w-full text-xs tabular">
                <thead className="sticky top-0 z-10 bg-sunken text-left text-muted">
                  <tr>
                    <th className="px-2 py-2 font-medium">Distributor</th>
                    <th className="px-2 py-2 font-medium">Region</th>
                    <th className="px-2 py-2 font-medium">ASM</th>
                    <th className="px-2 py-2 text-right font-medium">Target (₹)</th>
                    {fc && (
                      <th className="px-2 py-2 text-right font-medium" title="TD Target Forecaster suggestion · click a value to use it">
                        Suggested target
                      </th>
                    )}
                    <th className="px-2 py-2 text-right font-medium">Order value</th>
                    <th className="px-2 py-2 text-right font-medium">Orders</th>
                    <th className="px-2 py-2 text-right font-medium" title="Share of the month's order value">Share</th>
                    <th className="px-2 py-2 text-right font-medium">Remaining</th>
                    <th className="px-2 py-2 text-right font-medium">Achieved</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r) => {
                    const t = money(r.target);
                    const a = ach(r.sales, t || null);
                    return (
                      <tr key={r.distributor_id} className="border-t border-line">
                        <td className="px-2 py-1.5 font-medium text-ink">{r.distributor}</td>
                        <td className="px-2 py-1.5">
                          <select className="input w-24 py-1 text-xs" value={r.region} onChange={(e) => set(r.distributor_id, { region: e.target.value })}>
                            <option value="">–</option>
                            {(q.data?.regions ?? []).map((g) => (
                              <option key={g} value={g}>
                                {g}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="px-2 py-1.5">
                          <input className="input w-32 py-1 text-xs" list="asm-names" value={r.asm} placeholder="No ASM" onChange={(e) => set(r.distributor_id, { asm: e.target.value })} />
                        </td>
                        <td className="px-2 py-1.5 text-right">
                          <input
                            className={cx('input w-28 py-1 text-right text-xs', isBad(r.target) && 'border-bad')}
                            inputMode="numeric"
                            value={r.target}
                            placeholder="–"
                            onChange={(e) => set(r.distributor_id, { target: e.target.value.replace(/[^\d.]/g, '') })}
                            aria-label={`Target for ${r.distributor}`}
                            disabled={!!q.data?.managed_by_sheet}
                          />
                          {!!splitOf(r.distributor_id).length && (
                            <div className="mt-0.5 space-y-px text-right text-[10px] leading-tight text-muted">
                              {splitOf(r.distributor_id).map((p, i) => (
                                <div key={i} className="whitespace-nowrap">
                                  {p.person}
                                  {p.role === 'executive' ? ' (Exec)' : ''} {inr(p.value, { compact: true })}
                                </div>
                              ))}
                            </div>
                          )}
                        </td>
                        {fc && (
                          <td className="px-2 py-1.5 text-right">
                            {r.suggested ? (
                              <button
                                type="button"
                                className="rounded px-1 text-brand underline decoration-dotted underline-offset-2 hover:bg-brand/10"
                                title={`Use ${inr(r.suggested)} as the target`}
                                onClick={() => set(r.distributor_id, { target: String(Math.round(r.suggested ?? 0)) })}
                              >
                                {inr(r.suggested, { compact: true })}
                              </button>
                            ) : (
                              <span className="text-muted">–</span>
                            )}
                          </td>
                        )}
                        <td className="px-2 py-1.5 text-right text-ink">{inr(r.sales, { compact: true })}</td>
                        <td className="px-2 py-1.5 text-right text-ink2">{num(r.orders)}</td>
                        <td className="px-2 py-1.5 text-right text-ink2">{totals.sales ? pct((r.sales / totals.sales) * 100, 1) : '–'}</td>
                        <td className="px-2 py-1.5 text-right text-ink2">{t ? inr(Math.max(t - r.sales, 0), { compact: true }) : <span className="text-muted">–</span>}</td>
                        <td className={cx('px-2 py-1.5 text-right font-medium', achTone(a))}>{a === null ? <span className="font-normal text-muted">–</span> : pct(a, 0)}</td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot className="sticky bottom-0 bg-sunken font-semibold text-ink">
                  <tr className="border-t border-line">
                    <td className="px-2 py-2" colSpan={3}>
                      Total
                    </td>
                    <td className="px-2 py-2 text-right">{totals.target ? inr(totals.target, { compact: true }) : '–'}</td>
                    {fc && <td className="px-2 py-2 text-right text-brand">{fc.overall ? inr(fc.overall, { compact: true }) : '–'}</td>}
                    <td className="px-2 py-2 text-right">{inr(totals.sales, { compact: true })}</td>
                    <td className="px-2 py-2 text-right">{num(totals.orders)}</td>
                    <td className="px-2 py-2 text-right">100%</td>
                    <td className="px-2 py-2 text-right">{totals.target ? inr(Math.max(totals.target - totals.sales, 0), { compact: true }) : '–'}</td>
                    <td className={cx('px-2 py-2 text-right', achTone(ach(totals.sales, totals.target || null)))}>{totals.target ? pct(ach(totals.sales, totals.target), 0) : '–'}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
          <aside className="min-w-0">
            <div className="mb-1 text-xs font-semibold text-ink">ASM targets ({monthLabel(month)})</div>
            <p className="mb-2 text-[11px] leading-snug text-muted">Set by distributor targets, or one target for the ASM when none of their distributors has a target.</p>
            <div className="max-h-[60vh] space-y-1.5 overflow-auto pr-1">
              {asms.map((a) => {
                const pa = ach(a.sales, a.target);
                return (
                  <div key={a.name} className="rounded-md border border-line px-2.5 py-1.5 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium text-ink">
                        {a.name}
                        {a.region && <span className="ml-1 font-normal text-muted">{a.region}</span>}
                      </span>
                      <span className={cx('font-medium', achTone(pa))}>{pa === null ? '–' : pct(pa, 0)}</span>
                    </div>
                    {fc?.asm[a.name] !== undefined && (
                      <div className="mt-0.5 flex items-center justify-between gap-2 text-[11px] text-brand">
                        <span>Suggested {inr(fc.asm[a.name], { compact: true })}</span>
                        {!a.fromDists && (
                          <button
                            type="button"
                            className="underline decoration-dotted underline-offset-2"
                            onClick={() => {
                              setAsmTargets((m) => ({ ...m, [a.name]: String(Math.round(fc.asm[a.name])) }));
                              setDirty(true);
                            }}
                          >
                            Use
                          </button>
                        )}
                      </div>
                    )}
                    <div className="mt-1 flex items-center justify-between gap-2 text-muted">
                      <span>{inr(a.sales, { compact: true })} sold</span>
                      {a.fromDists ? (
                        <span title="Sum of this ASM's distributor targets">
                          target {inr(a.target, { compact: true })} <span className="text-[10px]">· {num(a.withTarget)} of {num(a.distributors)} dist.</span>
                        </span>
                      ) : (
                        <input
                          className={cx('input w-24 py-0.5 text-right text-xs', isBad(asmTargets[a.name] ?? '') && 'border-bad')}
                          inputMode="numeric"
                          placeholder="ASM target"
                          value={asmTargets[a.name] ?? ''}
                          onChange={(e) => {
                            setAsmTargets((m) => ({ ...m, [a.name]: e.target.value.replace(/[^\d.]/g, '') }));
                            setDirty(true);
                          }}
                          aria-label={`ASM target for ${a.name}`}
                        />
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </aside>
        </div>
      )}
      <InlineError error={q.error ?? save.error} />
    </Modal>
  );
}

type Added = { kind: 'asm'; name: string; region: string } | { kind: 'distributor'; id: number; name: string; region: string; asm: string };

/** Inline form in the editor: add an ASM (name as on the sheets, region, RSM, joining date) or a distributor. */
function AddForm({ kind, data, asmNames, onCancel, onAdded }: { kind: 'asm' | 'distributor'; data: AsmTrackerData; asmNames: string[]; onCancel: () => void; onAdded: (a: Added) => void }) {
  const [f, setF] = useState<Record<string, string>>({});
  const set = (k: string, v: string) => setF((x) => ({ ...x, [k]: v }));
  const regionRsm = (region: string) => data.rsms.find((r) => r.region === region);
  const state = data.states.find((s) => String(s.id) === f.state_id);

  const m = useMutation({
    mutationFn: () =>
      kind === 'asm'
        ? post<{ id: number; name: string }>('/masters/asm-tracker/asm/', {
            name: f.name,
            full_name: f.full_name,
            region: f.region,
            rsm_id: f.rsm_id ? Number(f.rsm_id) : null,
            joined_on: f.joined_on || null,
          })
        : post<{ id: number; name: string }>('/masters/asm-tracker/distributor/', { name: f.name, state_id: Number(f.state_id), city: f.city, asm: f.asm }),
    onSuccess: (r) =>
      onAdded(kind === 'asm' ? { kind, name: r.name, region: f.region ?? '' } : { kind, id: r.id, name: r.name, region: state?.region ?? '', asm: (f.asm ?? '').trim() }),
  });
  const ready = kind === 'asm' ? !!f.name?.trim() && !!f.region : !!f.name?.trim() && !!f.state_id;
  const field = 'flex flex-col gap-1 text-[11px] text-muted';

  return (
    <form
      className="mb-3 rounded-md border border-line bg-sunken/50 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) m.mutate();
      }}
    >
      <div className="mb-2 text-xs font-semibold text-ink">{kind === 'asm' ? 'Add an ASM' : 'Add a distributor'}</div>
      {kind === 'asm' ? (
        <div className="grid gap-2 sm:grid-cols-5">
          <label className={field}>
            Name on the sheets *
            <input className="input py-1 text-xs" value={f.name ?? ''} onChange={(e) => set('name', e.target.value)} placeholder="e.g. Ravi" autoFocus />
          </label>
          <label className={field}>
            Full name
            <input className="input py-1 text-xs" value={f.full_name ?? ''} onChange={(e) => set('full_name', e.target.value)} placeholder="Ravi Kumar" />
          </label>
          <label className={field}>
            Region *
            <select
              className="input py-1 text-xs"
              value={f.region ?? ''}
              onChange={(e) => {
                const region = e.target.value;
                setF((x) => ({ ...x, region, rsm_id: String(regionRsm(region)?.id ?? '') }));
              }}
            >
              <option value="">Choose…</option>
              {data.regions.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
          <label className={field}>
            Reports to (RSM)
            <select className="input py-1 text-xs" value={f.rsm_id ?? ''} onChange={(e) => set('rsm_id', e.target.value)}>
              <option value="">RSM of the region</option>
              {data.rsms.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                  {r.region ? ` (${r.region})` : ''}
                </option>
              ))}
            </select>
          </label>
          <label className={field}>
            Joined on
            <input type="date" className="input py-1 text-xs" value={f.joined_on ?? ''} onChange={(e) => set('joined_on', e.target.value)} />
          </label>
        </div>
      ) : (
        <div className="grid gap-2 sm:grid-cols-4">
          <label className={field}>
            Distributor name *
            <input className="input py-1 text-xs" value={f.name ?? ''} onChange={(e) => set('name', e.target.value)} placeholder="e.g. Noble Sports" autoFocus />
          </label>
          <label className={field}>
            State *
            <select className="input py-1 text-xs" value={f.state_id ?? ''} onChange={(e) => set('state_id', e.target.value)}>
              <option value="">Choose…</option>
              {data.states.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            {state && <span>Region: {state.region ?? 'not set'}</span>}
          </label>
          <label className={field}>
            City
            <input className="input py-1 text-xs" value={f.city ?? ''} onChange={(e) => set('city', e.target.value)} />
          </label>
          <label className={field}>
            ASM
            <input className="input py-1 text-xs" list="asm-names" value={f.asm ?? ''} onChange={(e) => set('asm', e.target.value)} placeholder="No ASM" />
            <span>Pick from {asmNames.length} ASMs; add a new one with Add ASM first</span>
          </label>
        </div>
      )}
      <div className="mt-2 flex items-center justify-end gap-2">
        {m.error && <span className="mr-auto text-xs text-bad">{errorMessage(m.error)}</span>}
        <button type="button" className="btn btn-sm" onClick={onCancel} disabled={m.isPending}>
          Cancel
        </button>
        <button type="submit" className="btn-primary btn-sm" disabled={!ready || m.isPending}>
          {m.isPending && <Spinner size={12} />} {kind === 'asm' ? 'Add ASM' : 'Add distributor'}
        </button>
      </div>
      {kind === 'distributor' && <p className="mt-1 text-[11px] text-muted">The new distributor appears at the top of the table: set its target there, then save the month.</p>}
    </form>
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
