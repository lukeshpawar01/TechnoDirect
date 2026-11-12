import { useEffect, useState, type ReactNode } from 'react';
import dayjs from 'dayjs';
import { errorMessage } from '@/lib/api';
import { relTime, signedPct } from '@/lib/format';
import type { Freshness, FreshnessStatus, Meta } from '@/api/types';
import { IconAlert, IconArrowDown, IconArrowUp, IconCheck, IconInfo, IconX } from './Icons';

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(' ');
}

// ---------------------------------------------------------------- containers
export function Card({ title, subtitle, actions, children, className, bodyClass }: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClass?: string;
}) {
  return (
    <section className={cx('card flex min-w-0 flex-col', className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 px-4 pt-3.5">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
        </header>
      )}
      <div className={cx('min-w-0 flex-1 p-4', bodyClass)}>{children}</div>
    </section>
  );
}

// ---------------------------------------------------------------- states
export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className="inline-block animate-spin rounded-full border-2 border-line border-t-brand"
      style={{ width: size, height: size }}
    />
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx('animate-pulse rounded-md bg-sunken', className)} />;
}

export function LoadingBlock({ height = 240, label = 'Loading…' }: { height?: number; label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 text-sm text-muted" style={{ minHeight: height }}>
      <Spinner /> {label}
    </div>
  );
}

export function ErrorState({ error, onRetry, compact }: { error: unknown; onRetry?: () => void; compact?: boolean }) {
  return (
    <div className={cx('flex flex-col items-center justify-center gap-2 text-center', compact ? 'py-4' : 'py-10')}>
      <div className="flex items-center gap-2 text-sm font-medium text-bad">
        <IconAlert /> Couldn't load this
      </div>
      <p className="max-w-md text-xs text-muted">{errorMessage(error)}</p>
      {onRetry && (
        <button className="btn btn-sm mt-1" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title = 'No data for this selection', hint, height = 160 }: { title?: string; hint?: string; height?: number }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 text-center" style={{ minHeight: height }}>
      <div className="text-sm font-medium text-ink2">{title}</div>
      <div className="text-xs text-muted">{hint ?? 'Try widening the date range or clearing filters.'}</div>
    </div>
  );
}

/** Wraps a react-query result: loading → error → empty → content. Holds previous render on refetch. */
export function QueryState<T>({
  q,
  isEmpty,
  height = 240,
  children,
  emptyTitle,
}: {
  q: { data: T | undefined; isLoading: boolean; error: unknown; isFetching?: boolean; isPlaceholderData?: boolean; refetch: () => unknown };
  isEmpty?: (d: T) => boolean;
  height?: number;
  emptyTitle?: string;
  children: (d: T) => ReactNode;
}) {
  if (q.isLoading) return <LoadingBlock height={height} />;
  if (q.error && !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (q.data === undefined) return <EmptyState height={height} />;
  if (isEmpty?.(q.data)) return <EmptyState height={height} title={emptyTitle} />;
  return <div className={cx('transition-opacity', q.isPlaceholderData && q.isFetching && 'opacity-60')}>{children(q.data)}</div>;
}

// ---------------------------------------------------------------- badges
export type Tone = 'good' | 'warn' | 'bad' | 'neutral' | 'brand';

const toneCls: Record<Tone, string> = {
  good: 'bg-good-bg text-good',
  warn: 'bg-warn-bg text-warn',
  bad: 'bg-bad-bg text-bad',
  neutral: 'bg-sunken text-ink2',
  brand: 'bg-brand/10 text-brand dark:text-ink',
};

export function Badge({ tone = 'neutral', children, icon, title }: { tone?: Tone; children: ReactNode; icon?: boolean; title?: string }) {
  const I = tone === 'good' ? IconCheck : tone === 'bad' ? IconX : tone === 'warn' ? IconAlert : IconInfo;
  return (
    <span className={cx('chip', toneCls[tone])} title={title}>
      {icon && <I size={12} />}
      {children}
    </span>
  );
}

const STATUS_TONE: Record<string, Tone> = {
  ok: 'good',
  success: 'good',
  delivered: 'good',
  approved: 'good',
  active: 'good',
  paid: 'good',
  captured: 'good',
  user_cancelled: 'neutral',
  in_stock: 'good',
  stale: 'warn',
  pending: 'warn',
  received: 'neutral',
  confirmed: 'brand',
  shipped: 'brand',
  low_stock: 'warn',
  medium: 'warn',
  running: 'brand',
  failed: 'bad',
  rejected: 'bad',
  cancelled: 'bad',
  high: 'bad',
  oos: 'bad',
  out_of_stock: 'bad',
  low: 'neutral',
  inactive: 'neutral',
};

export function StatusBadge({ status, label }: { status: string | null | undefined; label?: string }) {
  const s = (status ?? '').toLowerCase();
  const tone = STATUS_TONE[s] ?? 'neutral';
  return (
    <Badge tone={tone} icon={tone === 'good' || tone === 'bad' || tone === 'warn'}>
      {label ?? (s ? s.replace(/_/g, ' ') : '–')}
    </Badge>
  );
}

export function worstFreshness(f: Freshness[] | undefined | null): FreshnessStatus | null {
  if (!f || f.length === 0) return null;
  if (f.some((x) => x.status === 'failed')) return 'failed';
  if (f.some((x) => x.status === 'stale')) return 'stale';
  return 'ok';
}

function fmtAsOf(iso: string, ref?: string | null): string {
  const d = dayjs(iso);
  if (!d.isValid()) return iso;
  const sameDay = ref ? dayjs(ref).isSame(d, 'day') : false;
  return sameDay ? d.format('h:mm A') : d.format('h:mm A, D MMM');
}

/**
 * Freshness badge: "Data as of 10:00 AM, 11 Nov · next update 6:00 PM".
 * Green / amber / red from the worst source status (dot + words, never colour alone).
 * Hover lists every source.
 */
export function FreshnessBadge({ meta }: { meta: Meta | null | undefined }) {
  const freshness = meta?.freshness;
  const status = worstFreshness(freshness);
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((x) => x + 1), 60_000);
    return () => clearInterval(t);
  }, []);
  const asOf = meta?.last_refresh_at ?? meta?.as_of ?? null;
  const next = meta?.next_refresh_at ?? null;
  const overdue = next ? Date.now() > new Date(next).getTime() + 30 * 60_000 : false;
  const tone: Tone = status === 'failed' ? 'bad' : status === 'stale' || overdue ? 'warn' : status === 'ok' ? 'good' : 'neutral';
  const dot = { good: 'bg-[#0ca30c]', warn: 'bg-[#fab219]', bad: 'bg-[#d03b3b]', neutral: 'bg-muted', brand: 'bg-brand' }[tone];
  const prefix = status === 'failed' ? 'Sync failed · ' : status === 'stale' ? 'Stale · ' : overdue ? 'Update overdue · ' : '';
  const detail = (freshness ?? []).map((f) => `${f.source}: ${f.status} · last success ${relTime(f.last_success_at)}`).join('\n');
  return (
    <span className={cx('chip whitespace-nowrap', toneCls[tone])} title={detail || 'No freshness information yet'}>
      <span className={cx('h-2 w-2 shrink-0 rounded-full', dot)} aria-hidden />
      {asOf ? (
        <span>
          {prefix}Data as of {fmtAsOf(asOf)}
          {next && <span className="font-normal opacity-80"> · next update {fmtAsOf(next, asOf)}</span>}
        </span>
      ) : (
        'Freshness unknown'
      )}
    </span>
  );
}

/** Signed delta with direction-aware colouring. higherIsBetter=false flips good/bad. */
export function Delta({ value, higherIsBetter = true, suffix = 'vs prev', className }: { value: number | null | undefined; higherIsBetter?: boolean; suffix?: string; className?: string }) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return <span className={cx('text-xs text-muted', className)}>No comparison</span>;
  }
  const flat = Math.abs(value) < 0.05;
  const good = flat ? null : (value > 0) === higherIsBetter;
  const cls = good === null ? 'text-muted' : good ? 'text-good' : 'text-bad';
  const Arrow = value > 0 ? IconArrowUp : IconArrowDown;
  return (
    <span className={cx('inline-flex items-center gap-0.5 text-xs font-medium', cls, className)}>
      {!flat && <Arrow size={12} />}
      {signedPct(value)}
      {suffix && <span className="ml-1 font-normal text-muted">{suffix}</span>}
    </span>
  );
}

// ---------------------------------------------------------------- tabs / segmented
export function Segmented<T extends string>({ value, onChange, options, size = 'sm' }: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode }[];
  size?: 'sm' | 'xs';
}) {
  return (
    <div role="tablist" className="inline-flex rounded-md border border-line bg-sunken p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={cx(
            'rounded px-2.5 font-medium transition-colors',
            size === 'xs' ? 'py-0.5 text-xs' : 'py-1 text-xs',
            value === o.value ? 'bg-surface text-ink shadow-sm' : 'text-ink2 hover:text-ink',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, tabs }: { value: T; onChange: (v: T) => void; tabs: { value: T; label: ReactNode }[] }) {
  return (
    <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((t) => (
        <button
          key={t.value}
          role="tab"
          aria-selected={value === t.value}
          onClick={() => onChange(t.value)}
          className={cx(
            '-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium',
            value === t.value ? 'border-accent text-ink' : 'border-transparent text-ink2 hover:text-ink',
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- overlays
export function Modal({ open, onClose, title, children, footer, wide }: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-[8vh]" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        className={cx('card w-full shadow-xl', wide ? 'max-w-3xl' : 'max-w-lg')}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h3 className="text-sm font-semibold">{title}</h3>
          <button className="rounded p-1 text-muted hover:bg-sunken" onClick={onClose} aria-label="Close">
            <IconX />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto p-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-4 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Drawer({ open, onClose, title, children, width = 560 }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; width?: number }) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 bg-black/30" onMouseDown={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        className="absolute right-0 top-0 flex h-full max-w-full flex-col border-l border-line bg-surface shadow-2xl"
        style={{ width }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h3 className="text-sm font-semibold">{title}</h3>
          <button className="rounded p-1 text-muted hover:bg-sunken" onClick={onClose} aria-label="Close">
            <IconX />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
      </aside>
    </div>
  );
}

export function Field({ label, children, hint, error }: { label: string; children: ReactNode; hint?: string; error?: string }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && !error && <span className="mt-1 block text-2xs text-muted">{hint}</span>}
      {error && <span className="mt-1 block text-2xs text-bad">{error}</span>}
    </label>
  );
}

export function InlineError({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div className="flex items-start gap-2 rounded-md border border-bad/30 bg-bad-bg px-3 py-2 text-xs text-bad">
      <IconAlert size={14} className="mt-0.5 shrink-0" />
      <span>{errorMessage(error)}</span>
    </div>
  );
}

/** Label/value pair used in profile panels. */
export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted">{label}</div>
      <div className="truncate text-sm font-semibold text-ink">{value}</div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </div>
  );
}

/** Thin meter: fill carries state, track is a lighter step of the same hue. */
export function Meter({ value, max = 100, tone = 'brand' }: { value: number | null | undefined; max?: number; tone?: 'brand' | 'good' | 'warn' | 'bad' }) {
  const w = value == null ? 0 : Math.max(0, Math.min(100, (value / max) * 100));
  const fill = { brand: 'bg-brand', good: 'bg-[#0ca30c]', warn: 'bg-[#fab219]', bad: 'bg-[#d03b3b]' }[tone];
  const track = { brand: 'bg-brand/15', good: 'bg-[#0ca30c]/15', warn: 'bg-[#fab219]/20', bad: 'bg-[#d03b3b]/15' }[tone];
  return (
    <div className={cx('h-1.5 w-full overflow-hidden rounded-full', track)}>
      <div className={cx('h-full rounded-full', fill)} style={{ width: `${w}%` }} />
    </div>
  );
}
