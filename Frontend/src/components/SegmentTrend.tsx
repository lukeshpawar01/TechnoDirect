import { Fragment, useEffect, useMemo, useState } from 'react';
import { useAnalytics } from '@/api/hooks';
import { cartesian } from '@/charts/builders';
import { EChart, useChartTokens } from '@/charts/EChart';
import { Sparkline } from '@/components/KpiTile';
import { RfmDot } from '@/components/RfmPanel';
import { Card, Delta, ErrorState, Segmented, cx } from '@/components/ui';
import { date, num } from '@/lib/format';

type Kind = 'rfm' | 'lifecycle';
type Grain = 'day' | 'week' | 'month' | 'quarter';

interface TrendData {
  kind: Kind;
  grain: Grain;
  as_of: string;
  data_until: string;
  buckets: { start: string; end: string; label: string; partial: boolean }[];
  series: Record<string, number[]>;
  last_year: Record<string, (number | null)[]>;
  compare: {
    now_label: string;
    prev_label: string;
    last_year_label: string;
    like_for_like?: boolean;
    running?: boolean;
    rows: { key: string; now: number; prev: number | null; last_year: number | null }[];
  };
}

const RFM_ROWS: { title: string; keys: [string, string][] }[] = [
  {
    title: 'Active buyers',
    keys: [
      ['champions', 'Champions'],
      ['loyal', 'Loyal Customers'],
      ['potential_loyalists', 'Potential Loyalists'],
      ['new_customers', 'New Customers'],
      ['needs_attention', 'Needs Attention'],
      ['at_risk', 'At Risk'],
    ],
  },
  {
    title: 'Lapsed',
    keys: [
      ['no_orders_in_range', 'No Orders in Range'],
      ['churned', 'Churned'],
    ],
  },
];
const LIFE_ROWS: { title: string; keys: [string, string][] }[] = [
  {
    title: 'During each period',
    keys: [
      ['active', 'Active (ordered)'],
      ['new', 'New'],
      ['retained', 'Retained'],
      ['reactivated', 'Reactivated'],
      ['lost', 'Lost'],
    ],
  },
  {
    title: 'As of each period end',
    keys: [
      ['one_time', 'One-time'],
      ['repeat', 'Repeat'],
      ['inactive_30', 'Inactive 30–59 days'],
      ['inactive_60', 'Inactive 60–89 days'],
      ['inactive_90', 'Inactive 90+ days'],
      ['never_ordered', 'Never ordered'],
    ],
  },
];
/** more of these is bad news: deltas are coloured the other way round */
const LOWER_IS_BETTER = new Set(['lost', 'inactive_30', 'inactive_60', 'inactive_90', 'never_ordered', 'churned', 'no_orders_in_range', 'at_risk', 'needs_attention']);
const LIFECYCLE_KEYS = new Set(LIFE_ROWS.flatMap((g) => g.keys.map((k) => k[0])));
const RFM_KEYS = new Set(RFM_ROWS.flatMap((g) => g.keys.map((k) => k[0])));
const GRAIN_LABEL: Record<Grain, string> = { day: 'Daily', week: 'Weekly', month: 'Monthly', quarter: 'Quarterly' };

const deltaPct = (now: number, base: number | null | undefined) => (base ? ((now - base) / base) * 100 : null);

/**
 * Retailer segments over time (Retailers page): one segment in focus as bars with last year as a line, and every
 * segment in a comparison table with its own sparkline. The grain follows the period selector; it can be changed.
 */
export function SegmentTrend({ selected }: { selected: string }) {
  const t = useChartTokens();
  const [kind, setKind] = useState<Kind>(LIFECYCLE_KEYS.has(selected) || selected === 'inactive' ? 'lifecycle' : 'rfm');
  const [grain, setGrain] = useState<Grain | ''>('');
  const [focus, setFocus] = useState<string>('');
  // follow the segment picked on the page (tabs / RFM panel)
  useEffect(() => {
    if (RFM_KEYS.has(selected)) {
      setKind('rfm');
      setFocus(selected);
    } else if (LIFECYCLE_KEYS.has(selected)) {
      setKind('lifecycle');
      setFocus(selected);
    }
  }, [selected]);

  const q = useAnalytics<TrendData>('/retailers/segment-trend/', { kind, grain: grain || undefined }, { includeSegment: false });
  // while a new view / grain loads, never show the previous one's rows under the new headings
  const raw = q.data?.data;
  const d = raw && raw.kind === kind && (!grain || raw.grain === grain) ? raw : undefined;
  const groups = kind === 'rfm' ? RFM_ROWS : LIFE_ROWS;
  const labels = useMemo(() => Object.fromEntries(groups.flatMap((g) => g.keys)), [groups]);
  const key = focus && d?.series[focus] ? focus : kind === 'rfm' ? 'champions' : 'active';
  const rowsByKey = useMemo(() => new Map((d?.compare.rows ?? []).map((r) => [r.key, r])), [d]);

  const opt = useMemo(() => {
    if (!d?.series[key]) return null;
    const ly = d.last_year[key] ?? [];
    return cartesian(t, {
      x: d.buckets.map((b) => (b.partial ? `${b.label} · to date` : b.label)),
      legend: true,
      showBarLabels: d.buckets.length <= 14,
      series: [
        {
          name: labels[key] ?? key,
          data: d.series[key],
          // the running period is lighter: it is not finished
          colors: d.buckets.map((b) => (b.partial ? t.deemph : t.series[0])),
        },
        ...(ly.some((v) => v !== null) ? [{ name: 'Same period last year', type: 'line' as const, data: ly, ghost: true, dashed: true }] : []),
      ],
    });
  }, [d, key, t, labels]);

  const effGrain = (d?.grain ?? grain) as Grain;
  const cmp = d?.compare;

  return (
    <Card
      className="mb-4"
      title="Segment trends"
      subtitle={
        d
          ? `${GRAIN_LABEL[d.grain]} · ${d.buckets.length} periods to ${date(d.as_of)} · click a row to chart it`
          : 'How each retailer group changes over time'
      }
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Segmented
            value={kind}
            onChange={(v) => {
              setKind(v);
              setFocus('');
            }}
            size="xs"
            options={[
              { value: 'rfm', label: 'RFM segments' },
              { value: 'lifecycle', label: 'Lifecycle groups' },
            ]}
          />
          <Segmented
            value={(grain || effGrain || 'month') as Grain}
            onChange={(v) => setGrain(v)}
            size="xs"
            options={[
              { value: 'day', label: 'Day' },
              { value: 'week', label: 'Week' },
              { value: 'month', label: 'Month' },
              { value: 'quarter', label: 'Quarter' },
            ]}
          />
        </div>
      }
    >
      {q.error && !d ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : !d ? (
        <div className="m-4 h-72 animate-pulse rounded-md bg-sunken" />
      ) : (
        <div className={cx('grid grid-cols-1 gap-6 px-4 pb-4 pt-1 transition-opacity xl:grid-cols-5', q.isFetching && 'opacity-60')}>
          <div className="xl:col-span-2">
            <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-ink">
              {kind === 'rfm' && <RfmDot segment={key} />}
              {labels[key] ?? key}
              <span className="text-xs font-normal text-muted">retailers per {effGrain}</span>
            </div>
            <EChart option={opt ?? {}} height={260} ariaLabel={`${labels[key]} over time`} />
            <p className="mt-1 text-2xs text-muted">
              {kind === 'rfm'
                ? 'Each bar = retailers in the segment at the end of that period (same rules as the RFM panel, recalculated per period).'
                : 'New, retained, reactivated and lost are counted within each period; one-time, repeat, inactive and never-ordered are states at its end.'}
              {cmp?.running ? ' The latest period is still running (lighter bar).' : ''}
            </p>
          </div>

          <div className="overflow-x-auto xl:col-span-3">
            <table className="w-full min-w-[560px] text-sm tabular">
              <thead>
                <tr className="border-b border-line text-xs text-muted">
                  <th className="py-2 pr-2 text-left font-medium">{kind === 'rfm' ? 'Segment' : 'Group'}</th>
                  <th className="px-2 py-2 text-left font-medium">Trend</th>
                  <th className="px-2 py-2 text-right font-medium" title={cmp?.running ? 'Running period' : undefined}>
                    {cmp?.now_label}
                    {cmp?.running ? ' (to date)' : ''}
                  </th>
                  <th className="px-2 py-2 text-right font-medium" title={cmp?.like_for_like ? 'Same number of days into the period' : undefined}>
                    vs {cmp?.prev_label}
                    {cmp?.like_for_like ? ' *' : ''}
                  </th>
                  <th className="py-2 pl-2 text-right font-medium">vs {cmp?.last_year_label}</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((g) => (
                  <Fragment key={g.title}>
                    <tr>
                      <td colSpan={5} className="pb-1 pt-3 text-xs font-medium text-muted">
                        {g.title}
                      </td>
                    </tr>
                    {g.keys.map(([k, lbl]) => {
                      const r = rowsByKey.get(k);
                      if (!r || (k === 'no_orders_in_range' && !r.now && !r.prev)) return null;
                      const on = k === key;
                      const better = !LOWER_IS_BETTER.has(k);
                      return (
                        <tr
                          key={k}
                          onClick={() => setFocus(k)}
                          className={cx('cursor-pointer border-t border-line/60', on ? 'bg-brand/10' : 'hover:bg-sunken/70')}
                          aria-selected={on}
                        >
                          <td className="py-1.5 pr-2">
                            <span className="flex items-center gap-2 whitespace-nowrap font-medium text-ink">
                              {kind === 'rfm' && <RfmDot segment={k} />}
                              {lbl}
                            </span>
                          </td>
                          <td className="w-28 px-2 py-1">
                            <Sparkline data={d.series[k]} height={22} partialLast={cmp?.running} />
                          </td>
                          <td className="px-2 py-1.5 text-right font-semibold text-ink">{num(r.now)}</td>
                          <td className="px-2 py-1.5 text-right">
                            <span className="inline-flex items-center justify-end gap-1.5">
                              <span className="text-xs text-muted">{r.prev === null ? '–' : num(r.prev)}</span>
                              {deltaPct(r.now, r.prev) === null ? <span className="w-16 text-right text-xs text-muted">–</span> : <Delta value={deltaPct(r.now, r.prev)} higherIsBetter={better} suffix="" className="w-16 justify-end" />}
                            </span>
                          </td>
                          <td className="py-1.5 pl-2 text-right">
                            <span className="inline-flex items-center justify-end gap-1.5">
                              <span className="text-xs text-muted">{r.last_year === null ? '–' : num(r.last_year)}</span>
                              {deltaPct(r.now, r.last_year) === null ? <span className="w-16 text-right text-xs text-muted">–</span> : <Delta value={deltaPct(r.now, r.last_year)} higherIsBetter={better} suffix="" className="w-16 justify-end" />}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </Fragment>
                ))}
              </tbody>
            </table>
            {cmp?.like_for_like && (
              <p className="mt-2 text-2xs text-muted">* {cmp.now_label} is still running, so it is compared with the same number of days of {cmp.prev_label}.</p>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}
