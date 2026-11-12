import type { TargetBlock } from '@/api/types';
import { inr, pct } from '@/lib/format';
import { Badge, cx } from './ui';

/**
 * Bullet chart: achieved (solid) and projected month-end (light step of the same hue)
 * against a target marker, plus required vs current daily run-rate.
 */
export function TargetBullet({ t, basis }: { t: TargetBlock; basis?: string }) {
  const scale = Math.max(t.target, t.projected, t.achieved) * 1.08 || 1;
  const w = (n: number) => `${Math.max(0, Math.min(100, (n / scale) * 100))}%`;
  const onTrack = t.current_run_rate >= t.required_run_rate;
  const projPct = t.target ? (t.projected / t.target) * 100 : null;
  const rrMax = Math.max(t.current_run_rate, t.required_run_rate) * 1.1 || 1;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <div className="text-xs text-ink2">Achieved vs target</div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-semibold">{inr(t.achieved)}</span>
            <span className="text-sm text-muted">of {inr(t.target)}</span>
            <span className="text-sm font-semibold text-ink">{pct(t.achievement_pct)}</span>
          </div>
        </div>
        <Badge tone={onTrack ? 'good' : projPct !== null && projPct >= 90 ? 'warn' : 'bad'} icon>
          {onTrack ? 'On track' : 'Behind run-rate'} · projected {projPct === null ? '–' : pct(projPct, 0)}
        </Badge>
      </div>

      <div>
        <div className="relative h-7 w-full rounded bg-sunken" role="img" aria-label={`Achieved ${inr(t.achieved)}, projected ${inr(t.projected)}, target ${inr(t.target)}`}>
          <div className="absolute inset-y-1.5 left-0 rounded-r bg-brand/25 dark:bg-brand/45" style={{ width: w(t.projected) }} title={`Projected ${inr(t.projected)}`} />
          <div className="absolute inset-y-1.5 left-0 rounded-r bg-brand" style={{ width: w(t.achieved) }} title={`Achieved ${inr(t.achieved)}`} />
          <div className="absolute inset-y-0 w-[3px] rounded bg-ink" style={{ left: `calc(${w(t.target)} - 1px)` }} title={`Target ${inr(t.target)}`} />
        </div>
        <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-ink2">
          <span className="inline-flex items-center gap-1"><span className="h-2 w-3 rounded-sm bg-brand" /> Achieved {inr(t.achieved)}</span>
          <span className="inline-flex items-center gap-1"><span className="h-2 w-3 rounded-sm bg-brand/25 dark:bg-brand/45" /> Projected {inr(t.projected)}</span>
          <span className="inline-flex items-center gap-1"><span className="h-3 w-[3px] rounded bg-ink" /> Target {inr(t.target)}</span>
          <span className="text-muted">Balance {inr(t.balance)} · day {t.days_elapsed} of {t.days_total}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {[
          { label: 'Current daily run-rate', v: t.current_run_rate, strong: true },
          { label: 'Required daily run-rate', v: t.required_run_rate, strong: false },
        ].map((r) => (
          <div key={r.label}>
            <div className="flex justify-between text-xs">
              <span className="text-ink2">{r.label}</span>
              <span className="font-semibold">{inr(r.v)}/day</span>
            </div>
            <div className="mt-1 h-2 w-full rounded-full bg-sunken">
              <div className={cx('h-2 rounded-full', r.strong ? 'bg-brand' : 'bg-ink2/60')} style={{ width: `${Math.min(100, (r.v / rrMax) * 100)}%` }} />
            </div>
          </div>
        ))}
      </div>
      {basis && <div className="text-2xs text-muted">Sales basis: {basis}</div>}
    </div>
  );
}
