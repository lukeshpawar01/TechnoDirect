import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { SplitBlock, SplitCart } from '@/api/types';
import { useChartTokens } from '@/charts/EChart';
import { date, inr, num, sharePct } from '@/lib/format';
import { Badge, Segmented, cx, type Tone } from './ui';

const CART_STATE: Record<SplitCart['state'], { label: string; tone: Tone }> = {
  settled: { label: 'All parts settled', tone: 'good' },
  partly: { label: 'Partly settled', tone: 'warn' },
  open: { label: 'Not settled', tone: 'neutral' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
};
const PART_STATE: Record<string, { label: string; tone: Tone }> = {
  settled: { label: 'Settled', tone: 'good' },
  not_settled: { label: 'Not settled', tone: 'warn' },
  pending: { label: 'Not reviewed', tone: 'neutral' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
};

/**
 * Split (multi-distributor) carts: one retailer cart fulfilled by two or more distributors because no single one
 * had all the stock. Each part is settled to its own distributor. `focusId` highlights one distributor's parts.
 */
export function SplitCarts({ block, onOpenDistributor, focusId, compact }: {
  block: SplitBlock;
  onOpenDistributor?: (id: number) => void;
  focusId?: number;
  compact?: boolean;
}) {
  const t = useChartTokens();
  const [state, setState] = useState<'all' | SplitCart['state']>('all');
  const [more, setMore] = useState(false);
  const carts = block.list.filter((c) => state === 'all' || c.state === state);
  const shown = more ? carts : carts.slice(0, compact ? 6 : 8);
  const maxPair = Math.max(1, ...block.pairs.map((p) => p.carts));

  if (!block.carts)
    return <div className="p-4 text-sm text-muted">No split carts in this selection: every order was fulfilled by a single distributor.</div>;

  return (
    <div className={cx('grid gap-4', !compact && 'xl:grid-cols-5')}>
      <div className={cx('space-y-4', !compact && 'xl:col-span-2')}>
        <div className="grid grid-cols-2 gap-2">
          <Fig label="Split carts" value={num(block.carts)} sub={`${num(block.parts)} distributor orders · ${sharePct(block.share_pct)} of orders`} />
          <Fig label="Owed for split parts" value={inr(block.payable)} sub={`order value ${inr(block.order_value)}`} />
          <Fig label="Settled" value={inr(block.settled)} tone="good" sub={block.payable ? `${sharePct((block.settled / block.payable) * 100)} of owed` : undefined} />
          <Fig label="Remaining" value={inr(block.remaining)} tone={block.remaining ? 'warn' : undefined} sub={block.courier ? `extra courier ${inr(block.courier)}` : 'no extra courier charged'} />
        </div>
        {!compact && block.pairs.length > 0 && (
          <div>
            <div className="mb-1.5 text-xs font-medium text-ink2">Distributors sharing carts</div>
            <ul className="space-y-1.5">
              {block.pairs.map((p) => (
                <li key={p.pair} className="text-sm">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-ink" title={p.pair}>
                      {p.pair}
                    </span>
                    <span className="shrink-0 tabular text-xs text-ink2">
                      <b className="text-ink">{num(p.carts)}</b> carts · {inr(p.value)}
                    </span>
                  </div>
                  <div className="mt-0.5 h-1.5 rounded-full bg-sunken">
                    <div className="h-1.5 rounded-full" style={{ width: `${(p.carts / maxPair) * 100}%`, background: t.ordinal[2] }} />
                  </div>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-2xs text-muted">"Both parts" = finance paid every part of the cart to the same distributor (a part was reassigned).</p>
          </div>
        )}
      </div>

      <div className={cx(!compact && 'xl:col-span-3')}>
        <div className="mb-2">
          <Segmented
            size="xs"
            value={state}
            onChange={(v) => {
              setState(v);
              setMore(false);
            }}
            options={[
              { value: 'all', label: `All (${num(block.carts)})` },
              { value: 'partly', label: `Partly settled (${num(block.states.partly)})` },
              { value: 'open', label: `Not settled (${num(block.states.open)})` },
              { value: 'settled', label: `Settled (${num(block.states.settled)})` },
            ]}
          />
        </div>
        <div className="space-y-2">
          {shown.map((c) => (
            <div key={c.cart} className="rounded-lg border border-line px-3 py-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div className="min-w-0">
                  <span className="font-medium text-ink">{c.customer || 'Retailer'}</span>
                  <span className="ml-2 text-xs text-muted">{date(c.date, 'DD MMM YYYY')}</span>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="tabular text-ink2">
                    {inr(c.settled)} of {inr(c.payable)} settled
                  </span>
                  <Badge tone={CART_STATE[c.state].tone}>{CART_STATE[c.state].label}</Badge>
                </div>
              </div>
              <table className="mt-1.5 w-full text-xs tabular">
                <tbody>
                  {c.parts.map((p) => (
                    <tr key={p.order_ref} className={cx('border-t border-line/50', focusId != null && p.distributor_id === focusId && 'bg-brand/5')}>
                      <td className="py-1 pr-2">
                        {p.order_id ? (
                          <Link className="text-brand hover:underline dark:text-ink" to={`/orders/${p.order_id}`}>
                            #{p.order_ref}
                          </Link>
                        ) : (
                          `#${p.order_ref}`
                        )}
                      </td>
                      <td className="w-full py-1 pr-2">
                        {p.distributor_id && onOpenDistributor && p.distributor_id !== focusId ? (
                          <button className="text-left text-ink hover:text-brand hover:underline dark:hover:text-ink" onClick={() => onOpenDistributor(p.distributor_id!)}>
                            {p.distributor}
                          </button>
                        ) : (
                          <span className="text-ink">{p.distributor ?? 'Unmapped'}</span>
                        )}
                        {p.courier > 0 && <span className="ml-1.5 text-muted">+{inr(p.courier)} courier</span>}
                      </td>
                      <td className="whitespace-nowrap py-1 pr-2 text-right font-semibold">{inr(p.payable)}</td>
                      <td className="whitespace-nowrap py-1 pr-2">
                        <Badge tone={p.fulfilment === 'cancelled' ? 'neutral' : PART_STATE[p.settlement_status]?.tone ?? 'neutral'}>
                          {p.fulfilment === 'cancelled' ? 'Cancelled' : PART_STATE[p.settlement_status]?.label ?? p.settlement_status}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap py-1 text-right text-muted">{p.settled_on ? date(p.settled_on, 'DD MMM') : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
        {carts.length > shown.length && (
          <button className="mt-2 text-xs text-brand hover:underline dark:text-ink" onClick={() => setMore(true)}>
            Show all {num(carts.length)} carts
          </button>
        )}
      </div>
    </div>
  );
}

function Fig({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'good' | 'warn' }) {
  return (
    <div className="rounded-lg border border-line px-3 py-2">
      <div className="text-2xs text-ink2">{label}</div>
      <div className={cx('text-base font-semibold', tone === 'good' ? 'text-good' : tone === 'warn' ? 'text-warn' : 'text-ink')}>{value}</div>
      {sub && <div className="text-2xs text-muted">{sub}</div>}
    </div>
  );
}
