import { useMemo, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { KPI } from '@/api/types';
import { EChart, useChartTokens } from '@/charts/EChart';
import { sparkline } from '@/charts/builders';
import { Delta, Skeleton, cx } from './ui';

export function Sparkline({ data, height = 32, accent }: { data: (number | null)[] | undefined; height?: number; accent?: string }) {
  const t = useChartTokens();
  const clean = (data ?? []).map((v) => (typeof v === 'number' ? v : 0));
  const opt = useMemo(() => sparkline(t, clean, accent), [t, clean.join(','), accent]); // eslint-disable-line react-hooks/exhaustive-deps
  if (clean.length < 2) return <div style={{ height }} />;
  return <EChart option={opt} height={height} />;
}

/**
 * Stat tile: label · value · delta vs named period · 12-month sparkline.
 * Money tiles carry the sales basis so nobody mistakes gross for net.
 */
export function KpiTile({
  label,
  kpi,
  format,
  basis,
  higherIsBetter = true,
  to,
  compareLabel = 'vs prev',
  loading,
  hint,
}: {
  label: string;
  kpi: KPI | undefined | null;
  format: (n: number | null | undefined) => string;
  basis?: string;
  higherIsBetter?: boolean;
  to?: string;
  compareLabel?: string;
  loading?: boolean;
  hint?: ReactNode;
}) {
  const inner = (
    <>
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-medium text-ink2">{label}</span>
      </div>
      {loading ? (
        <Skeleton className="mt-2 h-7 w-24" />
      ) : (
        <div className="mt-1 text-[1.6rem] font-semibold leading-tight tracking-tight text-ink">{format(kpi?.value)}</div>
      )}
      <div className="mt-0.5 flex min-h-[18px] items-center gap-1">
        {!loading && <Delta value={kpi?.delta_pct} higherIsBetter={higherIsBetter} suffix={compareLabel} />}
      </div>
      <div className="mt-1">{!loading && <Sparkline data={kpi?.spark} />}</div>
      {(basis || hint) && <div className="mt-1 truncate text-2xs text-muted" title={basis}>{hint ?? basis}</div>}
    </>
  );
  const cls = cx('card block p-3.5 transition-colors', to && 'hover:border-brand/50 hover:bg-sunken/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/40');
  return to ? (
    <Link to={to} className={cls} title={`Open ${label.toLowerCase()} details`}>
      {inner}
    </Link>
  ) : (
    <div className={cls}>{inner}</div>
  );
}

/** Small numeric tile without sparkline. */
export function MiniStat({ label, value, sub, tone, to }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'good' | 'warn' | 'bad'; to?: string }) {
  const body = (
    <>
      <div className="text-xs text-ink2">{label}</div>
      <div className={cx('mt-0.5 text-xl font-semibold', tone === 'bad' ? 'text-bad' : tone === 'warn' ? 'text-warn' : tone === 'good' ? 'text-good' : 'text-ink')}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </>
  );
  const cls = cx('card block px-3.5 py-3', to && 'hover:border-brand/50 hover:bg-sunken/40');
  return to ? (
    <Link to={to} className={cls}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}
