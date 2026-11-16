import { useNavigate } from 'react-router-dom';
import { useAnalytics } from '@/api/hooks';
import { Card } from '@/components/ui';
import { linkWithFilters, useFilters } from '@/lib/filters';
import { inr, num } from '@/lib/format';

export interface DistributorsByState {
  summary: { states: number; distributors: number; selling: number };
  states: {
    state: string;
    region: string | null;
    sales: number;
    selling: number;
    distributors: { id: number; name: string; sales: number; orders: number }[];
  }[];
}

/** Distributors grouped by state (state per the sales team's distributor list), sorted by the period's sales. */
export function NetworkCoverage() {
  const q = useAnalytics<DistributorsByState>('/distributors/network/');
  const { searchParams } = useFilters();
  const navigate = useNavigate();
  const d = q.data?.data;
  const top = Math.max(1, ...(d?.states ?? []).map((r) => r.sales));

  return (
    <Card
      className="mt-4"
      title="Distributors by state"
      subtitle={d ? `${num(d.summary.distributors)} distributors across ${num(d.summary.states)} states · ${num(d.summary.selling)} with orders this period` : undefined}
    >
      <div className="px-4 pb-4 pt-2">
        <div className="max-h-[440px] overflow-auto">
          <table className="w-full text-xs tabular">
            <thead className="sticky top-0 z-10 bg-surface text-left text-muted">
              <tr className="border-b border-line">
                <th className="py-1.5 pr-3 font-medium">State</th>
                <th className="w-40 pr-3 text-right font-medium">Sales</th>
                <th className="font-medium">Distributors</th>
              </tr>
            </thead>
            <tbody>
              {(d?.states ?? []).map((r) => (
                <tr key={r.state} className="border-b border-line/60 align-top last:border-0">
                  <td className="py-2 pr-3">
                    <div className="font-medium text-ink">{r.state}</div>
                    {r.region && <div className="text-muted">{r.region}</div>}
                  </td>
                  <td className="py-2 pr-3 text-right">
                    <div>{r.sales ? inr(r.sales, { compact: true }) : <span className="text-muted">–</span>}</div>
                    <div className="mt-1 h-1 w-full rounded-full bg-sunken" aria-hidden>
                      <div className="ml-auto h-full rounded-full bg-ink2/40" style={{ width: `${(r.sales / top) * 100}%` }} />
                    </div>
                  </td>
                  <td className="py-2">
                    <div className="flex flex-wrap gap-1">
                      {r.distributors.map((x) => (
                        <button
                          key={x.id}
                          type="button"
                          onClick={() => navigate(linkWithFilters(`/distributors/${x.id}`, searchParams))}
                          className="chip bg-sunken text-ink hover:bg-brand/15"
                          title={x.orders ? `${inr(x.sales)} · ${num(x.orders)} orders this period` : 'No orders this period'}
                        >
                          {x.name}
                          <span className="text-muted">{x.orders ? inr(x.sales, { compact: true }) : '–'}</span>
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
              {!d?.states.length && (
                <tr>
                  <td colSpan={3} className="py-6 text-center text-muted">
                    {q.isLoading ? 'Loading…' : 'No distributors for these filters'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </Card>
  );
}
