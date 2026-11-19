import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useAnalytics, usePagedList } from '@/api/hooks';
import type { OrderDetail, OrderFlow, OrderRow, OrdersSummary } from '@/api/types';
import { cartesian } from '@/charts/builders';
import { useChartTokens } from '@/charts/EChart';
import { STATUS } from '@/charts/palette';
import { ChartCard } from '@/components/ChartCard';
import { DataTable } from '@/components/DataTable';
import { OrdersDrill, type OrdersDrillSpec } from '@/components/OrdersDrill';
import { MiniStat } from '@/components/KpiTile';
import { DailyFlowCard, DelaySection } from '@/components/OrderFlow';
import { MODE_LABELS } from '@/lib/format';
import { PageHeader } from '@/components/PageHeader';
import { Badge, Card, Drawer, ErrorState, LoadingBlock, Segmented, Stat, StatusBadge, cx } from '@/components/ui';
import { IconSearch } from '@/components/Icons';
import { getEnvelope } from '@/lib/api';
import { describePreset, linkWithFilters, parseFilters, useFilters } from '@/lib/filters';
import { dateTime, hours, inr, monthLabel, num, pct, asPct, titleCase } from '@/lib/format';

const STATUS_ORDER = ['received', 'confirmed', 'shipped', 'delivered', 'cancelled'];

// ------------------------------------------------------------------ order drawer
export function OrderDrawer({ id, onClose }: { id: string | number | null; onClose: () => void }) {
  const q = useQuery({
    queryKey: ['order', id],
    queryFn: () => getEnvelope<OrderDetail>(`/orders/${id}/`),
    enabled: id !== null,
  });
  const o = q.data?.data;
  return (
    <Drawer open={id !== null} onClose={onClose} title={o ? `Order ${o.display_id}` : 'Order'} width={600}>
      {q.isLoading ? (
        <LoadingBlock />
      ) : q.error || !o ? (
        <ErrorState error={q.error ?? new Error('Not found')} onRetry={() => q.refetch()} />
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Stat label="Status" value={<StatusBadge status={o.status} />} />
            <Stat label="Payment" value={<StatusBadge status={o.payment_status} />} sub={o.payment_mode ?? undefined} />
            <Stat label="Value" value={inr(o.value, { compact: false })} sub={`${num(o.units)} units`} />
            <Stat label="Retailer" value={o.retailer} />
            <Stat label="Distributor" value={o.distributor} sub={o.state} />
            <Stat label="Placed" value={dateTime(o.placed_at)} />
            <Stat label="AWB" value={o.awb ?? '–'} />
            <Stat label="Dispatch time" value={hours(o.dispatch_hours)} />
            <Stat label="Split order" value={o.is_split ? <Badge tone="brand">Split cart</Badge> : 'No'} />
          </div>

          <section>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Timeline</h4>
            {o.timeline?.length ? (
              <ol className="relative ml-2 border-l border-line">
                {o.timeline.map((e, i) => (
                  <li key={i} className="mb-3 ml-4">
                    <span className={cx('absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full ring-2 ring-surface', i === o.timeline.length - 1 ? 'bg-accent' : 'bg-brand')} />
                    <div className="text-sm font-medium">{titleCase(e.label ?? e.event ?? e.status ?? 'Event')}</div>
                    <div className="text-xs text-muted">
                      {dateTime(e.at)}
                      {e.actor ? ` · ${e.actor}` : ''}
                    </div>
                    {e.note && <div className="mt-0.5 text-xs text-ink2">{e.note}</div>}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-xs text-muted">No timeline events.</p>
            )}
          </section>

          <section>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Lines</h4>
            <div className="overflow-auto rounded-md border border-line">
              <table className="w-full text-xs">
                <thead className="bg-sunken">
                  <tr>
                    <th className="th">SKU / style</th>
                    <th className="th">Size</th>
                    <th className="th text-right">Qty</th>
                    <th className="th text-right">Value</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {(o.lines ?? []).map((l, i) => (
                    <tr key={i} className="border-t border-line">
                      <td className="px-3 py-1.5">
                        <div className="font-medium">{l.name ?? l.style ?? l.sku}</div>
                        <div className="text-muted">{l.sku ?? l.style}</div>
                      </td>
                      <td className="px-3 py-1.5">{l.size ?? '–'}</td>
                      <td className="px-3 py-1.5 text-right">{num(l.qty ?? l.quantity ?? null)}</td>
                      <td className="px-3 py-1.5 text-right">{inr(l.value ?? (l.price ?? 0) * (l.qty ?? l.quantity ?? 0), { compact: false })}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">PayU transactions</h4>
            {o.payments?.length ? (
              <div className="overflow-auto rounded-md border border-line">
                <table className="w-full text-xs">
                  <thead className="bg-sunken">
                    <tr>
                      <th className="th">Txn id</th>
                      <th className="th">Mode</th>
                      <th className="th">Status</th>
                      <th className="th text-right">Amount</th>
                      <th className="th">Time</th>
                    </tr>
                  </thead>
                  <tbody className="tabular">
                    {o.payments.map((p) => (
                      <tr key={p.txn_id} className="border-t border-line">
                        <td className="px-3 py-1.5 font-mono text-2xs">{p.txn_id}</td>
                        <td className="px-3 py-1.5">{p.mode ?? '–'}</td>
                        <td className="px-3 py-1.5">
                          <StatusBadge status={p.status} />
                        </td>
                        <td className="px-3 py-1.5 text-right">{inr(p.amount, { compact: false })}</td>
                        <td className="px-3 py-1.5">{dateTime(p.at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-xs text-muted">No PayU transaction linked to this order.</p>
            )}
          </section>
        </div>
      )}
    </Drawer>
  );
}

// ------------------------------------------------------------------ page

export default function Orders() {
  const q = useAnalytics<OrdersSummary>('/orders/summary/');
  const t = useChartTokens();
  const { apiParams, searchParams, update } = useFilters();
  const [sp] = useSearchParams();
  const d = q.data?.data;
  const orderStatus = sp.get('order_status') ?? '';
  const selectedStatuses = orderStatus ? orderStatus.split(',') : [];
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [page, setPage] = useState(1);
  const [ordering, setOrdering] = useState('-placed_at');
  const [openId, setOpenId] = useState<string | number | null>(null);

  useEffect(() => {
    const h = setTimeout(() => setDebounced(search), 350);
    return () => clearTimeout(h);
  }, [search]);
  useEffect(() => setPage(1), [debounced, apiParams]);

  const listParams = { page, page_size: 50, ordering, search: debounced || undefined };
  const list = usePagedList<OrderRow>('/orders/', listParams);

  const statusRows = useMemo(() => [...(d?.status_counts ?? [])].sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status)), [d]);
  // the status chart lists every status; the headline counts only the selected ones
  const scopedRows = statusRows.filter((r) => !selectedStatuses.length || selectedStatuses.includes(r.status));
  const totalOrders = scopedRows.reduce((s, r) => s + r.count, 0);

  const statusOpt = useMemo(
    () =>
      statusRows.length
        ? cartesian(t, {
            x: statusRows.map((r) => titleCase(r.status)),
            horizontal: true,
            legend: false,
            showBarLabels: true,
            series: [{ name: 'Orders', data: statusRows.map((r) => r.count), colors: statusRows.map((r, i) => (selectedStatuses.length && !selectedStatuses.includes(r.status) ? t.axis : r.status === 'cancelled' ? STATUS.critical : t.ordinal[Math.min(i + 1, t.ordinal.length - 1)])) }],
          })
        : null,
    [statusRows, t, orderStatus],
  );

  const [drill, setDrill] = useState<OrdersDrillSpec | null>(null);
  const periodLabel = describePreset(parseFilters(sp));
  const [groupBy, setGroupBy] = useState('distributor');
  const flow = useAnalytics<OrderFlow>('/orders/flow/', { group_by: groupBy });

  const [tatView, setTatView] = useState<'tat' | 'rate'>('tat');
  const rateOpt = useMemo(
    () =>
      d?.tat?.trend?.length
        ? cartesian(t, { x: d.tat.trend.map((m) => monthLabel(m.month)), format: 'pct', legend: false, yMax: 100, series: [{ name: 'Dispatch rate', type: 'line', area: true, endLabel: true, data: d.tat.trend.map((m) => m.dispatch_pct ?? null) }] })
        : null,
    [d, t],
  );
  const tatOpt = useMemo(
    () =>
      d?.tat?.trend?.length
        ? cartesian(t, {
            x: d.tat.trend.map((m) => monthLabel(m.month)),
            format: 'hours',
            series: [
              { name: 'Order → dispatch (median)', type: 'line', data: d.tat.trend.map((m) => m.dispatch_h), endLabel: true },
              { name: 'Order → delivery (median)', type: 'line', data: d.tat.trend.map((m) => m.delivery_h), endLabel: true },
            ],
          })
        : null,
    [d, t],
  );

  const pay = d?.payment ?? null;
  const payAttempts = pay ? pay.success + pay.failed + pay.pending : 0;
  const successRate = pay && payAttempts ? (pay.success / payAttempts) * 100 : null;
  // payment mode / platform come from the orders themselves — no gateway or settlement data needed
  const modeRows = useMemo(() => (d?.order_payment_modes ?? []).map((m) => ({ ...m, label: MODE_LABELS[m.key] ?? m.key })), [d]);
  const platformRows = useMemo(() => (d?.order_platforms ?? []).map((m) => ({ ...m, label: titleCase(m.key) })), [d]);
  const mixOpt = (rows: { label: string; value: number }[]) =>
    rows.length ? cartesian(t, { x: rows.map((m) => m.label), horizontal: true, format: 'inr', legend: false, showBarLabels: true, series: [{ name: 'Order value', data: rows.map((m) => m.value) }] }) : null;
  const modeOpt = useMemo(() => mixOpt(modeRows), [modeRows, t]); // eslint-disable-line react-hooks/exhaustive-deps
  const platformOpt = useMemo(() => mixOpt(platformRows), [platformRows, t]); // eslint-disable-line react-hooks/exhaustive-deps
  const crmOn = !!d?.crm?.connected;

  const crmOpt = useMemo(() => {
    const c = [...(d?.crm?.by_type ?? [])].sort((a, b) => b.count - a.count);
    if (!c.length) return null;
    return cartesian(t, { x: c.map((x) => x.type), horizontal: true, legend: false, showBarLabels: true, series: [{ name: 'Issues raised', data: c.map((x) => x.count) }] });
  }, [d, t]);

  return (
    <div>
      <PageHeader title="Orders & Fulfilment" subtitle="Status, daily flow, delays, turnaround, payment modes and ordering platform" meta={q.data?.meta} />

      {q.error && !q.data ? (
        <Card>
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
            <MiniStat label="Orders" value={num(totalOrders)} sub={`${inr(scopedRows.reduce((s, r) => s + r.value, 0))} value`} />
            <MiniStat label="Cancellation rate" value={pct(asPct(d?.cancellation_rate))} tone={(asPct(d?.cancellation_rate) ?? 0) > 5 ? 'bad' : undefined} />
            <MiniStat label="SLA breaches" value={num(d?.sla_breaches)} tone={d?.sla_breaches ? 'bad' : 'good'} sub={`Not dispatched within SLA · placed in the last ${d?.open_window_days ?? 30} days`} />
            <MiniStat label="Median order → dispatch" value={hours(d?.tat.order_to_dispatch_median_h)} />
            <MiniStat label="Median order → delivery" value={hours(d?.tat.order_to_delivery_median_h)} />
            <MiniStat
              label="Split carts"
              value={num(d?.split_orders.split_carts)}
              sub={d?.split_orders.total_carts ? `${pct((d.split_orders.split_carts / d.split_orders.total_carts) * 100)} of ${num(d.split_orders.total_carts)} carts` : undefined}
            />
            {crmOn && <MiniStat label="Open CRM tickets" value={num(d?.crm.open)} tone={d?.crm.open ? 'warn' : undefined} />}
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
            <ChartCard
              title="Order status"
              subtitle="Click a bar to list its retailers and orders"
              option={statusOpt}
              loading={q.isLoading}
              height={240}
              onClick={(p) => {
                const r = statusRows[p.dataIndex];
                if (!r) return;
                const on = selectedStatuses.includes(r.status);
                setDrill({
                  title: `${titleCase(r.status)} orders`,
                  subtitle: `${num(r.count)} orders · ${inr(r.value)} · placed in ${periodLabel}`,
                  params: { order_status: r.status },
                  actions: (
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => {
                        const next = on ? selectedStatuses.filter((x) => x !== r.status) : [...selectedStatuses, r.status];
                        update({ order_status: next.length ? next : undefined });
                        setDrill(null);
                      }}
                    >
                      {on ? 'Remove page filter' : 'Filter whole page'}
                    </button>
                  ),
                });
              }}
              table={{ columns: ['Status', 'Orders', 'Value'], rows: statusRows.map((r) => [titleCase(r.status), num(r.count), inr(r.value)]) }}
            />
            <DailyFlowCard d={flow.data?.data} loading={flow.isLoading} periodLabel={periodLabel} onDrill={setDrill} />
            <ChartCard
              title={tatView === 'tat' ? 'Turnaround time trend' : 'Dispatch rate trend'}
              subtitle={tatView === 'tat' ? 'Monthly median, hours · click a month to list its orders' : 'Share of non-cancelled orders dispatched, by order month · click a month'}
              option={tatView === 'tat' ? tatOpt : rateOpt}
              loading={q.isLoading}
              height={240}
              actions={<Segmented value={tatView} onChange={setTatView} size="xs" options={[{ value: 'tat', label: 'TAT' }, { value: 'rate', label: 'Dispatch %' }]} />}
              clickAxis
              onClick={(p) => {
                const m = d?.tat.trend[p.dataIndex];
                if (!m) return;
                setDrill({
                  title: `Orders placed in ${monthLabel(m.month)}`,
                  subtitle: `Cancelled excluded · median dispatch ${hours(m.dispatch_h)}, delivery ${hours(m.delivery_h)}, dispatched ${pct(m.dispatch_pct)}`,
                  params: { month: m.month.slice(0, 7) },
                });
              }}
              table={d ? { columns: ['Month', 'Dispatch (h)', 'Delivery (h)', 'Dispatch rate'], rows: d.tat.trend.map((m) => [monthLabel(m.month), hours(m.dispatch_h), hours(m.delivery_h), pct(m.dispatch_pct)]) } : undefined}
            />
          </div>

          <DelaySection d={flow.data?.data} loading={flow.isLoading} periodLabel={periodLabel} groupBy={groupBy} onGroupBy={setGroupBy} onDrill={setDrill} />

          <div className={cx('mt-4 grid grid-cols-1 gap-4', [true, true, !!pay, crmOn].filter(Boolean).length > 2 ? 'xl:grid-cols-3' : 'xl:grid-cols-2')}>
            <ChartCard
              title="Payment mode mix"
              subtitle="Value of paid orders by payment mode · click a bar to list them"
              option={modeOpt}
              loading={q.isLoading}
              height={200}
              onClick={(p) => {
                const m = modeRows[p.dataIndex];
                if (!m) return;
                setDrill({ title: `Paid by ${m.label}`, subtitle: `${num(m.orders)} paid orders · ${inr(m.value)} · ${periodLabel}`, params: { paid: '1', mode: m.key } });
              }}
              table={{ columns: ['Mode', 'Orders', 'Value', 'Share'], rows: modeRows.map((m) => [m.label, num(m.orders), inr(m.value), pct(m.share)]) }}
            />
            <ChartCard
              title="Ordering platform"
              subtitle="Value of paid orders by app / web · click a bar to list them"
              option={platformOpt}
              loading={q.isLoading}
              height={200}
              onClick={(p) => {
                const m = platformRows[p.dataIndex];
                if (!m || m.key === 'Unknown') return;
                setDrill({ title: `Ordered on ${m.label}`, subtitle: `${num(m.orders)} paid orders · ${inr(m.value)} · ${periodLabel}`, params: { paid: '1', platform: m.key } });
              }}
              table={{ columns: ['Platform', 'Orders', 'Value', 'Share'], rows: platformRows.map((m) => [m.label, num(m.orders), inr(m.value), pct(m.share)]) }}
            />
            {/* PayU gateway view: only once the PayU integration is connected (settlement is out of scope) */}
            {pay && (
              <Card title="Payments (PayU)" subtitle="Payment attempts on orders in the period">
                <div className="grid grid-cols-2 gap-3">
                  <MiniStat label="Success rate" value={pct(successRate)} sub={`${num(pay.success)} of ${num(payAttempts)} attempts`} tone={successRate !== null && successRate < 85 ? 'bad' : undefined} />
                  <MiniStat label="Failed value" value={inr(pay.failed_value)} sub={`${num(pay.failed)} failed · ${num(pay.pending)} pending`} tone={pay.failed ? 'bad' : undefined} />
                  <div className="col-span-2">
                    <MiniStat
                      label="Paid but no order"
                      value={num(pay.paid_no_order)}
                      sub="PayU success with no matching order — open Data Health →"
                      tone={pay.paid_no_order ? 'bad' : 'good'}
                      to={linkWithFilters('/data-health', searchParams)}
                    />
                  </div>
                </div>
              </Card>
            )}
            {crmOn && (
              <ChartCard
                title="CRM issues"
                subtitle={`${num(d?.crm.opened_in_period ?? 0)} raised in this period, ${num(d?.crm.open)} still open · refunds ${inr(d?.crm.refund_in_period ?? 0, { compact: true })} · from the B2B Order Tracker CRM sheet`}
                option={crmOpt}
                loading={q.isLoading}
                height={Math.max(200, (d?.crm.by_type.length ?? 4) * 30 + 40)}
                table={d ? { columns: ['Issue type', 'Raised', 'Still open'], rows: d.crm.by_type.map((c) => [c.type, num(c.count), num(c.open ?? 0)]) } : undefined}
              />
            )}
          </div>
        </>
      )}

      <Card title="Orders" className="mt-4">
        <DataTable
          rows={list.data?.results}
          loading={list.isLoading}
          fetching={list.isFetching}
          error={list.error}
          onRetry={() => list.refetch()}
          rowKey={(r) => r.id}
          onRowClick={(r) => setOpenId(r.id)}
          exportName="orders"
          exportPath="/orders/"
          exportParams={{ ...apiParams, search: debounced || undefined }}
          server={{ count: list.data?.count ?? 0, page, pageSize: 50, onPage: setPage, ordering, onOrdering: setOrdering }}
          emptyTitle="No orders match"
          toolbar={
            <>
              <div className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1">
                <IconSearch size={13} className="text-muted" />
                <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Order id, retailer, AWB…" className="w-48 bg-transparent text-xs outline-none placeholder:text-muted" aria-label="Search orders" />
              </div>
            </>
          }
          columns={[
            { key: 'display_id', header: 'Order', render: (r) => <span className="font-medium">{r.display_id}</span> },
            { key: 'placed_at', header: 'Placed', render: (r) => dateTime(r.placed_at) },
            { key: 'retailer', header: 'Retailer' },
            { key: 'distributor', header: 'Distributor' },
            { key: 'state', header: 'State' },
            { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
            { key: 'payment_status', header: 'Payment', render: (r) => <StatusBadge status={r.payment_status} /> },
            { key: 'payment_mode', header: 'Mode', render: (r) => r.payment_mode ?? '–' },
            { key: 'units', header: 'Units', align: 'right', render: (r) => num(r.units) },
            { key: 'value', header: 'Value', align: 'right', render: (r) => inr(r.value, { compact: false }) },
            { key: 'dispatch_hours', header: 'Dispatch', align: 'right', render: (r) => hours(r.dispatch_hours) },
            { key: 'awb', header: 'AWB', render: (r) => r.awb ?? '–' },
            { key: 'is_split', header: 'Split', align: 'center', render: (r) => (r.is_split ? <Badge tone="brand">Split</Badge> : ''), value: (r) => (r.is_split ? 'Yes' : 'No') },
          ]}
        />
        <p className="mt-2 text-2xs text-muted">
          Split carts count once in totals and once per distributor in distributor views. <Link to="/admin/metrics" className="underline">Definitions</Link>
        </p>
      </Card>
      <OrdersDrill spec={drill} onClose={() => setDrill(null)} onOpenOrder={setOpenId} />
      <OrderDrawer id={openId} onClose={() => setOpenId(null)} />
    </div>
  );
}
