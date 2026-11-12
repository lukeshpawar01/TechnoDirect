import { useSyncExternalStore } from 'react';
import type { Meta } from '@/api/types';

// Holds the most recent analytics `meta` seen by any request, so the top bar
// can show a freshness indicator on every page (including list/admin pages).
let current: Meta | null = null;
const listeners = new Set<() => void>();

export const freshnessStore = {
  set(meta: Meta) {
    current = meta;
    listeners.forEach((l) => l());
  },
  get: () => current,
  subscribe(l: () => void) {
    listeners.add(l);
    return () => listeners.delete(l);
  },
};

export function useLatestMeta(): Meta | null {
  return useSyncExternalStore(freshnessStore.subscribe, freshnessStore.get, freshnessStore.get);
}
