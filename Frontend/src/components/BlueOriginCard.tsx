import { useMemo } from 'react';
import type { BoRecord } from '@/api/types';
import { cartesian } from '@/charts/builders';
import { EChart, useChartTokens } from '@/charts/EChart';
import { Card } from '@/components/ui';
import { inr, monthLabel, titleCase } from '@/lib/format';
import { TierChip } from './TierChip';

/**
 * Retailer detail: the shop's offline (BlueOrigin) records, matched by phone. Tier per quarterly sheet and the
 * monthly distributor purchase beside its app orders (the sheet value already includes them: never add the two).
 */
export function BlueOriginCard({ records, appMonthly }: { records: BoRecord[] | undefined; appMonthly: { month: string; sales: number }[] }) {
  const t = useChartTokens();
  const opt = useMemo(() => {
    if (!records?.length) return null;
    const off = new Map<string, number>();
    records.forEach((r) => r.monthly.forEach((m) => off.set(m.month, (off.get(m.month) ?? 0) + m.value)));
    const app = new Map(appMonthly.map((m) => [m.month, m.sales]));
    const months = [...new Set([...off.keys(), ...app.keys()])].sort().slice(-18);
    return cartesian(t, {
      x: months.map(monthLabel),
      format: 'inr',
      legend: true,
      series: [
        { name: 'Distributor purchase (BlueOrigin)', data: months.map((m) => off.get(m) ?? 0), color: t.series[0] },
        { name: 'Ordered on the app', data: months.map((m) => app.get(m) ?? 0), color: t.series[1] },
      ],
    });
  }, [records, appMonthly, t]);

  if (!records) return null;
  if (!records.length)
    return (
      <Card className="mt-4" title="BlueOrigin (offline)">
        <div className="px-4 pb-4 text-sm text-muted">This retailer's phone number is not in the BlueOrigin distributor sheets.</div>
      </Card>
    );
  return (
    <Card className="mt-4" title="BlueOrigin (offline)" subtitle="What the distributor sold to this shop (app orders included) and its tier, matched by phone · last 18 months">
      <div className="grid grid-cols-1 gap-6 px-4 pb-4 pt-1 xl:grid-cols-5">
        <div className="space-y-4 xl:col-span-2">
          {records.map((r) => (
            <div key={r.bo_id}>
              <div className="mb-1 flex flex-wrap items-baseline gap-x-2 text-sm">
                <span className="font-semibold text-ink">{r.name}</span>
                <span className="text-xs text-muted">
                  {r.bo_id} · {r.distributor ?? '–'}
                  {r.district ? ` · ${r.district}` : ''}
                </span>
              </div>
              <table className="w-full text-sm tabular">
                <thead>
                  <tr className="border-b border-line text-xs text-muted">
                    <th className="py-1.5 pr-2 text-left font-medium">Quarter</th>
                    <th className="px-2 py-1.5 text-left font-medium">Tier</th>
                    <th className="px-2 py-1.5 text-right font-medium">Purchase</th>
                    <th className="py-1.5 pl-2 text-right font-medium">Deliverables</th>
                  </tr>
                </thead>
                <tbody>
                  {[...r.quarters].reverse().map((q) => (
                    <tr key={q.quarter} className="border-t border-line/60">
                      <td className="py-1 pr-2 text-ink2">{q.quarter}</td>
                      <td className="px-2 py-1">
                        <TierChip tier={q.tier} />
                      </td>
                      <td className="whitespace-nowrap px-2 py-1 text-right font-medium text-ink">{inr(q.purchase)}</td>
                      <td className="py-1 pl-2 text-right text-xs text-ink2">{q.deliverables ? titleCase(q.deliverables) : '–'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
        <div className="xl:col-span-3">
          <EChart option={opt ?? {}} height={260} ariaLabel="Distributor purchase and app orders by month" />
        </div>
      </div>
    </Card>
  );
}
