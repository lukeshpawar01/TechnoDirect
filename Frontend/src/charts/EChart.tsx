import { useMemo, useRef } from 'react';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { BarChart, FunnelChart, HeatmapChart, LineChart, PieChart, ScatterChart } from 'echarts/charts';
import {
  AriaComponent,
  DatasetComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { EChartsOption } from 'echarts';
import { useTheme } from '@/lib/theme';
import { chartTokens, type ChartTokens } from './palette';

echarts.use([
  BarChart,
  LineChart,
  FunnelChart,
  HeatmapChart,
  ScatterChart,
  PieChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  VisualMapComponent,
  MarkLineComponent,
  MarkPointComponent,
  DatasetComponent,
  AriaComponent,
  CanvasRenderer,
]);

export function useChartTokens(): ChartTokens {
  const { theme } = useTheme();
  return useMemo(() => chartTokens(theme), [theme]);
}

/** Base chrome shared by every chart: recessive hairline grid, text-token labels, tooltip. */
export function baseOption(t: ChartTokens): EChartsOption {
  return {
    backgroundColor: 'transparent',
    color: t.series,
    textStyle: { fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif', color: t.ink2 },
    aria: { enabled: true },
    animationDuration: 300,
    grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true },
    tooltip: {
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      borderWidth: 1,
      textStyle: { color: t.ink, fontSize: 12 },
      extraCssText: 'box-shadow: 0 4px 16px rgba(0,0,0,.12); border-radius: 8px;',
    },
    legend: {
      // one row that pages when it doesn't fit; a wrapped second row would overlap the plot (grid top is fixed)
      type: 'scroll',
      pageIconColor: t.ink2,
      pageIconInactiveColor: t.muted,
      pageIconSize: 10,
      pageTextStyle: { color: t.muted, fontSize: 11 },
      top: 0,
      left: 0,
      icon: 'roundRect',
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 14,
      textStyle: { color: t.ink2, fontSize: 12 },
    },
  };
}

export function axisStyle(t: ChartTokens) {
  return {
    axisLine: { lineStyle: { color: t.axis, width: 1 } },
    axisTick: { show: false },
    axisLabel: { color: t.muted, fontSize: 11 },
    splitLine: { lineStyle: { color: t.grid, width: 1, type: 'solid' as const } },
  };
}

interface Props {
  option: EChartsOption;
  height?: number;
  ariaLabel?: string;
  onClick?: (params: { name: string; dataIndex: number; seriesName?: string; value?: unknown; data?: unknown }) => void;
  /** Charts sharing a group get one linked crosshair / tooltip (small multiples on a common x-axis). */
  group?: string;
  /** Line charts: a click anywhere in a category's column counts (not only on the small data dots). */
  clickAxis?: boolean;
}

export function EChart({ option, height = 280, ariaLabel, onClick, group, clickAxis }: Props) {
  const clickRef = useRef(onClick);
  clickRef.current = onClick;
  const events = useMemo(() => (onClick && !clickAxis ? { click: onClick } : undefined), [onClick, clickAxis]);
  const onReady = useMemo(
    () =>
      group || clickAxis
        ? (inst: echarts.ECharts) => {
            if (group) {
              inst.group = group;
              echarts.connect(group);
            }
            if (clickAxis) {
              inst.getZr().on('click', (e: { offsetX: number; offsetY: number }) => {
                const pt = [e.offsetX, e.offsetY];
                if (!clickRef.current || !inst.containPixel({ gridIndex: 0 }, pt)) return;
                const xi = inst.convertFromPixel({ gridIndex: 0 }, pt) as unknown as number | number[] | null;
                if (xi == null) return;
                const idx = Math.round(Array.isArray(xi) ? xi[0] : xi);
                const cats = ((inst.getOption().xAxis as { data?: unknown[] }[] | undefined)?.[0]?.data ?? []) as unknown[];
                if (idx >= 0 && idx < cats.length) clickRef.current({ name: String(cats[idx]), dataIndex: idx });
              });
            }
          }
        : undefined,
    [group, clickAxis],
  );
  return (
    <div role="img" aria-label={ariaLabel} style={{ height }} className={onClick ? 'cursor-pointer' : undefined}>
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        notMerge
        lazyUpdate
        style={{ height: '100%', width: '100%' }}
        onEvents={events}
        onChartReady={onReady}
        opts={{ renderer: 'canvas' }}
      />
    </div>
  );
}
