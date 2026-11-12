import type { ReactNode } from 'react';
import type { Meta } from '@/api/types';
import { date } from '@/lib/format';
import { useLatestMeta } from '@/lib/freshnessStore';
import { useRefreshAll } from '@/lib/refresh';
import { FreshnessBadge, Spinner } from './ui';
import { IconRefresh } from './Icons';

/**
 * Page title + period + sales basis + "Data as of … · next update …" badge and a
 * manual Refresh. Uses the page's own `meta` when available, otherwise the latest
 * meta seen by any request.
 */
export function PageHeader({ title, subtitle, meta, actions, showBasis = true }: { title: string; subtitle?: ReactNode; meta?: Meta | null; actions?: ReactNode; showBasis?: boolean }) {
  const latest = useLatestMeta();
  const { refresh, refreshing } = useRefreshAll();
  const m = meta ?? latest;
  const p = m?.period;
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          {subtitle && <span>{subtitle}</span>}
          {p && meta !== undefined && showBasis && (
            <span>
              <span className="font-medium text-ink2">{p.label}</span> · {date(p.from, 'DD MMM YY')} – {date(p.to, 'DD MMM YY')}
              {p.compare_from && p.compare_to && (
                <>
                  {' '}
                  · compared with {date(p.compare_from, 'DD MMM YY')} – {date(p.compare_to, 'DD MMM YY')}
                </>
              )}
            </span>
          )}
          {showBasis && m?.sales_basis && meta !== undefined && (
            <span title="Definition of 'sales' used on this page">
              Sales basis: <span className="text-ink2">{m.sales_basis}</span>
            </span>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {actions}
        <FreshnessBadge meta={m} />
        <button className="btn btn-sm" onClick={() => void refresh()} disabled={refreshing} title="Reload this page's data from the server">
          {refreshing ? <Spinner size={12} /> : <IconRefresh size={13} />} Refresh
        </button>
      </div>
    </div>
  );
}
