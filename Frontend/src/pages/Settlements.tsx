import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAnalytics, usePagedList } from '@/api/hooks';
import type { SettlementDistributorRow, SettlementOrderRow, SettlementSummary, SettleStatus } from '@/api/types';
import { cartesian } from '@/charts/builders';
import { EChart, useChartTokens } from '@/charts/EChart';
import { STATUS } from '@/charts/palette';
import { ChartCard } from '@/components/ChartCard';
import { DataTable } from '@/components/DataTable';
import { IconInfo, IconSearch } from '@/components/Icons';
import { MiniStat } from '@/components/KpiTile';
import { PageHeader } from '@/components/PageHeader';
import { SettlementStatement } from '@/components/SettlementStatement';
import { SplitCarts } from '@/components/SplitCarts';
import { Badge, Card, ErrorState, Segmented, cx, type Tone } from '@/components/ui';
import { useFilters } from '@/lib/filters';
import { MODE_LABELS, date, inr, num, sharePct } from '@/lib/format';

const SETTLE: Record<SettleStatus, { label: string; tone: Tone }> = {
  settled: { label: 'Settled', tone: 'good' },
  not_settled: { label: 'Not settled', tone: 'warn' },
  pending: { label: 'Not reviewed', tone: 'neutral' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
};
const PAY: Record<string, { label: string; tone: Tone }> = {
  approved: { label: 'Approved', tone: 'good' },
  not_approved: { label: 'Not approved', tone: 'warn' },
  pending: { label: 'Not reviewed', tone: 'neutral' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
};
const FULFIL: Record<string, string> = { delivered: 'Delivered', in_transit: 'In transit', not_dispatched: 'Not dispatched', cancelled: 'Cancelled' };
type View = 'all' | 'due' | 'overdue' | 'split' | 'issues';

const dash = <span className="text-muted">·</span>;

export default function Settlements() {
  const t = useChartTokens();
  const { update, searchParams } = useFilters();
  const s = useAnalytics<SettlementSummary>('/settlements/summary/');
  const dist = useAnalytics<{ rows: SettlementDistributorRow[]; total: SettlementSummary['kpis'] }>('/settlements/distributors/');
  const d = s.data?.data;
  const k = d?.kpis;
  const sla = d?.sla_days ?? 15;
  const byPayout = searchParams.get('date_basis') === 'payout';

  const [page, setPage] = useState(1);
  const [ordering, setOrdering] = useState('-order_date');
  const [search, setSearch] = useState('');
  const [view, setView] = useState<View>('all');
  const [stmt, setStmt] = useState<number | null>(null);
  const showOrders = (v: View) => {
    setView(v);
    setPage(1);
    document.getElementById('settlement-orders')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  const listParams = { page, page_size: 50, ordering, search: search.trim() || undefined, view: view === 'all' ? undefined : view };
  const list = usePagedList<SettlementOrderRow>('/settlements/orders/', listParams);

  const weeklyOpt = useMemo(() => {
    if (!d?.weekly.length) return null;
    return cartesian(t, {
      x: d.weekly.map((w) => date(w.week, 'DD MMM')),
      format: 'inr',
      legend: true,
      series: [
        { name: 'Settled', stack: 'p', color: t.ordinal[3], data: d.weekly.map((w) => w.settled) },
        { name: 'Delivered, not settled', stack: 'p', color: STATUS.warning, data: d.weekly.map((w) => w.due) },
        { name: 'Not delivered yet', stack: 'p', color: t.deemph, data: d.weekly.map((w) => w.not_yet_due) },
      ],
    });
  }, [d, t]);

  const distRows = dist.data?.data.rows ?? [];
  const topDist = useMemo(() => [...distRows].sort((a, b) => b.payable - a.payable).slice(0, 15), [distRows]);
  const distOpt = useMemo(() => {
    if (!topDist.length) return null;
    return cartesian(t, {
      x: topDist.map((r) => r.distributor),
      horizontal: true,
      format: 'inr',
      legend: true,
      series: [
        { name: 'Settled', stack: 'd', color: t.ordinal[3], data: topDist.map((r) => r.settled) },
        { name: 'Delivered, not settled', stack: 'd', color: STATUS.warning, data: topDist.map((r) => r.due) },
        { name: 'Not delivered yet', stack: 'd', color: t.deemph, data: topDist.map((r) => r.not_yet_due) },
      ],
    });
  }, [topDist, t]);
  const byName = useMemo(() => [...distRows].filter((r) => r.id != null).sort((a, b) => a.distributor.localeCompare(b.distributor)), [distRows]);

  if (s.error && !s.data)
    return (
      <div>
        <PageHeader title="Distributor Settlements" />
        <Card>
          <ErrorState error={s.error} onRetry={() => s.refetch()} />
        </Card>
      </div>
    );

  const maxAge = Math.max(1, ...(d?.ageing.map((a) => a.amount) ?? [1]));

  return (
    <div>
      <PageHeader
        title="Distributor Settlements"
        subtitle="What each distributor is owed for app orders, what has been paid out and when, and what is still open"
        meta={s.data?.meta}
      />

      {d && !d.available && (
        <Card>
          <div className="p-6 text-sm text-ink2">
            No settlement data has been loaded yet. It is imported from the finance team's “Technodirect Order Tracking - Tracker” sheet on the next refresh.
          </div>
        </Card>
      )}

      {d?.available && (
        <div className="mb-4 flex items-start gap-2 rounded-lg border border-line bg-sunken/40 px-3 py-2 text-xs text-ink2">
          <IconInfo size={14} className="mt-0.5 shrink-0 text-muted" />
          <span>
            From the finance tracker: orders {date(d.data.from)} to {date(d.data.until)}, last payout <b className="text-ink">{date(d.data.last_payout)}</b>. The period
            filters the <b className="text-ink">{byPayout ? 'payout date' : 'order date'}</b> (change it under Date basis). Payable = order value − customer refund. Loyalty
            points are not deducted, because TechnoSport carries them. Overdue = delivered more than {sla} days ago and not settled.
          </span>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <MiniStat label="Payable to distributors" value={inr(k?.payable)} sub={k ? `${num(k.orders - k.cancelled_orders)} orders · refunds ${inr(k.refunds)}` : undefined} />
        <MiniStat label="Settled" value={inr(k?.settled)} tone="good" sub={k ? `${sharePct(k.settled_pct)} of payable · ${num(k.settled_orders)} orders` : undefined} />
        <button className="text-left" onClick={() => showOrders('due')} title="Show these orders">
        <MiniStat
          label="Delivered, not settled"
          value={inr(k?.due)}
          tone={k?.due ? 'warn' : undefined}
          sub={k ? `${num(k.due_orders)} orders waiting for payout · view` : undefined}
        />
        </button>
        <button className="text-left" onClick={() => showOrders('overdue')} title="Show these orders">
        <MiniStat
          label={`Overdue (> ${sla} days)`}
          value={inr(k?.overdue)}
          tone={k?.overdue ? 'bad' : 'good'}
          sub={k ? (k.overdue_orders ? `${num(k.overdue_orders)} orders past the usual cycle` : 'Nothing past the usual cycle') : undefined}
        />
        </button>
        <MiniStat label="Not delivered yet" value={inr(k?.not_yet_due)} sub={k ? `${num(k.not_yet_due_orders)} orders in transit / to dispatch` : undefined} />
        <MiniStat
          label="Delivery to payout"
          value={k?.median_days != null ? `${num(k.median_days)} days` : '–'}
          sub={k?.p90_days != null ? `median · 90% within ${num(k.p90_days)} days` : undefined}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-5">
        <ChartCard
          className="xl:col-span-3"
          title="Settlement position by order week"
          subtitle="Payable of the orders placed each week (Monday start), by how far they are through settlement"
          option={weeklyOpt}
          loading={s.isLoading}
          table={
            d
              ? {
                  columns: ['Week of', 'Orders', 'Settled', 'Delivered, not settled', 'Not delivered yet'],
                  rows: d.weekly.map((w) => [date(w.week), num(w.orders), inr(w.settled), inr(w.due), inr(w.not_yet_due)]),
                }
              : undefined
          }
        />
        <Card className="xl:col-span-2" title="Status" subtitle="Settlement status as recorded by finance (payment status is always the same) · click a status to filter">
          {!d?.by_status?.length ? (
            <div className="p-6 text-sm text-muted">{s.isLoading ? 'Loading…' : 'No orders in this selection.'}</div>
          ) : (
          <div className="space-y-4 px-4 pb-4">
            {[
              { title: 'Settlement status', rows: d?.by_status ?? [], map: SETTLE as Record<string, { label: string; tone: Tone }>, key: 'settlement_status' },
            ].map((g) => (
              <table key={g.title} className="w-full text-sm tabular">
                <thead>
                  <tr className="border-b border-line text-xs text-muted">
                    <th className="py-1.5 pr-2 text-left font-medium">{g.title}</th>
                    <th className="px-2 py-1.5 text-right font-medium">Orders</th>
                    <th className="py-1.5 pl-2 text-right font-medium">Payable</th>
                  </tr>
                </thead>
                <tbody>
                  {g.rows.map((r) => (
                    <tr
                      key={r.status}
                      className="cursor-pointer border-t border-line/60 hover:bg-sunken/50"
                      onClick={() => update({ [g.key]: [r.status] })}
                      title={`Filter to ${g.map[r.status]?.label ?? r.label}`}
                    >
                      <td className="py-1.5 pr-2">
                        <Badge tone={g.map[r.status]?.tone ?? 'neutral'}>{g.map[r.status]?.label ?? r.label}</Badge>
                      </td>
                      <td className="px-2 py-1.5 text-right">{num(r.orders)}</td>
                      <td className="whitespace-nowrap py-1.5 pl-2 text-right font-semibold text-ink">{inr(r.status === 'cancelled' ? r.order_value : r.payable)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ))}
            <p className="text-2xs text-muted">Cancelled rows show the order value. Click a status to filter the page to it.</p>
          </div>
          )}
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-5">
        <Card
          className="xl:col-span-3"
          title="Payout batches"
          subtitle={
            byPayout
              ? 'Distributor settlement dates in the period · click one to see its orders'
              : 'Whole payout batches dated in the period (every order paid that day, whatever its order date) · click one to see its orders'
          }
        >
          <DataTable
            rows={d?.payouts}
            loading={s.isLoading}
            rowKey={(r) => r.date}
            exportName="distributor_payouts"
            exportPath="/settlements/summary/"
            exportParams={{ table: 'payouts' }}
            initialSort={{ key: 'date', dir: 'desc' }}
            pageSize={10}
            dense
            onRowClick={(r) => update({ payout_date: [r.date] })}
            columns={[
              { key: 'date', header: 'Settlement date', render: (r) => <span className="whitespace-nowrap font-medium">{date(r.date, 'ddd, DD MMM YYYY')}</span> },
              { key: 'distributors', header: 'Distributors', align: 'right', render: (r) => num(r.distributors) },
              { key: 'orders', header: 'Orders', align: 'right', render: (r) => num(r.orders) },
              { key: 'amount', header: 'Amount paid', align: 'right', render: (r) => <span className="whitespace-nowrap font-semibold">{inr(r.amount)}</span> },
              { key: 'median_days', header: 'Days after delivery', align: 'right', render: (r) => (r.median_days != null ? num(r.median_days) : '–') },
            ]}
          />
        </Card>
        <Card className="xl:col-span-2" title="Waiting for payout" subtitle="Delivered, not settled · by days since delivery">
          <div className="space-y-2.5 px-4 pb-4">
            {(d?.ageing ?? []).map((a, i) => {
              const late = i >= 2;
              return (
                <div key={a.bucket}>
                  <div className="flex items-baseline justify-between text-sm">
                    <span className={cx(late && a.orders ? 'font-medium text-bad' : 'text-ink2')}>{a.bucket}</span>
                    <span className="tabular">
                      <b className="text-ink">{inr(a.amount)}</b> <span className="text-xs text-muted">{num(a.orders)} orders</span>
                    </span>
                  </div>
                  <div className="mt-1 h-2 rounded-full bg-sunken">
                    <div
                      className="h-2 rounded-full"
                      style={{ width: `${(a.amount / maxAge) * 100}%`, background: late ? STATUS.critical : i === 1 ? STATUS.warning : t.ordinal[2] }}
                    />
                  </div>
                </div>
              );
            })}
            {!!d?.issues.length && (
              <div className="mt-3 border-t border-line pt-3">
                <div className="mb-1 text-xs font-medium text-ink2">Tracker rows to check</div>
                <ul className="space-y-0.5 text-xs text-ink2">
                  {d.issues.map((x) => (
                    <li key={x.issue} className="flex justify-between gap-2">
                      <span>{x.issue === 'reassigned' ? 'Paid to a different distributor than the app order' : x.issue[0].toUpperCase() + x.issue.slice(1)}</span>
                      <span className="tabular text-ink">{num(x.orders)}</span>
                    </li>
                  ))}
                </ul>
                <button className="mt-1.5 text-xs text-brand hover:underline dark:text-ink" onClick={() => setView('issues')}>
                  Show these orders
                </button>
              </div>
            )}
          </div>
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-5">
        <Card
          className="xl:col-span-3"
          title="Settled vs remaining by distributor"
          subtitle="The 15 distributors owed the most · click a bar to open that distributor's statement"
          actions={
            <select
              className="rounded-md border border-line bg-surface px-2 py-1 text-xs"
              value=""
              onChange={(e) => e.target.value && setStmt(Number(e.target.value))}
              aria-label="Open a distributor's statement"
            >
              <option value="">Open statement for…</option>
              {byName.map((r) => (
                <option key={r.id} value={r.id!}>
                  {r.distributor}
                </option>
              ))}
            </select>
          }
        >
          <div className="px-2 pb-2">
            {distOpt ? (
              <EChart option={distOpt} height={Math.max(260, topDist.length * 26 + 60)} ariaLabel="Settled vs remaining by distributor" onClick={(e) => topDist[e.dataIndex]?.id && setStmt(topDist[e.dataIndex].id)} />
            ) : (
              <div className="p-6 text-sm text-muted">{dist.isLoading ? 'Loading…' : 'No distributors in this selection.'}</div>
            )}
          </div>
        </Card>
        <Card className="xl:col-span-2" title="Who is waiting longest" subtitle="Distributors with delivered orders not yet settled · click to open">
          <div className="space-y-1 px-2 pb-3">
            {distRows.filter((r) => r.due > 0).sort((a, b) => b.overdue - a.overdue || b.due - a.due).slice(0, 10).map((r) => (
              <button
                key={String(r.id)}
                className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-sunken/60"
                onClick={() => r.id && setStmt(r.id)}
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium text-ink">{r.distributor}</span>
                  <span className="text-2xs text-muted">
                    {num(r.due_orders)} orders · last paid {date(r.last_payout, 'DD MMM')}
                  </span>
                </span>
                <span className="shrink-0 text-right tabular">
                  <span className={cx('block font-semibold', r.overdue ? 'text-bad' : 'text-warn')}>{inr(r.due)}</span>
                  <span className="text-2xs text-muted">{r.overdue ? `${inr(r.overdue)} overdue` : `${sharePct(r.settled_pct)} settled`}</span>
                </span>
              </button>
            ))}
            {!distRows.some((r) => r.due > 0) && <div className="p-4 text-sm text-good">Every delivered order in this selection is settled.</div>}
          </div>
        </Card>
      </div>

      <Card
        className="mt-4"
        title="Split carts (multi-distributor orders)"
        subtitle="One retailer cart fulfilled by two or more distributors because of stock · each part is settled to its own distributor · click a distributor for its statement"
      >
        <div className="px-4 pb-4">
          {d?.split ? <SplitCarts block={d.split} onOpenDistributor={setStmt} /> : <div className="text-sm text-muted">Loading…</div>}
        </div>
      </Card>

      <Card className="mt-4" title="By distributor" subtitle="Settlement statement for the period · biggest open amount first · click a row for the full statement">
        <DataTable
          rows={dist.data?.data.rows}
          loading={dist.isLoading}
          error={dist.error}
          onRetry={() => dist.refetch()}
          rowKey={(r) => String(r.id)}
          exportName="distributor_settlements_by_distributor"
          exportPath="/settlements/distributors/"
          initialSort={{ key: 'due', dir: 'desc' }}
          pageSize={25}
          dense
          onRowClick={(r) => r.id && setStmt(r.id)}
          footer={
            dist.data?.data.total ? (
              <tfoot>
                <tr className="border-t-2 border-line font-semibold text-ink">
                  <td className="px-3 py-2">Total</td>
                  <td className="px-3 py-2 text-right">{num(dist.data.data.total.orders)}</td>
                  <td className="px-3 py-2 text-right">{inr(dist.data.data.total.refunds)}</td>
                  <td className="px-3 py-2 text-right">{inr(dist.data.data.total.payable)}</td>
                  <td className="px-3 py-2 text-right">{inr(dist.data.data.total.settled)}</td>
                  <td className="px-3 py-2 text-right">{inr(dist.data.data.total.due)}</td>
                  <td className="px-3 py-2 text-right">{inr(dist.data.data.total.overdue)}</td>
                  <td className="px-3 py-2 text-right">{inr(dist.data.data.total.not_yet_due)}</td>
                  <td className="px-3 py-2 text-right">{date(dist.data.data.total.last_payout, 'DD MMM')}</td>
                  <td className="px-3 py-2 text-right">{num(dist.data.data.total.median_days)}</td>
                </tr>
              </tfoot>
            ) : undefined
          }
          columns={[
            {
              key: 'distributor',
              header: 'Distributor',
              render: (r) => (
                <div>
                  <div className="font-medium text-ink">{r.distributor}</div>
                  <div className="text-2xs text-muted">{[r.asm ?? 'No ASM', r.state].filter(Boolean).join(' · ')}</div>
                </div>
              ),
            },
            { key: 'orders', header: 'Orders', align: 'right', render: (r) => num(r.orders) },
            { key: 'refunds', header: 'Refunds', align: 'right', render: (r) => (r.refunds ? <span className="whitespace-nowrap">{inr(r.refunds)}</span> : dash) },
            { key: 'payable', header: 'Payable', align: 'right', render: (r) => <span className="whitespace-nowrap">{inr(r.payable)}</span> },
            {
              key: 'settled',
              header: 'Settled',
              align: 'right',
              render: (r) => (
                <span className="whitespace-nowrap">
                  {inr(r.settled)} <span className="text-2xs text-muted">{sharePct(r.settled_pct)}</span>
                </span>
              ),
            },
            {
              key: 'due',
              header: 'Delivered, not settled',
              align: 'right',
              render: (r) =>
                r.due ? (
                  <span className="whitespace-nowrap font-semibold text-warn">
                    {inr(r.due)} <span className="text-2xs font-normal text-muted">{num(r.due_orders)}</span>
                  </span>
                ) : (
                  dash
                ),
            },
            {
              key: 'overdue',
              header: `Over ${sla} days`,
              align: 'right',
              render: (r) => (r.overdue ? <span className="whitespace-nowrap font-semibold text-bad">{inr(r.overdue)}</span> : dash),
            },
            { key: 'not_yet_due', header: 'Not delivered', align: 'right', render: (r) => (r.not_yet_due ? <span className="whitespace-nowrap">{inr(r.not_yet_due)}</span> : dash) },
            { key: 'last_payout', header: 'Last payout', align: 'right', render: (r) => <span className="whitespace-nowrap">{date(r.last_payout, 'DD MMM')}</span> },
            { key: 'median_days', header: 'Days to pay', align: 'right', render: (r) => (r.median_days != null ? num(r.median_days) : '–') },
            {
              key: 'split_orders',
              header: 'Split orders',
              align: 'right',
              render: (r) => (r.split_orders ? <span className="whitespace-nowrap" title={`Owed for split parts: ${inr(r.split_payable)}`}>{num(r.split_orders)}</span> : dash),
            },
          ]}
        />
      </Card>

      <div id="settlement-orders" className="scroll-mt-4" />
      <Card className="mt-4" title="Orders" subtitle="One row per app order in the tracker · days to pay = payout date − delivery date">
        <DataTable
          rows={list.data?.results}
          loading={list.isLoading}
          fetching={list.isFetching}
          error={list.error}
          onRetry={() => list.refetch()}
          rowKey={(r) => r.id}
          exportName="distributor_settlement_orders"
          exportPath="/settlements/orders/"
          exportParams={listParams}
          server={{ count: list.data?.count ?? 0, page, pageSize: 50, onPage: setPage, ordering, onOrdering: setOrdering }}
          dense
          toolbar={
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1">
                <IconSearch size={13} className="text-muted" />
                <input
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value);
                    setPage(1);
                  }}
                  placeholder="Order #, customer, transaction ID…"
                  className="w-56 bg-transparent text-xs outline-none placeholder:text-muted"
                  aria-label="Search settlement orders"
                />
              </div>
              <Segmented
                size="xs"
                value={view}
                onChange={(v) => {
                  setView(v);
                  setPage(1);
                }}
                options={[
                  { value: 'all', label: 'All' },
                  { value: 'due', label: 'Not settled' },
                  { value: 'overdue', label: 'Overdue' },
                  { value: 'split', label: 'Split carts' },
                  { value: 'issues', label: 'To check' },
                ]}
              />
            </div>
          }
          columns={[
            {
              key: 'order_ref',
              sortField: 'order_ref',
              header: 'Order',
              render: (r) => (
                <div>
                  {r.order_id ? (
                    <Link className="font-medium text-brand hover:underline dark:text-ink" to={`/orders/${r.order_id}`} onClick={(e) => e.stopPropagation()}>
                      #{r.order_ref}
                    </Link>
                  ) : (
                    <span className="font-medium">#{r.order_ref}</span>
                  )}
                  <div className="max-w-[14rem] truncate text-2xs text-muted" title={r.customer}>
                    {r.customer}
                  </div>
                </div>
              ),
            },
            { key: 'order_date', header: 'Ordered', render: (r) => <span className="whitespace-nowrap">{date(r.order_date, 'DD MMM YY')}</span> },
            {
              key: 'delivered_date',
              header: 'Delivered',
              render: (r) => (
                <span className="whitespace-nowrap">{r.delivered_date ? date(r.delivered_date, 'DD MMM YY') : <span className="text-muted">{FULFIL[r.fulfilment] ?? r.fulfilment}</span>}</span>
              ),
            },
            {
              key: 'distributor',
              header: 'Distributor',
              render: (r) => (
                <span>
                  {r.distributor_id ? (
                    <button className="text-left hover:text-brand hover:underline dark:hover:text-ink" onClick={(e) => { e.stopPropagation(); setStmt(r.distributor_id); }}>
                      {r.distributor}
                    </button>
                  ) : (
                    r.distributor
                  )}
                  {r.issues.some((x) => x.startsWith('reassigned')) && <span className="ml-1 text-2xs text-warn" title={r.issues.join('\n')}>reassigned</span>}
                  {r.is_split && (
                    <span className="block text-2xs text-muted">
                      <Badge tone="brand">Split</Badge>{' '}
                      {r.split_with.length
                        ? r.split_with.map((p, i) => (
                            <span key={p.order_ref}>
                              {i > 0 && ', '}
                              with {p.distributor ?? '–'} #{p.order_ref}
                            </span>
                          ))
                        : 'other part not in the tracker'}
                    </span>
                  )}
                </span>
              ),
            },
            { key: 'order_value', header: 'Order value', align: 'right', render: (r) => <span className="whitespace-nowrap">{inr(r.order_value)}</span> },
            {
              key: 'customer_refund',
              header: 'Refund',
              align: 'right',
              render: (r) => (r.customer_refund ? <span className="whitespace-nowrap text-ink2">−{inr(r.customer_refund)}</span> : dash),
            },
            { key: 'payable', header: 'Payable', align: 'right', render: (r) => <span className="whitespace-nowrap font-semibold">{inr(r.payable)}</span> },
            { key: 'payment_status', header: 'Payment', sortable: false, render: (r) => <Badge tone={PAY[r.payment_status]?.tone ?? 'neutral'}>{PAY[r.payment_status]?.label ?? r.payment_status}</Badge> },
            {
              key: 'settlement_status',
              header: 'Settlement',
              sortable: false,
              render: (r) =>
                r.overdue ? (
                  <Badge tone="bad" title={`Delivered ${r.days_since_delivery} days ago`}>
                    Overdue · {r.days_since_delivery}d
                  </Badge>
                ) : (
                  <Badge tone={SETTLE[r.settlement_status]?.tone ?? 'neutral'}>{SETTLE[r.settlement_status]?.label ?? r.settlement_status}</Badge>
                ),
            },
            { key: 'settled_on', header: 'Settlement date', render: (r) => <span className="whitespace-nowrap">{r.settled_on ? date(r.settled_on, 'DD MMM YY') : '–'}</span> },
            { key: 'days_to_settle', header: 'Days to pay', align: 'right', sortable: false, render: (r) => (r.days_to_settle != null ? num(r.days_to_settle) : '–') },
            {
              key: 'payment_mode',
              header: 'Mode',
              sortable: false,
              render: (r) => (
                <span className="whitespace-nowrap text-ink2" title={r.transaction_id ? `Txn ${r.transaction_id}` : undefined}>
                  {MODE_LABELS[r.payment_mode] ?? (r.payment_mode || '–')}
                </span>
              ),
            },
            {
              key: 'remark',
              header: 'Remark',
              sortable: false,
              render: (r) => {
                const txt = [r.remark, ...r.issues.filter((x) => !x.startsWith('reassigned'))].filter(Boolean).join(' · ');
                return txt ? (
                  <span className="block max-w-[16rem] truncate text-xs text-ink2" title={txt}>
                    {txt}
                  </span>
                ) : (
                  dash
                );
              },
            },
          ]}
        />
      </Card>
      <SettlementStatement id={stmt} onClose={() => setStmt(null)} onOpenDistributor={setStmt} />
    </div>
  );
}
