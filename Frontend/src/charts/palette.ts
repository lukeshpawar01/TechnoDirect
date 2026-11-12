/**
 * Chart palette — derived from the dataviz skill's reference palette, with slot 1
 * re-stepped toward the Technosport navy brand. Validated with
 * scripts/validate_palette.js (adjacent pairlist):
 *   light vs #ffffff : CVD worst 9.1, normal-vision worst 19.6 — PASS
 *                      (aqua/yellow/magenta < 3:1 → relief rule: legends, labels + table view)
 *   dark  vs #141a2e : CVD worst 8.4, normal-vision worst 19.3, all ≥ 3:1 — PASS
 * Rules: hues assigned in fixed order, never cycled; a 9th series folds into "Other".
 * Status colours are reserved for good/warning/serious/critical meaning only.
 */
import type { ResolvedTheme } from '@/lib/theme';

export const CATEGORICAL = {
  light: ['#3a56b0', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'],
  dark: ['#5b78d6', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
};

/** Sequential single-hue ramp (blue) for magnitude (heatmaps). Light → dark. */
export const SEQUENTIAL_BLUE = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'];
/** Dark mode: near-surface step is dark, high values bright. */
export const SEQUENTIAL_BLUE_DARK = ['#1b2a4d', '#1c3f75', '#1c5cab', '#2a78d6', '#5598e7', '#86b6ef', '#cde2fb'];

/** Ordinal ramp for ordered stages (funnels). Light starts ≥ step 250 for 2:1 contrast. */
export const ORDINAL_BLUE = {
  light: ['#86b6ef', '#5598e7', '#2a78d6', '#1c5cab', '#104281', '#0d366b'],
  dark: ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95'],
};

export const STATUS = {
  good: '#0ca30c',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#d03b3b',
};

export interface ChartTokens {
  theme: ResolvedTheme;
  surface: string;
  ink: string;
  ink2: string;
  muted: string;
  grid: string;
  axis: string;
  series: string[];
  ordinal: string[];
  sequential: string[];
  deemph: string;
  target: string;
  tooltipBg: string;
  tooltipBorder: string;
}

export function chartTokens(theme: ResolvedTheme): ChartTokens {
  if (theme === 'dark') {
    return {
      theme,
      surface: '#141a2e',
      ink: '#eef0f5',
      ink2: '#b9bfcf',
      muted: '#8c93a6',
      grid: '#262e48',
      axis: '#3a4362',
      series: CATEGORICAL.dark,
      ordinal: ORDINAL_BLUE.dark,
      sequential: SEQUENTIAL_BLUE_DARK,
      deemph: '#5c6680',
      target: '#b9bfcf',
      tooltipBg: '#1b2238',
      tooltipBorder: '#2a3350',
    };
  }
  return {
    theme,
    surface: '#ffffff',
    ink: '#0f1424',
    ink2: '#4a5063',
    muted: '#707687',
    grid: '#e8e9ee',
    axis: '#c9ccd6',
    series: CATEGORICAL.light,
    ordinal: ORDINAL_BLUE.light,
    sequential: SEQUENTIAL_BLUE,
    deemph: '#b4b9c6',
    target: '#4a5063',
    tooltipBg: '#ffffff',
    tooltipBorder: '#e3e5ea',
  };
}

/** Stable colour per entity name (colour follows the entity, never its rank). */
export function colorFor(names: string[], t: ChartTokens): Record<string, string> {
  const out: Record<string, string> = {};
  [...names].sort().forEach((n, i) => {
    // Never cycle: callers fold anything past 7 entities into "Other".
    out[n] = n === 'Other' || i >= t.series.length ? t.deemph : t.series[i];
  });
  return out;
}
