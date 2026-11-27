import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Badge, Field, InlineError, Modal, cx } from '@/components/ui';
import { IconSearch } from '@/components/Icons';
import { get, post } from '@/lib/api';
import { date, inr, num } from '@/lib/format';

/**
 * Admin → Mappings → Removed distributors (backend: masters/exclusions.py, RemovedDistributorsView).
 * Removing a distributor hides it from the dashboard now (lists, filters, stock, suggestions) while what it contributed
 * stays: its past orders and the retailers who ordered keep counting in the months they happened. A refresh keeps it
 * hidden. Restore shows it again; its stock comes back at the next refresh.
 */
interface Dist { id: number; name: string; city: string; is_active: boolean; bo_only: boolean; orders: number; last_order: string | null }
interface Impact { id: number; name: string; city: string; is_active: boolean; orders: number; sales: number; last_order: string | null; retailers: number; stock_units: number }
interface Removal { id: number; names: string[]; details: Impact[]; orders: number; sales: number; said: string; given_on: string; status: string; closed_on: string | null }
interface Data { removed: Removal[]; distributors: Dist[] }

const KEY = ['removed-distributors'];

export function RemovedDistributors() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: KEY, queryFn: () => get<Data>('/masters/removed-distributors/') });
  const [search, setSearch] = useState('');
  const [quiet, setQuiet] = useState(false);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [impact, setImpact] = useState<Impact[] | null>(null);
  const [reason, setReason] = useState('');
  const [restore, setRestore] = useState<Removal | null>(null);

  const list = useMemo(() => {
    const s = search.trim().toLowerCase();
    const cutoff = new Date(Date.now() - 90 * 864e5).toISOString().slice(0, 10);
    return (q.data?.distributors ?? []).filter((d) =>
      (!s || d.name.toLowerCase().includes(s) || (d.city ?? '').toLowerCase().includes(s))
      && (!quiet || !d.is_active || !d.last_order || d.last_order < cutoff));
  }, [q.data, search, quiet]);

  const preview = useMutation({
    mutationFn: () => post<{ impact: Impact[] }>('/masters/removed-distributors/', { action: 'preview', ids: [...picked] }),
    onSuccess: (r) => setImpact(r.impact),
  });
  const remove = useMutation({
    // removing recalculates the whole dashboard (about a minute and a half): allow more than the default timeout
    mutationFn: () => post('/masters/removed-distributors/', { action: 'remove', ids: [...picked], reason }, { timeout: 300_000 }),
    onSuccess: () => {
      setImpact(null); setPicked(new Set()); setReason('');
      qc.invalidateQueries({ queryKey: KEY });
      qc.invalidateQueries();
    },
  });
  const undo = useMutation({
    mutationFn: (id: number) => post('/masters/removed-distributors/', { action: 'restore', id }),
    onSuccess: () => { setRestore(null); qc.invalidateQueries({ queryKey: KEY }); },
  });

  const toggle = (id: number) => setPicked((p) => {
    const n = new Set(p);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });
  const total = (k: keyof Impact) => (impact ?? []).reduce((a, x) => a + Number(x[k] || 0), 0);
  const removed = q.data?.removed ?? [];

  return (
    <div className="space-y-6">
      <p className="text-sm text-ink2">
        Removing a distributor <b className="text-ink">hides it from the dashboard from now on</b>: distributor lists, filters, stock, sync status and suggestions.
        <b className="text-ink"> What it contributed stays</b>: its past orders and the retailers who ordered keep counting in sales for the months they
        happened, so no month's total changes. Refreshes keep it hidden. You can restore it below.
      </p>

      <section>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h3 className="mr-auto text-sm font-semibold text-ink">Remove distributors</h3>
          <label className="flex items-center gap-1.5 text-xs text-ink2">
            <input type="checkbox" checked={quiet} onChange={(e) => setQuiet(e.target.checked)} className="accent-brand" />
            Inactive or no order in 90 days
          </label>
          <div className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1">
            <IconSearch size={13} className="text-muted" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Distributor or city…" aria-label="Search distributors"
              className="w-44 bg-transparent text-xs outline-none placeholder:text-muted" />
          </div>
          <button type="button" className="btn btn-sm btn-danger" disabled={!picked.size || preview.isPending} onClick={() => preview.mutate()}>
            Review removal{picked.size ? ` (${picked.size})` : ''}
          </button>
        </div>
        <InlineError error={q.error ?? preview.error} />
        <div className="max-h-[26rem] overflow-auto rounded-md border border-line">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface">
              <tr className="border-b border-line text-left text-xs text-muted">
                <th className="w-8 px-3 py-2" />
                <th className="px-3 py-2 font-medium">Distributor</th>
                <th className="px-3 py-2 font-medium">City</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 text-right font-medium">Orders</th>
                <th className="px-3 py-2 text-right font-medium">Last order</th>
              </tr>
            </thead>
            <tbody>
              {list.map((d) => (
                <tr key={d.id} onClick={() => toggle(d.id)} className={cx('cursor-pointer border-b border-line/60 last:border-0 hover:bg-sunken/60', picked.has(d.id) && 'bg-bad/5')}>
                  <td className="px-3 py-1.5"><input type="checkbox" readOnly checked={picked.has(d.id)} className="accent-brand" aria-label={`Select ${d.name}`} /></td>
                  <td className="px-3 py-1.5 font-medium text-ink">{d.name}</td>
                  <td className="px-3 py-1.5 text-ink2">{d.city || '–'}</td>
                  <td className="px-3 py-1.5">
                    {d.bo_only ? <Badge tone="neutral">Offline only</Badge> : d.is_active ? <Badge tone="good">Active in TD</Badge> : <Badge tone="warn">Inactive in TD</Badge>}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{num(d.orders)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-ink2">{d.last_order ? date(d.last_order) : 'never'}</td>
                </tr>
              ))}
              {!list.length && <tr><td colSpan={6} className="px-3 py-6 text-center text-sm text-muted">{q.isLoading ? 'Loading…' : 'No distributors match.'}</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-ink">Removed so far</h3>
        {!removed.length ? <p className="text-sm text-muted">Nothing removed.</p> : (
          <ul className="divide-y divide-line rounded-md border border-line">
            {removed.map((r) => (
              <li key={r.id} className="flex flex-wrap items-start gap-3 px-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="font-medium text-ink">{r.names.join(', ')}</div>
                  <div className="text-xs text-ink2">
                    {date(r.given_on)} · history kept: {num(r.orders)} orders, {inr(r.sales)} in their months · <span className="text-muted">{r.said}</span>
                  </div>
                </div>
                {r.status === 'active'
                  ? <button type="button" className="btn btn-sm" onClick={() => setRestore(r)}>Restore</button>
                  : <Badge tone="neutral">Restored {r.closed_on ? date(r.closed_on) : ''}</Badge>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <Modal
        open={!!impact}
        onClose={() => setImpact(null)}
        title={`Remove ${impact?.length ?? 0} distributor${impact?.length === 1 ? '' : 's'} from the dashboard?`}
        wide
        footer={
          <>
            <button type="button" className="btn" onClick={() => setImpact(null)}>Cancel</button>
            <button type="button" className="btn btn-danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
              {remove.isPending ? 'Removing… (recalculating the dashboard)' : 'Remove from the dashboard'}
            </button>
          </>
        }
      >
        <p className="mb-3 text-sm text-ink2">They disappear from lists, filters and stock. Their history below <b className="text-ink">keeps counting</b> in the months it happened:</p>
        <table className="mb-3 w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th className="py-1.5 font-medium">Distributor</th>
              <th className="py-1.5 text-right font-medium">Orders</th>
              <th className="py-1.5 text-right font-medium">Sales</th>
              <th className="py-1.5 text-right font-medium">Retailers mapped</th>
              <th className="py-1.5 text-right font-medium">Stock units (cleared)</th>
            </tr>
          </thead>
          <tbody>
            {(impact ?? []).map((x) => (
              <tr key={x.id} className="border-b border-line/60">
                <td className="py-1.5 font-medium text-ink">{x.name}{x.city ? <span className="font-normal text-muted"> · {x.city}</span> : null}</td>
                <td className="py-1.5 text-right tabular-nums">{num(x.orders)}</td>
                <td className="py-1.5 text-right tabular-nums">{inr(x.sales)}</td>
                <td className="py-1.5 text-right tabular-nums">{num(x.retailers)}</td>
                <td className="py-1.5 text-right tabular-nums">{num(x.stock_units)}</td>
              </tr>
            ))}
            {impact && impact.length > 1 && (
              <tr className="font-semibold text-ink">
                <td className="py-1.5">Total</td>
                <td className="py-1.5 text-right tabular-nums">{num(total('orders'))}</td>
                <td className="py-1.5 text-right tabular-nums">{inr(total('sales'))}</td>
                <td className="py-1.5 text-right tabular-nums">{num(total('retailers'))}</td>
                <td className="py-1.5 text-right tabular-nums">{num(total('stock_units'))}</td>
              </tr>
            )}
          </tbody>
        </table>
        {total('sales') > 0 && (
          <p className="mb-3 rounded-md bg-sunken px-3 py-2 text-xs text-ink2">
            {inr(total('sales'))} of past sales stays in its months. The Distributors page still lists them for a period they sold in, marked “removed”, so the list adds up.
          </p>
        )}
        <Field label="Reason (kept in the register)">
          <input className="input w-full" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. inactive distributor" />
        </Field>
        <InlineError error={remove.error} />
      </Modal>

      <Modal
        open={!!restore}
        onClose={() => setRestore(null)}
        title={`Restore ${restore?.names.join(', ')}?`}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setRestore(null)}>Cancel</button>
            <button type="button" className="btn btn-primary" disabled={undo.isPending} onClick={() => restore && undo.mutate(restore.id)}>Restore</button>
          </>
        }
      >
        <p className="text-sm text-ink2">The distributor shows in lists and filters again right away; its stock comes back at the next data refresh.</p>
        <InlineError error={undo.error} />
      </Modal>
    </div>
  );
}
