import { useState } from 'react';
import { Badge, Card, Segmented, cx } from '@/components/ui';
import { dateTime, inr, num } from '@/lib/format';

/**
 * Data Health → "Dashboard vs sources": after every refresh the dashboard is compared with the sheets and databases
 * it reads (analytics/source_recon.py), so a figure never quietly differs from the sheet people check it against.
 */
type Month = { month: string; sheet: number; sheet_orders: number; dashboard: number; dashboard_orders: number; awaiting_import: number; diff: number; ok: boolean };
type SupaMonth = { month: string; supabase_orders: number; dashboard_orders: number; supabase_value: number; dashboard_value: number; diff: number; ok: boolean };
type TargetMonth = { month: string; levels: Record<string, number>; sheet: number | null; ok: boolean };
type Rows = { count: number; rows: Record<string, unknown>[] };
export interface SourceCheckData {
  checked_at: string | null;
  tracker_months: Month[];
  tracker: Record<'only_sheet' | 'only_td' | 'value_diff' | 'status_diff' | 'distributor_diff' | 'merged_in_sheet', Rows>;
  supabase_months: SupaMonth[];
  supabase_available: boolean;
  supabase_error?: string | null;
  targets: TargetMonth[];
  sheets: Record<string, string[]>;
}

const L = (v: number | null | undefined) => (v === null || v === undefined ? '–' : inr(v));
const ml = (ym: string) => new Date(`${ym}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'short', year: '2-digit' });
const OkBadge = ({ ok, warn }: { ok: boolean; warn?: boolean }) => (ok ? <Badge tone="good" icon>Matches</Badge> : <Badge tone={warn ? 'warn' : 'bad'} icon>Differs</Badge>);

type Tab = 'sheet' | 'supabase' | 'targets' | 'orders';
const TABS: { value: Tab; label: string }[] = [
  { value: 'sheet', label: 'Sales vs Order Tracking sheet' },
  { value: 'supabase', label: 'Import vs TD (Supabase)' },
  { value: 'targets', label: 'Targets' },
  { value: 'orders', label: 'Order differences' },
];

export function SourceCheck({ d }: { d: SourceCheckData | null | undefined }) {
  const [tab, setTab] = useState<Tab>('sheet');
  if (!d) return null;
  const bad = {
    sheet: d.tracker_months.filter((m) => !m.ok).length,
    supabase: d.supabase_months.filter((m) => !m.ok).length,
    targets: d.targets.filter((m) => !m.ok).length,
    orders: d.tracker.only_sheet.count + d.tracker.only_td.count + d.tracker.value_diff.count + d.tracker.status_diff.count,
  };
  return (
    <Card
      className="mt-4"
      title="Dashboard vs sources"
      subtitle={`Checked after every refresh${d.checked_at ? ` · last ${dateTime(d.checked_at)}` : ''}. Anything that differs is also listed under Data-quality issues.`}
      actions={<Segmented value={tab} onChange={setTab} size="xs" options={TABS.map((t) => ({ value: t.value, label: <>{t.label}{bad[t.value] ? <span className="ml-1 rounded bg-bad/15 px-1 text-bad">{bad[t.value]}</span> : null}</> }))} />}
      bodyClass="p-0"
    >
      {tab === 'sheet' && (
        <Table
          head={['Month', 'Sheet', 'Dashboard', 'Difference', 'Orders (sheet / TD)', '']}
          rows={[...d.tracker_months].reverse().map((m) => [
            ml(m.month), L(m.sheet), L(m.dashboard),
            <span key="d" className={cx('tabular-nums', m.ok ? 'text-muted' : 'font-semibold text-bad')}>{m.diff >= 0 ? '+' : '−'}{inr(Math.abs(m.diff), { compact: false })}</span>,
            <span key="o" className="tabular-nums text-ink2">{num(m.sheet_orders)} / {num(m.dashboard_orders)}{m.awaiting_import ? <span className="text-muted"> · {m.awaiting_import} new, next refresh</span> : null}</span>,
            <OkBadge key="b" ok={m.ok} />,
          ])}
          note="Sales = every paid order at its order value, cancelled and internal ones included: the same as the finance sheet. Up to ₹1,000 a month is rounding. Orders of the last 2 days can be in the sheet before the next TD import."
        />
      )}
      {tab === 'supabase' && (
        d.supabase_available ? (
          <Table
            head={['Month', 'TD orders', 'Imported', 'TD value', 'Imported value', '']}
            rows={[...d.supabase_months].reverse().map((m) => [ml(m.month), num(m.supabase_orders), num(m.dashboard_orders), L(m.supabase_value), L(m.dashboard_value), <OkBadge key="b" ok={m.ok} />])}
            note="Every order in TD's own database (Supabase) must be in the dashboard at the same value. The current month can be a few orders behind until the next refresh."
          />
        ) : <p className="px-4 py-6 text-sm text-muted">Supabase not reachable{d.supabase_error ? `: ${d.supabase_error}` : ''}.</p>
      )}
      {tab === 'targets' && (
        <Table
          head={['Month', 'Overall', 'Regions', 'States', 'ASMs', 'Distributors', 'Target sheet', '']}
          rows={[...d.targets].reverse().map((m) => [ml(m.month), L(m.levels.overall), L(m.levels.region), L(m.levels.state), L(m.levels.asm), L(m.levels.distributor), L(m.sheet), <OkBadge key="b" ok={m.ok} />])}
          note="The overall target must equal the regions' total, and the target sheet's total when there is one. States / ASMs / distributors can be partial (not every one has a target)."
        />
      )}
      {tab === 'orders' && (
        <div className="divide-y divide-line">
          <OrderList title="Value differs from the sheet (by cart)" r={d.tracker.value_diff} cols={['order', 'date', 'distributor', 'sheet', 'dashboard', 'diff']} />
          <OrderList title="In the sheet, not in TD data" r={d.tracker.only_sheet} cols={['order', 'date', 'distributor', 'value']} />
          <OrderList title="Paid TD order missing from the sheet" r={d.tracker.only_td} cols={['order', 'date', 'distributor', 'value', 'status']} />
          <OrderList title="Sheet and TD disagree whether it was cancelled" r={d.tracker.status_diff} cols={['order', 'date', 'sheet', 'dashboard']} />
          <OrderList title="Moved to another distributor in TD (sheet keeps the original; not an error)" r={d.tracker.distributor_diff} cols={['order', 'date', 'sheet', 'dashboard']} muted />
          <OrderList title="Merged into one row in the sheet (explained, not an error)" r={d.tracker.merged_in_sheet} cols={['sheet_row', 'merged_order', 'date', 'value']} muted />
        </div>
      )}
    </Card>
  );
}

function Table({ head, rows, note }: { head: string[]; rows: React.ReactNode[][]; note: string }) {
  return (
    <>
      <div className="max-h-[26rem] overflow-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="sticky top-0 bg-surface">
            <tr className="border-b border-line text-left text-xs text-muted">
              {head.map((h, i) => <th key={i} className={cx('px-3 py-2 font-medium first:pl-4', i > 0 && 'text-right', i === head.length - 1 && 'pr-4')}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-line/60 last:border-0">
                {r.map((c, j) => <td key={j} className={cx('px-3 py-1.5 tabular-nums first:pl-4', j > 0 && 'text-right', j === r.length - 1 && 'pr-4')}>{c}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-line px-4 py-2 text-2xs text-muted">{note}</p>
    </>
  );
}

const money = new Set(['sheet', 'dashboard', 'diff', 'value']);
function OrderList({ title, r, cols, muted }: { title: string; r: Rows; cols: string[]; muted?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="px-4 py-2.5">
      <button className="flex w-full items-center justify-between text-left" onClick={() => setOpen(!open)} disabled={!r.count}>
        <span className={cx('text-sm', muted ? 'text-ink2' : 'font-medium text-ink')}>{title}</span>
        <span className={cx('rounded px-1.5 text-xs tabular-nums', r.count && !muted ? 'bg-bad/15 font-semibold text-bad' : 'text-muted')}>{num(r.count)}</span>
      </button>
      {open && r.count > 0 && (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-muted">{cols.map((c) => <th key={c} className="py-1 pr-3 font-medium capitalize">{c.replace('_', ' ')}</th>)}</tr>
            </thead>
            <tbody>
              {r.rows.map((row, i) => (
                <tr key={i} className="border-t border-line/50">
                  {cols.map((c) => {
                    const v = row[c];
                    return <td key={c} className="py-1 pr-3 tabular-nums text-ink2">{money.has(c) && typeof v === 'number' ? inr(v, { compact: false }) : String(v ?? '–')}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          {r.count > r.rows.length && <p className="mt-1 text-2xs text-muted">Showing {r.rows.length} of {num(r.count)}; all are in Data-quality issues.</p>}
        </div>
      )}
    </div>
  );
}
