import { useMemo } from 'react';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { BarChart, FunnelChart, HeatmapChart, LineChart } from 'echarts/charts';
import {
  AriaComponent,
  DatasetComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
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
  GridComponent,
  TooltipComponent,
  LegendComponent,
  VisualMapComponent,
  MarkLineComponent,
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
}

export function EChart({ option, height = 280, ariaLabel, onClick }: Props) {
  const events = useMemo(() => (onClick ? { click: onClick } : undefined), [onClick]);
  return (
    <div role="img" aria-label={ariaLabel} style={{ height }} className={onClick ? 'cursor-pointer' : undefined}>
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        notMerge
        lazyUpdate
        style={{ height: '100%', width: '100%' }}
        onEvents={events}
        opts={{ renderer: 'canvas' }}
      />
    </div>
  );
}
