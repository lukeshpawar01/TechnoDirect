import { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/auth/AuthContext';
import { useTheme, type ThemePref } from '@/lib/theme';
import { post } from '@/lib/api';
import { fyLabel, linkWithFilters } from '@/lib/filters';
import { useRefreshScheduler } from '@/lib/refresh';
import { ADMIN_NAV, ALL_TOP_FILTERS, MAIN_NAV, allowed, navItemFor, type NavItem } from '@/nav';
import { FilterBar } from './FilterBar';
import { Logo } from './Logo';
import { Field, InlineError, Modal, cx } from './ui';
import { IconChevron, IconKey, IconLogout, IconMenu, IconMonitor, IconMoon, IconSun } from './Icons';

function readCollapsed() {
  try {
    return localStorage.getItem('td.sidebar') === 'collapsed';
  } catch {
    return false;
  }
}

function NavGroup({ items, collapsed, onNavigate, keepFilters }: { items: NavItem[]; collapsed: boolean; onNavigate: () => void; keepFilters?: boolean }) {
  const [sp] = useSearchParams();
  return (
    <ul className="space-y-0.5">
      {items.map((i) => (
        <li key={i.to}>
          <NavLink
            to={keepFilters ? linkWithFilters(i.to, sp) : i.to}
            onClick={onNavigate}
            title={collapsed ? i.label : undefined}
            className={({ isActive }) =>
              cx(
                'group flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium',
                isActive ? 'bg-brand text-white' : 'text-ink2 hover:bg-sunken hover:text-ink',
                collapsed && 'justify-center px-0',
              )
            }
          >
            <span className="shrink-0">{i.icon}</span>
            {!collapsed && <span className="truncate">{i.label}</span>}
          </NavLink>
        </li>
      ))}
    </ul>
  );
}

function ThemeToggle() {
  const { pref, setPref } = useTheme();
  const opts: { v: ThemePref; icon: JSX.Element; label: string }[] = [
    { v: 'light', icon: <IconSun size={14} />, label: 'Light' },
    { v: 'dark', icon: <IconMoon size={14} />, label: 'Dark' },
    { v: 'system', icon: <IconMonitor size={14} />, label: 'System' },
  ];
  return (
    <div className="inline-flex rounded-md border border-line bg-sunken p-0.5" role="radiogroup" aria-label="Theme">
      {opts.map((o) => (
        <button
          key={o.v}
          role="radio"
          aria-checked={pref === o.v}
          title={`${o.label} theme`}
          onClick={() => setPref(o.v)}
          className={cx('rounded px-1.5 py-1', pref === o.v ? 'bg-surface text-ink shadow-sm' : 'text-muted hover:text-ink')}
        >
          {o.icon}
        </button>
      ))}
    </div>
  );
}

function ChangePassword({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [oldP, setOld] = useState('');
  const [newP, setNew] = useState('');
  const [err, setErr] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  async function submit() {
    setErr(null);
    if (newP.length < 8) return setErr(new Error('New password must be at least 8 characters.'));
    setBusy(true);
    try {
      await post('/auth/change-password/', { old_password: oldP, new_password: newP });
      setDone(true);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Change password"
      footer={
        done ? (
          <button className="btn-primary" onClick={onClose}>
            Close
          </button>
        ) : (
          <>
            <button className="btn" onClick={onClose}>
              Cancel
            </button>
            <button className="btn-primary" onClick={submit} disabled={busy || !oldP || !newP}>
              Update password
            </button>
          </>
        )
      }
    >
      {done ? (
        <p className="text-sm text-good">Password updated.</p>
      ) : (
        <div className="space-y-3">
          <Field label="Current password">
            <input type="password" className="input" value={oldP} onChange={(e) => setOld(e.target.value)} autoComplete="current-password" />
          </Field>
          <Field label="New password" hint="At least 8 characters.">
            <input type="password" className="input" value={newP} onChange={(e) => setNew(e.target.value)} autoComplete="new-password" />
          </Field>
          <InlineError error={err} />
        </div>
      )}
    </Modal>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [pw, setPw] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [open]);
  if (!user) return null;
  const initials = (user.full_name || user.email)
    .split(/[\s@.]+/)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase())
    .join('');
  return (
    <div className="relative" ref={ref}>
      <button className="flex items-center gap-2 rounded-md px-1.5 py-1 hover:bg-sunken" onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}>
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent text-xs font-semibold text-white">{initials}</span>
        <span className="hidden text-left leading-tight lg:block">
          <span className="block max-w-[140px] truncate text-xs font-medium text-ink">{user.full_name || user.email}</span>
          <span className="block text-2xs text-muted">{user.is_master_admin ? 'Master admin' : (user.role?.name ?? 'No role')}</span>
        </span>
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-1 w-60 rounded-md border border-line bg-surface py-1 shadow-lg" role="menu">
          <div className="border-b border-line px-3 py-2">
            <div className="truncate text-xs font-medium">{user.email}</div>
            <div className="text-2xs text-muted">
              Data scope: {user.is_master_admin || user.scope.all ? 'All data' : 'Restricted'}
            </div>
          </div>
          <button role="menuitem" className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-sunken" onClick={() => { setPw(true); setOpen(false); }}>
            <IconKey size={14} /> Change password
          </button>
          <button role="menuitem" className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-bad hover:bg-sunken" onClick={logout}>
            <IconLogout size={14} /> Sign out
          </button>
        </div>
      )}
      <ChangePassword open={pw} onClose={() => setPw(false)} />
    </div>
  );
}

export function Layout() {
  const { can } = useAuth();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [mobileOpen, setMobileOpen] = useState(false);
  const loc = useLocation();
  useRefreshScheduler();
  const isAdmin = loc.pathname.startsWith('/admin');
  const hideFilters = isAdmin || loc.pathname.startsWith('/data-health');

  useEffect(() => {
    try {
      localStorage.setItem('td.sidebar', collapsed ? 'collapsed' : 'open');
    } catch {
      /* ignore */
    }
  }, [collapsed]);
  useEffect(() => setMobileOpen(false), [loc.pathname]);

  const main = MAIN_NAV.filter((i) => allowed(i, can));
  const admin = ADMIN_NAV.filter((i) => allowed(i, can));

  const sidebar = (isCollapsed: boolean) => (
    <div className="flex h-full flex-col">
      <div className={cx('flex items-center border-b border-line', isCollapsed ? 'justify-center px-2 py-3' : 'justify-center px-4 py-4')}>
        <Logo compact={isCollapsed} />
      </div>
      <nav className="flex-1 overflow-y-auto px-2 py-3" aria-label="Main">
        <NavGroup items={main} collapsed={isCollapsed} onNavigate={() => setMobileOpen(false)} keepFilters />
        {admin.length > 0 && (
          <>
            {!isCollapsed ? <div className="mb-1 mt-5 px-2.5 text-2xs font-semibold uppercase tracking-wider text-muted">Admin</div> : <div className="my-3 border-t border-line" />}
            <NavGroup items={admin} collapsed={isCollapsed} onNavigate={() => setMobileOpen(false)} />
          </>
        )}
      </nav>
      <div className={cx('border-t border-line py-2 text-2xs text-muted', isCollapsed ? 'text-center' : 'px-4')}>
        {isCollapsed ? fyLabel().replace('FY ', '') : `${fyLabel()} · Apr–Mar · IST`}
      </div>
    </div>
  );

  return (
    <div className="flex h-full">
      {/* desktop sidebar */}
      <aside className={cx('hidden shrink-0 border-r border-line bg-surface transition-[width] duration-200 md:block', collapsed ? 'w-16' : 'w-60')}>{sidebar(collapsed)}</aside>
      {/* mobile sidebar */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 md:hidden" onClick={() => setMobileOpen(false)}>
          <aside className="h-full w-64 bg-surface" onClick={(e) => e.stopPropagation()}>
            {sidebar(false)}
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur">
          <div className="flex items-center gap-2 px-3 py-2 md:px-4">
            <button className="rounded p-1.5 text-ink2 hover:bg-sunken md:hidden" onClick={() => setMobileOpen(true)} aria-label="Open menu">
              <IconMenu />
            </button>
            <button
              className="hidden rounded p-1.5 text-ink2 hover:bg-sunken md:block"
              onClick={() => setCollapsed((c) => !c)}
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              <IconChevron className={cx('transition-transform', !collapsed && 'rotate-180')} />
            </button>
            <div className="min-w-0 flex-1">{!hideFilters && <FilterBar visible={navItemFor(loc.pathname)?.filters ?? ALL_TOP_FILTERS} />}</div>
            <ThemeToggle />
            <UserMenu />
          </div>
        </header>
        <main className="min-w-0 flex-1 overflow-y-auto px-3 py-4 md:px-6 md:py-5">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
