import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { get, post, setOnAuthLost, tokens } from '@/lib/api';
import type { Me } from '@/api/types';

export const ALL_PERMISSIONS = [
  'view_overview',
  'view_funnel',
  'view_distributors',
  'view_territory',
  'view_orders',
  'view_products',
  'view_inventory',
  'view_retention',
  'view_data_health',
  'export_data',
  'view_pii',
  'manage_targets',
  'manage_mappings',
  'manage_users',
  'manage_metrics',
  'trigger_sync',
] as const;
export type PermissionCode = (typeof ALL_PERMISSIONS)[number];

interface AuthCtx {
  user: Me | null;
  loading: boolean;
  error: unknown;
  retry: () => void;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  can: (perm: PermissionCode | string) => boolean;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const hasToken = !!tokens.access || !!tokens.refresh;

  const me = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: () => get<Me>('/auth/me/'),
    enabled: hasToken,
    staleTime: 5 * 60_000,
    retry: false,
    refetchOnWindowFocus: false,
  });

  const logout = useCallback(() => {
    tokens.clear();
    qc.clear();
    if (!window.location.pathname.startsWith('/login')) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.assign(`/login?next=${next}`);
    }
  }, [qc]);

  useEffect(() => setOnAuthLost(logout), [logout]);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await post<{ access: string; refresh: string }>('/auth/token/', { email, password });
      tokens.set(res.access, res.refresh);
      await qc.fetchQuery({ queryKey: ['auth', 'me'], queryFn: () => get<Me>('/auth/me/') });
    },
    [qc],
  );

  const user = hasToken ? (me.data ?? null) : null;

  const can = useCallback(
    (perm: string) => !!user && (user.is_master_admin || user.permissions.includes(perm)),
    [user],
  );

  const value = useMemo<AuthCtx>(
    () => ({ user, loading: hasToken && me.isLoading, error: me.error, retry: () => void me.refetch(), login, logout, can }),
    [user, hasToken, me, login, logout, can],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error('useAuth outside AuthProvider');
  return c;
}
