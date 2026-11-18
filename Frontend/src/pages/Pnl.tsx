import { Fragment, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { del, download, errorMessage, get, patch, post } from '@/lib/api';
import { inr, pct, signedPct } from '@/lib/format';
import { PageHeader } from '@/components/PageHeader';
import { Badge, Card, Drawer, ErrorState, Field, InlineError, LoadingBlock, cx } from '@/components/ui';
import { IconDownload, IconEdit, IconInfo, IconPlus, IconTrash } from '@/components/Icons';
import { EChart, useChartTokens } from '@/charts/EChart';
import { cartesian, waterfall } from '@/charts/builders';

// ---------------------------------------------------------------- API shape (/api/masters/pnl/)
type LineKind = 'input' | 'calc' | 'assumption' | 'subtotal' | 'total' | 'margin';
interface PnlLine { key: string; label: string; kind: LineKind; formula: string }
interface CheckRow { key: string; label: string; entered: number | null; data: number | null; diff: number | null; diff_pct: number | null; ebitda_effect: number | null; basis: string }
interface Inputs {
  gross_revenue: number | null; returns: number | null; cogs_pct: number; pg_pct: number; loyalty_pct: number;
  tech_platform_cost: number | null; manpower_operating_cost: number | null; misc_expense: number | null; notes: string;
}
interface Quarter {
  start: string; end: string; label: string; status: 'complete' | 'in_progress'; previous: string | null;
  inputs: Inputs; values: Record<string, number | null>; growth: Record<string, number | null>; missing: string[];
  checks: { rows: CheckRow[]; tracker_coverage: number | null; pg_actual_rate: number | null; cancelled_value: number | null; data_orders: number };
  updated_by: string; updated_at: string | null;
}
interface Pnl { lines: PnlLine[]; quarters: Quarter[]; next_quarter: { start: string; label: string } | null; can_edit: boolean }

const MISSING_LABEL: Record<string, string> = {
  gross_revenue: 'Gross Revenue', returns: 'Returns', tech_platform_cost: 'Technology / platform',
  manpower_operating_cost: 'Manpower & operating', misc_expense: 'Misc',
};
const money = (v: number | null | undefined) => inr(v, { compact: false });
const isMargin = (l: PnlLine) => l.kind === 'margin';
/** value lines: QoQ %; margin lines: percentage-point change */
function growthText(l: PnlLine, g: number | null | undefined) {
  if (g === null || g === undefined) return '–';
  if (isMargin(l)) {
    const pp = g * 100;
    return `${pp > 0 ? '+' : pp < 0 ? '−' : '±'}${Math.abs(pp).toFixed(1)} pp`;
  }
  return signedPct(g * 100);
}
/** costs going up is bad, profit going up is good */
const COST_LINES = new Set(['returns', 'cogs', 'payment_gateway', 'loyalty', 'tech', 'manpower', 'misc']);
function growthTone(l: PnlLine, g: number | null | undefined) {
  if (g === null || g === undefined || Math.abs(g) < 0.0005) return 'text-muted';
  const up = g > 0;
  return (COST_LINES.has(l.key) ? !up : up) ? 'text-good' : 'text-bad';
}
function formulaText(l: PnlLine, q?: Quarter) {
  if (!q) return l.formula;
  return l.formula
    .replace('{cogs_pct}', String(q.inputs.cogs_pct))
    .replace('{pg_pct}', String(q.inputs.pg_pct))
    .replace('{loyalty_pct}', String(q.inputs.loyalty_pct));
}

export default function PnlPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['pnl'], queryFn: () => get<Pnl>('/masters/pnl/') });
  const d = q.data;
  const [focus, setFocus] = useState<string | null>(null);
  const [editing, setEditing] = useState<Quarter | null>(null);

  // focus = the latest quarter whose P&L is complete (all inputs entered), else the latest
  const complete = useMemo(() => (d?.quarters ?? []).filter((x) => x.missing.length === 0), [d]);
  useEffect(() => {
    if (d && !focus) setFocus((complete[complete.length - 1] ?? d.quarters[d.quarters.length - 1])?.start ?? null);
  }, [d, focus, complete]);
  const fq = d?.quarters.find((x) => x.start === focus);

  const add = useMutation({
    mutationFn: () => post<{ start: string; label: string }>('/masters/pnl/quarters/', {}),
    onSuccess: async (r) => {
      await qc.invalidateQueries({ queryKey: ['pnl'] });
      const fresh = await qc.fetchQuery({ queryKey: ['pnl'], queryFn: () => get<Pnl>('/masters/pnl/') });
      setEditing(fresh.quarters.find((x) => x.start === r.start) ?? null);
    },
  });

  if (q.isLoading) return <LoadingBlock height={400} />;
  if (q.error || !d) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;

  return (
    <>
      <PageHeader
        title="Profit & Loss"
        showBasis={false}
        subtitle={
          <span className="inline-flex flex-wrap items-center gap-2">
            TD P&amp;L quarter on quarter, calculated the way TD_P&amp;L_QoQ_Rev.xlsx does it.
            <Badge tone="warn" title="Only the Business Head role and the admin can open this page">Business Head &amp; Admin only</Badge>
          </span>
        }
        actions={
          <div className="flex items-center gap-2">
            <button className="btn" onClick={() => void download('/masters/pnl/', { export: 'xlsx' }, 'TD_PnL_QoQ.xlsx')}>
              <IconDownload size={14} /> Excel
            </button>
            {d.can_edit && d.next_quarter && (
              <button className="btn btn-primary" disabled={add.isPending} onClick={() => add.mutate()} title="Adds the quarter with costs and % carried forward; you enter revenue and returns">
                <IconPlus size={14} /> Add {d.next_quarter.label}
              </button>
            )}
          </div>
        }
      />
      {add.error ? <div className="mb-3"><InlineError error={add.error} /></div> : null}

      {fq && <Headline q={fq} lines={d.lines} />}

      <div className="mb-4 grid gap-4 xl:grid-cols-2">
        {fq && <BridgeCard q={fq} quarters={d.quarters} focus={focus} setFocus={setFocus} />}
        <TrendCard quarters={complete} />
      </div>

      <Statement d={d} focus={focus} setFocus={setFocus} onEdit={setEditing} />

      {fq && <ChecksCard q={fq} onEdit={d.can_edit ? () => setEditing(fq) : undefined} />}

      <MethodCard />

      {editing && (
        <EditQuarter
          q={editing}
          isLatest={editing.start === d.quarters[d.quarters.length - 1]?.start}
          onClose={() => setEditing(null)}
          onSaved={() => void qc.invalidateQueries({ queryKey: ['pnl'] })}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------- headline numbers
function Headline({ q, lines }: { q: Quarter; lines: PnlLine[] }) {
  const L = (k: string) => lines.find((l) => l.key === k)!;
  const tiles: { key: string; label: string; sub?: { key: string; label: string } }[] = [
    { key: 'gross_revenue', label: 'Gross Revenue' },
    { key: 'net_revenue', label: 'Net Revenue (after returns)' },
    { key: 'gross_profit', label: 'Gross Profit', sub: { key: 'gross_margin', label: 'gross margin' } },
    { key: 'cm2', label: 'CM 2', sub: { key: 'cm1_pct', label: 'CM %' } },
    { key: 'ebitda', label: 'EBITDA', sub: { key: 'op_margin', label: 'operating margin' } },
  ];
  return (
    <div className="mb-4">
      <div className="mb-2 flex flex-wrap items-baseline gap-2 text-xs text-muted">
        <span className="text-sm font-semibold text-ink">{q.label}</span>
        {q.status === 'in_progress' && <Badge tone="warn">Quarter in progress</Badge>}
        {q.previous && <span>compared with {q.previous}</span>}
        {q.missing.length > 0 && <Badge tone="warn">To enter: {q.missing.map((m) => MISSING_LABEL[m] ?? m).join(', ')}</Badge>}
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {tiles.map((t) => {
          const v = q.values[t.key];
          const g = q.growth[t.key];
          return (
            <div key={t.key} className="card p-4">
              <div className="text-xs text-muted">{t.label}</div>
              <div className={cx('mt-1 text-xl font-semibold tabular-nums', t.key === 'ebitda' && v !== null && v < 0 ? 'text-bad' : 'text-ink')}>
                {inr(v)}
              </div>
              {/* the exact figure, as the Excel shows it */}
              <div className="text-[11px] tabular-nums text-muted">{money(v)}</div>
              <div className="mt-1 flex flex-wrap items-center gap-x-2 text-xs">
                <span className={cx('font-medium', growthTone(L(t.key), g))}>{growthText(L(t.key), g)}</span>
                <span className="text-muted">QoQ</span>
                {t.sub && (
                  <span className="text-ink2">
                    · {pct((q.values[t.sub.key] ?? NaN) * 100)} {t.sub.label}
                    <span className={cx('ml-1', growthTone(L(t.sub.key), q.growth[t.sub.key]))}>({growthText(L(t.sub.key), q.growth[t.sub.key])})</span>
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Gross Revenue -> EBITDA bridge
function BridgeCard({ q, quarters, focus, setFocus }: { q: Quarter; quarters: Quarter[]; focus: string | null; setFocus: (s: string) => void }) {
  const t = useChartTokens();
  const v = q.values;
  const ready = v.ebitda !== null && v.ebitda !== undefined;
  const option = useMemo(
    () =>
      ready
        ? waterfall(t, [
            { label: 'Gross Revenue', value: v.gross_revenue ?? 0, total: true },
            { label: 'Returns', value: -(v.returns ?? 0) },
            { label: 'COGS', value: -(v.cogs ?? 0) },
            { label: 'Payment gateway', value: -(v.payment_gateway ?? 0) },
            { label: 'Loyalty', value: -(v.loyalty ?? 0) },
            { label: 'Technology', value: -(v.tech ?? 0) },
            { label: 'Manpower', value: -(v.manpower ?? 0) },
            { label: 'Misc', value: -(v.misc ?? 0) },
            { label: 'EBITDA', value: v.ebitda ?? 0, total: true },
          ])
        : null,
    [t, v, ready],
  );
  return (
    <Card
      title={`Where the revenue goes · ${q.label}`}
      subtitle="Gross Revenue to EBITDA, each cost in turn"
      actions={
        <select className="input py-1 text-xs" value={focus ?? ''} onChange={(e) => setFocus(e.target.value)} aria-label="Quarter">
          {quarters.map((x) => <option key={x.start} value={x.start}>{x.label}</option>)}
        </select>
      }
    >
      {option ? <EChart option={option} height={300} ariaLabel={`P&L bridge for ${q.label}`} /> : <p className="py-16 text-center text-sm text-muted">Enter this quarter's figures to see the bridge.</p>}
    </Card>
  );
}

// ---------------------------------------------------------------- trend
function TrendCard({ quarters }: { quarters: Quarter[] }) {
  const t = useChartTokens();
  const option = useMemo(
    () =>
      cartesian(t, {
        x: quarters.map((q) => q.label),
        series: [
          { name: 'Net Revenue', data: quarters.map((q) => q.values.net_revenue ?? null), type: 'bar' },
          { name: 'EBITDA', data: quarters.map((q) => q.values.ebitda ?? null), type: 'bar' },
        ],
        format: 'inr',
        legend: true,
        showBarLabels: false,
      }),
    [t, quarters],
  );
  const margins = quarters.map((q) => ({ label: q.label, m: q.values.op_margin }));
  return (
    <Card title="Revenue and profit by quarter" subtitle="Net Revenue and EBITDA (complete quarters)">
      {quarters.length ? (
        <>
          <EChart option={option} height={250} ariaLabel="Net revenue and EBITDA by quarter" />
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
            <span className="text-ink2">Operating margin:</span>
            {margins.map((x) => <span key={x.label}>{x.label} <b className="font-semibold text-ink">{pct((x.m ?? NaN) * 100)}</b></span>)}
          </div>
        </>
      ) : (
        <p className="py-16 text-center text-sm text-muted">No complete quarter yet.</p>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- the statement (the sheet's layout)
function Statement({ d, focus, setFocus, onEdit }: { d: Pnl; focus: string | null; setFocus: (s: string) => void; onEdit: (q: Quarter) => void }) {
  return (
    <Card
      title="P&L statement"
      subtitle="As in the Excel: each quarter with its growth on the quarter before. Margin rows change in percentage points (pp). Hover a line to see how it is calculated."
      bodyClass="p-0"
      className="mb-4"
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-xs text-muted">
              <th className="sticky left-0 z-10 bg-surface px-4 py-2 text-left font-medium">P&amp;L particular</th>
              {d.quarters.map((q) => (
                <th key={q.start} colSpan={2} className={cx('px-3 py-2 text-right font-medium', q.start === focus && 'bg-brand/5')}>
                  <div className="flex items-center justify-end gap-1.5">
                    <button className="font-semibold text-ink hover:underline" onClick={() => setFocus(q.start)} title="Show this quarter above">{q.label}</button>
                    {q.status === 'in_progress' && <Badge tone="warn">in progress</Badge>}
                    {d.can_edit && (
                      <button className="rounded p-0.5 text-muted hover:bg-sunken hover:text-ink" onClick={() => onEdit(q)} title={`Edit ${q.label}`} aria-label={`Edit ${q.label}`}>
                        <IconEdit size={13} />
                      </button>
                    )}
                  </div>
                  <div className="mt-0.5 flex justify-end gap-6 text-[11px] font-normal">
                    <span>Amount</span>
                    <span className="w-16 text-right">QoQ</span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {d.lines.map((l) => {
              const strong = l.kind === 'subtotal' || l.kind === 'total';
              return (
                <tr
                  key={l.key}
                  className={cx(
                    'border-b border-line/60',
                    strong && 'font-semibold text-ink',
                    l.kind === 'total' && 'bg-brand/5',
                    isMargin(l) && 'text-xs italic text-ink2',
                  )}
                >
                  <td className="sticky left-0 z-10 bg-surface px-4 py-1.5" title={formulaText(l, d.quarters[d.quarters.length - 1])}>
                    <span className={cx(l.label.startsWith('Less:') && 'pl-3 text-ink2', strong && 'text-ink')}>{l.label}</span>
                    {(l.kind === 'assumption') && (
                      <span className="ml-1.5 text-[11px] font-normal not-italic text-muted">{formulaText(l, d.quarters[d.quarters.length - 1])}</span>
                    )}
                  </td>
                  {d.quarters.map((q) => {
                    const v = q.values[l.key];
                    const g = q.growth[l.key];
                    const inputMissing = l.kind === 'input' && (v === null || v === undefined);
                    return (
                      <Fragment key={q.start}>
                        <td className={cx('whitespace-nowrap px-3 py-1.5 text-right tabular-nums', q.start === focus && 'bg-brand/5', l.key === 'ebitda' && v !== null && v < 0 && 'text-bad')}>
                          {inputMissing ? (
                            d.can_edit ? (
                              <button className="text-xs font-medium text-brand hover:underline" onClick={() => onEdit(q)}>Enter</button>
                            ) : (
                              <span className="text-xs text-muted">not entered</span>
                            )
                          ) : isMargin(l) ? (
                            pct((v ?? NaN) * 100)
                          ) : (
                            money(v)
                          )}
                        </td>
                        <td className={cx('w-16 whitespace-nowrap px-3 py-1.5 text-right text-xs tabular-nums', q.start === focus && 'bg-brand/5', growthTone(l, g))}>
                          {growthText(l, g)}
                        </td>
                      </Fragment>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
// ---------------------------------------------------------------- checks against the data
function ChecksCard({ q, onEdit }: { q: Quarter; onEdit?: () => void }) {
  const c = q.checks;
  const partial = c.tracker_coverage !== null && c.tracker_coverage < 0.95;
  const totalEffect = c.rows.reduce((s, r) => s + (r.ebitda_effect ?? 0), 0);
  return (
    <Card
      className="mb-4"
      title={`Check against the data · ${q.label}`}
      subtitle="The P&L uses the entered figures and the sheet's % assumptions. This compares them with what the order data and the finance tracker say. Nothing here changes the P&L."
      actions={onEdit && <button className="btn" onClick={onEdit}><IconEdit size={14} /> Edit {q.label}</button>}
    >
      {partial && (
        <p className="mb-3 rounded-md bg-warn-bg px-3 py-2 text-xs text-ink2">
          The finance tracker covers only {pct(c.tracker_coverage! * 100, 0)} of this quarter's orders (it starts in Feb 2026), so the
          returns and payment-gateway figures from it are partial.
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th className="py-1.5 pr-3 font-medium">Line</th>
              <th className="py-1.5 pr-3 text-right font-medium">In the P&amp;L</th>
              <th className="py-1.5 pr-3 text-right font-medium">From the data</th>
              <th className="py-1.5 pr-3 text-right font-medium">Difference</th>
              <th className="py-1.5 pr-3 text-right font-medium">Effect on EBITDA</th>
              <th className="py-1.5 font-medium">Data basis</th>
            </tr>
          </thead>
          <tbody>
            {c.rows.map((r) => (
              <tr key={r.key} className="border-b border-line/60 align-top">
                <td className="py-1.5 pr-3 font-medium text-ink">{r.label}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{money(r.entered)}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{r.data === null ? <span className="text-xs text-muted">no data</span> : money(r.data)}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">
                  {r.diff === null ? '–' : (
                    <>
                      {money(r.diff)}
                      {r.diff_pct !== null && Math.abs(r.diff_pct) < 100 && <span className="ml-1 text-xs text-muted">({signedPct(r.diff_pct * 100)})</span>}
                    </>
                  )}
                </td>
                {/* ebitda_effect = EBITDA with the actual cost − EBITDA in the P&L: negative = the P&L overstates profit */}
                <td className={cx('py-1.5 pr-3 text-right tabular-nums', r.ebitda_effect === null || Math.abs(r.ebitda_effect) < 1 ? 'text-muted' : r.ebitda_effect < 0 ? 'text-bad' : 'text-good')}>
                  {r.ebitda_effect === null ? '–' : `${r.ebitda_effect < 0 ? 'overstated by ' : 'understated by '}${inr(Math.abs(r.ebitda_effect))}`}
                </td>
                <td className="py-1.5 text-xs text-muted">{r.basis}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {Math.abs(totalEffect) >= 1 && (
        <p className="mt-3 text-xs text-ink2">
          <IconInfo size={12} className="mr-1 inline" />
          With the actual payment-gateway and loyalty costs, EBITDA would be {inr(Math.abs(totalEffect))} {totalEffect < 0 ? 'lower' : 'higher'} than the P&amp;L shows
          {q.values.ebitda ? <> ({inr((q.values.ebitda ?? 0) + totalEffect)}, operating margin {pct((((q.values.ebitda ?? 0) + totalEffect) / (q.values.gross_revenue || 1)) * 100)})</> : null}.
        </p>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- method
function MethodCard() {
  return (
    <Card title="How this P&L is calculated" className="mb-2">
      <ul className="list-disc space-y-1 pl-5 text-xs text-ink2">
        <li><b>Entered each quarter:</b> Gross Revenue, Returns / refunds / cancellations, Technology / platform cost, Manpower &amp; operating cost and Misc. A new quarter starts with the previous quarter's costs and % filled in.</li>
        <li><b>Net Revenue</b> = Gross − Returns. <b>COGS</b> = 70% of Net Revenue, so Gross Margin is 30%. <b>Payment gateway</b> = 1% and <b>Loyalty</b> = 0.25% (0.5% ÷ 2) of Gross Revenue. All three % can be changed per quarter.</li>
        <li><b>CM 1</b> = Gross Profit − payment gateway − loyalty (CM % on Net Revenue). <b>CM 2</b> = CM 1 − technology − manpower. <b>EBITDA</b> = CM 2 − Misc. <b>Operating margin</b> = EBITDA ÷ Gross Revenue, as in the sheet (CM % uses Net Revenue).</li>
        <li><b>Growth</b> = change on the previous quarter, as in the sheet. Two corrections to the sheet: margin rows show the change in percentage points, and loyalty growth is calculated (the sheet had a fixed 0).</li>
        <li>The four quarters Q2 FY25-26 to Q1 FY26-27 are the figures of TD_P&amp;L_QoQ_Rev.xlsx and reproduce it to the paisa. Every change is recorded in the Audit Log and backed up to Supabase (folder <code>pnl</code>).</li>
      </ul>
    </Card>
  );
}

// ---------------------------------------------------------------- edit a quarter
const AMOUNT_FIELDS: { key: keyof Inputs; label: string; hint?: string }[] = [
  { key: 'gross_revenue', label: 'Gross Revenue (₹)' },
  { key: 'returns', label: 'Returns / refunds / cancellations (₹)' },
  { key: 'tech_platform_cost', label: 'Technology / platform cost (₹)' },
  { key: 'manpower_operating_cost', label: 'Manpower & operating cost (₹)' },
  { key: 'misc_expense', label: 'Misc expense (₹)' },
];
const PCT_FIELDS: { key: keyof Inputs; label: string; hint: string }[] = [
  { key: 'cogs_pct', label: 'COGS %', hint: 'of Net Revenue (sheet: 70)' },
  { key: 'pg_pct', label: 'Payment gateway %', hint: 'of Gross Revenue (sheet: 1)' },
  { key: 'loyalty_pct', label: 'Loyalty %', hint: 'of Gross Revenue (sheet: 0.25 = 0.5 ÷ 2)' },
];

function EditQuarter({ q, isLatest, onClose, onSaved }: { q: Quarter; isLatest: boolean; onClose: () => void; onSaved: () => void }) {
  const init = () => Object.fromEntries([...AMOUNT_FIELDS, ...PCT_FIELDS].map((f) => [f.key, q.inputs[f.key] === null ? '' : String(q.inputs[f.key])]));
  const [form, setForm] = useState<Record<string, string>>(init);
  const [notes, setNotes] = useState(q.inputs.notes ?? '');
  const dataFor = (key: string) => q.checks.rows.find((r) => r.key === key)?.data ?? null;
  const save = useMutation({
    mutationFn: () => patch(`/masters/pnl/quarters/${q.start}/`, { ...form, notes }),
    onSuccess: () => { onSaved(); onClose(); },
  });
  const remove = useMutation({
    mutationFn: () => del(`/masters/pnl/quarters/${q.start}/`),
    onSuccess: () => { onSaved(); onClose(); },
  });
  return (
    <Drawer open onClose={onClose} title={`Edit P&L · ${q.label}`} width={520}>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <p className="text-xs text-muted">Amounts in rupees (commas are fine). Every other line is calculated. Saved changes go to the Audit Log and to Supabase.</p>
        {AMOUNT_FIELDS.map((f) => {
          const suggestion = f.key === 'gross_revenue' ? dataFor('gross_revenue') : f.key === 'returns' ? dataFor('returns') : null;
          return (
            <Field key={f.key} label={f.label}>
              <div className="flex gap-2">
                <input className="input flex-1 tabular-nums" inputMode="decimal" value={form[f.key]} onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} placeholder="Enter amount" />
                {suggestion !== null && (
                  <button type="button" className="btn btn-sm whitespace-nowrap" onClick={() => setForm({ ...form, [f.key]: String(Math.round(suggestion * 100) / 100) })} title="Fill in the figure from the data">
                    Use data {inr(suggestion)}
                  </button>
                )}
              </div>
            </Field>
          );
        })}
        <div className="grid grid-cols-3 gap-2">
          {PCT_FIELDS.map((f) => (
            <Field key={f.key} label={f.label} hint={f.hint}>
              <input className="input tabular-nums" inputMode="decimal" value={form[f.key]} onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} />
            </Field>
          ))}
        </div>
        <Field label="Notes">
          <textarea className="input min-h-[64px]" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        {save.error ? <InlineError error={save.error} /> : null}
        {remove.error ? <p className="text-xs text-bad">{errorMessage(remove.error)}</p> : null}
        <div className="flex items-center justify-between gap-2 pt-2">
          {isLatest ? (
            <button
              type="button"
              className="btn text-bad"
              disabled={remove.isPending}
              onClick={() => { if (window.confirm(`Remove ${q.label} from the P&L?`)) remove.mutate(); }}
            >
              <IconTrash size={14} /> Remove quarter
            </button>
          ) : <span />}
          <div className="flex gap-2">
            <button type="button" className="btn" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save'}</button>
          </div>
        </div>
        {q.updated_by && <p className="text-[11px] text-muted">Last changed by {q.updated_by}{q.updated_at ? ` on ${new Date(q.updated_at).toLocaleString('en-IN')}` : ''}</p>}
      </form>
    </Drawer>
  );
}
