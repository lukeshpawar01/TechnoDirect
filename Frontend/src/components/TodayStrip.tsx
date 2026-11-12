import { useAnalytics } from '@/api/hooks';
import type { Overview } from '@/api/types';
import { inr, num } from '@/lib/format';
import { Delta, Spinner } from './ui';

/**
 * "Today so far" — the normal overview endpoint with preset=today (scope filters kept).
 * Values are as of the last scheduled refresh, not real-time.
 */
export function TodayStrip() {
  const q = useAnalytics<Overview>('/overview/', { preset: 'today', date_from: undefined, date_to: undefined });
  const k = q.data?.data.kpis;
  const asOf = q.data?.meta?.last_refresh_at ?? q.data?.meta?.as_of;
  const items = k
    ? [
        { label: 'Sales', v: inr(k.sales?.value), d: k.sales?.delta_pct },
        { label: 'Orders', v: num(k.orders?.value), d: k.orders?.delta_pct },
        { label: 'AOV', v: inr(k.aov?.value), d: k.aov?.delta_pct },
        { label: 'Active retailers', v: num(k.active_retailers?.value), d: k.active_retailers?.delta_pct },
        { label: 'New retailers', v: num(k.new_retailers?.value), d: k.new_retailers?.delta_pct },
      ]
    : [];
  return (
    <div className="card mb-4 flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5">
      <div className="text-xs font-semibold uppercase tracking-wide text-ink">Today so far</div>
      {q.isLoading ? (
        <Spinner size={12} />
      ) : q.error && !q.data ? (
        <span className="text-xs text-bad">Unavailable</span>
      ) : (
        items.map((i) => (
          <div key={i.label} className="flex items-baseline gap-1.5 text-xs text-ink2">
            {i.label} <span className="text-base font-semibold text-ink">{i.v}</span>
            <Delta value={i.d} suffix="" />
          </div>
        ))
      )}
      {asOf && (
        <span className="ml-auto text-2xs text-muted">
          vs yesterday · as of last refresh {new Date(asOf).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' })}
        </span>
      )}
    </div>
  );
}
