import { useCallback, useEffect, useState } from 'react';
import { useQueryClient, useIsFetching } from '@tanstack/react-query';
import { useLatestMeta } from './freshnessStore';

/** Scheduled warehouse refreshes (IST). */
export const REFRESH_SCHEDULE = ['10:00', '18:00'];

const DATA_KEYS = [['analytics'], ['list'], ['order']];

/** Invalidate every data query (active ones refetch immediately). */
export function useRefreshAll() {
  const qc = useQueryClient();
  const fetching = useIsFetching({ predicate: (q) => DATA_KEYS.some((k) => q.queryKey[0] === k[0]) });
  const refresh = useCallback(async () => {
    await Promise.all(DATA_KEYS.map((queryKey) => qc.invalidateQueries({ queryKey })));
  }, [qc]);
  return { refresh, refreshing: fetching > 0 };
}

/**
 * Mount once. When the clock passes meta.next_refresh_at (+ a 2-minute grace for the
 * backend job to finish), invalidate cached data so the next view shows the new batch.
 * Also re-checks when the tab becomes visible (background timers are throttled).
 */
export function useRefreshScheduler() {
  const meta = useLatestMeta();
  const { refresh } = useRefreshAll();
  const next = meta?.next_refresh_at ? new Date(meta.next_refresh_at).getTime() : null;
  const [firedFor, setFiredFor] = useState<number | null>(null);

  useEffect(() => {
    if (!next || Number.isNaN(next) || firedFor === next) return;
    const due = next + 2 * 60_000;
    const fire = () => {
      setFiredFor(next);
      void refresh();
    };
    const check = () => {
      if (document.visibilityState === 'visible' && Date.now() >= due) fire();
    };
    const ms = due - Date.now();
    // setTimeout caps at ~24.8 days; refreshes are ≤ 16h apart so this is safe.
    const timer = ms <= 0 ? (fire(), undefined) : setTimeout(fire, ms);
    document.addEventListener('visibilitychange', check);
    return () => {
      if (timer) clearTimeout(timer);
      document.removeEventListener('visibilitychange', check);
    };
  }, [next, firedFor, refresh]);
}
