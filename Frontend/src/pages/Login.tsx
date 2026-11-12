import { useState, type FormEvent } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/auth/AuthContext';
import { errorMessage, tokens } from '@/lib/api';
import { Logo } from '@/components/Logo';
import { Spinner } from '@/components/ui';

export default function LoginPage() {
  const { login, user } = useAuth();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const next = sp.get('next') || '/';

  if (user && tokens.access) return <Navigate to={next} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await login(email.trim(), password);
      nav(next.startsWith('/') && !next.startsWith('/login') ? next : '/', { replace: true });
    } catch (e2) {
      const msg = errorMessage(e2);
      setErr(msg.includes('401') || /credential|active account/i.test(msg) ? 'Incorrect email or password.' : msg);
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
        <form onSubmit={submit} className="card space-y-4 p-6 shadow-sm">
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
            {busy && <Spinner size={14} />} Sign in
          </button>
        </form>
        <p className="mt-4 text-center text-2xs text-muted">Accounts are created by your master admin.</p>
      </div>
    </div>
  );
}
