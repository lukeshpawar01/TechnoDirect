import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { get, getEnvelope, getList, type Params } from '@/lib/api';
import { useFilters } from '@/lib/filters';
import type { FilterOptions } from './types';

/*
 * Refresh policy: the warehouse refreshes twice a day (10:00 and 18:00 IST).
 * No interval polling. Each filter set is cached indefinitely (staleTime: Infinity)
 * and refetched only when:
 *   - the filter set / page is new (new query key),
 *   - the user clicks "Refresh" (invalidates everything), or
 *   - the clock passes meta.next_refresh_at (see RefreshScheduler).
 */
const CACHE = {
  staleTime: Infinity,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
  placeholderData: keepPreviousData,
} as const;

/** Analytics endpoint ({data, meta}) scoped by the global filters. */
export function useAnalytics<T>(path: string, extra: Params = {}, opts: { enabled?: boolean; includeSegment?: boolean } = {}) {
  const { apiParams } = useFilters();
  const params: Params = { ...apiParams, ...extra };
  if (opts.includeSegment === false) delete params.segment;
  return useQuery({
    queryKey: ['analytics', path, params],
    queryFn: () => getEnvelope<T>(path, params),
    ...CACHE,
    enabled: opts.enabled ?? true,
  });
}

/** Paginated list endpoint scoped by the global filters + list-specific params. */
export function usePagedList<T>(path: string, extra: Params, opts: { enabled?: boolean; global?: boolean } = {}) {
  const { apiParams } = useFilters();
  const params: Params = { ...(opts.global === false ? {} : apiParams), ...extra };
  return useQuery({
    queryKey: ['list', path, params],
    queryFn: () => getList<T>(path, params),
    ...CACHE,
    enabled: opts.enabled ?? true,
  });
}

/** Admin collections — fetched whole (large page) and handled client-side. */
export function useCollection<T>(path: string, extra: Params = {}, enabled = true) {
  return useQuery({
    queryKey: ['collection', path, extra],
    queryFn: () => getList<T>(path, { page_size: 1000, ...extra }).then((p) => p.results),
    staleTime: 60_000,
    enabled,
  });
}

export function useFilterOptions() {
  return useQuery({
    queryKey: ['meta', 'filters'],
    queryFn: () => get<FilterOptions>('/meta/filters/'),
    // option lists change when masters / imports change: re-check at most every 5 min and on returning to the tab
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: true,
  });
}
