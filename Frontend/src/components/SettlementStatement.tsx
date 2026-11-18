import { useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useAnalytics } from '@/api/hooks';
import type { SettlementStatement as Stmt } from '@/api/types';
import { cartesian } from '@/charts/builders';
import { EChart, useChartTokens } from '@/charts/EChart';
import { STATUS } from '@/charts/palette';
import { download } from '@/lib/api';
import { useFilters } from '@/lib/filters';
import { date, inr, monthLabel, num, sharePct } from '@/lib/format';
import { IconDownload } from './Icons';
import { SplitCarts } from './SplitCarts';
import { Badge, Drawer, ErrorState, LoadingBlock, Segmented, cx } from './ui';

/** Distributor settlement statement: how much is owed, how much is paid, what remains, and which orders. */
export function SettlementStatement({ id, onClose, onOpenDistributor }: { id: number | null; onClose: () => void; onOpenDistributor?: (id: number) => void }) {
  const t = useChartTokens();
  const { update, apiParams } = useFilters();
  const q = useAnalytics<Stmt>(`/settlements/distributors/${id ?? 0}/`, {}, { enabled: id != null });
  const s = q.data?.data;
  const b = s?.bridge;
  const k = s?.kpis;
  const [tab, setTab] = useState<'open' | 'payouts' | 'trend' | 'split'>('open');
  const [openFilter, setOpenFilter] = useState<'all' | 'due' | 'not_yet_due' | 'overdue'>('all');

  const trendOpt = useMemo(() => {
    if (!s?.monthly.length) return null;
    return cartesian(t, {
      x: s.monthly.map((m) => monthLabel(m.month)),
      format: 'inr',
      legend: true,
      series: [
        { name: 'Settled', stack: 'm', color: t.ordinal[3], data: s.monthly.map((m) => m.settled) },
        { name: 'Remaining', stack: 'm', color: STATUS.warning, data: s.monthly.map((m) => m.remaining) },
      ],
    });
  }, [s, t]);

  const open = (s?.open_orders ?? []).filter((o) =>
    openFilter === 'all' ? true : openFilter === 'overdue' ? o.overdue : o.state === openFilter,
  );
  const overdueN = s?.open_orders.filter((o) => o.overdue).length ?? 0;
  const pct = (v: number) => (b?.payable ? (v / b.payable) * 100 : 0);

  return (
    <Drawer open={id != null} onClose={onClose} width={780} title={s ? `Settlement statement · ${s.distributor.name}` : 'Settlement statement'}>
      {q.isLoading && <LoadingBlock height={400} />}
      {q.error && !s && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {s && b && k && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="text-xs text-ink2">
              {[s.distributor.asm ? `ASM ${s.distributor.asm}` : 'No ASM', s.distributor.rsm ? `RSM ${s.distributor.rsm}` : null, s.distributor.state].filter(Boolean).join(' · ')}
              <div className="mt-0.5 text-muted">
                Orders {s.basis === 'payout' ? 'paid out' : 'placed'} in the selected period · {num(k.orders)} orders
              </div>
            </div>
            <div className="flex gap-2">
              <button
                className="rounded-md border border-line px-2.5 py-1.5 text-xs hover:bg-sunken"
                onClick={() => {
                  update({ distributor: [String(s.distributor.id)] });
                  onClose();
                }}
              >
                Filter the page to this distributor
              </button>
              <button
                className="inline-flex items-center gap-1 rounded-md border border-line px-2.5 py-1.5 text-xs hover:bg-sunken"
                onClick={() =>
                  download('/settlements/orders/', { ...apiParams, distributor: String(s.distributor.id), export: 'xlsx' }, `settlement_${s.distributor.name}.xlsx`)
                }
              >
                <IconDownload size={13} /> All orders
              </button>
            </div>
          </div>

          {/* headline: settled vs remaining */}
          <div>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div>
                <span className="text-2xl font-semibold text-ink">{inr(b.settled)}</span>
                <span className="ml-1.5 text-sm text-ink2">settled of {inr(b.payable)} owed</span>
              </div>
              <div className="text-right">
                <span className={cx('text-2xl font-semibold', b.remaining ? 'text-warn' : 'text-good')}>{inr(b.remaining)}</span>
                <span className="ml-1.5 text-sm text-ink2">remaining</span>
              </div>
            </div>
            <div className="mt-2 flex h-3 overflow-hidden rounded-full bg-sunken" role="img" aria-label={`${sharePct(k.settled_pct)} settled`}>
              <div style={{ width: `${pct(b.settled)}%`, background: t.ordinal[3] }} title={`Settled ${inr(b.settled)}`} />
              <div className="border-l-2 border-surface" style={{ width: `${pct(b.due)}%`, background: STATUS.warning }} title={`Delivered, not settled ${inr(b.due)}`} />
              <div className="border-l-2 border-surface" style={{ width: `${pct(b.not_yet_due)}%`, background: t.deemph }} title={`Not delivered yet ${inr(b.not_yet_due)}`} />
            </div>
            <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink2">
              <Legend color={t.ordinal[3]}>Settled {sharePct(k.settled_pct)}</Legend>
              <Legend color={STATUS.warning}>Delivered, not settled {inr(b.due)}</Legend>
              <Legend color={t.deemph}>Not delivered yet {inr(b.not_yet_due)}</Legend>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Mini label={`Overdue (> ${s.sla_days} days)`} value={inr(k.overdue)} tone={k.overdue ? 'bad' : 'good'} sub={k.overdue_orders ? `${num(k.overdue_orders)} orders` : 'None'} />
            <Mini label="Last payout" value={date(k.last_payout, 'DD MMM')} sub={s.payout_gap_days != null ? `usually every ${num(s.payout_gap_days)} days` : undefined} />
            <Mini label="Delivery to payout" value={k.median_days != null ? `${num(k.median_days)} days` : '–'} sub={k.p90_days != null ? `90% within ${num(k.p90_days)}` : undefined} />
            <Mini label="Payouts" value={num(s.payouts.length)} sub={`${num(k.settled_orders)} orders paid`} />
          </div>

          {/* reconciliation */}
          <div className="rounded-lg border border-line">
            <div className="border-b border-line px-3 py-2 text-xs font-medium text-ink2">How the amount adds up</div>
            <table className="w-full text-sm tabular">
              <tbody>
                <Line label="Order value" value={b.order_value} />
                <Line label="Cancelled orders" value={-b.cancelled} muted />
                <Line label="Customer refunds (stock / MRP / courier)" value={-b.refunds} muted />
                {b.adjustments !== 0 && <Line label="Sheet adjustments" value={b.adjustments} muted />}
                <Line label="Owed to distributor" value={b.payable} strong />
                <Line label={`Paid out in ${num(s.payouts.length)} payouts`} value={-b.settled} muted />
                <Line label="Remaining" value={b.remaining} strong tone={b.remaining ? 'warn' : 'good'} />
                {b.remaining > 0 && (
                  <>
                    <Line label="of which delivered, waiting for payout" value={b.due} indent />
                    <Line label="of which not delivered yet" value={b.not_yet_due} indent />
                  </>
                )}
              </tbody>
            </table>
            <p className="border-t border-line px-3 py-1.5 text-2xs text-muted">
              Loyalty points used on these orders ({inr(k.loyalty)}) are carried by TechnoSport and not deducted.
            </p>
          </div>

          <div>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <Segmented
                size="xs"
                value={tab}
                onChange={setTab}
                options={[
                  { value: 'open', label: `Open orders (${num(s.open_orders.length)})` },
                  { value: 'payouts', label: `Payout history (${num(s.payouts.length)})` },
                  { value: 'trend', label: 'By month' },
                  ...(s.split?.carts ? [{ value: 'split' as const, label: `Split carts (${num(s.split.carts)})` }] : []),
                ]}
              />
              {tab === 'open' && (
                <Segmented
                  size="xs"
                  value={openFilter}
                  onChange={setOpenFilter}
                  options={[
                    { value: 'all', label: 'All' },
                    { value: 'due', label: 'Delivered' },
                    { value: 'not_yet_due', label: 'Not delivered' },
                    { value: 'overdue', label: `Overdue (${overdueN})` },
                  ]}
                />
              )}
            </div>

            {tab === 'open' &&
              (open.length ? (
                <div className="max-h-[420px] overflow-auto rounded-lg border border-line">
                  <table className="w-full text-sm tabular">
                    <thead className="sticky top-0 bg-surface">
                      <tr className="border-b border-line text-xs text-muted">
                        <th className="px-3 py-1.5 text-left font-medium">Order</th>
                        <th className="px-2 py-1.5 text-left font-medium">Ordered</th>
                        <th className="px-2 py-1.5 text-left font-medium">Delivery</th>
                        <th className="px-2 py-1.5 text-left font-medium">Waiting</th>
                        <th className="px-3 py-1.5 text-right font-medium">Owed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {open.map((o) => (
                        <tr key={o.order_ref} className="border-t border-line/60">
                          <td className="px-3 py-1.5">
                            {o.order_id ? (
                              <Link className="font-medium text-brand hover:underline dark:text-ink" to={`/orders/${o.order_id}`}>
                                #{o.order_ref}
                              </Link>
                            ) : (
                              `#${o.order_ref}`
                            )}
                            <div className="max-w-[12rem] truncate text-2xs text-muted">{o.customer}</div>
                          </td>
                          <td className="whitespace-nowrap px-2 py-1.5">{date(o.order_date, 'DD MMM')}</td>
                          <td className="whitespace-nowrap px-2 py-1.5">
                            {o.delivered_date ? date(o.delivered_date, 'DD MMM') : <span className="text-muted">{o.fulfilment === 'in_transit' ? 'In transit' : 'Not dispatched'}</span>}
                          </td>
                          <td className="whitespace-nowrap px-2 py-1.5">
                            {o.state === 'due' ? (
                              <Badge tone={o.overdue ? 'bad' : 'warn'}>{num(o.days_since_delivery)} days</Badge>
                            ) : (
                              <span className="text-xs text-muted">not due yet</span>
                            )}
                          </td>
                          <td className="whitespace-nowrap px-3 py-1.5 text-right font-semibold">{inr(o.payable)}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t-2 border-line font-semibold">
                        <td className="px-3 py-1.5" colSpan={4}>
                          {num(open.length)} orders
                        </td>
                        <td className="whitespace-nowrap px-3 py-1.5 text-right">{inr(open.reduce((a, o) => a + o.payable, 0))}</td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              ) : (
                <div className="rounded-lg border border-line p-6 text-center text-sm text-good">Nothing open: everything in this selection is settled.</div>
              ))}

            {tab === 'payouts' && (
              <div className="max-h-[420px] overflow-auto rounded-lg border border-line">
                <table className="w-full text-sm tabular">
                  <thead className="sticky top-0 bg-surface">
                    <tr className="border-b border-line text-xs text-muted">
                      <th className="px-3 py-1.5 text-left font-medium">Settlement date</th>
                      <th className="px-2 py-1.5 text-right font-medium">Orders</th>
                      <th className="px-2 py-1.5 text-right font-medium">Paid</th>
                      <th className="px-2 py-1.5 text-right font-medium">Paid to date</th>
                      <th className="px-3 py-1.5 text-right font-medium">Days after delivery</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.payouts.map((p) => (
                      <tr
                        key={p.date}
                        className="cursor-pointer border-t border-line/60 hover:bg-sunken/50"
                        title="Filter the page to this distributor and settlement date"
                        onClick={() => {
                          update({ distributor: [String(s.distributor.id)], payout_date: [p.date] });
                          onClose();
                        }}
                      >
                        <td className="whitespace-nowrap px-3 py-1.5 font-medium">{date(p.date, 'ddd, DD MMM YYYY')}</td>
                        <td className="px-2 py-1.5 text-right">{num(p.orders)}</td>
                        <td className="whitespace-nowrap px-2 py-1.5 text-right font-semibold">{inr(p.amount)}</td>
                        <td className="whitespace-nowrap px-2 py-1.5 text-right text-ink2">{inr(p.cumulative)}</td>
                        <td className="px-3 py-1.5 text-right">{p.median_days != null ? num(p.median_days) : '–'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {tab === 'split' && s.split && (
              <div>
                <SplitCarts block={s.split} focusId={s.distributor.id} onOpenDistributor={onOpenDistributor} compact />
                <p className="mt-2 text-2xs text-muted">Highlighted rows are this distributor's parts. Click the partner distributor to open its statement.</p>
              </div>
            )}

            {tab === 'trend' && (
              <div className="rounded-lg border border-line p-2">
                {trendOpt ? <EChart option={trendOpt} height={260} ariaLabel="Settled and remaining by order month" /> : <div className="p-6 text-sm text-muted">No orders.</div>}
                <p className="px-2 pb-1 text-2xs text-muted">Owed for the orders placed each month, split into what has been settled and what remains.</p>
              </div>
            )}
          </div>
        </div>
      )}
    </Drawer>
  );
}

function Legend({ color, children }: { color: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
      {children}
    </span>
  );
}

function Mini({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'good' | 'bad' }) {
  return (
    <div className="rounded-lg border border-line px-3 py-2">
      <div className="text-2xs text-ink2">{label}</div>
      <div className={cx('text-base font-semibold', tone === 'bad' ? 'text-bad' : tone === 'good' ? 'text-good' : 'text-ink')}>{value}</div>
      {sub && <div className="text-2xs text-muted">{sub}</div>}
    </div>
  );
}

function Line({ label, value, strong, muted, indent, tone }: { label: string; value: number; strong?: boolean; muted?: boolean; indent?: boolean; tone?: 'warn' | 'good' }) {
  return (
    <tr className={cx(strong && 'border-t border-line font-semibold')}>
      <td className={cx('px-3 py-1.5', muted && 'text-ink2', indent && 'pl-7 text-xs text-ink2')}>{label}</td>
      <td className={cx('whitespace-nowrap px-3 py-1.5 text-right', tone === 'warn' && 'text-warn', tone === 'good' && 'text-good', indent && 'text-xs text-ink2')}>
        {value < 0 ? `− ${inr(-value)}` : inr(value)}
      </td>
    </tr>
  );
}
