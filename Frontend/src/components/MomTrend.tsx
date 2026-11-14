import { useMemo, useState } from 'react';
import type { EChartsOption } from 'echarts';
import { useAnalytics } from '@/api/hooks';
import type { MomMonth, MomTrend as MomTrendData } from '@/api/types';
import { fmtAxis, fmtValue, type ValueFormat } from '@/charts/builders';
import { EChart, axisStyle, baseOption, useChartTokens } from '@/charts/EChart';
import type { ChartTokens } from '@/charts/palette';
import { DataTable } from './DataTable';
import { Card, Delta, EmptyState, ErrorState, Segmented, Skeleton } from './ui';
import { inr, monthLabel, num, signedPct } from '@/lib/format';

type Qty = 'pieces' | 'boxes';
type View = 'chart' | 'table';
type Range = '6' | '12' | '24';

const GROUP = 'mom-trend';
// identical plot margins so the three panels' month columns line up vertically
const GRID = { left: 64, right: 88, top: 14, bottom: 26, containLabel: false };

const qtyLabel = (q: Qty) => (q === 'pieces' ? 'Pieces' : 'Boxes');
const qtyOf = (r: MomMonth, q: Qty) => (q === 'pieces' ? r.pieces : r.boxes);
const qtyMom = (r: MomMonth, q: Qty) => (q === 'pieces' ? r.pieces_mom_pct : r.boxes_mom_pct);

function xLabel(r: MomMonth) {
  return r.is_partial ? `${monthLabel(r.month)} · MTD` : monthLabel(r.month);
}

function basisNote(r: MomMonth) {
  return r.is_partial ? `days 1–${r.days} vs same days of previous month` : 'vs previous month';
}

/** Diagonal hatch in the series colour marking the running (incomplete) month — texture, not colour alone. */
const hatchCache = new Map<string, HTMLCanvasElement>();
function hatch(color: string, t: ChartTokens): { image: HTMLCanvasElement; repeat: 'repeat' } | string {
  if (typeof document === 'undefined') return color;
  const key = color + t.theme;
  let c = hatchCache.get(key);
  if (!c) {
    c = document.createElement('canvas');
    const size = 8;
    c.width = c.height = size * 2; // 2x for crisp stripes on HiDPI
    const g = c.getContext('2d')!;
    g.scale(2, 2);
    g.fillStyle = color;
    g.globalAlpha = 0.45;
    g.fillRect(0, 0, size, size);
    g.globalAlpha = 1;
    g.strokeStyle = color;
    g.lineWidth = 2;
    g.beginPath();
    for (let k = -size; k <= size * 2; k += 4) {
      g.moveTo(k, size);
      g.lineTo(k + size, 0);
    }
    g.stroke();
    hatchCache.set(key, c);
  }
  return { image: c, repeat: 'repeat' };
}

function tooltipBox(t: ChartTokens, title: string, rows: [string, string, string?][]) {
  const line = (c: string, label: string, value: string) =>
    `<div style="display:flex;align-items:center;gap:8px;justify-content:space-between;min-width:190px">` +
    `<span style="display:inline-flex;align-items:center;gap:6px;color:${t.ink2}">` +
    (c ? `<span style="width:8px;height:8px;border-radius:2px;background:${c};display:inline-block"></span>` : '') +
    `${label}</span><b style="color:${t.ink}">${value}</b></div>`;
  return `<div style="font-size:12px;line-height:1.6"><div style="font-weight:600;color:${t.ink};margin-bottom:2px">${title}</div>${rows
    .map(([label, value, c]) => line(c ?? '', label, value))
    .join('')}</div>`;
}

/** One measure per panel (never a dual axis), bars anchored at zero. */
function barPanel(t: ChartTokens, rows: MomMonth[], o: { name: string; color: string; fmt: ValueFormat; values: number[]; mom: (number | null)[] }): EChartsOption {
  const ax = axisStyle(t);
  const base = baseOption(t);
  return {
    ...base,
    legend: { show: false },
    grid: GRID,
    tooltip: {
      ...(base.tooltip as object),
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: t.grid, opacity: 0.6 } },
      formatter: (ps: unknown) => {
        const p = (Array.isArray(ps) ? ps[0] : ps) as { dataIndex: number };
        const r = rows[p.dataIndex];
        const m = o.mom[p.dataIndex];
        return tooltipBox(t, xLabel(r), [
          [o.name, fmtValue(o.values[p.dataIndex], o.fmt), o.color],
          ['MoM', m === null ? '–' : signedPct(m)],
          ['Basis', basisNote(r)],
        ]);
      },
    },
    xAxis: { type: 'category', data: rows.map(xLabel), ...ax, splitLine: { show: false }, axisLabel: { ...ax.axisLabel, hideOverlap: true, interval: rows.length <= 12 ? 0 : 'auto' } },
    yAxis: { type: 'value', ...ax, axisLine: { show: false }, splitNumber: 3, axisLabel: { ...ax.axisLabel, formatter: (v: number) => fmtAxis(v, o.fmt) } },
    series: [
      {
        name: o.name,
        type: 'bar',
        barMaxWidth: 28,
        data: rows.map((r, i) => ({
          value: o.values[i],
          itemStyle: r.is_partial ? { color: hatch(o.color, t) } : undefined,
        })),
        itemStyle: { color: o.color, borderRadius: [4, 4, 0, 0] },
        emphasis: { focus: 'none' },
        // selective direct label: only the latest month carries its value
        label: {
          show: true,
          position: 'top',
          color: t.ink2,
          fontSize: 11,
          formatter: (p: { dataIndex: number; value: unknown }) => (p.dataIndex === rows.length - 1 ? fmtValue(p.value, o.fmt) : ''),
        },
      },
    ],
  } as EChartsOption;
}

/** Both growth rates share one % axis — same unit, so overlaying them is honest. */
function growthPanel(t: ChartTokens, rows: MomMonth[], q: Qty): EChartsOption {
  const ax = axisStyle(t);
  const base = baseOption(t);
  const value = rows.map((r) => r.sales_mom_pct);
  const qty = rows.map((r) => qtyMom(r, q));
  const line = (name: string, data: (number | null)[], color: string) => ({
    name,
    type: 'line' as const,
    data,
    connectNulls: false,
    showSymbol: true,
    symbol: 'circle',
    symbolSize: 8,
    lineStyle: { width: 2, color, cap: 'round' as const, join: 'round' as const },
    itemStyle: { color, borderColor: t.surface, borderWidth: 2 },
    // comparison chart: hovering one line must not fade the other
    emphasis: { focus: 'none' as const },
    endLabel: { show: true, color: t.ink2, fontSize: 11, formatter: (p: { seriesName: string }) => p.seriesName },
  });
  return {
    ...base,
    legend: { ...(base.legend as object), show: true, top: 0, right: 0, left: 'auto' },
    grid: { ...GRID, top: 30 },
    tooltip: {
      ...(base.tooltip as object),
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: t.axis } },
      formatter: (ps: unknown) => {
        const p = (Array.isArray(ps) ? ps[0] : ps) as { dataIndex: number };
        const i = p.dataIndex;
        const r = rows[i];
        const gap = value[i] !== null && qty[i] !== null ? (value[i] as number) - (qty[i] as number) : null;
        return tooltipBox(t, xLabel(r), [
          ['Sales value MoM', value[i] === null ? '–' : signedPct(value[i]), t.series[0]],
          [`${qtyLabel(q)} MoM`, qty[i] === null ? '–' : signedPct(qty[i]), t.series[1]],
          ['Value − volume gap', gap === null ? '–' : `${gap > 0 ? '+' : ''}${gap.toFixed(1)} pts`],
          ['Basis', basisNote(r)],
        ]);
      },
    },
    xAxis: { type: 'category', data: rows.map(xLabel), ...ax, splitLine: { show: false }, axisLabel: { ...ax.axisLabel, hideOverlap: true, interval: rows.length <= 12 ? 0 : 'auto' } },
    yAxis: { type: 'value', ...ax, axisLine: { show: false }, splitNumber: 4, axisLabel: { ...ax.axisLabel, formatter: (v: number) => `${v}%` } },
    series: [
      {
        ...line('Sales value', value, t.series[0]),
        // zero = no change: the reference every growth reading is judged against
        markLine: { silent: true, symbol: 'none', lineStyle: { color: t.muted, width: 1, type: 'solid' }, label: { show: false }, data: [{ yAxis: 0 }] },
      },
      line(qtyLabel(q), qty, t.series[1]),
    ],
  } as EChartsOption;
}

/** Plain-language read of the latest month with a comparison: did value move with volume, or on price / mix? */
function insight(r: MomMonth | undefined, q: Qty): string | null {
  if (!r || r.sales_mom_pct === null || qtyMom(r, q) === null) return null;
  const v = r.sales_mom_pct;
  const u = qtyMom(r, q) as number;
  const when = r.is_partial ? `${monthLabel(r.month)} (days 1–${r.days}) vs the same days last month` : `${monthLabel(r.month)} vs the previous month`;
  const gap = v - u;
  const driver =
    Math.abs(gap) < 1
      ? 'value moved in line with volume'
      : gap > 0
        ? `value grew ${gap.toFixed(1)} pts faster than volume, so the average price per piece rose (price / mix)`
        : `volume grew ${Math.abs(gap).toFixed(1)} pts faster than value, so the average price per piece fell (cheaper mix or discounts)`;
  return `${when}: sales value ${signedPct(v)}, ${qtyLabel(q).toLowerCase()} ${signedPct(u)} — ${driver}.`;
}

export function MomTrend() {
  const [range, setRange] = useState<Range>('12');
  const [qty, setQty] = useState<Qty>('pieces');
  const [view, setView] = useState<View>('chart');
  const q = useAnalytics<MomTrendData>('/trends/mom/', { months: range });
  const t = useChartTokens();
  // months before the first loaded month are 'no data', not zero sales: leave them off the axis
  const rows = useMemo(() => {
    const all = q.data?.data?.months ?? [];
    const first = all.findIndex((r) => r.sales > 0 || r.pieces > 0);
    return first < 0 ? [] : all.slice(first);
  }, [q.data]);
  const hasGrowth = rows.some((r) => r.sales_mom_pct !== null || qtyMom(r, qty) !== null);
  const withData = rows.filter((r) => r.sales > 0 || r.pieces > 0);
  const latest = rows[rows.length - 1];
  const latestCompared = [...rows].reverse().find((r) => r.sales_mom_pct !== null);

  const valueOpt = useMemo(
    () => (rows.length ? barPanel(t, rows, { name: 'Sales value', color: t.series[0], fmt: 'inr', values: rows.map((r) => r.sales), mom: rows.map((r) => r.sales_mom_pct) }) : null),
    [rows, t],
  );
  const qtyOpt = useMemo(
    () => (rows.length ? barPanel(t, rows, { name: qtyLabel(qty), color: t.series[1], fmt: 'num', values: rows.map((r) => qtyOf(r, qty)), mom: rows.map((r) => qtyMom(r, qty)) }) : null),
    [rows, t, qty],
  );
  const growthOpt = useMemo(() => (rows.length ? growthPanel(t, rows, qty) : null), [rows, t, qty]);
  const note = insight(latestCompared, qty);

  const controls = (
    <div className="flex flex-wrap items-center gap-2">
      <Segmented<Qty> value={qty} onChange={setQty} options={[{ value: 'pieces', label: 'Pieces' }, { value: 'boxes', label: 'Boxes' }]} />
      <Segmented<Range> value={range} onChange={setRange} options={[{ value: '6', label: '6M' }, { value: '12', label: '12M' }, { value: '24', label: '24M' }]} />
      <Segmented<View> value={view} onChange={setView} options={[{ value: 'chart', label: 'Chart' }, { value: 'table', label: 'Table' }]} />
    </div>
  );

  return (
    <Card
      title="Month-on-month: sales value vs quantity"
      subtitle="Value and volume on separate scales, aligned by month · growth compared on one % axis · running month is like-for-like (MTD)"
      actions={controls}
    >
      {q.error && !q.data ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : q.isLoading ? (
        <Skeleton className="h-[560px]" />
      ) : !withData.length ? (
        <EmptyState title="No sales in this range" hint="Change the filters or the range." height={200} />
      ) : (
        <>
          {/* headline: latest month and its MoM for each measure */}
          <div className="mb-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Headline label={`Sales value · ${latest ? xLabel(latest) : ''}`} value={inr(latest?.sales, { compact: true })} delta={latest?.sales_mom_pct} color={t.series[0]} />
            <Headline label={`${qtyLabel(qty)} · ${latest ? xLabel(latest) : ''}`} value={num(latest ? qtyOf(latest, qty) : null)} delta={latest ? qtyMom(latest, qty) : null} color={t.series[1]} />
            <Headline label="Avg price per piece" value={latest?.avg_price_per_piece ? inr(latest.avg_price_per_piece) : '–'} delta={latest?.avg_price_mom_pct} />
            <Headline label="Orders" value={num(latest?.orders)} sub={latest?.is_partial ? `${latest.days} days so far` : undefined} />
          </div>
          {withData.length < 2 && (
            <div className="mb-3 rounded-md border border-warn/30 bg-warn-bg px-3 py-2 text-xs text-ink2">
              Sales data starts {monthLabel(q.data!.data.first_data_month ?? latest.month)}, so there is no earlier month to compare with yet. MoM % appears once a second month of orders is loaded.
            </div>
          )}
          {note && <p className="mb-3 text-sm text-ink2">{note}</p>}

          {view === 'chart' ? (
            <div className="space-y-1">
              <PanelTitle color={t.series[0]} title="Sales value (₹)" />
              <EChart option={valueOpt!} height={180} group={GROUP} ariaLabel="Monthly sales value" />
              <PanelTitle color={t.series[1]} title={`Quantity (${qtyLabel(qty).toLowerCase()})`} />
              <EChart option={qtyOpt!} height={180} group={GROUP} ariaLabel={`Monthly quantity in ${qty}`} />
              <PanelTitle title="MoM growth % — value vs quantity" />
              {hasGrowth ? (
                <EChart option={growthOpt!} height={210} group={GROUP} ariaLabel="Month-on-month growth of sales value and quantity" />
              ) : (
                <EmptyState title="Growth % needs two months of data" hint="It appears automatically once the previous month's orders are loaded." height={120} />
              )}
              <p className="pt-1 text-2xs text-muted">
                Hatched bar = month still running; its MoM compares the same number of days of the previous month. When value grows faster than quantity, the
                average price per piece is rising (price or product mix); when quantity grows faster, it is falling.
              </p>
            </div>
          ) : (
            <DataTable<MomMonth>
              rows={[...rows].reverse()}
              rowKey={(r) => r.month}
              exportName="mom_sales_vs_quantity"
              exportPath="/trends/mom/"
              exportParams={{ months: range }}
              pageSize={24}
              columns={[
                { key: 'month', header: 'Month', render: (r) => xLabel(r), value: (r) => r.month },
                { key: 'sales', header: 'Sales value', align: 'right', render: (r) => inr(r.sales) },
                { key: 'sales_mom_pct', header: 'Value MoM', align: 'right', render: (r) => <Delta value={r.sales_mom_pct} suffix="" /> },
                { key: 'qty', header: qtyLabel(qty), align: 'right', render: (r) => num(qtyOf(r, qty)), value: (r) => qtyOf(r, qty) },
                { key: 'qty_mom', header: `${qtyLabel(qty)} MoM`, align: 'right', render: (r) => <Delta value={qtyMom(r, qty)} suffix="" />, value: (r) => qtyMom(r, qty) },
                { key: 'avg_price_per_piece', header: 'Avg ₹ / piece', align: 'right', render: (r) => (r.avg_price_per_piece ? inr(r.avg_price_per_piece) : '–') },
                { key: 'avg_price_mom_pct', header: 'Price MoM', align: 'right', render: (r) => <Delta value={r.avg_price_mom_pct} suffix="" /> },
                { key: 'orders', header: 'Orders', align: 'right', render: (r) => num(r.orders) },
                { key: 'basis', header: 'MoM basis', render: (r) => <span className="text-xs text-muted">{basisNote(r)}</span> },
              ]}
            />
          )}
        </>
      )}
    </Card>
  );
}

function PanelTitle({ title, color }: { title: string; color?: string }) {
  return (
    <div className="flex items-center gap-1.5 pt-2 text-xs font-medium text-ink2">
      {color && <span className="inline-block h-2 w-2 rounded-sm" style={{ background: color }} aria-hidden="true" />}
      {title}
    </div>
  );
}

function Headline({ label, value, delta, sub, color }: { label: string; value: string; delta?: number | null; sub?: string; color?: string }) {
  return (
    <div className="rounded-md border border-line px-3 py-2">
      <div className="flex items-center gap-1.5 text-xs text-ink2">
        {color && <span className="inline-block h-2 w-2 rounded-sm" style={{ background: color }} aria-hidden="true" />}
        {label}
      </div>
      <div className="mt-0.5 text-lg font-semibold text-ink">{value}</div>
      {delta !== undefined ? <Delta value={delta} suffix="MoM" /> : sub ? <div className="text-xs text-muted">{sub}</div> : null}
    </div>
  );
}
