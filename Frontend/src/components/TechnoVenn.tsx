import { useState, type MouseEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, cx } from '@/components/ui';
import { num, pct } from '@/lib/format';

/**
 * Retailer Funnel → "TD is a solid acquisition lever" (the Way Forward deck's base diagram, drawn from live data).
 * Circle AREAS are in proportion to the counts and the overlaps are solved to the real overlaps:
 *   dashed circle  = retailers who ever bought TechnoSport offline (BlueOrigin)
 *   filled ring    = ANTs: TD KYC-approved, never transacted
 *   inner circle   = TD transacting retailers
 * Hover a part (or a legend row) to highlight it; click to open the retailers behind it.
 */
export interface TechnoBase {
  universe: number;
  kyc: number;
  kyc_in_bo: number;
  kyc_new: number;
  expansion_pct: number | null;
  transacting: number;
  transacting_in_bo: number;
  ants: number;
  ants_in_bo: number;
  ants_pct: number | null;
  bo_never_transacted: number;
  as_of: string;
}

type Part = 'bo' | 'kyc' | 'ants' | 'trans';
type Open = (title: string, params: Record<string, string>, subtitle?: string) => void;

const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : num(n));

/** Area of the lens where two circles (radii a, b) with centres d apart overlap. */
function lens(a: number, b: number, d: number) {
  if (d >= a + b) return 0;
  if (d <= Math.abs(a - b)) return Math.PI * Math.min(a, b) ** 2;
  const x = (d * d + a * a - b * b) / (2 * d * a);
  const y = (d * d + b * b - a * a) / (2 * d * b);
  return a * a * Math.acos(x) + b * b * Math.acos(y) - 0.5 * Math.sqrt((-d + a + b) * (d + a - b) * (d - a + b) * (d + a + b));
}

/** Centre distance that gives the target overlap area (the lens shrinks as d grows). */
function distanceFor(a: number, b: number, area: number) {
  let lo = Math.abs(a - b);
  let hi = a + b;
  for (let i = 0; i < 60; i++) {
    const mid = (lo + hi) / 2;
    if (lens(a, b, mid) > area) lo = mid;
    else hi = mid;
  }
  return (lo + hi) / 2;
}

export function TechnoVenn({ tb, onOpen, className }: { tb: TechnoBase; onOpen: Open; className?: string }) {
  const navigate = useNavigate();
  const [hot, setHot] = useState<Part | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number } | null>(null);
  if (!tb.universe || !tb.kyc) return null;

  // geometry: viewBox W x 230
  const R1 = 100;
  const scale = R1 / Math.sqrt(tb.universe);
  const R2 = scale * Math.sqrt(tb.kyc);
  const R3 = scale * Math.sqrt(Math.max(tb.transacting, 1));
  const px = (n: number) => n * scale * scale * Math.PI;
  const cy = 115;
  const c1 = 108;
  const c2 = c1 + distanceFor(R1, R2, px(tb.kyc_in_bo));
  const c3 = Math.min(Math.max(c1 + distanceFor(R1, R3, px(tb.transacting_in_bo)), c2 - R2 + R3 + 2), c2 + R2 - R3 - 2);
  const W = Math.ceil(c2 + R2 + 8);

  const parts: Record<Part, { label: string; n: number; swatch: string; detail: string; go: () => void; split?: [string, number, Record<string, string>][] }> = {
    bo: {
      label: 'Ever bought TechnoSport offline', n: tb.universe, swatch: 'border-muted border-dashed',
      detail: `${num(tb.bo_never_transacted)} of them have never transacted on TD. Opens BlueOrigin (Offline).`,
      go: () => navigate('/blueorigin'),
    },
    kyc: {
      label: 'KYC approved on TD', n: tb.kyc, swatch: 'border-ink bg-ink',
      detail: `+${pct(tb.expansion_pct, 0)} to the base: ${num(tb.kyc_new)} are new to TechnoSport`,
      go: () => onOpen('KYC approved on TD', { stage: 'kyc_approved' }, 'KYC approved by the end of the period'),
      split: [['already buy offline', tb.kyc_in_bo, { stage: 'kyc_approved', in_bo: '1' }], ['new to TechnoSport', tb.kyc_new, { stage: 'kyc_approved', in_bo: '0' }]],
    },
    ants: {
      label: 'ANTs: KYC done, never transacted', n: tb.ants, swatch: 'border-ink bg-ink',
      detail: `${pct(tb.ants_pct, 0)} of KYC retailers: the activation problem`,
      go: () => onOpen('ANTs: KYC done, never transacted', { stage: 'kyc_never' }, 'KYC approved, no order ever (as of the end of the period)'),
      split: [['already buy offline (warm)', tb.ants_in_bo, { stage: 'kyc_never', in_bo: '1' }], ['new to TechnoSport', tb.ants - tb.ants_in_bo, { stage: 'kyc_never', in_bo: '0' }]],
    },
    trans: {
      label: 'Transacting on TD', n: tb.transacting, swatch: 'border-line bg-sunken',
      detail: `${pct((tb.transacting / tb.kyc) * 100, 0)} of KYC retailers have ordered`,
      go: () => onOpen('Transacting on TD', { stage: 'first_order' }, 'At least one order by the end of the period'),
      split: [['already buy offline', tb.transacting_in_bo, { stage: 'first_order', in_bo: '1' }], ['new to TechnoSport', tb.transacting - tb.transacting_in_bo, { stage: 'first_order', in_bo: '0' }]],
    },
  };

  const hoverProps = (p: Part) => ({
    onMouseEnter: () => setHot(p),
    onMouseMove: (e: MouseEvent<SVGCircleElement>) => {
      const r = e.currentTarget.ownerSVGElement?.parentElement?.getBoundingClientRect();
      if (r) setTip({ x: e.clientX - r.left, y: e.clientY - r.top });
    },
    onMouseLeave: () => { setHot(null); setTip(null); },
    onClick: () => parts[p].go(),
    style: { cursor: 'pointer' },
  });
  // the KYC circle = the ANTs ring + the transacting circle, so it lights both
  const lit = (p: Part) => !hot || hot === p || (hot === 'kyc' && (p === 'ants' || p === 'trans'));

  return (
    <Card
      className={className}
      title="TD is a solid acquisition lever"
      subtitle={`Expanded the TechnoSport retailer base by ${pct(tb.expansion_pct, 0)} with ~${k(tb.kyc_new)} new retailers; activation remains the problem: ~${k(tb.ants)} KYC retailers never transacted. Hover for detail, click for the retailers.`}
    >
      <div className="grid items-center gap-4 md:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
        <div className="relative">
          <svg viewBox={`0 0 ${W} 230`} className="mx-auto block max-h-52 w-full" role="img"
            aria-label={`${num(tb.universe)} TechnoSport retailers; ${num(tb.kyc)} TD KYC retailers; ${num(tb.transacting)} transacting; ${num(tb.ants)} never transacted`}>
            <circle cx={c1} cy={cy} r={R1} className={cx('stroke-muted transition-opacity', hot === 'bo' ? 'fill-muted/10' : 'fill-transparent')}
              strokeWidth={1.5} strokeDasharray="4 4" opacity={lit('bo') ? 1 : 0.35} {...hoverProps('bo')} />
            <circle cx={c2} cy={cy} r={R2} className="fill-ink transition-opacity" opacity={lit('ants') ? 1 : 0.3} {...hoverProps('ants')} />
            <circle cx={c3} cy={cy} r={R3} className={cx('stroke-surface transition-opacity', hot === 'trans' ? 'fill-brand' : 'fill-sunken')}
              strokeWidth={2} opacity={lit('trans') ? 1 : 0.35} {...hoverProps('trans')} />
            <text x={c1 - R1 * 0.45} y={cy + 4} textAnchor="middle" className="pointer-events-none fill-ink2 text-[13px] font-semibold">{k(tb.universe)}</text>
            <text x={(c3 + R3 + c2 + R2) / 2} y={cy + 4} textAnchor="middle" className="pointer-events-none fill-surface text-[13px] font-semibold">{k(tb.ants)}</text>
            <text x={c3} y={cy + 4} textAnchor="middle" className={cx('pointer-events-none text-[11px] font-semibold', hot === 'trans' ? 'fill-white' : 'fill-ink')}>{k(tb.transacting)}</text>
          </svg>
          {hot && tip && (
            <div className="pointer-events-none absolute z-10 w-56 rounded-md border border-line bg-surface px-2.5 py-2 text-xs shadow-lg"
              style={{ left: Math.min(tip.x + 12, 120), top: tip.y + 12 }}>
              <div className="font-semibold text-ink">{parts[hot].label}</div>
              <div className="text-base font-semibold tabular-nums text-ink">{num(parts[hot].n)}</div>
              <div className="text-ink2">{parts[hot].detail}</div>
              <div className="mt-1 text-2xs text-muted">{hot === 'bo' ? 'Click to open BlueOrigin (Offline)' : 'Click to see the retailers'}</div>
            </div>
          )}
        </div>

        <ul className="divide-y divide-line/60 text-sm">
          {(['bo', 'kyc', 'ants', 'trans'] as Part[]).map((p) => {
            const x = parts[p];
            return (
              <li key={p} onMouseEnter={() => setHot(p)} onMouseLeave={() => setHot(null)}
                className={cx('rounded-md px-2 py-1.5 transition-colors', hot === p && 'bg-sunken/70', p === 'ants' && 'pl-6', p === 'trans' && 'pl-6')}>
                <button type="button" onClick={x.go} className="flex w-full items-center gap-2 text-left">
                  <span className={cx('size-3 shrink-0 rounded-full border', x.swatch)} />
                  <span className="flex-1 text-ink2">{x.label}</span>
                  <span className="font-semibold tabular-nums text-ink">{num(x.n)}</span>
                </button>
                {x.split && (
                  <div className="ml-5 mt-0.5 flex flex-wrap gap-x-3 text-2xs text-muted">
                    {x.split.map(([l, n, params]) => (
                      <button key={l} type="button" className="hover:text-ink hover:underline" onClick={() => onOpen(`${x.label}: ${l}`, params)}>
                        {num(n)} {l}
                      </button>
                    ))}
                  </div>
                )}
              </li>
            );
          })}
          <li className="px-2 pt-1.5 text-2xs text-muted">
            Circle areas to scale. TechnoSport retailers = bought from our distributors offline (BlueOrigin), matched to TD by phone. As of {tb.as_of.split('-').reverse().join('-')}.
          </li>
        </ul>
      </div>
    </Card>
  );
}
