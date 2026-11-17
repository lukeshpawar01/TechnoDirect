import { useMemo, useState } from 'react';
import type { Period, Products, SelectedStyle } from '@/api/types';
import { cartesian } from '@/charts/builders';
import { EChart, useChartTokens } from '@/charts/EChart';
import { colorFor } from '@/charts/palette';
import { Card, Delta, Segmented } from '@/components/ui';
import { useFilters } from '@/lib/filters';
import { date, inr, monthTick, num, sharePct } from '@/lib/format';
import { IconX } from './Icons';

const MAX_LINES = 7; // categorical hues never cycle: past 7 styles the smallest fold into "Other"
const cap = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
const delta = (now: number, prev: number | null) => (prev ? ((now - prev) / prev) * 100 : null);
const shortName = (s: SelectedStyle) => s.name.replace(new RegExp(`^${s.code}[\\s-]+`, 'i'), '').trim();

/**
 * Products page, Style filter on: the selected styles' sales this period vs the comparison period, and their last
 * 12 months. Line values (an order with several styles counts only these styles' lines).
 */
export function StylePerformance({ data, period, loading }: { data: Products | undefined; period: Period | undefined; loading?: boolean }) {
  const t = useChartTokens();
  const { update, searchParams } = useFilters();
  const [metric, setMetric] = useState<'sales' | 'units'>('sales');
  const rows = data?.selected_styles ?? [];
  const multi = rows.length > 1;

  const opt = useMemo(() => {
    const m = data?.style_monthly ?? [];
    if (!m.length) return null;
    const months = [...new Set(m.map((x) => x.month))].sort();
    const val = (code: string, mo: string) => m.find((x) => x.code === code && x.month === mo)?.[metric] ?? 0;
    const totals = new Map(rows.map((r) => [r.code, months.reduce((s, mo) => s + val(r.code, mo), 0)]));
    const ranked = [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([c]) => c);
    const shown = ranked.length > MAX_LINES ? ranked.slice(0, MAX_LINES - 1) : ranked;
    const rest = ranked.filter((c) => !shown.includes(c));
    const names = [...shown, ...(rest.length ? [`Other (${rest.length})`] : [])];
    const colors = colorFor(names, t);
    const x = months.map((mo) => monthTick(mo, period?.to));
    if (!multi) {
      // one style: bars, the running month lighter
      const lastPartial = !!period?.to && x[x.length - 1] !== months.map((mo) => monthTick(mo, null))[months.length - 1];
      return cartesian(t, {
        x,
        format: metric === 'sales' ? 'inr' : 'num',
        legend: false,
        showBarLabels: false,
        series: [{ name: rows[0]?.code ?? '', data: months.map((mo) => val(names[0], mo)), colors: months.map((_, i) => (lastPartial && i === months.length - 1 ? t.deemph : t.series[0])) }],
      });
    }
    return cartesian(t, {
      x,
      format: metric === 'sales' ? 'inr' : 'num',
      legend: true,
      series: names.map((n) => ({
        name: n,
        type: 'line' as const,
        color: colors[n],
        data: months.map((mo) => (rest.length && n === names[names.length - 1] ? rest.reduce((s, c) => s + val(c, mo), 0) : val(n, mo))),
      })),
    });
  }, [data, metric, rows, multi, t, period?.to]);

  if (!rows.length) return null;
  const selected = (searchParams.get('article') ?? '').split(',').filter(Boolean);
  const remove = (code: string) => {
    const left = selected.filter((c) => c !== code);
    update({ article: left.length ? left : undefined });
  };
  const cmpLabel = period?.compare_from && period?.compare_to ? `${date(period.compare_from)} – ${date(period.compare_to)}` : null;
  const total = rows.reduce((s, r) => s + r.sales, 0);
  const lastMonth = (data?.style_monthly ?? []).map((x) => x.month).sort().pop();
  const tick = lastMonth ? monthTick(lastMonth, period?.to) : '';
  const running = lastMonth && tick !== monthTick(lastMonth, null) ? tick.split(' ')[0] : '';

  return (
    <Card
      className="mt-4"
      title={multi ? `Style performance · ${rows.length} styles` : `Style performance · ${rows[0].code}`}
      subtitle={`Line value of ${multi ? 'these styles' : 'this style'} only, ${period?.label ?? 'this period'}${cmpLabel ? ` vs ${cmpLabel}` : ''} · all colours and batches of a code are included`}
      actions={
        <Segmented
          value={metric}
          onChange={setMetric}
          size="xs"
          options={[
            { value: 'sales', label: 'Sales' },
            { value: 'units', label: 'Units' },
          ]}
        />
      }
    >
      <div className={`grid grid-cols-1 gap-6 px-4 pb-4 pt-1 xl:grid-cols-5 ${loading ? 'opacity-60' : ''}`}>
        <div className="overflow-x-auto xl:col-span-3">
          <table className="w-full min-w-[620px] text-sm tabular">
            <thead>
              <tr className="border-b border-line text-xs text-muted">
                <th className="py-2 pr-2 text-left font-medium">Style</th>
                <th className="px-2 py-2 text-right font-medium">{metric === 'sales' ? 'Sales' : 'Units'}</th>
                <th className="px-2 py-2 text-right font-medium">vs previous</th>
                <th className="px-2 py-2 text-right font-medium">Orders</th>
                <th className="px-2 py-2 text-right font-medium">Retailers</th>
                <th className="px-2 py-2 text-right font-medium">₹ / unit</th>
                {multi && <th className="py-2 pl-2 text-right font-medium">Share</th>}
                <th className="w-6" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const now = metric === 'sales' ? r.sales : r.units;
                const prev = metric === 'sales' ? r.prev_sales : r.prev_units;
                const d = delta(now, prev);
                return (
                  <tr key={r.code} className="border-t border-line/60">
                    <td className="py-2 pr-2">
                      <div className="font-semibold text-ink">{r.code}</div>
                      <div className="max-w-[260px] truncate text-xs text-muted" title={r.name}>
                        {r.known ? [shortName(r), [cap(r.l1), r.l2, r.l3].filter(Boolean).join(' · ')].filter(Boolean).join(' — ') : 'Not in the catalogue'}
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-2 py-2 text-right font-semibold text-ink">{metric === 'sales' ? inr(r.sales) : num(r.units)}</td>
                    <td className="px-2 py-2 text-right">
                      <span className="inline-flex items-center justify-end gap-1.5">
                        <span className="whitespace-nowrap text-xs text-muted">{prev === null ? '–' : metric === 'sales' ? inr(prev) : num(prev)}</span>
                        {d === null ? <span className="w-16 text-right text-xs text-muted">{prev === 0 && now > 0 ? 'new' : '–'}</span> : <Delta value={d} suffix="" className="w-16 justify-end" />}
                      </span>
                    </td>
                    <td className="px-2 py-2 text-right">{num(r.orders)}</td>
                    <td className="px-2 py-2 text-right">{num(r.retailers)}</td>
                    <td className="whitespace-nowrap px-2 py-2 text-right">{inr(r.realisation, { compact: false })}</td>
                    {multi && <td className="py-2 pl-2 text-right text-ink2">{total ? sharePct((r.sales / total) * 100) : '–'}</td>}
                    <td className="pl-1 text-right">
                      <button className="rounded p-1 text-muted hover:bg-sunken hover:text-ink" title={`Remove ${r.code} from the filter`} aria-label={`Remove ${r.code}`} onClick={() => remove(r.code)}>
                        <IconX size={12} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-2 text-2xs text-muted">
            Orders and retailers are counted per style: a retailer who bought two of these styles counts once for each. The rest of the page also shows only {multi ? 'these styles' : 'this style'}.
          </p>
        </div>
        <div className="xl:col-span-2">
          <div className="mb-1 text-sm font-semibold text-ink">
            Last 12 months <span className="text-xs font-normal text-muted">{metric === 'sales' ? 'sales (line value)' : 'units'} per month</span>
          </div>
          <EChart option={opt ?? {}} height={240} ariaLabel="Selected styles by month" />
          {running && <p className="mt-1 text-2xs text-muted">{running} is month to date, so its point is lower than a full month.</p>}
        </div>
      </div>
    </Card>
  );
}
