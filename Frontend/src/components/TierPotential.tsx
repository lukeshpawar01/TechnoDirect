import { useMemo, useState } from 'react';
import { useAnalytics } from '@/api/hooks';
import { cartesian } from '@/charts/builders';
import { EChart, useChartTokens } from '@/charts/EChart';
import { inr, num, pct } from '@/lib/format';
import { Card, EmptyState, ErrorState, Meter, Segmented, Skeleton } from './ui';

interface Totals {
  bo_purchase: number;
  td_actual: number;
  td_expected: number;
  gap: number;
  offline_only_bo: number;
  td_share_pct: number | null;
  expected_share_pct: number | null;
  bo_retailers: number;
  on_td: number;
  td_buyers: number;
  wallet_retailers: number;
  wallet_td: number;
  wallet_bo: number;
  wallet_gap: number;
  wallet_pct: number | null;
}
interface WalletQuarter {
  quarter: string;
  start: string;
  retailers: number;
  td: number;
  bo: number;
  gap: number;
  wallet_pct: number | null;
}
interface TierRow extends Totals {
  tier: string;
  benchmark_pct: number;
  benchmark_cells: number;
  benchmark_basis: 'tier' | 'pooled';
}
interface GroupRow extends Totals {
  id: number | null;
  name: string;
  gap_by_tier: Record<string, number>;
}
interface Potential {
  available: boolean;
  window?: { label: string; shifted: boolean; tier_quarter: string | null };
  by_tier: TierRow[];
  total: Totals;
  not_in_bo_td: number;
  group_by: string;
  rows: GroupRow[];
  method: { percentile: number; min_monthly: number; min_retailers: number };
  wallet_by_quarter?: WalletQuarter[];
}

type Group = 'asm' | 'rsm' | 'state' | 'distributor' | 'region';
const GROUPS: { value: Group; label: string }[] = [
  { value: 'asm', label: 'ASM' },
  { value: 'rsm', label: 'RSM' },
  { value: 'state', label: 'State' },
  { value: 'distributor', label: 'Distributor' },
  { value: 'region', label: 'Region' },
];
const lakh = (v: number) => inr(v, { compact: true });
const reach = (r: Totals) => (r.td_expected > 0 ? (r.td_actual / r.td_expected) * 100 : null);

/**
 * TD sales against what BlueOrigin says the same retailers buy from our distributors. Expected TD per tier = the
 * tier's BO purchase x the TD share the best quarter of distributors already reach in that tier (network-wide).
 * Monthly averages over the latest BO months the period maps to (BO sheets lag the app).
 */
export function TierPotential() {
  const [group, setGroup] = useState<Group>('asm');
  const [all, setAll] = useState(false);
  const q = useAnalytics<Potential>('/blueorigin/potential/', { group_by: group });
  const d = q.data?.data;
  const t = useChartTokens();
  const wq = d?.wallet_by_quarter ?? [];
  const walletOpt = useMemo(
    () =>
      wq.length
        ? cartesian(t, {
            x: wq.map((w) => w.quarter.replace('FY', 'FY ')),
            format: 'pct',
            series: [{ name: 'TD wallet share', type: 'line', data: wq.map((w) => w.wallet_pct), endLabel: true, color: t.series[0] }],
            legend: false,
          })
        : null,
    [wq, t],
  );
  const lastQ = wq[wq.length - 1];

  if (q.isError) return <Card className="mt-4" title="Expected TD from BlueOrigin"><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card>;
  if (d && !d.available) return null;

  const rows = d ? (all ? d.rows : d.rows.slice(0, 12)) : [];
  const groupLabel = GROUPS.find((g) => g.value === group)?.label ?? 'ASM';

  return (
    <Card
      className="mt-4"
      title="Expected TD from BlueOrigin"
      subtitle={
        d?.window
          ? `Per month, ${d.window.label}${d.window.shifted ? ' (latest BlueOrigin months; the sheets lag the app)' : ''}. Expected = each tier's distributor purchase × the TD share the best ${100 - (d.method.percentile ?? 75)}% of distributors already reach in that tier.`
          : 'TD sales against what the same retailers buy from our distributors'
      }
    >
      {q.isLoading || !d ? (
        <Skeleton className="h-64" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Figure label="BO purchase (same retailers)" value={lakh(d.total.bo_purchase)} note={`${num(d.total.bo_retailers)} retailers buying`} />
            <Figure label="TD today" value={lakh(d.total.td_actual)} note={`${pct(d.total.td_share_pct, 1)} of their purchase`} />
            <Figure label="Expected TD" value={lakh(d.total.td_expected)} note={`${pct(d.total.expected_share_pct, 1)} of their purchase`} />
            <Figure label="Gap to expected" value={lakh(d.total.gap)} note="extra TD a month" strong />
          </div>
          <p className="mt-2 text-xs text-muted">
            Plus {lakh(d.not_in_bo_td)} a month of TD from retailers not in BlueOrigin.
            {d.total.offline_only_bo > 0 && ` ${lakh(d.total.offline_only_bo)} of BO purchase goes through offline-only distributors (not on the app), so it carries no expected TD.`}
          </p>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm tabular">
              <thead>
                <tr className="border-b border-line text-xs text-muted">
                  <th className="py-2 pr-2 text-left font-medium">BO tier</th>
                  <th className="px-2 py-2 text-right font-medium">Retailers on TD</th>
                  <th className="px-2 py-2 text-right font-medium">BO purchase</th>
                  <th className="px-2 py-2 text-right font-medium">TD today</th>
                  <th className="px-2 py-2 text-right font-medium">TD share</th>
                  <th className="px-2 py-2 text-right font-medium" title="TD share reached by the best quarter of distributors in this tier">Benchmark share</th>
                  <th className="px-2 py-2 text-right font-medium">Expected TD</th>
                  <th className="px-2 py-2 text-right font-medium">Gap</th>
                  <th className="py-2 pl-2 text-left font-medium">Reached</th>
                </tr>
              </thead>
              <tbody>
                {d.by_tier.map((r) => (
                  <tr key={r.tier} className="border-t border-line/60">
                    <td className="py-2 pr-2 font-medium text-ink">{r.tier}</td>
                    <td className="px-2 py-2 text-right">
                      {num(r.td_buyers)} <span className="text-xs text-muted">of {num(r.bo_retailers)}</span>
                    </td>
                    <td className="px-2 py-2 text-right">{lakh(r.bo_purchase)}</td>
                    <td className="px-2 py-2 text-right">{lakh(r.td_actual)}</td>
                    <td className="px-2 py-2 text-right">{pct(r.td_share_pct, 1)}</td>
                    <td className="px-2 py-2 text-right" title={r.benchmark_basis === 'pooled' ? 'Too few distributors in this tier: benchmark of all tiers pooled' : `${r.benchmark_cells} distributors with enough purchase in this tier`}>
                      {pct(r.benchmark_pct, 1)}
                      {r.benchmark_basis === 'pooled' && <span className="text-xs text-muted"> (all tiers)</span>}
                    </td>
                    <td className="px-2 py-2 text-right">{lakh(r.td_expected)}</td>
                    <td className="px-2 py-2 text-right font-semibold text-ink">{lakh(r.gap)}</td>
                    <td className="py-2 pl-2">
                      <ReachMeter r={r} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-6">
            <h3 className="text-sm font-semibold text-ink">TD wallet share of BlueOrigin spend</h3>
            <p className="mt-0.5 text-xs text-ink2">
              Matched retailers = BlueOrigin retailers linked to an app retailer who has ever ordered on TD. Wallet share = their TD sales ÷ their BlueOrigin
              purchase (which already includes app orders), so the rest is TechnoSport buying still outside the app.
            </p>
            <div className="mt-3 grid grid-cols-1 gap-4 xl:grid-cols-5">
              <div className="xl:col-span-2">
                <div className="flex items-baseline justify-between">
                  <span className="text-xs text-muted">Blended wallet share by quarter</span>
                  {lastQ && (
                    <span className="text-xs text-ink2">
                      {lastQ.quarter}: <b className="text-ink">{pct(lastQ.wallet_pct, 1)}</b> of {lakh(lastQ.bo)} ({num(lastQ.retailers)} retailers)
                    </span>
                  )}
                </div>
                {walletOpt ? <EChart option={walletOpt} height={220} ariaLabel="TD wallet share of BlueOrigin spend by quarter" /> : <EmptyState height={220} />}
                <p className="text-2xs text-muted">
                  Quarters up to FY25-26 Q1 lean on BlueOrigin files that repeat later figures for some distributors, which pulls those points down.
                </p>
              </div>
              <div className="overflow-x-auto xl:col-span-3">
                <table className="w-full min-w-[560px] text-sm tabular">
                  <thead>
                    <tr className="border-b border-line text-xs text-muted">
                      <th className="py-2 pr-2 text-left font-medium">BO tier</th>
                      <th className="px-2 py-2 text-right font-medium">Matched retailers</th>
                      <th className="px-2 py-2 text-right font-medium">TD sales</th>
                      <th className="px-2 py-2 text-right font-medium">BO purchase</th>
                      <th className="px-2 py-2 text-right font-medium">BO − TD gap</th>
                      <th className="py-2 pl-2 text-right font-medium">Wallet share</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...d.by_tier.map((r) => ({ key: r.tier, label: r.tier, r })), { key: 'total', label: 'Total', r: d.total }].map(({ key, label, r }) => (
                      <tr key={key} className={key === 'total' ? 'border-t border-line font-semibold text-ink' : 'border-t border-line/60'}>
                        <td className="py-2 pr-2 font-medium text-ink">{label}</td>
                        <td className="px-2 py-2 text-right">{num(r.wallet_retailers)}</td>
                        <td className="px-2 py-2 text-right">{lakh(r.wallet_td)}</td>
                        <td className="px-2 py-2 text-right">{lakh(r.wallet_bo)}</td>
                        <td className="px-2 py-2 text-right">{lakh(r.wallet_gap)}</td>
                        <td className="py-2 pl-2 text-right">{pct(r.wallet_pct, 1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-1 text-2xs text-muted">Totals for {d.window?.label ?? 'the window'} (not per month).</p>
              </div>
            </div>
          </div>

          <div className="mt-6 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-ink">Where the gap is, by {groupLabel}</h3>
            <Segmented value={group} onChange={(v) => { setGroup(v); setAll(false); }} options={GROUPS} />
          </div>
          {q.isFetching && q.isPlaceholderData ? (
            <Skeleton className="mt-3 h-48" />
          ) : d.rows.length ? (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm tabular">
                <thead>
                  <tr className="border-b border-line text-xs text-muted">
                    <th className="py-2 pr-2 text-left font-medium">{groupLabel}</th>
                    <th className="px-2 py-2 text-right font-medium">BO purchase</th>
                    <th className="px-2 py-2 text-right font-medium">TD today</th>
                    <th className="px-2 py-2 text-right font-medium">Expected TD</th>
                    <th className="px-2 py-2 text-right font-medium">Gap</th>
                    <th className="px-2 py-2 text-left font-medium">Biggest gap in</th>
                    <th className="py-2 pl-2 text-left font-medium">Reached</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const top = Object.entries(r.gap_by_tier).sort((a, b) => b[1] - a[1])[0];
                    return (
                      <tr key={`${r.id}`} className="border-t border-line/60">
                        <td className="py-2 pr-2 text-ink">{r.name}</td>
                        <td className="px-2 py-2 text-right">{lakh(r.bo_purchase)}</td>
                        <td className="px-2 py-2 text-right">{lakh(r.td_actual)}</td>
                        <td className="px-2 py-2 text-right">{lakh(r.td_expected)}</td>
                        <td className="px-2 py-2 text-right font-semibold text-ink">{lakh(r.gap)}</td>
                        <td className="px-2 py-2 text-xs text-ink2">{top && top[1] > 0 ? `${top[0]} (${lakh(top[1])})` : '–'}</td>
                        <td className="py-2 pl-2">
                          <ReachMeter r={r} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {d.rows.length > 12 && (
                <button className="mt-2 text-xs text-ink2 hover:text-ink" onClick={() => setAll((v) => !v)}>
                  {all ? 'Show top 12' : `Show all ${d.rows.length}`}
                </button>
              )}
            </div>
          ) : (
            <EmptyState height={120} />
          )}
        </>
      )}
    </Card>
  );
}

function Figure({ label, value, note, strong }: { label: string; value: string; note: string; strong?: boolean }) {
  return (
    <div>
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-0.5 text-xl tabular ${strong ? 'font-semibold text-ink' : 'font-medium text-ink'}`}>{value}</div>
      <div className="text-xs text-ink2">{note}</div>
    </div>
  );
}

function ReachMeter({ r }: { r: Totals }) {
  const v = reach(r);
  if (v === null) return <span className="text-xs text-muted">–</span>;
  return (
    <div className="flex items-center gap-2">
      <div className="w-20">
        <Meter value={Math.min(v, 100)} tone={v >= 100 ? 'good' : v >= 80 ? 'warn' : 'bad'} />
      </div>
      <span className="w-10 text-right text-xs">{pct(v, 0)}</span>
    </div>
  );
}
