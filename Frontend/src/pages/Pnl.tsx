import { Fragment, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { del, download, errorMessage, get, patch, post } from '@/lib/api';
import { inr, pct, signedPct } from '@/lib/format';
import { PageHeader } from '@/components/PageHeader';
import { Badge, Card, Drawer, ErrorState, Field, InlineError, LoadingBlock, Segmented, cx } from '@/components/ui';
import { IconDownload, IconEdit, IconPlus, IconTrash } from '@/components/Icons';
import { EChart, useChartTokens } from '@/charts/EChart';
import { cartesian, waterfall } from '@/charts/builders';

// ---------------------------------------------------------------- API shape (/api/masters/pnl/ and /pnl/months/)
type LineKind = 'input' | 'calc' | 'assumption' | 'subtotal' | 'total' | 'margin';
interface PnlLine { key: string; label: string; kind: LineKind; formula: string }
interface CheckRow { key: string; data: number | null }
interface Inputs {
  gross_revenue: number | null; returns: number | null; cogs_pct: number; pg_pct: number; loyalty_pct: number;
  tech_platform_cost: number | null; manpower_operating_cost: number | null; misc_expense: number | null; notes: string;
}
/** a quarter or a month of the P&L */
interface Period {
  start: string; end: string; label: string; status: 'complete' | 'in_progress' | 'future'; previous: string | null;
  inputs: Inputs; values: Record<string, number | null>; growth: Record<string, number | null>; missing: string[];
  /** quarters: data figures offered as "Use data" in the edit form (gross revenue, returns) */
  checks?: { rows: CheckRow[] };
  /** months: where each input comes from, what was entered over the default, and the data figures */
  sources?: Record<string, string>;
  entered?: Record<string, number | null>;
  data?: { gross_revenue: number | null; returns: number | null };
  updated_by: string; updated_at: string | null;
}
interface Pnl { lines: PnlLine[]; quarters: Period[]; next_quarter: { start: string; label: string } | null; can_edit: boolean }
interface PnlMonths {
  lines: PnlLine[]; months: Period[]; can_edit: boolean;
  range: { from: string; to: string; earliest: string | null; latest: string; max_months: number };
}
type View = 'month' | 'quarter';
type Unit = 'MoM' | 'QoQ';

const MISSING_LABEL: Record<string, string> = {
  gross_revenue: 'Gross Revenue', returns: 'Returns', tech_platform_cost: 'Technology / platform',
  manpower_operating_cost: 'Manpower & operating', misc_expense: 'Misc',
};
/** statement line -> the input it comes from (to show where a month's figure comes from) */
const LINE_INPUT: Record<string, keyof Inputs> = {
  gross_revenue: 'gross_revenue', returns: 'returns', cogs: 'cogs_pct', payment_gateway: 'pg_pct', loyalty: 'loyalty_pct',
  tech: 'tech_platform_cost', manpower: 'manpower_operating_cost', misc: 'misc_expense',
};
const money = (v: number | null | undefined) => inr(v, { compact: false });
const isMargin = (l: PnlLine) => l.kind === 'margin';
/** value lines: growth %; margin lines: percentage-point change */
/** a change that shows as 0.0 (under 0.05% / 0.05 pp) is flat: no sign, no colour */
const flat = (g: number) => Math.abs(g) < 0.0005;
function growthText(l: PnlLine, g: number | null | undefined) {
  if (g === null || g === undefined) return '–';
  if (flat(g)) return isMargin(l) ? '±0.0 pp' : '±0.0%';
  if (isMargin(l)) {
    const pp = g * 100;
    return `${pp > 0 ? '+' : '−'}${Math.abs(pp).toFixed(1)} pp`;
  }
  return signedPct(g * 100);
}
/** the user's rule: an increase is green with "+", a decrease red with "−", on every line (costs included) */
function growthTone(_l: PnlLine, g: number | null | undefined) {
  if (g === null || g === undefined || flat(g)) return 'text-muted';
  return g > 0 ? 'text-good' : 'text-bad';
}
function formulaText(l: PnlLine, q?: Period) {
  if (!q) return l.formula;
  return l.formula
    .replace('{cogs_pct}', String(+q.inputs.cogs_pct.toFixed(4)))
    .replace('{pg_pct}', String(+q.inputs.pg_pct.toFixed(4)))
    .replace('{loyalty_pct}', String(+q.inputs.loyalty_pct.toFixed(4)));
}

// ---------------------------------------------------------------- month helpers (YYYY-MM)
const ymAdd = (ym: string, n: number) => {
  const [y, m] = ym.split('-').map(Number);
  const d = new Date(y, m - 1 + n, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
};
const ymLabel = (ym: string) => new Date(`${ym}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' });
const ymDiff = (a: string, b: string) => {
  const [ya, ma] = a.split('-').map(Number);
  const [yb, mb] = b.split('-').map(Number);
  return (yb - ya) * 12 + (mb - ma);
};
function thisMonthIST() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit' }).format(new Date()).slice(0, 7);
}
/** first month of the Indian FY (April) containing ym */
const fyStart = (ym: string) => {
  const [y, m] = ym.split('-').map(Number);
  return `${m >= 4 ? y : y - 1}-04`;
};
type Preset = '3' | '6' | '12' | 'fy' | 'custom';
const PRESETS: { value: Preset; label: string }[] = [
  { value: '3', label: 'Last 3 months' },
  { value: '6', label: '6 months' },
  { value: '12', label: '12 months' },
  { value: 'fy', label: 'This FY' },
  { value: 'custom', label: 'Custom' },
];

export default function PnlPage() {
  const [view, setView] = useState<View>('month');
  return view === 'month' ? <MonthlyPnl view={view} setView={setView} /> : <QuarterlyPnl view={view} setView={setView} />;
}

function Header({ view, setView, actions }: { view: View; setView: (v: View) => void; actions: React.ReactNode }) {
  return (
    <PageHeader
      title="Profit & Loss"
      showBasis={false}
      subtitle={
        <span className="inline-flex flex-wrap items-center gap-2">
          {view === 'month'
            ? 'TD P&L month by month, with the sheet’s formulas. Each month fills in from the data and its quarter; edit any month to enter your own figures.'
            : 'TD P&L quarter on quarter, calculated the way TD_P&L_QoQ_Rev.xlsx does it.'}
          <Badge tone="warn" title="Only the Business Head role and the admin can open this page">Business Head &amp; Admin only</Badge>
        </span>
      }
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Segmented value={view} onChange={setView} options={[{ value: 'month', label: 'Monthly' }, { value: 'quarter', label: 'Quarterly' }]} />
          {actions}
        </div>
      }
    />
  );
}

// ---------------------------------------------------------------- monthly view
function MonthlyPnl({ view, setView }: { view: View; setView: (v: View) => void }) {
  const qc = useQueryClient();
  const latest = thisMonthIST();
  const [preset, setPreset] = useState<Preset>('3');
  const [custom, setCustom] = useState<{ from: string; to: string }>({ from: ymAdd(latest, -2), to: latest });
  const range = useMemo(() => {
    if (preset === 'custom') return custom;
    if (preset === 'fy') return { from: fyStart(latest), to: latest };
    return { from: ymAdd(latest, -(Number(preset) - 1)), to: latest };
  }, [preset, custom, latest]);
  const q = useQuery({
    queryKey: ['pnl', 'months', range.from, range.to],
    queryFn: () => get<PnlMonths>('/masters/pnl/months/', { from: range.from, to: range.to }),
    placeholderData: (prev) => prev,
  });
  const d = q.data;
  const [focus, setFocus] = useState<string | null>(null);
  const [editing, setEditing] = useState<Period | null>(null);
  const months = d?.months ?? [];
  useEffect(() => {
    if (months.length && !months.some((m) => m.start === focus)) setFocus(months[months.length - 1].start);
  }, [months, focus]);
  const fm = months.find((x) => x.start === focus);

  // month choices for the custom range: from the first month with data to this month
  const choices = useMemo(() => {
    const first = d?.range.earliest ?? ymAdd(latest, -23);
    const out: string[] = [];
    for (let m = latest; ymDiff(first, m) >= 0; m = ymAdd(m, -1)) out.push(m);
    return out;
  }, [d?.range.earliest, latest]);
  const max = d?.range.max_months ?? 12;
  const setFrom = (from: string) => setCustom((c) => ({ from, to: ymDiff(from, c.to) < 0 ? from : ymDiff(from, c.to) >= max ? ymAdd(from, max - 1) : c.to }));
  const setTo = (to: string) => setCustom((c) => ({ to, from: ymDiff(c.from, to) < 0 ? to : ymDiff(c.from, to) >= max ? ymAdd(to, -(max - 1)) : c.from }));

  const head = (
    <Header
      view={view}
      setView={setView}
      actions={
        <button className="btn" onClick={() => void download('/masters/pnl/months/', { from: range.from, to: range.to, export: 'xlsx' }, `TD_PnL_${range.from}_to_${range.to}.xlsx`)}>
          <IconDownload size={14} /> Excel
        </button>
      }
    />
  );
  if (q.isLoading) return <>{head}<LoadingBlock height={400} /></>;
  if (q.error || !d) return <>{head}<ErrorState error={q.error} onRetry={() => void q.refetch()} /></>;

  return (
    <>
      {head}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Segmented value={preset} onChange={(p) => { if (p === 'custom') setCustom(range); setPreset(p); }} options={PRESETS} size="xs" />
        {preset === 'custom' && (
          <div className="flex items-center gap-1.5 text-xs text-ink2">
            <label className="sr-only" htmlFor="pnl-from">From</label>
            <select id="pnl-from" className="input py-1 text-xs" value={custom.from} onChange={(e) => setFrom(e.target.value)}>
              {choices.map((m) => <option key={m} value={m}>{ymLabel(m)}</option>)}
            </select>
            to
            <label className="sr-only" htmlFor="pnl-to">To</label>
            <select id="pnl-to" className="input py-1 text-xs" value={custom.to} onChange={(e) => setTo(e.target.value)}>
              {choices.map((m) => <option key={m} value={m}>{ymLabel(m)}</option>)}
            </select>
            <span className="whitespace-nowrap text-muted">(up to {max} months)</span>
          </div>
        )}
        <span className="text-xs text-muted">{ymLabel(range.from)} – {ymLabel(range.to)}{q.isFetching ? ' · updating…' : ''}</span>
      </div>

      {fm && <Headline q={fm} lines={d.lines} unit="MoM" />}

      <div className="mb-4 grid gap-4 xl:grid-cols-2">
        {fm && <BridgeCard q={fm} periods={months} focus={focus} setFocus={setFocus} unit="MoM" />}
        <TrendCard periods={months.filter((m) => m.missing.length === 0)} unit="MoM" />
      </div>

      <Statement lines={d.lines} periods={months} canEdit={d.can_edit} unit="MoM" focus={focus} setFocus={setFocus} onEdit={setEditing} />

      <MethodCard view="month" />

      {editing && <EditMonth m={editing} onClose={() => setEditing(null)} onSaved={() => void qc.invalidateQueries({ queryKey: ['pnl', 'months'] })} />}
    </>
  );
}

// ---------------------------------------------------------------- quarterly view (as before)
function QuarterlyPnl({ view, setView }: { view: View; setView: (v: View) => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['pnl'], queryFn: () => get<Pnl>('/masters/pnl/') });
  const d = q.data;
  const [focus, setFocus] = useState<string | null>(null);
  const [editing, setEditing] = useState<Period | null>(null);

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

  const head = (
    <Header
      view={view}
      setView={setView}
      actions={
        <>
          <button className="btn" onClick={() => void download('/masters/pnl/', { export: 'xlsx' }, 'TD_PnL_QoQ.xlsx')}>
            <IconDownload size={14} /> Excel
          </button>
          {d?.can_edit && d.next_quarter && (
            <button className="btn btn-primary" disabled={add.isPending} onClick={() => add.mutate()} title="Adds the quarter with costs and % carried forward; you enter revenue and returns">
              <IconPlus size={14} /> Add {d.next_quarter.label}
            </button>
          )}
        </>
      }
    />
  );
  if (q.isLoading) return <>{head}<LoadingBlock height={400} /></>;
  if (q.error || !d) return <>{head}<ErrorState error={q.error} onRetry={() => void q.refetch()} /></>;

  return (
    <>
      {head}
      {add.error ? <div className="mb-3"><InlineError error={add.error} /></div> : null}

      {fq && <Headline q={fq} lines={d.lines} unit="QoQ" />}

      <div className="mb-4 grid gap-4 xl:grid-cols-2">
        {fq && <BridgeCard q={fq} periods={d.quarters} focus={focus} setFocus={setFocus} unit="QoQ" />}
        <TrendCard periods={complete} unit="QoQ" />
      </div>

      <Statement lines={d.lines} periods={d.quarters} canEdit={d.can_edit} unit="QoQ" focus={focus} setFocus={setFocus} onEdit={setEditing} />

      <MethodCard view="quarter" />

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
function Headline({ q, lines, unit }: { q: Period; lines: PnlLine[]; unit: Unit }) {
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
        {q.status === 'in_progress' && <Badge tone="warn">{unit === 'MoM' ? 'Month to date' : 'Quarter in progress'}</Badge>}
        {q.previous && <span>compared with {q.previous}{q.status === 'in_progress' && unit === 'MoM' ? ' (whole month)' : ''}</span>}
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
                <span className="text-muted">{unit}</span>
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
function BridgeCard({ q, periods, focus, setFocus, unit }: { q: Period; periods: Period[]; focus: string | null; setFocus: (s: string) => void; unit: Unit }) {
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
            { label: 'Gateway', value: -(v.payment_gateway ?? 0) },
            { label: 'Loyalty', value: -(v.loyalty ?? 0) },
            { label: 'Technology', value: -(v.tech ?? 0) },
            { label: 'Manpower', value: -(v.manpower ?? 0) },
            { label: 'Misc', value: -(v.misc ?? 0) },
            { label: 'EBITDA', value: v.ebitda ?? 0, total: true },
          ], { unsigned: true, down: t.series[3] })
        : null,
    [t, v, ready],
  );
  const what = unit === 'MoM' ? 'month' : 'quarter';
  return (
    <Card
      title={`Where the revenue goes · ${q.label}`}
      subtitle="Gross Revenue (blue) less each cost (amber) leaves EBITDA (blue)"
      actions={
        <select className="input py-1 text-xs" value={focus ?? ''} onChange={(e) => setFocus(e.target.value)} aria-label={what}>
          {periods.map((x) => <option key={x.start} value={x.start}>{x.label}</option>)}
        </select>
      }
    >
      {option ? <EChart option={option} height={300} ariaLabel={`P&L bridge for ${q.label}`} /> : <p className="py-16 text-center text-sm text-muted">Enter this {what}'s figures to see the bridge.</p>}
    </Card>
  );
}

// ---------------------------------------------------------------- trend
function TrendCard({ periods, unit }: { periods: Period[]; unit: Unit }) {
  const t = useChartTokens();
  const option = useMemo(
    () =>
      cartesian(t, {
        x: periods.map((q) => q.label),
        series: [
          { name: 'Net Revenue', data: periods.map((q) => q.values.net_revenue ?? null), type: 'bar' },
          { name: 'EBITDA', data: periods.map((q) => q.values.ebitda ?? null), type: 'bar' },
        ],
        format: 'inr',
        legend: true,
        showBarLabels: false,
      }),
    [t, periods],
  );
  const what = unit === 'MoM' ? 'month' : 'quarter';
  const margins = periods.map((q) => ({ label: q.label, m: q.values.op_margin, partial: q.status === 'in_progress' }));
  return (
    <Card title={`Revenue and profit by ${what}`} subtitle={unit === 'MoM' ? 'Net Revenue and EBITDA; the current month is month to date' : 'Net Revenue and EBITDA (complete quarters)'}>
      {periods.length ? (
        <>
          <EChart option={option} height={250} ariaLabel={`Net revenue and EBITDA by ${what}`} />
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
            <span className="text-ink2">Operating margin:</span>
            {margins.map((x) => <span key={x.label}>{x.label}{x.partial ? '*' : ''} <b className="font-semibold text-ink">{pct((x.m ?? NaN) * 100)}</b></span>)}
          </div>
        </>
      ) : (
        <p className="py-16 text-center text-sm text-muted">No complete {what} yet.</p>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- the statement (the sheet's layout)
function Statement({ lines, periods, canEdit, unit, focus, setFocus, onEdit }: {
  lines: PnlLine[]; periods: Period[]; canEdit: boolean; unit: Unit;
  focus: string | null; setFocus: (s: string) => void; onEdit: (q: Period) => void;
}) {
  const monthly = unit === 'MoM';
  const last = periods[periods.length - 1];
  return (
    <Card
      title="P&L statement"
      subtitle={monthly
        ? 'Each month with its growth on the month before. Hover a figure to see where it comes from; a dot marks a figure you entered.'
        : 'As in the Excel: each quarter with its growth on the quarter before. Margin rows change in percentage points (pp). Hover a line to see how it is calculated.'}
      bodyClass="p-0"
      className="mb-4"
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-xs text-muted">
              <th className="sticky left-0 z-10 bg-surface px-4 py-2 text-left font-medium">P&amp;L particular</th>
              {periods.map((q) => (
                <th key={q.start} colSpan={2} className={cx('px-3 py-2 text-right font-medium', q.start === focus && 'bg-brand/5')}>
                  <div className="flex items-center justify-end gap-1.5">
                    <button className="font-semibold text-ink hover:underline" onClick={() => setFocus(q.start)} title={`Show this ${monthly ? 'month' : 'quarter'} above`}>{q.label}</button>
                    {q.status === 'in_progress' && <Badge tone="warn">{monthly ? 'to date' : 'in progress'}</Badge>}
                    {canEdit && (
                      <button className="rounded p-0.5 text-muted hover:bg-sunken hover:text-ink" onClick={() => onEdit(q)} title={`Edit ${q.label}`} aria-label={`Edit ${q.label}`}>
                        <IconEdit size={13} />
                      </button>
                    )}
                  </div>
                  <div className="mt-0.5 flex justify-end gap-6 text-[11px] font-normal">
                    <span>Amount</span>
                    <span className="w-16 text-right">{unit}</span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => {
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
                  <td className="sticky left-0 z-10 bg-surface px-4 py-1.5" title={formulaText(l, last)}>
                    <span className={cx(l.label.startsWith('Less:') && 'pl-3 text-ink2', strong && 'text-ink')}>{l.label}</span>
                    {(l.kind === 'assumption') && (
                      <span className="ml-1.5 text-[11px] font-normal not-italic text-muted">{formulaText(l, last)}</span>
                    )}
                  </td>
                  {periods.map((q) => {
                    const v = q.values[l.key];
                    const g = q.growth[l.key];
                    const inputMissing = l.kind === 'input' && (v === null || v === undefined);
                    const input = LINE_INPUT[l.key];
                    const src = monthly && input ? q.sources?.[input] : undefined;
                    const entered = src === 'entered';
                    return (
                      <Fragment key={q.start}>
                        <td
                          className={cx('whitespace-nowrap px-3 py-1.5 text-right tabular-nums', q.start === focus && 'bg-brand/5', l.key === 'ebitda' && v !== null && v < 0 && 'text-bad')}
                          title={src ? `From: ${src}` : undefined}
                        >
                          {inputMissing ? (
                            canEdit ? (
                              <button className="text-xs font-medium text-brand hover:underline" onClick={() => onEdit(q)}>Enter</button>
                            ) : (
                              <span className="text-xs text-muted">not entered</span>
                            )
                          ) : isMargin(l) ? (
                            pct((v ?? NaN) * 100)
                          ) : (
                            <>
                              {entered && <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-brand align-middle" aria-label="entered" />}
                              {money(v)}
                            </>
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

// ---------------------------------------------------------------- method
function MethodCard({ view }: { view: View }) {
  return (
    <Card title="How this P&L is calculated" className="mb-2">
      <ul className="list-disc space-y-1 pl-5 text-xs text-ink2">
        {view === 'month' ? (
          <>
            <li><b>Each month fills in by itself:</b> Gross Revenue = TD order value incl. points of paid orders placed in the month; Returns = customer refunds in the finance tracker for the month's orders (before Feb 2026: the quarter's entered returns, in proportion to revenue); COGS / payment gateway / loyalty % = the month's quarter; Technology, Manpower and Misc = the quarter's figure ÷ 3.</li>
            <li><b>The current month is month to date:</b> revenue so far, and the three costs for the days so far (e.g. 26 of 30 days), so its margin is comparable. Its growth is against the whole previous month.</li>
            <li><b>Edit a month</b> (pencil on its column) to enter any figure; it replaces the automatic one and is marked with a dot. Clear a field to go back to the automatic figure. Changes go to the Audit Log and to Supabase.</li>
            <li>The formulas are the sheet's: Net = Gross − Returns; COGS = 70% of Net; payment gateway 1% and loyalty 0.25% of Gross; CM 1 = Gross Profit − gateway − loyalty; CM 2 = CM 1 − technology − manpower; EBITDA = CM 2 − Misc; operating margin on Gross. The three months of a quarter add up to the quarter (Q1 FY 26-27: ₹7.46 Cr Gross, ₹1.96 Cr EBITDA).</li>
          </>
        ) : (
          <>
            <li><b>Entered each quarter:</b> Gross Revenue, Returns / refunds / cancellations, Technology / platform cost, Manpower &amp; operating cost and Misc. A new quarter starts with the previous quarter's costs and % filled in.</li>
            <li><b>Net Revenue</b> = Gross − Returns. <b>COGS</b> = 70% of Net Revenue, so Gross Margin is 30%. <b>Payment gateway</b> = 1% and <b>Loyalty</b> = 0.25% (0.5% ÷ 2) of Gross Revenue. All three % can be changed per quarter.</li>
            <li><b>CM 1</b> = Gross Profit − payment gateway − loyalty (CM % on Net Revenue). <b>CM 2</b> = CM 1 − technology − manpower. <b>EBITDA</b> = CM 2 − Misc. <b>Operating margin</b> = EBITDA ÷ Gross Revenue, as in the sheet (CM % uses Net Revenue).</li>
            <li><b>Growth</b> = change on the previous quarter, as in the sheet. Two corrections to the sheet: margin rows show the change in percentage points, and loyalty growth is calculated (the sheet had a fixed 0).</li>
            <li>The four quarters Q2 FY25-26 to Q1 FY26-27 are the figures of TD_P&amp;L_QoQ_Rev.xlsx and reproduce it to the paisa. Every change is recorded in the Audit Log and backed up to Supabase (folder <code>pnl</code>).</li>
          </>
        )}
      </ul>
    </Card>
  );
}

// ---------------------------------------------------------------- edit
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

/** A month: every field is optional. Blank = the automatic figure (shown as the placeholder with its source). */
function EditMonth({ m, onClose, onSaved }: { m: Period; onClose: () => void; onSaved: () => void }) {
  const fields = [...AMOUNT_FIELDS, ...PCT_FIELDS];
  const [form, setForm] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.key, m.entered?.[f.key] === null || m.entered?.[f.key] === undefined ? '' : String(m.entered[f.key])])),
  );
  const [notes, setNotes] = useState(m.inputs.notes ?? '');
  const save = useMutation({
    mutationFn: () => patch(`/masters/pnl/months/${m.start.slice(0, 7)}/`, { ...form, notes }),
    onSuccess: () => { onSaved(); onClose(); },
  });
  const auto = (k: keyof Inputs) => {
    const v = m.sources?.[k] === 'entered' ? null : (m.inputs[k] as number | null);
    return v;
  };
  const isPct = (k: keyof Inputs) => PCT_FIELDS.some((f) => f.key === k);
  const show = (k: keyof Inputs, v: number | null) => (v === null ? '–' : isPct(k) ? `${+v.toFixed(4)}%` : money(v));
  return (
    <Drawer open onClose={onClose} title={`Edit P&L · ${m.label}`} width={540}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <p className="text-xs text-muted">
          Leave a field blank to use the automatic figure (shown in grey with where it comes from). Anything you enter replaces it for this month only.
          {m.status === 'in_progress' ? ' This month is in progress: the automatic costs cover the days so far.' : ''}
        </p>
        {fields.map((f) => {
          const a = auto(f.key);
          const src = m.sources?.[f.key];
          return (
            <Field key={f.key} label={f.label} hint={src && src !== 'entered' ? `Automatic: ${show(f.key, a)} · ${src}` : isPct(f.key) ? (f as { hint?: string }).hint : undefined}>
              <div className="flex gap-2">
                <input
                  className="input flex-1 tabular-nums"
                  inputMode="decimal"
                  value={form[f.key]}
                  onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                  placeholder={a === null ? 'Enter amount' : `${show(f.key, a)} (automatic)`}
                />
                {form[f.key] !== '' && (
                  <button type="button" className="btn btn-sm whitespace-nowrap" onClick={() => setForm({ ...form, [f.key]: '' })} title="Go back to the automatic figure">
                    Use automatic
                  </button>
                )}
              </div>
            </Field>
          );
        })}
        <Field label="Notes">
          <textarea className="input min-h-[64px]" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        {save.error ? <InlineError error={save.error} /> : null}
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save'}</button>
        </div>
        {m.updated_by && <p className="text-[11px] text-muted">Last changed by {m.updated_by}{m.updated_at ? ` on ${new Date(m.updated_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}` : ''}</p>}
      </form>
    </Drawer>
  );
}

function EditQuarter({ q, isLatest, onClose, onSaved }: { q: Period; isLatest: boolean; onClose: () => void; onSaved: () => void }) {
  const init = () => Object.fromEntries([...AMOUNT_FIELDS, ...PCT_FIELDS].map((f) => [f.key, q.inputs[f.key] === null ? '' : String(q.inputs[f.key])]));
  const [form, setForm] = useState<Record<string, string>>(init);
  const [notes, setNotes] = useState(q.inputs.notes ?? '');
  const dataFor = (key: string) => q.checks?.rows.find((r) => r.key === key)?.data ?? null;
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
        {q.updated_by && <p className="text-[11px] text-muted">Last changed by {q.updated_by}{q.updated_at ? ` on ${new Date(q.updated_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}` : ''}</p>}
      </form>
    </Drawer>
  );
}
