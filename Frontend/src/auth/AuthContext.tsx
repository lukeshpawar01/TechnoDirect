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
  'use_assistant',
  'export_data',
  'view_pii',
  'manage_targets',
  'manage_mappings',
  'manage_users',
  'manage_metrics',
  'trigger_sync',
] as const;
export type PermissionCode = (typeof ALL_PERMISSIONS)[number];

/** Returned by step 1 (password) when an emailed one-time code is required. */
export interface OtpChallenge {
  otp_required: true;
  challenge_id: string;
  email: string;
  expires_in: number;
  resend_in: number;
  resends_left: number;
}
type TokenPair = { access: string; refresh: string };

interface AuthCtx {
  user: Me | null;
  loading: boolean;
  error: unknown;
  retry: () => void;
  /** Step 1. Resolves with a challenge when an OTP is required, or null when signed in directly. */
  login: (email: string, password: string) => Promise<OtpChallenge | null>;
  /** Step 2. Signs in when the emailed code is correct. */
  verifyOtp: (challengeId: string, code: string) => Promise<void>;
  resendOtp: (challengeId: string) => Promise<OtpChallenge>;
  logout: () => void;
  can: (perm: PermissionCode | string) => boolean;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  // React state (not a direct localStorage read) so that signing in re-renders the app.
  const [hasToken, setHasToken] = useState(() => !!tokens.access || !!tokens.refresh);

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
    if (!window.location.pathname.startsWith('/login')) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.assign(`/login?next=${next}`);
    }
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
      const res = await post<TokenPair | OtpChallenge>('/auth/token/', { email, password });
      if ('otp_required' in res && res.otp_required) return res;
      await finish(res as TokenPair);
      return null;
    },
    [finish],
  );

  const verifyOtp = useCallback(
    async (challengeId: string, code: string) => {
      await finish(await post<TokenPair>('/auth/otp/verify/', { challenge_id: challengeId, code }));
    },
    [finish],
  );

  const resendOtp = useCallback((challengeId: string) => post<OtpChallenge>('/auth/otp/resend/', { challenge_id: challengeId }), []);

  const user = hasToken ? (me.data ?? null) : null;

  const can = useCallback(
    (perm: string) => !!user && (user.is_master_admin || user.permissions.includes(perm)),
    [user],
  );

  const value = useMemo<AuthCtx>(
    () => ({ user, loading: hasToken && me.isLoading, error: me.error, retry: () => void me.refetch(), login, verifyOtp, resendOtp, logout, can }),
    [user, hasToken, me, login, verifyOtp, resendOtp, logout, can],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error('useAuth outside AuthProvider');
  return c;
}
