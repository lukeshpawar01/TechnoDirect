import { useChartTokens } from '@/charts/EChart';
import { tierColor } from '@/lib/tiers';

/** BlueOrigin tier: a swatch from the tier ramp + the name (identity never by colour alone). */
export function TierChip({ tier }: { tier: string | null | undefined }) {
  const t = useChartTokens();
  if (!tier) return <span className="text-xs text-muted">–</span>;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-ink">
      <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: tierColor(tier, t) }} aria-hidden />
      {tier}
    </span>
  );
}
