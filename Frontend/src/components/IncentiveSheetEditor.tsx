import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, get } from '@/lib/api';
import { inr, monthLabel, num } from '@/lib/format';
import { todayIst } from '@/lib/filters';
import { IconPlus } from './Icons';
import { InlineError, Modal, Spinner, cx } from './ui';

interface EditRow {
  key: number;
  distributor_id: number | '';
  role: 'asm' | 'executive';
  person: string;
  td_target: string;
  new_target: string;
  gps_target: string;
  kyc_target: string;
  eligible: string;
}
interface ApiRow {
  distributor_id: number;
  role: 'asm' | 'executive';
  person: string;
  td_target: number;
  new_target: number | null;
  gps_target: number | null;
  kyc_target: number | null;
  eligible: number | null;
}
interface EditorData {
  month: string;
  rows: ApiRow[];
  copied_from: string | null;
  owner: 'sheet' | 'dashboard' | null;
  source: string | null;
  distributors: { id: number; name: string; region: string; state: string }[];
  people: { asm: string[]; executive: string[] };
}

let nextKey = 1;
const s = (v: number | null | undefined) => (v === null || v === undefined ? '' : String(v));
const toEdit = (r: ApiRow): EditRow => ({
  key: nextKey++,
  distributor_id: r.distributor_id,
  role: r.role,
  person: r.person,
  td_target: s(r.td_target),
  new_target: s(r.new_target),
  gps_target: s(r.gps_target),
  kyc_target: s(r.kyc_target),
  eligible: s(r.eligible),
});
const blank = (from?: EditRow): EditRow => ({
  key: nextKey++,
  distributor_id: from?.distributor_id ?? '',
  role: 'executive',
  person: '',
  td_target: '',
  new_target: '',
  gps_target: '',
  kyc_target: '',
  eligible: '',
});
const badNum = (v: string, whole = false) => v.trim() !== '' && (!/^\d+(\.\d+)?$/.test(v.trim()) || (whole && v.includes('.')));

/**
 * Edit the incentive sheet (TD_ASM_Executive_Incentive_Tracker) for one month, in the sheet's own columns.
 * A month without rows opens as a copy of the last month. Saving replaces that month's targets.
 */
export function IncentiveSheetEditor({ open, onClose, initialMonth }: { open: boolean; onClose: () => void; initialMonth: string }) {
  const qc = useQueryClient();
  const [month, setMonth] = useState(initialMonth);
  const [rows, setRows] = useState<EditRow[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setMonth(initialMonth);
      setSaved(null);
    }
  }, [open, initialMonth]);

  const q = useQuery({
    queryKey: ['incentive-sheet-edit', month],
    queryFn: () => get<EditorData>('/masters/incentives/sheet/edit/', { month }),
    enabled: open && !!month,
    staleTime: 0,
  });
  useEffect(() => {
    if (q.data) {
      setRows(q.data.rows.map(toEdit));
      setDirty(!!q.data.copied_from);
    }
  }, [q.data]);

  const dists = useMemo(() => new Map((q.data?.distributors ?? []).map((d) => [d.id, d])), [q.data]);
  const save = useMutation({
    mutationFn: () =>
      api
        .put<{ saved: number }>('/masters/incentives/sheet/edit/', {
          month,
          rows: rows.map((r) => ({
            distributor_id: r.distributor_id,
            role: r.role,
            person: r.person.trim(),
            td_target: r.td_target.trim(),
            new_target: r.new_target.trim(),
            gps_target: r.gps_target.trim(),
            kyc_target: r.kyc_target.trim(),
            eligible: r.eligible.trim(),
          })),
        })
        .then((res) => res.data),
    onSuccess: (r) => {
      setDirty(false);
      setSaved(`Saved ${num(r.saved)} rows for ${monthLabel(month)}.`);
      void qc.invalidateQueries();
    },
  });

  const set = (key: number, patch: Partial<EditRow>) => {
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
    setDirty(true);
    setSaved(null);
  };
  const insertAfter = (key: number | null) => {
    setRows((rs) => {
      const i = key === null ? rs.length - 1 : rs.findIndex((r) => r.key === key);
      const out = [...rs];
      out.splice(i + 1, 0, blank(rs[i]));
      return out;
    });
    setDirty(true);
  };
  const remove = (key: number) => {
    setRows((rs) => rs.filter((r) => r.key !== key));
    setDirty(true);
  };
  const changeMonth = (m: string) => {
    if (!m || m === month) return;
    if (dirty && !window.confirm('Discard your changes to this month?')) return;
    setSaved(null);
    setMonth(m);
  };

  const problems = rows.filter(
    (r) => r.distributor_id === '' || !r.person.trim() || !(Number(r.td_target) > 0) || badNum(r.td_target) || badNum(r.new_target, true) || badNum(r.gps_target, true) || badNum(r.kyc_target, true) || badNum(r.eligible),
  ).length;
  const sum = (f: 'td_target' | 'new_target' | 'gps_target' | 'kyc_target' | 'eligible') => rows.reduce((a, r) => a + (Number(r[f]) || 0), 0);
  const d = q.data;
  const inputCls = 'input w-full px-2 py-1 text-xs';
  const numCls = (bad: boolean) => cx('input w-full px-2 py-1 text-right text-xs tabular-nums', bad && 'border-bad');

  return (
    <Modal
      open={open}
      onClose={() => (!dirty || window.confirm('Discard your changes?')) && onClose()}
      xl
      title={
        <span className="flex items-center gap-3">
          Edit incentive sheet
          <input
            type="month"
            className="input w-40 py-1 text-xs"
            value={month}
            max={todayIst().add(3, 'month').format('YYYY-MM')}
            onChange={(e) => changeMonth(e.target.value)}
            aria-label="Month"
          />
        </span>
      }
      footer={
        <>
          <span className="mr-auto text-xs text-muted">
            {saved ? (
              <span className="font-medium text-good">{saved}</span>
            ) : problems ? (
              <span className="text-bad">
                {problems} row{problems === 1 ? '' : 's'} need a distributor, an employee name (or "Vacant") and a TD target above 0. KPI targets are whole numbers; the eligible incentive is an amount in ₹.
              </span>
            ) : (
              `Saving replaces every target of ${monthLabel(month)}: distributor, ASM, region and company totals are the sums of these rows.`
            )}
          </span>
          <button className="btn btn-sm" onClick={() => (!dirty || window.confirm('Discard your changes?')) && onClose()}>
            Close
          </button>
          <button className="btn-primary btn-sm" disabled={!rows.length || !!problems || save.isPending || !dirty} onClick={() => save.mutate()}>
            {save.isPending && <Spinner size={12} />} Save {monthLabel(month)}
          </button>
        </>
      }
    >
      {q.isLoading ? (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      ) : q.error ? (
        <InlineError error={q.error} />
      ) : (
        <>
          {d?.copied_from && (
            <p className="mb-3 rounded-md bg-sunken px-3 py-2 text-xs text-ink2">
              {monthLabel(month)} has no incentive sheet yet, so this starts as a copy of {monthLabel(d.copied_from)}. Change what's different, then save.
            </p>
          )}
          {d?.owner === 'sheet' && (
            <p className="mb-3 rounded-md border border-warn/40 bg-warn-bg px-3 py-2 text-xs text-ink">
              {monthLabel(month)} comes from the live Google sheet. Once you save it here, the dashboard keeps your version and stops taking this month from the Google
              sheet.
            </p>
          )}
          {save.error ? (
            <div className="mb-3">
              <InlineError error={save.error} />
            </div>
          ) : null}
          <datalist id="isheet-asm">
            {d?.people.asm.map((n) => <option key={n} value={n} />)}
          </datalist>
          <datalist id="isheet-exec">
            {d?.people.executive.map((n) => <option key={n} value={n} />)}
          </datalist>
          <div className="max-h-[62vh] overflow-auto rounded-md border border-line">
            <table className="w-full min-w-[1150px] text-xs">
              <thead className="sticky top-0 z-10 bg-sunken text-left text-ink2">
                <tr>
                  <th className="px-2 py-2 font-medium">Month</th>
                  <th className="px-2 py-2 font-medium">Region</th>
                  <th className="px-2 py-2 font-medium">State</th>
                  <th className="w-52 px-2 py-2 font-medium">Distributor</th>
                  <th className="w-28 px-2 py-2 font-medium">Role</th>
                  <th className="w-44 px-2 py-2 font-medium">Employee Name</th>
                  <th className="w-32 px-2 py-2 text-right font-medium">TD Target (₹)</th>
                  <th className="w-24 px-2 py-2 text-right font-medium">New Retailer Target</th>
                  <th className="w-24 px-2 py-2 text-right font-medium">BO G/P/S Target</th>
                  <th className="w-24 px-2 py-2 text-right font-medium">KYC Conversion Target</th>
                  <th className="w-28 px-2 py-2 text-right font-medium">Eligible Incentive (₹)</th>
                  <th className="w-20 px-2 py-2" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const dist = r.distributor_id === '' ? undefined : dists.get(r.distributor_id);
                  return (
                    <tr key={r.key} className="border-t border-line align-middle">
                      <td className="whitespace-nowrap px-2 py-1 text-muted">{monthLabel(month)}</td>
                      <td className="px-2 py-1 text-ink2">{dist?.region || '–'}</td>
                      <td className="px-2 py-1 text-ink2">{dist?.state || '–'}</td>
                      <td className="px-2 py-1">
                        <select
                          className={cx(inputCls, r.distributor_id === '' && 'border-bad')}
                          value={r.distributor_id}
                          onChange={(e) => set(r.key, { distributor_id: e.target.value ? Number(e.target.value) : '' })}
                          aria-label="Distributor"
                        >
                          <option value="">Choose…</option>
                          {d?.distributors.map((x) => (
                            <option key={x.id} value={x.id}>
                              {x.name}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-2 py-1">
                        <select className={inputCls} value={r.role} onChange={(e) => set(r.key, { role: e.target.value as EditRow['role'] })} aria-label="Role">
                          <option value="asm">ASM</option>
                          <option value="executive">Executive</option>
                        </select>
                      </td>
                      <td className="px-2 py-1">
                        <input
                          className={cx(inputCls, !r.person.trim() && 'border-bad')}
                          list={r.role === 'asm' ? 'isheet-asm' : 'isheet-exec'}
                          value={r.person}
                          placeholder="Name or Vacant"
                          onChange={(e) => set(r.key, { person: e.target.value })}
                          aria-label="Employee name"
                        />
                      </td>
                      <td className="px-2 py-1">
                        <input
                          className={numCls(!(Number(r.td_target) > 0) || badNum(r.td_target))}
                          inputMode="decimal"
                          value={r.td_target}
                          onChange={(e) => set(r.key, { td_target: e.target.value.replace(/[,₹\s]/g, '') })}
                          title={Number(r.td_target) > 0 ? inr(Number(r.td_target), { compact: false }) : undefined}
                          aria-label="TD target"
                        />
                      </td>
                      {(['new_target', 'gps_target', 'kyc_target'] as const).map((f) => (
                        <td key={f} className="px-2 py-1">
                          <input className={numCls(badNum(r[f], true))} inputMode="numeric" value={r[f]} onChange={(e) => set(r.key, { [f]: e.target.value.trim() })} aria-label={f} />
                        </td>
                      ))}
                      <td className="px-2 py-1">
                        <input
                          className={numCls(badNum(r.eligible))}
                          inputMode="decimal"
                          value={r.eligible}
                          placeholder={/^vacant$/i.test(r.person.trim()) ? '' : '5,000'}
                          onChange={(e) => set(r.key, { eligible: e.target.value.replace(/[,₹\s]/g, '') })}
                          aria-label="Eligible incentive"
                        />
                      </td>
                      <td className="whitespace-nowrap px-2 py-1 text-right">
                        <button className="btn btn-sm px-1.5" title="Add a row below (same distributor)" onClick={() => insertAfter(r.key)}>
                          <IconPlus size={12} />
                        </button>{' '}
                        <button className="btn btn-sm px-1.5 text-bad" title="Remove this row" onClick={() => remove(r.key)}>
                          ✕
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot className="sticky bottom-0 bg-sunken font-medium text-ink">
                <tr className="border-t border-line">
                  <td className="px-2 py-2" colSpan={6}>
                    Total · {num(rows.length)} rows
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums">{inr(sum('td_target'), { compact: false })}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{num(sum('new_target'))}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{num(sum('gps_target'))}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{num(sum('kyc_target'))}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{inr(sum('eligible'), { compact: false })}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
          <button className="btn btn-sm mt-3" onClick={() => insertAfter(null)}>
            <IconPlus size={13} /> Add row
          </button>
        </>
      )}
    </Modal>
  );
}
