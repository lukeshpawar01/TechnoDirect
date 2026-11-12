import type { EChartsOption } from 'echarts';
import { hours, inr, inrAxis, num, numAxis, pct } from '@/lib/format';
import { axisStyle, baseOption } from './EChart';
import type { ChartTokens } from './palette';

export type ValueFormat = 'inr' | 'num' | 'pct' | 'hours' | 'dec';

export function fmtValue(v: unknown, f: ValueFormat): string {
  const n = typeof v === 'number' ? v : Number(v);
  if (v === null || v === undefined || Number.isNaN(n)) return '–';
  switch (f) {
    case 'inr':
      return inr(n);
    case 'pct':
      return pct(n);
    case 'hours':
      return hours(n);
    case 'dec':
      return num(n, 2);
    default:
      return num(n);
  }
}

export function fmtAxis(v: number, f: ValueFormat): string {
  switch (f) {
    case 'inr':
      return inrAxis(v);
    case 'pct':
      return `${v}%`;
    case 'hours':
      return `${v}h`;
    case 'dec':
      return String(v);
    default:
      return numAxis(v);
  }
}

export interface SeriesSpec {
  name: string;
  data: (number | null)[];
  type?: 'bar' | 'line';
  color?: string;
  stack?: string;
  area?: boolean;
  /** de-emphasised comparison series (prior year, target) */
  ghost?: boolean;
  dashed?: boolean;
  endLabel?: boolean;
  /** per-bar colours (e.g. status) */
  colors?: string[];
}

interface CartesianOpts {
  x: string[];
  series: SeriesSpec[];
  format?: ValueFormat;
  horizontal?: boolean;
  markLine?: { value: number; label: string };
  legend?: boolean;
  yMax?: number;
  showBarLabels?: boolean;
}

/** Bars and/or lines on ONE value axis (never dual-axis). */
export function cartesian(t: ChartTokens, o: CartesianOpts): EChartsOption {
  const f = o.format ?? 'num';
  const base = baseOption(t);
  const ax = axisStyle(t);
  const showLegend = o.legend ?? o.series.length > 1;
  const hasStack = o.series.some((s) => s.stack);
  const lastStackIdx = new Map<string, number>();
  o.series.forEach((s, i) => s.stack && lastStackIdx.set(s.stack, i));

  const valueAxis = {
    type: 'value' as const,
    ...ax,
    axisLine: { show: false },
    // keep a reference line (e.g. 100% target) inside the plot
    max: o.yMax ?? (o.markLine ? (v: { max: number }) => Math.max(v.max, o.markLine!.value) * 1.08 : undefined),
    axisLabel: { ...ax.axisLabel, formatter: (v: number) => fmtAxis(v, f) },
  };
  const catAxis = {
    type: 'category' as const,
    data: o.x,
    ...ax,
    splitLine: { show: false },
    axisLabel: { ...ax.axisLabel, hideOverlap: true },
  };

  const series = o.series.map((s, i) => {
    const color = s.color ?? t.series[i] ?? t.deemph;
    if ((s.type ?? 'bar') === 'line') {
      return {
        name: s.name,
        type: 'line' as const,
        data: s.data,
        smooth: false,
        showSymbol: false,
        symbol: 'circle',
        symbolSize: 8,
        connectNulls: false,
        lineStyle: { width: 2, color, type: s.dashed ? ('dashed' as const) : ('solid' as const), cap: 'round' as const, join: 'round' as const },
        itemStyle: { color, borderColor: t.surface, borderWidth: 2 },
        areaStyle: s.area ? { color, opacity: 0.1 } : undefined,
        emphasis: { focus: 'series' as const },
        endLabel: s.endLabel
          ? { show: true, color: t.ink2, fontSize: 11, formatter: (p: { value: unknown }) => fmtValue(Array.isArray(p.value) ? p.value[1] : p.value, f) }
          : undefined,
        z: s.ghost ? 2 : 3,
      };
    }
    const isTop = !s.stack || lastStackIdx.get(s.stack) === i;
    const r = 4;
    const radius = o.horizontal ? [0, r, r, 0] : [r, r, 0, 0];
    return {
      name: s.name,
      type: 'bar' as const,
      stack: s.stack,
      data: s.colors
        ? s.data.map((v, j) => ({ value: v, itemStyle: { color: s.colors![j] ?? color } }))
        : s.data.map((v) => ({
            value: v,
            // negative values in a stack (e.g. "lost") round at the bottom end
            itemStyle: v !== null && v < 0 ? { borderRadius: o.horizontal ? [r, 0, 0, r] : [0, 0, r, r] } : undefined,
          })),
      barMaxWidth: 24,
      barGap: '10%',
      itemStyle: {
        color: s.ghost ? t.deemph : color,
        borderRadius: hasStack && !isTop ? 0 : radius,
        // 2px surface gap between touching segments/bars (never a dark outline)
        borderColor: t.surface,
        borderWidth: hasStack ? 1 : 0,
      },
      label: o.showBarLabels
        ? { show: true, position: o.horizontal ? ('right' as const) : ('top' as const), color: t.ink2, fontSize: 11, formatter: (p: { value: unknown }) => fmtValue(p.value, f) }
        : undefined,
      emphasis: { focus: 'series' as const },
      markLine:
        o.markLine && i === 0
          ? {
              silent: true,
              symbol: 'none',
              lineStyle: { color: t.target, width: 1.5, type: 'solid' as const },
              label: { color: t.ink2, formatter: o.markLine.label, position: 'insideStartTop' as const, fontSize: 11 },
              data: [o.horizontal ? { xAxis: o.markLine.value } : { yAxis: o.markLine.value }],
            }
          : undefined,
    };
  });

  return {
    ...base,
    legend: showLegend ? base.legend : { show: false },
    grid: { left: 8, right: o.series.some((s) => s.endLabel) ? 72 : o.horizontal && o.showBarLabels ? 64 : 16, top: showLegend ? 32 : o.showBarLabels && !o.horizontal ? 22 : 12, bottom: 4, containLabel: true },
    tooltip: {
      ...(base.tooltip as object),
      trigger: 'axis',
      axisPointer: o.series.some((s) => s.type === 'line') ? { type: 'line', lineStyle: { color: t.axis } } : { type: 'shadow', shadowStyle: { color: t.grid, opacity: 0.5 } },
      valueFormatter: (v: unknown) => fmtValue(v, f),
    },
    xAxis: o.horizontal ? valueAxis : catAxis,
    yAxis: o.horizontal ? { ...catAxis, inverse: true } : valueAxis,
    series,
  } as EChartsOption;
}

/** Heatmap: sequential single-hue ramp with a scale legend. data = [xIndex, yIndex, value|null] */
export function heatmap(
  t: ChartTokens,
  o: { x: string[]; y: string[]; data: [number, number, number | null][]; format?: ValueFormat; min?: number; max?: number; labels?: boolean },
): EChartsOption {
  const f = o.format ?? 'num';
  const vals = o.data.map((d) => d[2]).filter((v): v is number => v !== null);
  const ax = axisStyle(t);
  return {
    ...baseOption(t),
    legend: { show: false },
    grid: { left: 8, right: 16, top: 8, bottom: 44, containLabel: true },
    tooltip: {
      ...(baseOption(t).tooltip as object),
      trigger: 'item',
      formatter: (p: unknown) => {
        const d = (p as { value: [number, number, number | string] }).value;
        return `${o.y[d[1]]} · ${o.x[d[0]]}<br/><b>${fmtValue(d[2] === '-' ? null : d[2], f)}</b>`;
      },
    },
    xAxis: { type: 'category', data: o.x, ...ax, splitLine: { show: false }, axisLine: { show: false }, position: 'top' },
    yAxis: { type: 'category', data: o.y, ...ax, splitLine: { show: false }, axisLine: { show: false }, inverse: true },
    visualMap: {
      min: o.min ?? Math.min(0, ...vals),
      max: o.max ?? Math.max(1, ...vals),
      calculable: false,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      itemHeight: 140,
      itemWidth: 10,
      text: [fmtValue(o.max ?? Math.max(1, ...vals), f), fmtValue(o.min ?? 0, f)],
      textStyle: { color: t.muted, fontSize: 11 },
      inRange: { color: t.sequential },
    },
    series: [
      {
        type: 'heatmap',
        // Label ink is picked per cell from the fill's lightness (white on dark steps, near-black on light).
        data: o.data.map((d) => {
          if (d[2] === null) return [d[0], d[1], '-'];
          const lo = o.min ?? Math.min(0, ...vals);
          const hi = o.max ?? Math.max(1, ...vals);
          const n = hi > lo ? (d[2] - lo) / (hi - lo) : 0;
          const darkFill = t.theme === 'dark' ? n < 0.55 : n > 0.45;
          return { value: d, label: { color: darkFill ? '#ffffff' : '#0b0b0b' } };
        }),
        itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 3 },
        label: o.labels
          ? {
              show: true,
              fontSize: 10,
              formatter: (p: unknown) => {
                const v = (p as { value: [number, number, number | string] }).value[2];
                return typeof v === 'number' ? (f === 'pct' ? `${Math.round(v)}` : fmtAxis(v, f)) : '';
              },
            }
          : undefined,
        emphasis: { itemStyle: { borderColor: t.ink, borderWidth: 1 } },
      },
    ],
  } as EChartsOption;
}

/** Funnel for ordered stages — ordinal single-hue ramp, conversion % in tooltip. */
export function funnel(t: ChartTokens, stages: { label: string; count: number }[]): EChartsOption {
  const top = stages[0]?.count || 1;
  return {
    ...baseOption(t),
    legend: { show: false },
    tooltip: {
      ...(baseOption(t).tooltip as object),
      trigger: 'item',
      formatter: (p: unknown) => {
        const x = p as { name: string; value: number; dataIndex: number };
        const prev = x.dataIndex > 0 ? stages[x.dataIndex - 1].count : null;
        return `${x.name}<br/><b>${num(x.value)}</b> · ${pct((x.value / top) * 100)} of top${
          prev ? `<br/>${pct((x.value / prev) * 100)} from previous stage` : ''
        }`;
      },
    },
    series: [
      {
        type: 'funnel',
        sort: 'none',
        left: '4%',
        width: '62%',
        top: 8,
        bottom: 8,
        minSize: '8%',
        gap: 2,
        data: stages.map((s, i) => ({ name: s.label, value: s.count, itemStyle: { color: t.ordinal[Math.min(i, t.ordinal.length - 1)], borderColor: t.surface, borderWidth: 0 } })),
        label: {
          position: 'right',
          color: t.ink2,
          fontSize: 12,
          formatter: (p: unknown) => {
            const x = p as { name: string; value: number };
            return `{n|${x.name}}  {v|${num(x.value)}}  {p|${pct((x.value / top) * 100, 0)}}`;
          },
          rich: { n: { color: t.ink2, fontSize: 12 }, v: { color: t.ink, fontWeight: 600, fontSize: 12 }, p: { color: t.muted, fontSize: 11 } },
        },
        labelLine: { show: true, lineStyle: { color: t.axis } },
      },
    ],
  } as EChartsOption;
}

/** Tiny sparkline: de-emphasis line, current (last) point in the accent. */
export function sparkline(t: ChartTokens, data: number[], accent?: string): EChartsOption {
  const last = data.length - 1;
  return {
    animation: false,
    grid: { left: 2, right: 6, top: 4, bottom: 4 },
    xAxis: { type: 'category', show: false, data: data.map((_, i) => i) },
    yAxis: { type: 'value', show: false, scale: true },
    tooltip: { show: false },
    series: [
      {
        type: 'line',
        data: data.map((v, i) =>
          i === last
            ? { value: v, symbol: 'circle', symbolSize: 7, itemStyle: { color: accent ?? t.series[0], borderColor: t.surface, borderWidth: 1.5 } }
            : v,
        ),
        showSymbol: true,
        symbol: 'none',
        lineStyle: { width: 1.5, color: t.deemph },
        silent: true,
      },
    ],
  } as EChartsOption;
}
