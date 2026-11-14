import { useCallback, useEffect, useState } from 'react';
import { useQueryClient, useIsFetching } from '@tanstack/react-query';
import { get } from './api';
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

/**
 * Mount once. Polls the server's data version (while the tab is visible, and when it becomes
 * visible again; every 15 s). Any save — ASM tracker, targets, mappings, sync — bumps it, so every open dashboard
 * reloads its data within ~15 s instead of waiting for the next scheduled refresh.
 */
export function useDataVersionWatcher(intervalMs = 15_000) {
  const qc = useQueryClient();
  useEffect(() => {
    let last: number | null = null;
    let stopped = false;
    const check = async () => {
      if (stopped || document.visibilityState !== 'visible') return;
      try {
        const { version } = await get<{ version: number }>('/meta/data-version/');
        if (last !== null && version !== last) {
          await Promise.all([...DATA_KEYS, ['meta'], ['asm-tracker']].map((queryKey) => qc.invalidateQueries({ queryKey })));
        }
        last = version;
      } catch {
        /* offline / signed out: try again next tick */
      }
    };
    void check();
    const timer = window.setInterval(() => void check(), intervalMs);
    const onVisible = () => void check();
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      stopped = true;
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [qc, intervalMs]);
}
