import { useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { get } from '@/lib/api';
import { useAuth } from '@/auth/AuthContext';
import { IconEdit } from './Icons';
import { IncentiveSheetEditor } from './IncentiveSheetEditor';
import { AchievedEdit } from './AchievedEdit';
import { date, inr, monthLabel, num, pct } from '@/lib/format';
import { DataTable } from './DataTable';
import { MultiSelect } from './MultiSelect';
import { Badge, Card, Drawer } from './ui';

type Kpi = 'td' | 'new' | 'gps' | 'kyc';
interface Row {
  id: number;
  month: string;
  region: string;
  state: string;
  distributor_id: number;
  distributor: string;
  role: 'ASM' | 'Executive';
  employee: string;
  vacant: boolean;
  asm_id: number | null;
  shared_with: string[];
  td_target: number | null;
  td_actual: number;
  td_pct: number | null;
  new_target: number | null;
  new_actual: number;
  new_pct: number | null;
  new_via_bo_asm?: number;
  gps_target: number | null;
  gps_actual: number;
  gps_pct: number | null;
  gps_via_bo_asm?: number;
  kyc_target: number | null;
  kyc_actual: number;
  kyc_pct: number | null;
  td_factor: number;
  new_factor: number;
  gps_factor: number;
  kyc_factor: number;
  td_payable: number;
  new_payable: number;
  gps_payable: number;
  kyc_payable: number;
  payout_pct: number;
  td_edited?: boolean;
  new_edited?: boolean;
  gps_edited?: boolean;
  kyc_edited?: boolean;
  td_calculated?: number;
  new_calculated?: number;
  gps_calculated?: number;
  kyc_calculated?: number;
  edited_by?: string | null;
  eligible: number | null;
  td_amount: number | null;
  new_amount: number | null;
  gps_amount: number | null;
  kyc_amount: number | null;
  payment: number | null;
}
interface Sheet {
  requested: string;
  month: string | null;
  as_of?: string;
  fallback?: boolean;
  rows: Row[];
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
interface Drill {
  row: Row;
  kpi: Exclude<Kpi, 'td'>;
}

const KPI_NAME: Record<Exclude<Kpi, 'td'>, string> = { new: 'New retailers (BlueOrigin → TD)', gps: 'BO Gold / Platinum / Silver', kyc: 'KYC converted' };
const TIER_OPTS = ['Platinum', 'Gold', 'Silver', 'Green', 'Yellow', 'Untiered'].map((t) => ({ value: t, label: t })).concat([{ value: 'None', label: 'Not in BlueOrigin' }]);
const PARTS: [Kpi, string, number][] = [['td', 'TD', 50], ['new', 'New Retailer', 20], ['gps', 'BO G/P/S', 20], ['kyc', 'KYC', 10]];
const payoutTitle = (r: Row) =>
  PARTS.map(
    ([k, name, w]) =>
      `${name}: ${r[`${k}_pct`] === null ? 'no target' : pct(r[`${k}_pct`] as number, 1)} → factor ${r[`${k}_factor`].toFixed(2)} × ${w}% = ${r[`${k}_payable`].toFixed(1)}%`,
  ).join('\n') + `\nPayout = ${r.payout_pct.toFixed(1)}% of the eligible incentive`;
const factorCell = (r: Row, k: Kpi) =>
  r[`${k}_pct`] === null ? (
    <span className="text-muted">–</span>
  ) : (
    <span className={r[`${k}_factor`] ? (r[`${k}_factor`] >= 1 ? 'font-semibold text-good' : 'text-ink') : 'text-muted'}>{r[`${k}_factor`].toFixed(2)}</span>
  );
const n1 = (v: number) => (Number.isInteger(v) ? num(v) : v.toFixed(1));
const achieved = (v: number | null) => (v === null ? '–' : <span className={v >= 100 ? 'font-semibold text-good' : undefined}>{pct(v, 1)}</span>);

/**
 * The team's sheet "TD_ASM_Executive_Incentive_Tracker", same rows and columns, with every Actual / Achieved
 * column computed from data (base incentive and the incentive amount are decided outside the dashboard).
 */
export function IncentiveSheet({ month, actions }: { month?: string; actions?: ReactNode }) {
  const [drill, setDrill] = useState<Drill | null>(null);
  const [editing, setEditing] = useState(false);
  const { can } = useAuth();
  const canEdit = can('manage_targets');
  const q = useQuery({
    queryKey: ['incentive-sheet', month],
    queryFn: () => get<Sheet>('/masters/incentives/sheet/', { month }),
    enabled: !!month,
    staleTime: 60_000,
  });
  const d = q.data;
  const shown = d?.month ?? null;

  const count = (r: Row, k: Exclude<Kpi, 'td'>) => {
    const a = r[`${k}_actual`];
    const via = k === 'new' ? r.new_via_bo_asm : k === 'gps' ? r.gps_via_bo_asm : undefined;
    const shownValue = !a ? (
      <span className="text-muted">0</span>
    ) : (
      <button
        type="button"
        className="font-medium text-ink underline decoration-dotted underline-offset-4 hover:text-brand"
        title={`Click to see the retailers found in the data${via ? ` · ${via} credited through the BlueOrigin ASM` : ''}`}
        onClick={() => setDrill({ row: r, kpi: k })}
      >
        {n1(a)}
      </button>
    );
    return edit(r, k, shownValue);
  };
  const edit = (r: Row, k: Kpi, shownValue: ReactNode) => (
    <AchievedEdit
      id={r.id}
      kpi={k}
      value={r[`${k}_actual`]}
      calculated={r[`${k}_calculated`]}
      edited={r[`${k}_edited`]}
      editedBy={r.edited_by}
      canEdit={canEdit}
      money={k === 'td'}
    >
      {shownValue}
    </AchievedEdit>
  );
  const named = (d?.rows ?? []).filter((r) => !r.vacant);
  const paid = named.filter((r) => r.payout_pct > 0);
  const full = named.filter((r) => r.payout_pct >= 100).length;
  const totalPayment = named.reduce((a, r) => a + (r.payment ?? 0), 0);
  const target = (v: number | null, money = false) => (v === null ? '' : money ? inr(v, { compact: false }) : num(v));

  return (
    <Card
      className="mt-4"
      title="TD_ASM_Executive_Incentive_Tracker"
      subtitle={
        shown
          ? `${monthLabel(shown)} · targets from the incentive sheet, achievement calculated from data${d?.as_of ? ` (sales up to ${date(d.as_of)})` : ''}. New Retailer = BlueOrigin retailers (offline first) placing their first-ever TD order; BO G/P/S = the Gold/Platinum/Silver ones; KYC Converted = first TD order with KYC done before the month. Shared distributors are split by each row's target. Click an achieved number for its retailers.`
          : 'Targets from the incentive sheet, achievement calculated from data'
      }
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {actions}
          {canEdit && (
            <button className="btn-primary btn-sm" onClick={() => setEditing(true)} title="Edit this sheet's rows and targets, month by month">
              <IconEdit size={13} /> Edit incentive sheet
            </button>
          )}
        </div>
      }
    >
      {canEdit && <IncentiveSheetEditor open={editing} onClose={() => setEditing(false)} initialMonth={month ?? shown ?? ''} />}
      {d?.fallback && shown && (
        <p className="mb-3 rounded-md bg-sunken px-3 py-2 text-xs text-ink2">
          The incentive sheet has no rows for {monthLabel(d.requested)}, so this shows {monthLabel(shown)}, the latest month in the sheet.
        </p>
      )}
      {shown && d && named.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <span className="text-ink">
            <span className="font-semibold">{paid.length}</span> of {named.length} people earn an incentive
          </span>
          {full > 0 && <span className="text-ink2">{full} get the full 100%</span>}
          <span className="text-ink2">{named.length - paid.length} get nothing (every KPI below 70%)</span>
          <span className="ml-auto text-ink">
            Total payment <span className="font-semibold">{inr(totalPayment, { compact: false })}</span>
          </span>
        </div>
      )}
      {!q.isLoading && !shown ? (
        <p className="py-6 text-sm text-ink2">The incentive sheet has no months yet.</p>
      ) : (
        <DataTable
          rows={d?.rows}
          rowClassName={(r) => (r.payout_pct > 0 && !r.vacant ? 'bg-good/5' : undefined)}
          loading={q.isLoading}
          fetching={q.isFetching}
          error={q.error}
          onRetry={() => q.refetch()}
          rowKey={(r) => r.id}
          exportName={`TD_ASM_Executive_Incentive_Tracker_${shown ?? ''}`}
          pageSize={50}
          dense
          columns={[
            { key: 'month', header: 'Month' },
            { key: 'region', header: 'Region' },
            { key: 'state', header: 'State' },
            { key: 'distributor', header: 'Distributor' },
            { key: 'role', header: 'Role' },
            {
              key: 'employee',
              header: 'Employee Name',
              render: (r) => (r.vacant ? <Badge tone="warn">Vacant</Badge> : <span className="font-medium text-ink">{r.employee}</span>),
              value: (r) => r.employee,
            },
            { key: 'td_target', header: 'TD Target (₹)', align: 'right', render: (r) => target(r.td_target, true) },
            { key: 'td_actual', header: 'TD Actual (₹)', align: 'right', render: (r) => edit(r, 'td', inr(r.td_actual, { compact: false })) },
            { key: 'td_pct', header: 'TD Target Achievement %', align: 'right', render: (r) => achieved(r.td_pct) },
            { key: 'td_factor', header: 'TD Payout Factor', align: 'right', render: (r) => factorCell(r, 'td'), value: (r) => (r.td_pct === null ? null : r.td_factor) },
            { key: 'new_target', header: 'New Retailer Target', align: 'right', render: (r) => target(r.new_target) },
            { key: 'new_actual', header: 'New Retailer Achieved', align: 'right', render: (r) => count(r, 'new') },
            { key: 'new_pct', header: 'New Retailer Achievement %', align: 'right', render: (r) => achieved(r.new_pct) },
            { key: 'new_factor', header: 'New Retailer Payout Factor', align: 'right', render: (r) => factorCell(r, 'new'), value: (r) => (r.new_pct === null ? null : r.new_factor) },
            { key: 'gps_target', header: 'BO G/P/S Target', align: 'right', render: (r) => target(r.gps_target) },
            { key: 'gps_actual', header: 'BO G/P/S Achieved', align: 'right', render: (r) => count(r, 'gps') },
            { key: 'gps_pct', header: 'BO G/P/S Achievement %', align: 'right', render: (r) => achieved(r.gps_pct) },
            { key: 'gps_factor', header: 'BO G/P/S Payout Factor', align: 'right', render: (r) => factorCell(r, 'gps'), value: (r) => (r.gps_pct === null ? null : r.gps_factor) },
            { key: 'kyc_target', header: 'KYC Conversion Target', align: 'right', render: (r) => target(r.kyc_target) },
            { key: 'kyc_actual', header: 'KYC Converted', align: 'right', render: (r) => count(r, 'kyc') },
            { key: 'kyc_pct', header: 'KYC Conversion %', align: 'right', render: (r) => achieved(r.kyc_pct) },
            { key: 'kyc_factor', header: 'KYC Payout Factor', align: 'right', render: (r) => factorCell(r, 'kyc'), value: (r) => (r.kyc_pct === null ? null : r.kyc_factor) },
            {
              key: 'payout_pct',
              header: 'Incentive Payout % (of eligible)',
              align: 'right',
              render: (r) =>
                r.vacant ? (
                  <span className="text-muted">–</span>
                ) : (
                  <span className="cursor-help" title={payoutTitle(r)}>
                    {r.payout_pct ? <Badge tone="good">{pct(r.payout_pct, 1)}</Badge> : <span className="text-ink2 underline decoration-dotted underline-offset-4">0%</span>}
                  </span>
                ),
              value: (r) => r.payout_pct,
            },
            {
              key: 'payment',
              header: 'Incentive Payment (₹)',
              align: 'right',
              render: (r) =>
                r.payment === null ? (
                  <span className="text-muted">–</span>
                ) : (
                  <span className={r.payment ? 'font-semibold text-good' : 'text-ink2'} title={`${inr(r.eligible ?? 0, { compact: false })} eligible × ${pct(r.payout_pct, 1)}`}>
                    {inr(r.payment, { compact: false })}
                  </span>
                ),
            },
          ]}
        />
      )}
      <p className="mt-2 text-2xs text-muted">
        As per the TD Incentive Policy each KPI is paid on its own. Payout factor by achievement: below 70% → 0, 70% to below 90% → 0.90, 90% and above → 1.00
        (a KPI with no target pays 0). The eligible incentive is split TD 50%, New Retailer 20%, BO G/P/S 20%, KYC 10%; payout % = sum of weight × factor. Example:
        TD 71%, New 99%, G/P/S 89%, KYC 100% → 45 + 20 + 18 + 10 = 93% (₹4,650 of ₹5,000). Hover a payout to see how it adds up. Achieved values can be typed over with the pencil (marked with a dot; Reset goes back to the calculated value) and the payout follows them. Incentive Payment = eligible incentive (₹5,000 as in the policy, unless set for the person in Edit incentive sheet) × Incentive Payout %.
      </p>
      {shown && <RetailerDrawer month={shown} drill={drill} onClose={() => setDrill(null)} />}
    </Card>
  );
}

function RetailerDrawer({ month, drill, onClose }: { month: string; drill: Drill | null; onClose: () => void }) {
  const [tiers, setTiers] = useState<string[]>([]);
  const r = drill?.row;
  const list = useQuery({
    queryKey: ['incentive-sheet-retailers', month, drill?.kpi, r?.distributor_id, r?.asm_id, tiers.join(',')],
    queryFn: () =>
      get<{ rows: RetailerRow[] }>('/masters/incentives/retailers/', {
        month,
        kpi: drill?.kpi,
        distributor: r?.distributor_id,
        asm: r?.asm_id ?? undefined,
        tier: tiers.join(',') || undefined,
      }),
    enabled: !!drill,
  });
  return (
    <Drawer open={!!drill} onClose={onClose} width={1100} title={drill && r ? `${KPI_NAME[drill.kpi]} · ${r.employee} · ${r.distributor}` : ''}>
      {drill && r && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <p className="mr-auto text-xs text-ink2">
              {list.data ? `${num(list.data.rows.length)} retailers` : 'Loading…'} for {r.distributor}
              {r.shared_with.length ? ` (shared with ${r.shared_with.join(', ')}: ${r.employee} is credited their target's share)` : ''}
            </p>
            <MultiSelect label="BO Tier" options={TIER_OPTS} value={tiers} onChange={setTiers} width="w-40" />
          </div>
          <DataTable
            rows={list.data?.rows}
            loading={list.isLoading}
            fetching={list.isFetching}
            error={list.error}
            onRetry={() => list.refetch()}
            rowKey={(x) => x.retailer_id}
            exportName={`${drill.kpi}_retailers_${r.employee}_${month}`.toLowerCase().replace(/[^a-z0-9]+/g, '_')}
            emptyTitle="No retailers for this selection"
            pageSize={20}
            dense
            columns={[
              { key: 'retailer', header: 'Retailer', render: (x) => <div><div className="text-ink">{x.retailer}</div><div className="text-xs text-muted">{[x.city, x.state].filter(Boolean).join(', ')}</div></div>, value: (x) => x.retailer },
              { key: 'phone', header: 'Phone' },
              { key: 'tier', header: 'BO tier' },
              { key: 'bo_distributor', header: 'BO distributor', render: (x) => x.bo_distributor ?? '–' },
              { key: 'bo_asm', header: 'BO ASM', render: (x) => x.bo_asm ?? '–' },
              { key: 'td_distributor', header: 'TD distributor (1st order)' },
              { key: 'first_order_date', header: 'First TD order', render: (x) => `${date(x.first_order_date)} · #${x.first_order}`, value: (x) => x.first_order_date },
              { key: 'first_order_value', header: 'Order value', align: 'right', render: (x) => inr(x.first_order_value), value: (x) => x.first_order_value },
              { key: 'kyc_on', header: 'KYC on', render: (x) => date(x.kyc_on) },
              { key: 'credited_to', header: 'Credited to' },
            ]}
          />
        </>
      )}
    </Drawer>
  );
}
