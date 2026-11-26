import { inr, num, pct } from '@/lib/format';
import { Card, cx } from '@/components/ui';
import { Change } from './shared';
import type { Scorecard, TierRow } from './types';

/**
 * MBR page 3: what drove the month's growth - KYC, BlueOrigin tiers and new retailers - in one compact card,
 * with the conclusions for next month underneath.
 */
const DOT = { good: 'bg-good', bad: 'bg-bad', warn: 'bg-warn', neutral: 'bg-muted' };
const signed = (v: number) => `${v >= 0 ? '+' : '−'}${inr(Math.abs(v))}`;
const TOP = new Set(['Platinum', 'Gold', 'Silver']);

export function GrowthDrivers({ s }: { s: Scorecard }) {
  const g = s.growth_drivers;
  if (!g) return null;
  const k = g.kyc;
  const maxAbs = Math.max(...g.tiers.map((t) => Math.abs(t.change)), 1);
  return (
    <Card
      className="mb-4"
      title="What drove growth: KYC, BlueOrigin tiers, new retailers"
      subtitle={`${g.window.current} vs ${g.window.previous} · sales ${signed(g.change)}`}
      bodyClass="p-0"
    >
      <div className="grid grid-cols-2 gap-px border-b border-line bg-line md:grid-cols-4">
        <Tile label="KYC approved (this month's sign-ups)" value={num(k.kyc_new?.value)} sub={<>last month {num(k.kyc_new?.prev)}</>} />
        <Tile label="KYC → first order, same month" value={pct(k.kyc_to_order_pct?.value, 0)}
          sub={<><Change v={k.kyc_to_order_pct?.value != null && k.kyc_to_order_pct?.prev != null ? k.kyc_to_order_pct.value - k.kyc_to_order_pct.prev : null} f="pct" /> vs last month</>}
          tone={(k.kyc_to_order_pct?.value ?? 0) < 20 ? 'text-warn' : undefined} />
        <Tile label="New retailers (first order)" value={num(g.new.retailers)}
          sub={<>{inr(g.new.sales)} · {pct(g.new.share_pct, 0)} of sales · last month {num(g.new.prev_retailers)}</>} />
        <Tile label="KYC done, never ordered" value={num(k.ants?.value)} sub={<>the pool to convert</>} tone="text-warn" />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th className="px-4 py-2 font-medium">BlueOrigin tier</th>
              <th className="px-3 py-2 text-right font-medium">Sales</th>
              <th className="w-48 px-3 py-2 font-medium">Change vs last month</th>
              <th className="px-3 py-2 text-right font-medium" title="Tier's ₹ change ÷ TD's ₹ change">Share of growth</th>
              <th className="px-3 py-2 text-right font-medium">Buying retailers</th>
              <th className="px-3 py-2 text-right font-medium">New</th>
              <th className="px-3 py-2 text-right font-medium" title="Sales ÷ buying retailers">Spend / retailer</th>
              <th className="px-4 py-2 text-right font-medium" title="BlueOrigin retailers of the tier buying on TD this month ÷ all BlueOrigin retailers of the tier">TD reach of tier</th>
            </tr>
          </thead>
          <tbody>
            {g.tiers.map((t) => <TierLine key={t.tier} t={t} maxAbs={maxAbs} />)}
          </tbody>
        </table>
      </div>

      <div className="border-t border-line px-4 py-3">
        <div className="mb-1.5 text-xs font-medium text-muted">What it means for next month</div>
        <ul className="grid gap-x-6 gap-y-1.5 lg:grid-cols-2">
          {g.reads.map((r) => (
            <li key={r.text} className="flex gap-2 text-sm text-ink">
              <span className={cx('mt-1.5 h-2 w-2 shrink-0 rounded-full', DOT[r.tone])} aria-hidden />
              <span>{r.text}</span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-2xs text-muted">
          KYC counts the KYC-approved retailers who signed up in the month (the data has no approval date). Tier = the retailer's BlueOrigin tier in its latest quarter; "Not in BlueOrigin" = retailers TD found who don't buy TechnoSport offline.
        </p>
      </div>
    </Card>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub: React.ReactNode; tone?: string }) {
  return (
    <div className="bg-surface p-3.5">
      <div className="text-xs text-muted">{label}</div>
      <div className={cx('mt-0.5 text-xl font-semibold tabular-nums', tone ?? 'text-ink')}>{value}</div>
      <div className="mt-0.5 text-2xs text-muted">{sub}</div>
    </div>
  );
}

function TierLine({ t, maxAbs }: { t: TierRow; maxAbs: number }) {
  const w = (Math.abs(t.change) / maxAbs) * 50;
  return (
    <tr className={cx('border-b border-line/60 last:border-0', TOP.has(t.tier) && 'bg-brand/5')}>
      <td className="px-4 py-2 font-medium text-ink">{t.tier}</td>
      <td className="px-3 py-2 text-right tabular-nums text-ink">{inr(t.sales)}<span className="block text-2xs text-muted">{pct(t.share_pct, 0)} of sales</span></td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          {/* centred bar: right = up, left = down */}
          <div className="relative h-2 w-24 shrink-0 rounded bg-sunken">
            <span className="absolute inset-y-0 left-1/2 w-px bg-line" aria-hidden />
            <span className={cx('absolute inset-y-0 rounded', t.change >= 0 ? 'left-1/2 bg-good' : 'right-1/2 bg-bad')} style={{ width: `${w}%` }} />
          </div>
          <span className={cx('whitespace-nowrap text-xs tabular-nums', t.change >= 0 ? 'text-good' : 'text-bad')}>{signed(t.change)}</span>
        </div>
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-ink2">{t.growth_share_pct === null ? '–' : `${t.growth_share_pct.toFixed(0)}%`}</td>
      <td className="px-3 py-2 text-right tabular-nums text-ink2">{num(t.retailers)}<span className="block text-2xs"><Change v={t.prev_retailers ? ((t.retailers - t.prev_retailers) / t.prev_retailers) * 100 : null} f="inr" /></span></td>
      <td className="px-3 py-2 text-right tabular-nums text-ink2">{num(t.new)}</td>
      <td className="px-3 py-2 text-right tabular-nums text-ink2">{inr(t.spend)}</td>
      <td className="px-4 py-2 text-right tabular-nums text-ink2">
        {t.reach_pct === null ? <span className="text-muted">–</span> : <>{pct(t.reach_pct, 1)}<span className="block text-2xs text-muted">of {num(t.bo_retailers)}</span></>}
      </td>
    </tr>
  );
}
