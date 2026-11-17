import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAnalytics } from '@/api/hooks';
import type { Funnel as FunnelData } from '@/api/types';
import { cartesian, funnel } from '@/charts/builders';
import { useChartTokens } from '@/charts/EChart';
import { ChartCard } from '@/components/ChartCard';
import { DataTable } from '@/components/DataTable';
import { MiniStat } from '@/components/KpiTile';
import { PageHeader } from '@/components/PageHeader';
import { Card, ErrorState, Meter } from '@/components/ui';
import { linkWithFilters } from '@/lib/filters';
import { asPct, monthLabel, num, pct, titleCase, monthTick } from '@/lib/format';

export default function Funnel() {
  const q = useAnalytics<FunnelData>('/funnel/');
  const t = useChartTokens();
  const [sp] = useSearchParams();
  const d = q.data?.data;
  const dim = q.isFetching && q.isPlaceholderData;

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
              { name: 'KYC approved (% of sign-ups)', type: 'line', data: cohorts.map((m) => m.kyc_rate), endLabel: true, color: t.series[0] },
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
      <PageHeader title="Retailer Funnel" subtitle="Sign-up → KYC → first order → repeat" meta={q.data?.meta} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        <MiniStat label="Never ordered" value={num(d?.never_ordered.total)} sub="KYC approved, zero orders" to={linkWithFilters('/retailers', sp, { segment: 'never_ordered' })} />
        {d && d.never_ordered.warm_available === false ? (
          <>
            <MiniStat label="· Warm (ledger match)" value="–" sub="BlueOrigin ledger not loaded yet" />
            <MiniStat label="· Cold" value="–" sub="Needs the ledger match" />
          </>
        ) : (
          <>
            <MiniStat label="· Warm (ledger match)" value={num(d?.never_ordered.warm)} sub="Existing BlueOrigin buyers" to={linkWithFilters('/retailers', sp, { segment: 'never_ordered', warm: 'true' })} />
            <MiniStat label="· Cold" value={num(d?.never_ordered.cold)} to={linkWithFilters('/retailers', sp, { segment: 'never_ordered', warm: 'false' })} />
          </>
        )}
        <MiniStat label="· Flagged" value={num(d?.never_ordered.flagged)} sub="Data issues to fix" tone={d?.never_ordered.flagged ? 'warn' : undefined} />
        <MiniStat label="Inactive 30+ days" value={num(d?.inactivity.d30)} to={linkWithFilters('/retailers', sp, { segment: 'inactive_30' })} />
        <MiniStat label="Inactive 60+ days" value={num(d?.inactivity.d60)} to={linkWithFilters('/retailers', sp, { segment: 'inactive_60' })} />
        <MiniStat label="Inactive 90+ days" value={num(d?.inactivity.d90)} tone={d?.inactivity.d90 ? 'bad' : undefined} to={linkWithFilters('/retailers', sp, { segment: 'inactive_90' })} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ChartCard
          className="xl:col-span-2"
          title="Retailer funnel"
          subtitle="Share of top stage · hover for stage-to-stage conversion"
          option={funnelOpt}
          loading={q.isLoading}
          height={300}
          table={d ? { columns: ['Stage', 'Retailers', '% of sign-ups'], rows: d.stages.map((s) => [s.label, num(s.count), pct((s.count / (d.stages[0]?.count || 1)) * 100)]) } : undefined}
        />
        <Card title="KYC status" subtitle={`${num(kycTotal)} applications`}>
          <ul className="space-y-3">
            {(d?.kyc_status ?? []).map((k) => (
              <li key={k.status}>
                <div className="flex justify-between text-xs">
                  <span className="text-ink2">{titleCase(k.status)}</span>
                  <span className="font-semibold tabular">
                    {num(k.count)} <span className="font-normal text-muted">· {pct(kycTotal ? (k.count / kycTotal) * 100 : null, 0)}</span>
                  </span>
                </div>
                <div className="mt-1">
                  <Meter value={kycTotal ? (k.count / kycTotal) * 100 : 0} tone={k.status === 'approved' ? 'good' : k.status === 'rejected' ? 'bad' : 'warn'} />
                </div>
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
          sub={d?.kyc_penetration ? `${num(d.kyc_penetration.ever_ordered)} of ${num(d.kyc_penetration.kyc_approved)} KYC-verified` : undefined}
        />
        <MiniStat
          label={`KYC base ordering (${d?.kyc_penetration?.period_label ?? 'period'})`}
          value={pct(d?.kyc_penetration?.active_pct)}
          sub={d?.kyc_penetration ? `${num(d.kyc_penetration.active)} KYC-verified retailers ordered` : undefined}
        />
        <MiniStat
          label="KYC → first order"
          value={pct(d?.kyc_conversion?.rate)}
          sub={d?.kyc_conversion ? `${num(d.kyc_conversion.converted)} of ${num(d.kyc_conversion.kyc_approved)} KYC-approved` : undefined}
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
        />
        <MiniStat
          label="Repeat purchase rate"
          value={pct(repeatRate)}
          sub={firstN ? `${num(repeatN)} of ${num(firstN)} first-time buyers ordered again` : undefined}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard
          title="Sign-up → KYC → first order conversion"
          subtitle="By month of sign-up (customer created date) · status as of today · the latest months are still maturing: those retailers have had less time to order"
          option={convOpt}
          loading={q.isLoading}
          empty={!cohorts.length}
          table={{
            columns: ['Sign-up month', 'Signed up', 'KYC approved', 'KYC %', 'First order', 'Order % of KYC'],
            rows: cohorts.map((m) => [monthLabel(m.month), num(m.signed_up), num(m.kyc_approved), pct(m.kyc_rate), num(m.first_order), pct(m.order_rate)]),
          }}
        />
        <ChartCard
          title="Retailer acquisition"
          subtitle={`New ordering retailers per month · current month to date${lastCum !== undefined ? ` · ${num(lastCum)} cumulative` : ''}`}
          option={acqOpt}
          loading={q.isLoading}
          table={d ? { columns: ['Month', 'New retailers', 'Cumulative'], rows: d.acquisition_monthly.map((m) => [monthLabel(m.month), num(m.new_retailers), num(m.cumulative)]) } : undefined}
        />
      </div>

      <Card title="Adoption by state" subtitle="Share of KYC-approved retailers who have ever ordered" className="mt-4">
        <DataTable
          rows={d?.by_state}
          loading={q.isLoading}
          rowKey={(r) => r.state}
          exportName="funnel_by_state"
          initialSort={{ key: 'kyc_approved', dir: 'desc' }}
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
    </div>
  );
}
