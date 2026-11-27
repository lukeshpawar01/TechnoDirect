import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useAnalytics } from '@/api/hooks';
import type { DataHealth as DH } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { DataTable } from '@/components/DataTable';
import { ManualMappings } from '@/components/ManualMappings';
import { SourceCheck } from '@/components/SourceCheck';
import { PageHeader } from '@/components/PageHeader';
import { Badge, Card, ErrorState, InlineError, LoadingBlock, Spinner, StatusBadge } from '@/components/ui';
import { IconRefresh } from '@/components/Icons';
import { errorMessage, post } from '@/lib/api';
import { REFRESH_SCHEDULE, useRefreshAll } from '@/lib/refresh';
import { dateTime, num, relTime, titleCase } from '@/lib/format';

const SOURCE_LABEL: Record<string, string> = {
  supabase: 'TD orders & retailers (Supabase)',
  payu: 'PayU payments',
  sheets_crm: 'CRM tracker (Google Sheets)',
  google_sheets: 'CRM issues (Google Sheet)',
  targets_sheet: 'Monthly targets (incentive sheet)',
  settlement: 'Distributor settlement (Tracker sheet)',
  distributor_sync: 'Stock sync (TechnoD Distributors sheet)',
  blueorigin: 'BlueOrigin sheets',
  channel_konnect: 'Channel Konnect stock',
  clevertap: 'CleverTap events',
};

export default function DataHealth() {
  const { can } = useAuth();
  const q = useAnalytics<DH>('/data-health/', {}, { includeSegment: false });
  const { refresh } = useRefreshAll();
  const d = q.data?.data;
  const [msg, setMsg] = useState<string | null>(null);

  const sync = useMutation({
    // a full refresh runs in the request and takes about 1.5 minutes (BlueOrigin alone ~1): wait up to 15, not the 60 s default
    mutationFn: () => post<{ detail?: string; status?: string }>('/data-health/sync/', { source: 'all' }, { timeout: 900_000 }),
    onSuccess: (r) => {
      setMsg(r?.detail ?? 'Refresh started. New numbers appear once all sources finish (usually a few minutes).');
      setTimeout(() => void refresh(), 5_000);
    },
  });

  const nextAt = q.data?.meta?.next_refresh_at;
  const lastAt = q.data?.meta?.last_refresh_at;

  return (
    <div>
      <PageHeader
        title="Data Health"
        subtitle="Source syncs, data-quality issues and MIS reconciliation"
        meta={q.data?.meta}
        showBasis={false}
        actions={
          can('trigger_sync') ? (
            <button className="btn-primary btn-sm" onClick={() => sync.mutate()} disabled={sync.isPending} title="Run a full refresh of all sources now">
              {sync.isPending ? <Spinner size={12} /> : <IconRefresh size={13} />} Refresh now
            </button>
          ) : undefined
        }
      />

      <Card className="mb-4" bodyClass="py-3">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
          <div>
            <span className="text-muted">Refresh schedule</span>{' '}
            <span className="font-semibold text-ink">{REFRESH_SCHEDULE.map((s) => `${s} IST`).join(' and ')}</span> daily
          </div>
          <div>
            <span className="text-muted">Last refresh</span> <span className="font-medium">{lastAt ? dateTime(lastAt) : '–'}</span>
          </div>
          <div>
            <span className="text-muted">Next refresh</span> <span className="font-medium">{nextAt ? dateTime(nextAt) : '–'}</span>
          </div>
          <div className="text-muted">Dashboard numbers never query source systems directly — they show the last completed refresh.</div>
        </div>
        {msg && <div className="mt-2 text-xs text-good">{msg}</div>}
        {sync.error && <div className="mt-2"><InlineError error={new Error(errorMessage(sync.error))} /></div>}
      </Card>

      {q.isLoading ? (
        <LoadingBlock />
      ) : q.error && !d ? (
        <Card>
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        </Card>
      ) : d ? (
        <>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-5">
            {d.sources.map((s) => (
              <div key={s.source} className="card p-3.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-sm font-semibold">{SOURCE_LABEL[s.source] ?? titleCase(s.source)}</div>
                  <StatusBadge status={s.status} />
                </div>
                <dl className="mt-2 space-y-1 text-xs">
                  {s.last_checked_at ? (
                    <>
                      <div className="flex justify-between"><dt className="text-muted">Last checked</dt><dd title={dateTime(s.last_checked_at)}>{relTime(s.last_checked_at)} · no changes</dd></div>
                      <div className="flex justify-between"><dt className="text-muted">Data loaded</dt><dd title={dateTime(s.last_success_at)}>{dateTime(s.last_success_at)}</dd></div>
                    </>
                  ) : (
                    <div className="flex justify-between"><dt className="text-muted">Last success</dt><dd title={dateTime(s.last_success_at)}>{relTime(s.last_success_at)}</dd></div>
                  )}
                  {s.via && <div className="flex justify-between"><dt className="text-muted">Comes from</dt><dd>{s.via}</dd></div>}
                  <div className="flex justify-between">
                    <dt className="text-muted">{s.last_checked_at ? 'Rows in use' : 'Rows last run'}</dt>
                    <dd>{num(s.last_checked_at ? (s.rows_loaded ?? s.rows_last_run) : s.rows_last_run)}</dd>
                  </div>
                  <div className="flex justify-between"><dt className="text-muted">Next run</dt><dd>{dateTime(s.next_run_at)}</dd></div>
                </dl>
                {s.last_error && <div className="mt-2 line-clamp-3 rounded bg-bad-bg px-2 py-1 text-2xs text-bad" title={s.last_error}>{s.last_error}</div>}
              </div>
            ))}
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Card title="Data-quality issues" subtitle="Open issues detected in the last refresh">
              <DataTable
                rows={d.issues}
                rowKey={(r) => r.code}
                exportName="data_quality_issues"
                initialSort={{ key: 'count', dir: 'desc' }}
                emptyTitle="No data-quality issues"
                emptyHint="All checks passed in the last refresh."
                columns={[
                  { key: 'severity', header: 'Severity', render: (r) => <Badge tone={r.severity === 'high' ? 'bad' : r.severity === 'medium' ? 'warn' : 'neutral'} icon>{r.severity}</Badge> },
                  { key: 'count', header: 'Open', align: 'right', render: (r) => <span className={r.count ? 'font-semibold' : 'text-muted'}>{num(r.count)}</span> },
                  {
                    key: 'label',
                    header: 'Issue',
                    className: 'whitespace-normal',
                    // the code sits under the label: as its own column it pushed Count out of the half-width card
                    render: (r) => (
                      <div>
                        <div className="font-medium">{r.label}</div>
                        <div className="font-mono text-2xs text-muted">{r.code}</div>
                      </div>
                    ),
                  },
                ]}
              />
            </Card>
            <Card title="Reconciliation vs MIS" subtitle="Dashboard value vs reference MIS value · tolerance 1%">
              <DataTable
                rows={d.reconciliation}
                rowKey={(r, i) => `${r.metric}-${r.period}-${i}`}
                exportName="reconciliation"
                emptyTitle="No MIS reference values"
                emptyHint="Add them in Admin → Mappings → MIS reconciliation."
                columns={[
                  { key: 'metric', header: 'Metric', render: (r) => titleCase(r.metric) },
                  { key: 'period', header: 'Period' },
                  { key: 'dashboard_value', header: 'Dashboard', align: 'right', render: (r) => num(r.dashboard_value) },
                  { key: 'mis_value', header: 'MIS', align: 'right', render: (r) => num(r.mis_value) },
                  {
                    key: 'diff_pct',
                    header: 'Diff',
                    align: 'right',
                    render: (r) =>
                      r.diff_pct === null ? '–' : (
                        <Badge tone={Math.abs(r.diff_pct) <= 1 ? 'good' : Math.abs(r.diff_pct) <= 3 ? 'warn' : 'bad'} icon>
                          {r.diff_pct > 0 ? '+' : ''}
                          {r.diff_pct.toFixed(2)}%
                        </Badge>
                      ),
                  },
                ]}
              />
            </Card>
          </div>
          <SourceCheck d={d.source_check} />
        </>
      ) : null}
      <ManualMappings />
    </div>
  );
}
