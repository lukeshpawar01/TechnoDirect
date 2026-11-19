import { useQuery } from '@tanstack/react-query';
import { get } from '@/lib/api';
import { inr, monthLabel, pct } from '@/lib/format';
import { Card, Meter } from './ui';

interface ExecDistributor {
  distributor_id: number;
  distributor: string;
  target: number;
  distributor_sales: number;
  share_pct: number;
  sales: number;
  exact: boolean;
  shared_with: string[];
}
interface ExecRow {
  person: string;
  hr_name: string | null;
  region: string;
  target: number;
  sales: number;
  achieved_pct: number | null;
  basis: 'exact' | 'allocated' | 'mixed';
  distributors: ExecDistributor[];
}
interface ExecData {
  month: string;
  as_of: string;
  executives: ExecRow[];
}

const tone = (a: number | null) => (a === null ? 'brand' : a >= 100 ? 'good' : a >= 80 ? 'warn' : 'bad') as 'brand' | 'good' | 'warn' | 'bad';

/**
 * Executives' monthly targets (live incentive sheet) against sales. Orders carry no executive, so sales come from the
 * executive's distributor: exactly when they work it alone, split by target share when they share it with an ASM.
 */
export function ExecutivePerformance({ month }: { month?: string }) {
  const q = useQuery({
    queryKey: ['exec-performance', month],
    queryFn: () => get<ExecData>('/masters/asm-tracker/executives/', { month }),
    enabled: !!month,
    staleTime: 60_000,
  });
  const rows = q.data?.executives ?? [];
  if (!month || (!q.isLoading && !rows.length)) return null;

  return (
    <Card
      className="mt-4"
      title={`Executive performance · ${monthLabel(month)}`}
      subtitle="Targets from the incentive sheet. Orders carry no executive: sales are the distributor's own when the executive works it alone, and split by target share when shared with an ASM (marked allocated)."
    >
      {q.isLoading ? (
        <div className="m-4 h-40 animate-pulse rounded-md bg-sunken" />
      ) : (
        <div className="overflow-x-auto px-4 pb-4">
          <table className="w-full min-w-[720px] text-sm tabular">
            <thead>
              <tr className="border-b border-line text-xs text-muted">
                <th className="py-2 pr-2 text-left font-medium">Executive</th>
                <th className="px-2 py-2 text-left font-medium">Distributor</th>
                <th className="px-2 py-2 text-right font-medium">Target</th>
                <th className="px-2 py-2 text-right font-medium">Sales</th>
                <th className="py-2 pl-2 text-right font-medium">Achieved</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.person} className="border-t border-line/60 align-top">
                  <td className="py-2 pr-2">
                    <div className="font-medium text-ink">{r.person}</div>
                    <div className="text-xs text-muted">{[r.hr_name && r.hr_name !== r.person ? r.hr_name : null, r.region].filter(Boolean).join(', ')}</div>
                  </td>
                  <td className="px-2 py-2">
                    {r.distributors.map((d) => (
                      <div key={d.distributor_id}>
                        <span className="text-ink">{d.distributor}</span>
                        <div className="text-xs text-muted">
                          {d.exact
                            ? 'works it alone: its sales in full'
                            : `allocated ${pct(d.share_pct, 0)} of ${inr(d.distributor_sales, { compact: true })}, shared with ${d.shared_with.join(', ')}`}
                        </div>
                      </div>
                    ))}
                  </td>
                  <td className="px-2 py-2 text-right">{inr(r.target)}</td>
                  <td className="px-2 py-2 text-right">
                    {inr(r.sales)}
                    {r.basis !== 'exact' && <div className="text-xs text-muted">allocated</div>}
                  </td>
                  <td className="py-2 pl-2">
                    {r.achieved_pct === null ? (
                      <span className="text-xs text-muted">No target</span>
                    ) : (
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-24">
                          <Meter value={r.achieved_pct} tone={tone(r.achieved_pct)} />
                        </div>
                        <span className="w-11 text-right">{pct(r.achieved_pct, 0)}</span>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
