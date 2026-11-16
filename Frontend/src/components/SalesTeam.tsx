import { Fragment, useState } from 'react';
import type { TerritoryRow, TerritoryTeamRow } from '@/api/types';
import { Card, Delta, Meter } from '@/components/ui';
import { IconChevron, IconChevronDown } from '@/components/Icons';
import { useFilters } from '@/lib/filters';
import { asPct, date, inr, num, pct } from '@/lib/format';

const tone = (a: number | null) => (a === null ? 'brand' : a >= 100 ? 'good' : a >= 80 ? 'warn' : 'bad') as 'brand' | 'good' | 'warn' | 'bad';

function Achieved({ value }: { value: number | null }) {
  const a = asPct(value);
  if (a === null) return <span className="text-xs text-muted">No target</span>;
  return (
    <div className="flex items-center justify-end gap-2">
      <div className="w-24">
        <Meter value={a} tone={tone(a)} />
      </div>
      <span className="w-11 text-right">{pct(a, 0)}</span>
    </div>
  );
}

/** Share of the parent's sales as a thin bar under the figure — where the money comes from, at a glance. */
function SalesCell({ sales, of }: { sales: number; of: number }) {
  const w = of > 0 ? Math.max(0, Math.min(100, (sales / of) * 100)) : 0;
  return (
    <div className="ml-auto w-28">
      <div className="text-right">{inr(sales)}</div>
      <div className="mt-1 h-1 w-full rounded-full bg-sunken" aria-hidden>
        <div className="h-full rounded-full bg-ink2/40" style={{ width: `${w}%` }} />
      </div>
    </div>
  );
}

/**
 * Sales team hierarchy: each RSM with the ASMs reporting to them (from the Master ASM Tracker).
 * Retailers and orders roll up through their ASM; sales with no ASM sit under the RSM of their region.
 */
export function SalesTeam({ rsms, team, loading, periodStart }: { rsms: TerritoryRow[]; team: TerritoryTeamRow[]; loading?: boolean; periodStart?: string }) {
  const { update } = useFilters();
  const [closed, setClosed] = useState<Set<number>>(new Set());
  const total = rsms.reduce((s, r) => s + r.sales, 0);
  const toggle = (id: number) =>
    setClosed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <Card
      title="Sales team: RSM → ASM"
      subtitle="Each ASM sits under the RSM they report to. Bars under sales show the share of the level above; achievement counts sales in months that have a target. Click a name to filter the dashboard."
      className="mb-4"
    >
      <div className="overflow-x-auto px-4 pb-3 pt-2">
        {loading && !rsms.length ? (
          <div className="h-48 animate-pulse rounded-md bg-sunken" />
        ) : (
          <table className="w-full min-w-[860px] text-sm tabular">
            <thead>
              <tr className="border-b border-line">
                <th className="th pl-0">Team</th>
                <th className="th text-right">Sales</th>
                <th className="th text-right">Target</th>
                <th className="th text-right">Achieved</th>
                <th className="th text-right">Growth</th>
                <th className="th text-right">Active retailers</th>
                <th className="th text-right">Field staff</th>
              </tr>
            </thead>
            {rsms.map((r) => {
              const open = !closed.has(r.id);
              const kids = team.filter((t) => t.rsm_id === r.id);
              return (
                <tbody key={r.id} className="border-b border-line last:border-0">
                  <tr className="bg-sunken/60">
                    <td className="py-2.5 pr-3">
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => toggle(r.id)}
                          className="rounded p-0.5 text-muted hover:bg-line hover:text-ink"
                          aria-expanded={open}
                          aria-label={open ? `Collapse ${r.name}` : `Expand ${r.name}`}
                        >
                          {open ? <IconChevronDown size={14} /> : <IconChevron size={14} />}
                        </button>
                        <div className="min-w-0">
                          <button type="button" className="font-display text-[1.0625rem] font-semibold leading-tight text-ink hover:underline" onClick={() => update({ rsm: String(r.id) })}>
                            {r.name}
                          </button>
                          <div className="text-xs text-muted">
                            RSM{r.region ? `, ${r.region}` : ''} · {num(r.asms ?? 0)} ASMs
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="td font-semibold">
                      <SalesCell sales={r.sales} of={total} />
                    </td>
                    <td className="td text-right">{inr(r.target)}</td>
                    <td className="td">
                      <Achieved value={r.achievement_pct} />
                    </td>
                    <td className="td text-right">
                      <Delta value={r.growth_pct} suffix="" />
                    </td>
                    <td className="td text-right">{num(r.active_retailers)}</td>
                    <td className="td text-right">{num(r.field_staff ?? 0)}</td>
                  </tr>
                  {open &&
                    kids.map((k) => (
                      <Fragment key={`${k.rsm_id}-${k.asm_id ?? 'none'}`}>
                        <tr className="hover:bg-sunken/40">
                          <td className="py-2 pl-9 pr-3">
                            {k.asm_id ? (
                              <button type="button" className="text-left hover:underline" onClick={() => update({ asm: String(k.asm_id) })}>
                                <span className="font-medium text-ink">{k.name}</span>
                                {k.full_name && k.full_name !== k.name && <span className="ml-1.5 text-xs text-muted">{k.full_name}</span>}
                                {k.is_active === false && (
                                  <span className="chip ml-1.5 bg-sunken text-ink2" title="No longer in charge: credited with the months they were in charge">
                                    {k.name.includes('&') ? 'Ended' : 'Left'}
                                  </span>
                                )}
                                {k.is_active !== false && k.joined_on && periodStart && k.joined_on >= periodStart && (
                                  <span className="chip ml-1.5 bg-brand/10 text-brand" title="Joined during this period">Joined {date(k.joined_on)}</span>
                                )}
                              </button>
                            ) : (
                              <span className="text-ink2" title="Sales of distributors with no ASM, counted under the RSM of their region">
                                {k.name}
                              </span>
                            )}
                          </td>
                          <td className="td">
                            <SalesCell sales={k.sales} of={r.sales} />
                          </td>
                          <td className="td text-right">{inr(k.target)}</td>
                          <td className="td">
                            <Achieved value={k.achievement_pct} />
                          </td>
                          <td className="td text-right">
                            <Delta value={k.growth_pct} suffix="" />
                          </td>
                          <td className="td text-right">{num(k.active_retailers)}</td>
                          <td className="td text-right">{k.asm_id ? num(k.field_staff) : <span className="text-muted">–</span>}</td>
                        </tr>
                      </Fragment>
                    ))}
                </tbody>
              );
            })}
          </table>
        )}
      </div>
    </Card>
  );
}
