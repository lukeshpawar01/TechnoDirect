import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { get } from '@/lib/api';
import { date, inr, monthLabel, num, pct } from '@/lib/format';
import { DataTable } from './DataTable';
import { MultiSelect } from './MultiSelect';
import { Badge, Card, Meter, Segmented } from './ui';

type Kpi = 'td' | 'new' | 'gps' | 'kyc';
interface DistRow {
  distributor_id: number;
  distributor: string;
  shared: boolean;
  shared_with: string[];
}
interface Person extends Record<string, unknown> {
  person: string;
  role: 'asm' | 'executive';
  asm_id: number | null;
  via_bo_asm: { new: number; gps: number };
  region: string;
  base_incentive: number | null;
  distributors: DistRow[];
  score_pct: number;
  payout_pct: number;
  incentive: number | null;
}
interface Tracker {
  month: string;
  as_of: string;
  people: Person[];
  totals: { new: number; gps: number; kyc: number };
  uncredited: { new: number; gps: number; kyc: number };
  slabs: { from: number; payout: number }[];
}
interface RetailerRow {
  retailer_id: number;
  retailer: string;
  phone: string | null;
  city: string;
  state: string | null;
  td_distributor: string | null;
  bo_distributor: string | null;
  bo_asm: string | null;
  tier: string;
  first_order: string;
  first_order_date: string;
  first_order_value: number;
  kyc_on: string | null;
  counts_for: string[];
  credited_to: string;
}

const KPI_COLS: { k: Kpi; label: string; weight: string }[] = [
  { k: 'td', label: 'TD sales', weight: '50%' },
  { k: 'new', label: 'New (BO to TD)', weight: '20%' },
  { k: 'gps', label: 'BO G/P/S', weight: '20%' },
  { k: 'kyc', label: 'KYC conversion', weight: '10%' },
];
const TIER_OPTS = ['Platinum', 'Gold', 'Silver', 'Green', 'Yellow', 'Untiered'].map((t) => ({ value: t, label: t })).concat([{ value: 'None', label: 'Not in BlueOrigin' }]);
const LIST_KPIS = [
  { value: 'new', label: 'New (BO to TD)' },
  { value: 'gps', label: 'BO G/P/S' },
  { value: 'kyc', label: 'KYC conversion' },
] as const;
type ListKpi = (typeof LIST_KPIS)[number]['value'];

const n1 = (v: number) => (Number.isInteger(v) ? num(v) : v.toFixed(1));
const tone = (v: number | null) => (v === null ? 'brand' : v >= 100 ? 'good' : v >= 75 ? 'warn' : 'bad') as 'brand' | 'good' | 'warn' | 'bad';

/**
 * The team's incentive sheet, computed from TD data: per person TD sales, new retailers, new BO Gold/Platinum/Silver
 * retailers and KYC conversions against the sheet's targets, overall score, payout % and incentive - plus the
 * retailers behind every count (filter by KPI, BO tier, person; export).
 */
export function IncentiveTracker({ month }: { month?: string }) {
  const [person, setPerson] = useState<string | null>(null);
  const [kpi, setKpi] = useState<ListKpi>('new');
  const [tiers, setTiers] = useState<string[]>([]);
  const q = useQuery({
    queryKey: ['incentives', month],
    queryFn: () => get<Tracker>('/masters/incentives/', { month }),
    enabled: !!month,
    staleTime: 60_000,
  });
  const people = q.data?.people ?? [];
  const sel = people.find((p) => `${p.role}:${p.person}` === person) ?? null;
  const distIds = sel ? sel.distributors.map((d) => d.distributor_id).join(',') : undefined;
  const asmId = sel?.asm_id ?? undefined;
  const list = useQuery({
    queryKey: ['incentive-retailers', month, kpi, tiers.join(','), distIds, asmId],
    queryFn: () => get<{ rows: RetailerRow[] }>('/masters/incentives/retailers/', { month, kpi, tier: tiers.join(',') || undefined, distributor: distIds, asm: asmId }),
    enabled: !!month && !!q.data?.people.length,
    staleTime: 60_000,
  });
  const byTier = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of list.data?.rows ?? []) c[r.tier] = (c[r.tier] ?? 0) + 1;
    return Object.entries(c).sort((a, b) => b[1] - a[1]);
  }, [list.data]);

  if (!month || (!q.isLoading && !people.length)) return null;

  return (
    <Card
      className="mt-4"
      title={`Incentive tracker · ${monthLabel(month)}`}
      subtitle="Targets from the incentive sheet. New = retailers already buying offline in BlueOrigin who placed their first-ever TD order in the month, credited to their BlueOrigin distributor (or BlueOrigin ASM); BO G/P/S = the Gold/Platinum/Silver ones among them; KYC conversion = any first TD order whose KYC was done before the month. Shared distributors are split by each person's target."
    >
      {q.isLoading || !q.data ? (
        <div className="m-4 h-48 animate-pulse rounded-md bg-sunken" />
      ) : (
        <>
          <div className="overflow-x-auto px-4">
            <table className="w-full min-w-[980px] text-sm tabular">
              <thead>
                <tr className="border-b border-line text-xs text-muted">
                  <th className="py-2 pr-2 text-left font-medium">Person</th>
                  {KPI_COLS.map((c) => (
                    <th key={c.k} className="px-2 py-2 text-right font-medium">
                      {c.label} <span className="font-normal">· {c.weight}</span>
                    </th>
                  ))}
                  <th className="px-2 py-2 text-left font-medium">Overall score</th>
                  <th className="px-2 py-2 text-right font-medium">Payout</th>
                  <th className="py-2 pl-2 text-right font-medium">Incentive</th>
                </tr>
              </thead>
              <tbody>
                {people.map((p) => {
                  const key = `${p.role}:${p.person}`;
                  const active = key === person;
                  return (
                    <tr
                      key={key}
                      className={`cursor-pointer border-t border-line/60 align-top hover:bg-sunken/60 ${active ? 'bg-sunken' : ''}`}
                      onClick={() => setPerson(active ? null : key)}
                      title="Show this person's retailers below"
                    >
                      <td className="py-2 pr-2">
                        <div className="font-medium text-ink">{p.person}</div>
                        <div className="text-xs text-muted">
                          {p.role === 'asm' ? 'ASM' : 'Executive'} · {p.distributors.map((d) => d.distributor).join(', ')}
                          {p.distributors.some((d) => d.shared) && ' (shared)'}
                        </div>
                      </td>
                      {KPI_COLS.map(({ k }) => {
                        const t = p[`${k}_target`] as number;
                        const a = p[`${k}_actual`] as number;
                        const pc = p[`${k}_pct`] as number | null;
                        return (
                          <td key={k} className="px-2 py-2 text-right">
                            {t ? (
                              <>
                                <div className="text-ink">{k === 'td' ? `${inr(a)} / ${inr(t)}` : `${n1(a)} / ${num(t)}`}</div>
                                <div className={`text-xs ${pc !== null && pc >= 100 ? 'text-good' : 'text-muted'}`}>
                                  {pct(pc, 0)}
                                  {(k === 'new' || k === 'gps') && p.via_bo_asm[k] > 0 && ` · ${p.via_bo_asm[k]} via BO ASM`}
                                </div>
                              </>
                            ) : (
                              <span className="text-xs text-muted">No target</span>
                            )}
                          </td>
                        );
                      })}
                      <td className="px-2 py-2">
                        <div className="flex items-center gap-2">
                          <div className="w-20">
                            <Meter value={Math.min(p.score_pct, 150)} max={150} tone={tone(p.score_pct)} />
                          </div>
                          <span className="w-12 text-right">{pct(p.score_pct, 1)}</span>
                        </div>
                      </td>
                      <td className="px-2 py-2 text-right">
                        {p.payout_pct ? <Badge tone="good">{p.payout_pct}%</Badge> : <span className="text-xs text-muted">0%</span>}
                      </td>
                      <td className="py-2 pl-2 text-right">
                        {p.incentive !== null ? inr(p.incentive, { compact: false }) : <span className="text-xs text-muted" title="Fill 'Base Incentive (₹)' in the sheet">No base set</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-muted">
              Overall score = TD % × 50% + New % × 20% + BO G/P/S % × 20% + KYC % × 10%. Payout: below 75% → 0%,
              75–90% → 90%, 90–100% → 100%, 100–150% → 200%, 150%+ → 300% of the base incentive. Sales up to {date(q.data.as_of)}.
              {q.data.uncredited.new + q.data.uncredited.kyc > 0 &&
                ` Not credited to anyone (no one in the sheet for their distributor): ${q.data.uncredited.new} BO conversions, ${q.data.uncredited.kyc} KYC conversions.`}
            </p>
          </div>

          <div className="mt-6 border-t border-line px-4 pt-4">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="mr-auto text-sm font-semibold text-ink">
                Retailers behind the counts{sel ? ` · ${sel.person}` : ''}
                {sel && (
                  <button className="ml-2 text-xs font-normal text-ink2 hover:text-ink" onClick={() => setPerson(null)}>
                    Show everyone
                  </button>
                )}
              </h3>
              <Segmented value={kpi} onChange={setKpi} options={LIST_KPIS.map((x) => ({ value: x.value, label: x.label }))} />
              <MultiSelect label="BO Tier" options={TIER_OPTS} value={tiers} onChange={setTiers} width="w-40" />
            </div>
            {byTier.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5 text-xs text-ink2">
                {byTier.map(([t, c]) => (
                  <span key={t} className="chip">
                    {t}: {c}
                  </span>
                ))}
              </div>
            )}
            <div className="mt-2 pb-4">
              <DataTable
                rows={list.data?.rows}
                loading={list.isLoading}
                fetching={list.isFetching}
                error={list.error}
                onRetry={() => list.refetch()}
                rowKey={(r) => r.retailer_id}
                exportName={`incentive_${kpi}_retailers_${month}`}
                emptyTitle="No retailers for this selection"
                pageSize={15}
                dense
                columns={[
                  { key: 'retailer', header: 'Retailer', render: (r) => <div><div className="text-ink">{r.retailer}</div><div className="text-xs text-muted">{[r.city, r.state].filter(Boolean).join(', ')}</div></div>, value: (r) => r.retailer },
                  { key: 'phone', header: 'Phone' },
                  { key: 'tier', header: 'BO tier' },
                  { key: 'bo_distributor', header: 'BO distributor', render: (r) => r.bo_distributor ?? '–' },
                  { key: 'bo_asm', header: 'BO ASM', render: (r) => r.bo_asm ?? '–' },
                  { key: 'td_distributor', header: 'TD distributor (1st order)' },
                  { key: 'credited_to', header: 'Credited to' },
                  { key: 'first_order_date', header: 'First order', render: (r) => `${date(r.first_order_date)} · #${r.first_order}`, value: (r) => r.first_order_date },
                  { key: 'first_order_value', header: 'Order value', align: 'right', render: (r) => inr(r.first_order_value), value: (r) => r.first_order_value },
                  { key: 'kyc_on', header: 'KYC on', render: (r) => date(r.kyc_on) },
                  { key: 'counts_for', header: 'Counts for', render: (r) => r.counts_for.join(', '), value: (r) => r.counts_for.join(', ') },
                ]}
              />
            </div>
          </div>
        </>
      )}
    </Card>
  );
}
