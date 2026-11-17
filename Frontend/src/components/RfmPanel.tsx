import { Fragment } from 'react';
import { useAnalytics } from '@/api/hooks';
import type { RfmData, RfmSegment } from '@/api/types';
import { Card, ErrorState, cx } from '@/components/ui';
import { date, inr, num, pct } from '@/lib/format';

/**
 * Health group of each RFM segment. One dot colour per group (not per segment) so the eye reads
 * "thriving / slipping / at risk / lapsed" first, then the name.
 */
export const RFM_GROUP: Record<string, 'thriving' | 'new' | 'slipping' | 'risk' | 'lapsed'> = {
  champions: 'thriving',
  loyal: 'thriving',
  potential_loyalists: 'thriving',
  new_customers: 'new',
  promising: 'new',
  needs_attention: 'slipping',
  about_to_sleep: 'slipping',
  cant_lose: 'risk',
  at_risk: 'risk',
  hibernating: 'risk',
  no_orders_in_range: 'lapsed',
  churned: 'lapsed',
  prospect: 'lapsed',
};
const DOT = { thriving: 'bg-good', new: 'bg-brand', slipping: 'bg-warn', risk: 'bg-bad', lapsed: 'bg-ink2/40' } as const;

export function RfmDot({ segment }: { segment: string | null | undefined }) {
  const g = RFM_GROUP[segment ?? ''] ?? 'lapsed';
  return <span aria-hidden className={cx('inline-block h-2 w-2 shrink-0 rounded-full', DOT[g])} />;
}

const MEASURE: Record<string, { label: string; fmt: (v: number) => string; hint: string }> = {
  recency_ratio: { label: 'Recency ratio', fmt: (v) => v.toFixed(2), hint: 'days silent ÷ own usual gap · lower is better' },
  orders_per_month: { label: 'Orders / month', fmt: (v) => v.toFixed(2), hint: 'orders in window ÷ tenure months' },
  value_per_month: { label: 'Value / month', fmt: (v) => inr(v, { compact: true }), hint: 'sales in window ÷ tenure months' },
};

const GROUPS: { title: string; keys: string[] }[] = [
  { title: 'Active buyers · scored', keys: ['champions', 'loyal', 'potential_loyalists', 'new_customers', 'promising', 'needs_attention', 'about_to_sleep', 'cant_lose', 'at_risk', 'hibernating'] },
  { title: 'Lapsed', keys: ['no_orders_in_range', 'churned'] },
  { title: 'Never ordered', keys: ['prospect'] },
];

/**
 * RFM segments of the retailers in scope (Retailers page). Click a segment row or a grid cell to list those retailers.
 * Cut-offs are percentiles of all active buyers, recalculated on every refresh.
 */
export function RfmPanel({ selected, onSelect }: { selected: string; onSelect: (segment: string) => void }) {
  const q = useAnalytics<RfmData>('/retailers/rfm/', {}, { includeSegment: false });
  const d = q.data?.data;
  if (q.error) return <Card className="mb-4"><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card>;

  const by = new Map((d?.segments ?? []).map((s) => [s.segment, s]));
  const maxCell = Math.max(1, ...(d?.grid ?? []).map((c) => c.retailers));
  const champ = d?.validation?.segments.find((s) => s.segment === 'champions');
  const churn = d?.validation?.segments.find((s) => s.segment === 'churned');

  return (
    <Card
      className="mb-4"
      title="RFM segments"
      subtitle={
        d
          ? `As of ${date(d.as_of)} · ${num(d.summary.buyers)} retailers have ordered, ${num(d.summary.active)} active and scored · frequency and value over the last ${d.window_months} months`
          : 'Recency against each retailer’s own reorder rhythm, frequency and value per month of tenure'
      }
    >
      {!d ? (
        <div className="m-4 h-64 animate-pulse rounded-md bg-sunken" />
      ) : (
        <div className="grid grid-cols-1 gap-6 px-4 pb-4 pt-1 xl:grid-cols-5">
          {/* segment table */}
          <div className="overflow-x-auto xl:col-span-3">
            <table className="w-full min-w-[560px] text-sm tabular">
              <thead>
                <tr className="border-b border-line text-xs text-muted">
                  <th className="py-2 pr-2 text-left font-medium">Segment</th>
                  <th className="px-2 py-2 text-right font-medium">Retailers</th>
                  <th className="px-2 py-2 text-right font-medium">Of buyers</th>
                  <th className="px-2 py-2 text-left font-medium">Share of sales</th>
                  <th className="py-2 pl-2 text-left font-medium">What to do</th>
                </tr>
              </thead>
              <tbody>
                {GROUPS.map((g) => {
                  const rows = g.keys.map((k) => by.get(k)).filter((s): s is RfmSegment => !!s && (s.retailers > 0 || s.segment !== 'no_orders_in_range'));
                  if (!rows.length) return null;
                  return (
                    <Fragment key={g.title}>
                      <tr>
                        <td colSpan={5} className="pb-1 pt-3 text-xs font-medium text-muted">
                          {g.title}
                        </td>
                      </tr>
                      {rows.map((s) => {
                        const on = selected === s.segment;
                        return (
                          <tr
                            key={s.segment}
                            onClick={() => onSelect(s.segment)}
                            className={cx('cursor-pointer border-t border-line/60', on ? 'bg-brand/10' : 'hover:bg-sunken/70')}
                            title={s.meaning}
                            aria-selected={on}
                          >
                            <td className="py-1.5 pr-2">
                              <span className="flex items-center gap-2 whitespace-nowrap">
                                <RfmDot segment={s.segment} />
                                <span className="font-medium text-ink">{s.label}</span>
                              </span>
                            </td>
                            <td className="px-2 py-1.5 text-right">{num(s.retailers)}</td>
                            <td className="px-2 py-1.5 text-right text-ink2">{s.pct_buyers === null ? '–' : pct(s.pct_buyers, 1)}</td>
                            <td className="px-2 py-1.5">
                              {s.pct_value === null ? (
                                <span className="text-muted">–</span>
                              ) : (
                                <span className="flex items-center gap-2">
                                  <span className="h-1.5 w-20 overflow-hidden rounded-full bg-sunken" aria-hidden>
                                    <span className="block h-full rounded-full bg-ink2/50" style={{ width: `${Math.min(100, s.pct_value)}%` }} />
                                  </span>
                                  <span className="w-12 text-right">{pct(s.pct_value, 1)}</span>
                                </span>
                              )}
                            </td>
                            <td className="max-w-[16rem] truncate py-1.5 pl-2 text-xs text-ink2" title={s.action}>
                              {s.action}
                            </td>
                          </tr>
                        );
                      })}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* R x FM grid */}
          <div className="xl:col-span-2">
            <div className="mb-2 text-xs text-muted">Recency score × frequency-and-value score (active buyers). Click a cell to list them.</div>
            <div className="grid grid-cols-[auto_repeat(5,minmax(0,1fr))] gap-1 text-xs">
              <div />
              {[1, 2, 3, 4, 5].map((fm) => (
                <div key={fm} className="pb-1 text-center text-muted">
                  FM {fm}
                </div>
              ))}
              {[5, 4, 3, 2, 1].map((r) => (
                <Fragment key={r}>
                  <div className="flex items-center pr-2 text-muted">R {r}</div>
                  {[1, 2, 3, 4, 5].map((fm) => {
                    const c = d.grid.find((x) => x.r === r && x.fm === fm);
                    if (!c) return <div key={fm} />;
                    const label = by.get(c.segment)?.label ?? c.segment;
                    const on = selected === c.segment;
                    const a = c.retailers / maxCell;
                    return (
                      <button
                        key={fm}
                        type="button"
                        onClick={() => onSelect(c.segment)}
                        title={`R${r} · FM${fm} → ${label}: ${num(c.retailers)} retailers`}
                        className={cx('relative flex h-14 flex-col items-start justify-between rounded-md border px-1.5 py-1 text-left', on ? 'border-brand ring-1 ring-brand' : 'border-line hover:border-ink2/40')}
                        style={{ background: `rgb(var(--brand) / ${(0.05 + a * 0.35).toFixed(3)})` }}
                      >
                        <span className="flex w-full items-start gap-1 text-[10px] leading-tight text-ink2">
                          <span className="mt-[3px]">
                            <RfmDot segment={c.segment} />
                          </span>
                          <span className="line-clamp-2">{label}</span>
                        </span>
                        <span className="text-sm font-semibold text-ink">{num(c.retailers)}</span>
                      </button>
                    );
                  })}
                </Fragment>
              ))}
            </div>
            <div className="mt-1 flex justify-between text-[11px] text-muted">
              <span>R 5 = ordering on or ahead of their usual rhythm</span>
              <span>FM 5 = highest frequency & value</span>
            </div>

            {champ && churn && d.validation && (
              <p className="mt-3 rounded-md border border-line bg-sunken/60 px-3 py-2 text-xs text-ink2">
                <span className="font-semibold text-ink">Back-test:</span> of the retailers segmented on {date(d.validation.as_of)}, Champions reordered within{' '}
                {d.validation.months} months <span className="font-semibold text-ink">{pct(champ.returned_pct, 0)}</span> of the time; Churned only{' '}
                <span className="font-semibold text-ink">{pct(churn.returned_pct, 0)}</span>.
              </p>
            )}

            <details className="mt-3 text-xs text-ink2">
              <summary className="cursor-pointer text-ink hover:underline">How segments are calculated</summary>
              <ul className="mt-2 list-disc space-y-1 pl-4">
                <li>Only paid, non-cancelled orders count. Retailers who never ordered are Prospects and are not scored.</li>
                <li>
                  Churned: silent for more than {d.params.churn_ratio}× their own usual gap <em>and</em> more than {num(d.population?.p90_gap ?? 0)} days (90th-percentile gap of all
                  retailers; typical gap {num(d.population?.median_gap ?? 0)} days).
                </li>
                <li>New Customers: first order in the last {d.params.new_days} days, decided before scoring.</li>
                <li>
                  Scores 1–5 compare each active buyer with the 20/40/60/80th percentiles of all active buyers (ties stay at the lower score), so a Champion means the same
                  for every distributor and ASM.
                </li>
              </ul>
              <table className="mt-2 w-full tabular">
                <thead>
                  <tr className="text-muted">
                    <th className="py-1 text-left font-medium">Cut-offs</th>
                    <th className="py-1 text-right font-medium">P20</th>
                    <th className="py-1 text-right font-medium">P40</th>
                    <th className="py-1 text-right font-medium">P60</th>
                    <th className="py-1 text-right font-medium">P80</th>
                  </tr>
                </thead>
                <tbody>
                  {d.cutoffs.map((c) => {
                    const m = MEASURE[c.measure];
                    return (
                      <tr key={c.measure} className="border-t border-line/60" title={m.hint}>
                        <td className="py-1">{m.label}</td>
                        <td className="py-1 text-right">{m.fmt(c.p20)}</td>
                        <td className="py-1 text-right">{m.fmt(c.p40)}</td>
                        <td className="py-1 text-right">{m.fmt(c.p60)}</td>
                        <td className="py-1 text-right">{m.fmt(c.p80)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </details>
          </div>
        </div>
      )}
    </Card>
  );
}
