import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
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
  'view_loyalty',
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

type TokenPair = { access: string; refresh: string };

interface AuthCtx {
  user: Me | null;
  loading: boolean;
  error: unknown;
  retry: () => void;
  /** Email + password sign-in (internal accounts made by an admin; no emailed code). */
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  can: (perm: PermissionCode | string) => boolean;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  // React state (not a direct localStorage read) so that signing in re-renders the app.
  // Open access (no login anywhere): the server treats every visitor as the built-in "Everyone" account, so the
  // profile is always fetched. Old sign-in tokens are dropped so they are never sent.
  const [hasToken, setHasToken] = useState(() => {
    tokens.clear();
    return true;
  });

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
    setHasToken(false);
    qc.clear();
    setHasToken(true);
    void qc.invalidateQueries({ queryKey: ['auth', 'me'] });
  }, [qc]);

  useEffect(() => setOnAuthLost(logout), [logout]);

  const finish = useCallback(
    async (res: TokenPair) => {
      tokens.set(res.access, res.refresh);
      const profile = await get<Me>('/auth/me/');
      qc.setQueryData(['auth', 'me'], profile);
      setHasToken(true);
    },
    [qc],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      await finish(await post<TokenPair>('/auth/token/', { email, password }));
    },
    [finish],
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
