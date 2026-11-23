import { useMemo, useState } from 'react';
import { useAnalytics } from '@/api/hooks';
import type { Funnel as FunnelData } from '@/api/types';
import { cartesian, funnel } from '@/charts/builders';
import { useChartTokens } from '@/charts/EChart';
import { ChartCard } from '@/components/ChartCard';
import { DataTable } from '@/components/DataTable';
import { MiniStat } from '@/components/KpiTile';
import { PageHeader } from '@/components/PageHeader';
import { RetailersDrill, type RetailersDrillSpec } from '@/components/RetailersDrill';
import { Card, ErrorState, Meter } from '@/components/ui';
import { useFilters } from '@/lib/filters';
import { ACTION_HINT, SEGMENT_TABS } from '@/lib/lifecycle';
import { asPct, monthLabel, num, pct, titleCase, monthTick } from '@/lib/format';

const FROM = 'Retailer Funnel';
const KYC_LINE = 'KYC approved (% of sign-ups)';

export default function Funnel() {
  const q = useAnalytics<FunnelData>('/funnel/');
  const { filters } = useFilters();
  const segment = filters.segment ?? '';
  const t = useChartTokens();
  const d = q.data?.data;
  const dim = q.isFetching && q.isPlaceholderData;
  const periodLabel = q.data?.meta?.period?.label ?? 'the period';
  // every number, bar and row on this page opens the retailers behind it
  const [drill, setDrill] = useState<RetailersDrillSpec | null>(null);
  const open = (title: string, params: Record<string, string>, subtitle?: string) => setDrill({ title, params, subtitle });

  const funnelOpt = useMemo(() => (d?.stages?.length ? funnel(t, d.stages) : null), [d, t]);
  // both series are percentages -> one shared % axis (no dual axis); counts are in the table view
  const cohorts = useMemo(() => {
    const rows = d?.signup_cohorts ?? [];
    const first = rows.findIndex((r) => r.signed_up > 0);
    return first < 0 ? [] : rows.slice(first);
  }, [d]);
  const convOpt = useMemo(
    () =>
      cohorts.length
        ? cartesian(t, {
            x: cohorts.map((m) => monthLabel(m.month)),
            format: 'pct',
            series: [
              { name: KYC_LINE, type: 'line', data: cohorts.map((m) => m.kyc_rate), endLabel: true, color: t.series[0] },
              { name: 'First order (% of KYC-approved)', type: 'line', data: cohorts.map((m) => m.order_rate), endLabel: true, color: t.series[1] },
            ],
          })
        : null,
    [cohorts, t],
  );
  const acqOpt = useMemo(
    () =>
      d?.acquisition_monthly?.length
        ? cartesian(t, {
            x: d.acquisition_monthly.map((m) => monthTick(m.month, q.data?.meta?.period?.to)),
            format: 'num',
            series: [{ name: 'New retailers (first order)', data: d.acquisition_monthly.map((m) => m.new_retailers) }],
            legend: false,
          })
        : null,
    [d, t],
  );
  const lastCum = d?.acquisition_monthly?.[d.acquisition_monthly.length - 1]?.cumulative;
  const kycTotal = d?.kyc_status?.reduce((s, x) => s + x.count, 0) ?? 0;
  // repeat purchase rate = retailers with 2+ orders / retailers with a first order
  const firstN = d?.stages?.find((s) => s.key === 'first_order')?.count ?? 0;
  const repeatN = d?.stages?.find((s) => s.key === 'repeat_order')?.count ?? 0;
  const repeatRate = firstN ? (repeatN / firstN) * 100 : null;

  if (q.error && !q.data)
    return (
      <div>
        <PageHeader title="Retailer Funnel" />
        <Card>
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        </Card>
      </div>
    );

  return (
    <div className={dim ? 'opacity-70 transition-opacity' : ''}>
      <PageHeader title="Retailer Funnel" subtitle="Sign-up → KYC → first order → repeat · click any number, bar or row to see its retailers" meta={q.data?.meta} />

      <div className="mb-3">
        {segment && (
          <p className="rounded-md bg-sunken px-3 py-2 text-xs text-ink2">
            <span className="font-semibold text-ink">{SEGMENT_TABS.find((x) => x.value === segment)?.label ?? segment}:</span>{' '}
            {ACTION_HINT[segment] ?? 'RFM segment chosen on the Retailers page.'} Every number on this page counts only these retailers.
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        <MiniStat label="Never ordered" value={num(d?.never_ordered.total)} sub="Signed up in the period, KYC approved, no order yet" onClick={() => open('Never ordered', { stage: 'never_ordered' }, `Signed up (KYC) in ${periodLabel}, KYC approved, no order by the end of the period`)} />
        {d && d.never_ordered.warm_available === false ? (
          <>
            <MiniStat label="· Warm (ledger match)" value="–" sub="BlueOrigin ledger not loaded yet" />
            <MiniStat label="· Cold" value="–" sub="Needs the ledger match" />
          </>
        ) : (
          <>
            <MiniStat label="· Warm (ledger match)" value={num(d?.never_ordered.warm)} sub="Existing BlueOrigin buyers" onClick={() => open('Never ordered · warm', { stage: 'never_ordered', warm: 'true' }, 'Existing BlueOrigin buyers who have not ordered on the app')} />
            <MiniStat label="· Cold" value={num(d?.never_ordered.cold)} onClick={() => open('Never ordered · cold', { stage: 'never_ordered', warm: 'false' }, 'Not found in the BlueOrigin ledger')} />
          </>
        )}
        <MiniStat label="· Flagged" value={num(d?.never_ordered.flagged)} sub="Data issues to fix" tone={d?.never_ordered.flagged ? 'warn' : undefined} onClick={() => open('Never ordered · flagged', { stage: 'never_flagged' }, 'No distributor or state mapped')} />
        <MiniStat label="Inactive 30+ days" value={num(d?.inactivity.d30)} onClick={() => open('Inactive 30–59 days', { stage: 'inactive_30' }, 'Days since the last order, counted from the end of the period')} />
        <MiniStat label="Inactive 60+ days" value={num(d?.inactivity.d60)} onClick={() => open('Inactive 60–89 days', { stage: 'inactive_60' }, 'Days since the last order, counted from the end of the period')} />
        <MiniStat label="Inactive 90+ days" value={num(d?.inactivity.d90)} tone={d?.inactivity.d90 ? 'bad' : undefined} onClick={() => open('Inactive 90+ days', { stage: 'inactive_90' }, 'Days since the last order, counted from the end of the period')} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ChartCard
          className="xl:col-span-2"
          title="Retailer funnel"
          subtitle="Share of top stage · hover for stage-to-stage conversion · click a stage for its retailers"
          option={funnelOpt}
          loading={q.isLoading}
          height={300}
          onClick={(p) => {
            const s = d?.stages[p.dataIndex];
            if (s) open(s.label, { stage: s.key }, `${num(s.count)} retailers`);
          }}
          table={d ? { columns: ['Stage', 'Retailers', '% of sign-ups'], rows: d.stages.map((s) => [s.label, num(s.count), pct((s.count / (d.stages[0]?.count || 1)) * 100)]) } : undefined}
        />
        <Card title="KYC status" subtitle={`${num(kycTotal)} applications · click a status for its retailers`}>
          <ul className="space-y-1">
            {(d?.kyc_status ?? []).map((k) => (
              <li key={k.status}>
                <button
                  type="button"
                  disabled={!k.count}
                  onClick={() => open(`KYC ${k.status}`, { stage: `kyc_${k.status}` })}
                  className="block w-full rounded-md px-1 py-1.5 text-left enabled:hover:bg-sunken/60 disabled:cursor-default"
                >
                  <div className="flex justify-between text-xs">
                    <span className="text-ink2">{titleCase(k.status)}</span>
                    <span className="font-semibold tabular">
                      {num(k.count)} <span className="font-normal text-muted">· {pct(kycTotal ? (k.count / kycTotal) * 100 : null, 0)}</span>
                    </span>
                  </div>
                  <div className="mt-1">
                    <Meter value={kycTotal ? (k.count / kycTotal) * 100 : 0} tone={k.status === 'approved' ? 'good' : k.status === 'rejected' ? 'bad' : 'warn'} />
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      {/* KYC → first order. The source has no KYC approval date, so timing runs from sign-up (created date). */}
      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <MiniStat
          label="KYC base ever ordered"
          value={pct(d?.kyc_penetration?.ever_pct)}
          sub={d?.kyc_penetration ? `${num(d.kyc_penetration.ever_ordered)} of ${num(d.kyc_penetration.kyc_approved)} KYC-approved` : undefined}
          onClick={() => open('KYC-approved, ever ordered', { stage: 'kyc_ever_ordered' })}
        />
        <MiniStat
          label={`KYC base ordering (${d?.kyc_penetration?.period_label ?? 'period'})`}
          value={pct(d?.kyc_penetration?.active_pct)}
          sub={d?.kyc_penetration ? `${num(d.kyc_penetration.active)} KYC-approved retailers ordered` : undefined}
          onClick={() => open(`KYC-approved, ordered in ${periodLabel}`, { stage: 'kyc_active' })}
        />
        <MiniStat
          label="KYC → first order"
          value={pct(d?.kyc_conversion?.rate)}
          sub={d?.kyc_conversion ? `${num(d.kyc_conversion.converted)} of ${num(d.kyc_conversion.kyc_approved)} KYC-approved` : undefined}
          onClick={() => open('KYC-approved, placed a first order', { stage: 'kyc_ever_ordered' })}
        />
        <MiniStat
          label="Median sign-up → first order"
          value={d?.kyc_conversion?.median_days == null ? '–' : `${num(d.kyc_conversion.median_days)} days`}
          sub="From the created date (no KYC approval date)"
        />
        <MiniStat
          label="First order within 30 days"
          value={pct(d?.kyc_conversion?.within_30d_pct)}
          sub={d?.kyc_conversion ? `${num(d.kyc_conversion.within_30d)} retailers` : undefined}
          onClick={() => open('First order within 30 days of sign-up', { stage: 'first_order_30d' })}
        />
        <MiniStat
          label="Repeat purchase rate"
          value={pct(repeatRate)}
          sub={firstN ? `${num(repeatN)} of ${num(firstN)} first-time buyers ordered again` : undefined}
          onClick={() => open('Placed a repeat order', { stage: 'repeat_order' })}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard
          title="Sign-up → KYC → first order conversion"
          subtitle="By month of sign-up (customer created date) · status as of today · the latest months are still maturing: those retailers have had less time to order · click a point for its retailers"
          option={convOpt}
          loading={q.isLoading}
          empty={!cohorts.length}
          onClick={(p) => {
            const m = cohorts[p.dataIndex];
            if (!m) return;
            const kyc = p.seriesName === KYC_LINE;
            open(
              `${monthLabel(m.month)} sign-ups · ${kyc ? 'KYC approved' : 'placed a first order'}`,
              { signup_month: m.month, stage: kyc ? 'kyc_approved' : 'kyc_ever_ordered' },
              kyc ? `${num(m.kyc_approved)} of ${num(m.signed_up)} sign-ups` : `${num(m.first_order)} of ${num(m.kyc_approved)} KYC-approved`,
            );
          }}
          table={{
            columns: ['Sign-up month', 'Signed up', 'KYC approved', 'KYC %', 'First order', 'Order % of KYC'],
            rows: cohorts.map((m) => [monthLabel(m.month), num(m.signed_up), num(m.kyc_approved), pct(m.kyc_rate), num(m.first_order), pct(m.order_rate)]),
          }}
        />
        <ChartCard
          title="Retailer acquisition"
          subtitle={`New ordering retailers per month · current month to date${lastCum !== undefined ? ` · ${num(lastCum)} cumulative` : ''} · click a bar for its retailers`}
          option={acqOpt}
          loading={q.isLoading}
          onClick={(p) => {
            const m = d?.acquisition_monthly[p.dataIndex];
            if (m?.new_retailers) open(`First order in ${monthLabel(m.month)}`, { first_order_month: m.month }, `${num(m.new_retailers)} new ordering retailers`);
          }}
          table={d ? { columns: ['Month', 'New retailers', 'Cumulative'], rows: d.acquisition_monthly.map((m) => [monthLabel(m.month), num(m.new_retailers), num(m.cumulative)]) } : undefined}
        />
      </div>

      <Card title="Adoption by state" subtitle="Share of KYC-approved retailers who have ever ordered · click a state for its retailers" className="mt-4">
        <DataTable
          rows={d?.by_state}
          loading={q.isLoading}
          rowKey={(r) => r.state}
          exportName="funnel_by_state"
          initialSort={{ key: 'kyc_approved', dir: 'desc' }}
          onRowClick={(r) =>
            open(`${r.state} · KYC approved`, r.state_id == null ? { stage: 'kyc_approved', state_none: '1' } : { stage: 'kyc_approved', state: String(r.state_id) }, `${num(r.ever_ordered)} of ${num(r.kyc_approved)} have ordered`)
          }
          columns={[
            { key: 'state', header: 'State' },
            { key: 'kyc_approved', header: 'KYC approved', align: 'right', render: (r) => num(r.kyc_approved) },
            { key: 'ever_ordered', header: 'Ever ordered', align: 'right', render: (r) => num(r.ever_ordered) },
            { key: 'active', header: 'Active in period', align: 'right', render: (r) => num(r.active) },
            {
              key: 'adoption_pct',
              header: 'Adoption',
              align: 'right',
              render: (r) => (
                <div className="flex items-center justify-end gap-2">
                  <div className="w-24">
                    <Meter value={asPct(r.adoption_pct)} />
                  </div>
                  <span className="w-12">{pct(asPct(r.adoption_pct))}</span>
                </div>
              ),
            },
          ]}
        />
      </Card>

      <RetailersDrill spec={drill} onClose={() => setDrill(null)} fromLabel={FROM} />
    </div>
  );
}
