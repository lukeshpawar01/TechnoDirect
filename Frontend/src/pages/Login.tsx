import { useEffect, useRef, useState, type FormEvent } from 'react';
import axios from 'axios';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth, type OtpChallenge } from '@/auth/AuthContext';
import { errorMessage, tokens } from '@/lib/api';
import { Logo } from '@/components/Logo';
import { Spinner } from '@/components/ui';

/** Seconds counting down to 0 from `from`, restarted whenever `from` or `key` changes. */
function useCountdown(from: number, key: unknown) {
  const [left, setLeft] = useState(from);
  useEffect(() => {
    setLeft(from);
    if (from <= 0) return;
    const started = Date.now();
    const id = window.setInterval(() => {
      const v = Math.max(0, from - Math.floor((Date.now() - started) / 1000));
      setLeft(v);
      if (v === 0) window.clearInterval(id);
    }, 500);
    return () => window.clearInterval(id);
  }, [from, key]);
  return left;
}

function errCode(e: unknown): string | undefined {
  if (axios.isAxiosError(e)) return (e.response?.data as { code?: string } | undefined)?.code;
  return undefined;
}

export default function LoginPage() {
  const { login, verifyOtp, resendOtp, user } = useAuth();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [challenge, setChallenge] = useState<OtpChallenge | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const codeRef = useRef<HTMLInputElement>(null);
  const next = sp.get('next') || '/';
  const target = next.startsWith('/') && !next.startsWith('/login') ? next : '/';
  const resendIn = useCountdown(challenge?.resend_in ?? 0, challenge);

  useEffect(() => {
    if (challenge) codeRef.current?.focus();
  }, [challenge]);

  // auto-submit once 6 digits are typed or pasted
  useEffect(() => {
    if (challenge && code.length === 6 && !busy) void submitCode();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  if (user && tokens.access) return <Navigate to={target} replace />;

  function restart(message?: string) {
    setChallenge(null);
    setCode('');
    setInfo(null);
    setErr(message ?? null);
  }

  async function submitPassword(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const ch = await login(email.trim(), password);
      if (ch) {
        setChallenge(ch);
        setInfo(`We sent a 6-digit code to ${ch.email}.`);
      } else {
        nav(target, { replace: true });
      }
    } catch (e2) {
      const msg = errorMessage(e2);
      setErr(msg.includes('401') || /credential|active account/i.test(msg) ? 'Incorrect email or password.' : msg);
    } finally {
      setBusy(false);
    }
  }

  async function submitCode(e?: FormEvent) {
    e?.preventDefault();
    if (!challenge || code.length !== 6) return;
    setErr(null);
    setBusy(true);
    try {
      await verifyOtp(challenge.challenge_id, code);
      nav(target, { replace: true });
    } catch (e2) {
      if (errCode(e2) === 'restart') restart(errorMessage(e2));
      else {
        setErr(errorMessage(e2));
        setCode('');
        codeRef.current?.focus();
      }
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    if (!challenge) return;
    setErr(null);
    setBusy(true);
    try {
      const ch = await resendOtp(challenge.challenge_id);
      setChallenge(ch);
      setCode('');
      setInfo(`A new code was sent to ${ch.email}.`);
    } catch (e2) {
      if (errCode(e2) === 'restart') restart(errorMessage(e2));
      else setErr(errorMessage(e2));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-page p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex justify-center">
          <Logo size="lg" />
        </div>
        {!challenge ? (
          <form onSubmit={submitPassword} className="card space-y-4 p-6 shadow-sm">
            <div>
              <h1 className="text-lg font-semibold">Sign in</h1>
              <p className="mt-0.5 text-xs text-muted">Live business dashboard for Technosport management, ops and ASMs.</p>
            </div>
            <label className="block">
              <span className="label">Email</span>
              <input className="input" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <label className="block">
              <span className="label">Password</span>
              <input className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            </label>
            {err && <div className="rounded-md border border-bad/30 bg-bad-bg px-3 py-2 text-xs text-bad">{err}</div>}
            <button type="submit" className="btn-primary w-full py-2" disabled={busy}>
              {busy && <Spinner size={14} />} Continue
            </button>
          </form>
        ) : (
          <form onSubmit={submitCode} className="card space-y-4 p-6 shadow-sm">
            <div>
              <h1 className="text-lg font-semibold">Enter login code</h1>
              <p className="mt-0.5 text-xs text-muted">{info}</p>
            </div>
            <label className="block">
              <span className="label">6-digit code</span>
              <input
                ref={codeRef}
                className="input text-center font-mono text-xl tracking-[0.5em]"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                required
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                aria-describedby="otp-help"
              />
              <span id="otp-help" className="mt-1 block text-2xs text-muted">
                The code expires in {Math.round(challenge.expires_in / 60)} minutes. Check your spam folder if it hasn't arrived.
              </span>
            </label>
            {err && <div className="rounded-md border border-bad/30 bg-bad-bg px-3 py-2 text-xs text-bad">{err}</div>}
            <button type="submit" className="btn-primary w-full py-2" disabled={busy || code.length !== 6}>
              {busy && <Spinner size={14} />} Verify and sign in
            </button>
            <div className="flex items-center justify-between text-xs">
              <button type="button" className="text-muted hover:text-ink" onClick={() => restart()} disabled={busy}>
                ← Use a different account
              </button>
              {challenge.resends_left > 0 ? (
                <button type="button" className="font-medium text-brand disabled:text-muted" onClick={resend} disabled={busy || resendIn > 0}>
                  {resendIn > 0 ? `Resend code in ${resendIn}s` : 'Resend code'}
                </button>
              ) : (
                <span className="text-muted">No resends left</span>
              )}
            </div>
          </form>
        )}
        <p className="mt-4 text-center text-2xs text-muted">Accounts are created by your master admin.</p>
      </div>
    </div>
  );
}
