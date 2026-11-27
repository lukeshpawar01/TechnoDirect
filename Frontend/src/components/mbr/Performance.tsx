import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { inr, monthLabel, num, pct, signedPct } from '@/lib/format';
import { useChartTokens } from '@/charts/EChart';
import { cartesian } from '@/charts/builders';
import { ChartCard } from '@/components/ChartCard';
import { Badge, Card, Meter, Segmented, cx } from '@/components/ui';
import { IconInfo } from '@/components/Icons';
import { Change, MiniTrend, NoteBox, STATUS_TONE, SectionTitle, Verdict, fmt, statusText, useSaveReview } from './shared';
import type { MbrNotes, ScoreRow, Scorecard } from './types';
import { ProductMatrixSection } from './ProductMatrix';
import { Takeaways } from './Summary';

export function Performance({ s, notes }: { s: Scorecard; notes?: MbrNotes }) {
  const h = s.headline;
  const rows = useMemo(() => Object.fromEntries(s.rows.map((r) => [r.key, r])), [s.rows]);
  const tone = h.status ? STATUS_TONE[h.status] : 'neutral';
  const save = useSaveReview(s.month);

  const vs = (p: number | null) => (p === null ? '' : `${p >= 0 ? 'up' : 'down'} ${Math.abs(p).toFixed(1)}%`);
  return (
    <>
      <Verdict
        tone={tone}
        label={h.target ? (s.partial ? `Projected ${pct(h.projected_pct, 0)} of target` : `${pct(h.achievement_pct, 0)} of target`) : 'No sales target set'}
      >
        {s.partial ? (
          <>
            <b className="font-semibold">{inr(h.sales)}</b> of sales in {s.compare.current}
            {h.target ? <> against a target of <b className="font-semibold">{inr(h.target)}</b> ({pct(h.achievement_pct, 0)} with {s.days_total - s.days_elapsed} days left)</> : null}.
            {' '}At {inr(h.run_rate_per_day)} a day the month ends near <b className="font-semibold">{inr(h.projected)}</b>
            {h.required_per_day ? <>; hitting target needs {inr(h.required_per_day)} a day</> : null}.
          </>
        ) : (
          <>
            {s.label} closed at <b className="font-semibold">{inr(h.sales)}</b>
            {h.target ? <> against a target of <b className="font-semibold">{inr(h.target)}</b> ({pct(h.achievement_pct, 0)})</> : null}.
          </>
        )}
        {' '}Sales are {vs(h.mom_pct) || 'level'} on {s.compare.prev}
        {h.yoy_pct !== null && s.compare.last_year ? <> and {vs(h.yoy_pct)} on {s.compare.last_year}</> : null}, from{' '}
        {num(rows.active_retailers?.value)} transacting retailers ({pct(rows.adoption_pct?.value, 1)} of the KYC base).
      </Verdict>

      <Takeaways s={s} areas={['drivers', 'retailers', 'territory', 'product', 'operations']} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {(['sales', 'active_retailers', 'new_retailers', 'adoption_pct'] as const).map((k) => rows[k] && <HeadTile key={k} r={rows[k]} s={s} />)}
      </div>

      <SalesTrend s={s} />

      <SectionTitle n="2.1" title="Scorecard" sub={`${s.compare.current} vs ${s.compare.prev}${s.compare.last_year ? ` and ${s.compare.last_year}` : ''}`} />
      {s.targets_note && <p className="mb-2 text-xs text-warn">{s.targets_note}</p>}
      <ScoreTable s={s} />

      <div className="mt-4 grid gap-4 xl:grid-cols-5">
        <RegionCard s={s} className="xl:col-span-3" />
        <MoversCard s={s} className="xl:col-span-2" />
      </div>

      <SectionTitle n="2.2" title="Product decisions" sub="What to act on, where growth came from, and how each category is doing" />
      <ProductMatrixSection s={s} />

      <SectionTitle n="2.3" title="Commentary" sub="What the numbers mean, in the team's words" />
      {notes ? (
        <div className="grid gap-4 md:grid-cols-2" key={notes.month}>
          <NoteBox title="What went well" tone="good" value={notes.review.went_well} canEdit={notes.can_edit} saving={save.isPending}
            placeholder={'East beat target by 11%\nRetention up to 48%'} onSave={(v) => save.mutate({ went_well: v })} />
          <NoteBox title="What needs attention" tone="bad" value={notes.review.needs_attention} canEdit={notes.can_edit} saving={save.isPending}
            placeholder={'North at 49% of target\nKYC → first order flat at 12%'} onSave={(v) => save.mutate({ needs_attention: v })} />
        </div>
      ) : null}
    </>
  );
}

function HeadTile({ r, s }: { r: ScoreRow; s: Scorecard }) {
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="text-xs text-muted">{r.label}</div>
        {r.status && r.status !== 'in_progress' && <Badge tone={STATUS_TONE[r.status]}>{statusText(r.status)}</Badge>}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-ink">{fmt(r.value, r.format)}</div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs">
        <Change v={r.mom_pct} f={r.format} up={r.higher_is_better} />
        <span className="text-muted">vs {s.compare.prev}</span>
      </div>
      {r.target ? (
        <div className="mt-2">
          <Meter value={r.achievement_pct} tone={r.status === 'good' ? 'good' : r.status === 'warn' ? 'warn' : 'brand'} />
          <div className="mt-1 text-2xs text-ink2">
            {pct(r.achievement_pct, 0)} of {fmt(r.target, r.format)}
            {r.projected_pct !== null && <> · projected {pct(r.projected_pct, 0)}</>}
          </div>
        </div>
      ) : (
        <div className="mt-2"><MiniTrend data={r.trend} partial={s.partial} width={140} height={28} /></div>
      )}
    </div>
  );
}

function SalesTrend({ s }: { s: Scorecard }) {
  const t = useChartTokens();
  const option = useMemo(
    () =>
      cartesian(t, {
        x: s.trend.map((p, i) => monthLabel(p.month) + (s.partial && i === s.trend.length - 1 ? ' (MTD)' : '')),
        format: 'inr',
        legend: true,
        series: [
          { name: 'Sales', data: s.trend.map((p) => p.sales), type: 'bar', color: t.series[0] },
          { name: 'Target', data: s.trend.map((p) => p.target_sales), type: 'line', dashed: true, color: t.target },
        ],
      }),
    [t, s],
  );
  return (
    <ChartCard
      className="mt-4"
      title="Sales vs target, last 12 months"
      subtitle={`Bars are sales, the dashed line the month's target.${s.partial ? ' The last bar is month to date.' : ''}`}
      option={option}
      height={260}
      table={{
        columns: ['Month', 'Sales', 'Target', '% of target', 'Transacting retailers', 'New'],
        rows: s.trend.map((p) => [monthLabel(p.month), inr(p.sales), p.target_sales ? inr(p.target_sales) : '–', p.target_sales ? pct((p.sales / p.target_sales) * 100, 0) : '–', num(p.active_retailers), num(p.new_retailers)]),
      }}
    />
  );
}

function ScoreTable({ s }: { s: Scorecard }) {
  const groups: { key: 'business' | 'product'; title: string }[] = [
    { key: 'business', title: 'Business metrics' },
    { key: 'product', title: 'Product metrics: the retailer journey on the app' },
  ];
  return (
    <div className="card overflow-x-auto">
      <table className="w-full min-w-[920px] text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-muted">
            <th className="px-4 py-2 font-medium">Metric</th>
            <th className="px-3 py-2 text-right font-medium">{s.partial ? 'Month to date' : s.label}</th>
            <th className="px-3 py-2 text-right font-medium">{s.compare.prev}</th>
            <th className="px-3 py-2 text-right font-medium">MoM</th>
            <th className="px-3 py-2 text-right font-medium">{s.compare.last_year ?? 'Last year'}</th>
            <th className="px-3 py-2 text-right font-medium">YoY</th>
            <th className="px-3 py-2 text-right font-medium">Target</th>
            <th className="px-3 py-2 text-right font-medium">Achieved</th>
            <th className="px-3 py-2 font-medium">12 months</th>
          </tr>
        </thead>
        {groups.map((g) => (
          <tbody key={g.key}>
            <tr className="bg-sunken/60">
              <td colSpan={9} className="px-4 py-1.5 text-xs font-semibold text-ink2">{g.title}</td>
            </tr>
            {s.rows.filter((r) => r.group === g.key).map((r) => (
              <tr key={r.key} className="border-b border-line/60 last:border-0 hover:bg-sunken/40">
                <td className="px-4 py-2">
                  <span className="inline-flex items-center gap-1.5 text-ink" title={r.definition}>
                    {r.label}
                    <IconInfo size={12} className="text-muted" />
                  </span>
                </td>
                <td className="px-3 py-2 text-right font-semibold tabular-nums text-ink">
                  {fmt(r.value, r.format)}
                  {r.projected !== null && <div className="text-2xs font-normal text-muted">→ {fmt(r.projected, r.format)} projected</div>}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-ink2">{fmt(r.prev, r.format)}</td>
                <td className="px-3 py-2 text-right"><Change v={r.mom_pct} f={r.format} up={r.higher_is_better} /></td>
                <td className="px-3 py-2 text-right tabular-nums text-ink2">{fmt(r.last_year, r.format)}</td>
                <td className="px-3 py-2 text-right"><Change v={r.yoy_pct} f={r.format} up={r.higher_is_better} /></td>
                <td className="px-3 py-2 text-right tabular-nums text-ink2">{r.target ? fmt(r.target, r.format) : <span className="text-muted">–</span>}</td>
                <td className="px-3 py-2 text-right">
                  {r.achievement_pct !== null ? (
                    <span className={cx('tabular-nums font-medium', r.status === 'good' ? 'text-good' : r.status === 'bad' ? 'text-bad' : r.status === 'warn' ? 'text-warn' : 'text-ink')}>
                      {pct(r.achievement_pct, 0)}
                    </span>
                  ) : <span className="text-muted">–</span>}
                </td>
                <td className="px-3 py-1"><MiniTrend data={r.trend} partial={s.partial} /></td>
              </tr>
            ))}
          </tbody>
        ))}
      </table>
      <p className="border-t border-line px-4 py-2 text-2xs text-muted">
        Hover a metric for its definition. Rates change in percentage points (pp). {s.partial ? `A month in progress is compared on the same days (${s.compare.prev}); sales and orders are also projected to month end at the current daily rate.` : ''}
        {' '}KYC timing uses the sign-up date (the data has no approval date), as on the Retailer Funnel.
      </p>
    </div>
  );
}

type Dim = keyof Scorecard['territory'];
const DIMS: { value: Dim; label: string }[] = [
  { value: 'region', label: 'Region' }, { value: 'rsm', label: 'RSM' }, { value: 'state', label: 'State' }, { value: 'asm', label: 'ASM' },
];

function RegionCard({ s, className }: { s: Scorecard; className?: string }) {
  const [dim, setDim] = useState<Dim>('region');
  const label = DIMS.find((d) => d.value === dim)!.label;
  return (
    <Card
      className={className}
      title={`${label === 'Region' ? 'Regions' : label === 'State' ? 'States' : `${label}s`} vs target`}
      subtitle={`${s.compare.current}; growth vs ${s.compare.prev}`}
      actions={<Segmented value={dim} onChange={setDim} size="xs" options={DIMS} />}
      bodyClass="p-0"
    >
      <div className={cx(s.territory[dim].length > 10 && 'max-h-[30rem] overflow-y-auto')}>
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-surface">
          <tr className="border-b border-line text-left text-xs text-muted">
            <th className="px-4 py-2 font-medium">{label}</th>
            <th className="px-3 py-2 text-right font-medium">Sales</th>
            <th className="w-[34%] px-3 py-2 font-medium">Of target</th>
            <th className="px-3 py-2 text-right font-medium">MoM</th>
            <th className="px-4 py-2 text-right font-medium">Retailers</th>
          </tr>
        </thead>
        <tbody>
          {s.territory[dim].map((r) => {
            const a = r.achievement_pct;
            // mid-month, judge by where the region lands at the current daily rate
            const proj = a === null ? null : s.partial ? (a * s.days_total) / s.days_elapsed : a;
            const tone = proj === null ? 'brand' : proj >= 100 ? 'good' : proj >= 90 ? 'warn' : 'bad';
            return (
              <tr key={r.id ?? r.name} className="border-b border-line/60 last:border-0">
                <td className="px-4 py-2 text-ink">{r.name}</td>
                <td className="px-3 py-2 text-right tabular-nums text-ink">{inr(r.sales)}</td>
                <td className="px-3 py-2">
                  {r.target ? (
                    <div className="flex items-center gap-2">
                      <div className="flex-1"><Meter value={a} tone={tone} /></div>
                      <span className="w-32 whitespace-nowrap text-right text-xs tabular-nums text-ink2">
                        {pct(a, 0)} of {inr(r.target)}
                        {s.partial && proj !== null && <span className="block text-2xs text-muted">projected {pct(proj, 0)}</span>}
                      </span>
                    </div>
                  ) : <span className="text-xs text-muted">No target</span>}
                </td>
                <td className="px-3 py-2 text-right"><Change v={r.mom_pct} f="inr" /></td>
                <td className="px-4 py-2 text-right tabular-nums text-ink2">{num(r.active_retailers)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>
      {s.partial && <p className="px-4 py-2 text-2xs text-muted">Month in progress: % of target is so far ({s.days_total - s.days_elapsed} days to go); the bar colour follows the projected month end.</p>}
    </Card>
  );
}

function MoversCard({ s, className }: { s: Scorecard; className?: string }) {
  const all = [...s.movers.up, ...s.movers.down];
  const max = Math.max(...all.map((m) => Math.abs(m.change)), 1);
  const Row = ({ m }: { m: (typeof all)[number] }) => (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 py-1">
      <Link to={`/distributors/${m.id}`} className="truncate text-sm text-ink hover:underline">{m.name}</Link>
      <span className={cx('text-right text-xs font-medium tabular-nums', m.change > 0 ? 'text-good' : 'text-bad')}>
        {m.change > 0 ? '+' : '−'}{inr(Math.abs(m.change))}
      </span>
      <div className="col-span-2 h-1 rounded-full bg-sunken">
        <div className={cx('h-1 rounded-full', m.change > 0 ? 'bg-good' : 'bg-bad')} style={{ width: `${(Math.abs(m.change) / max) * 100}%` }} />
      </div>
    </li>
  );
  return (
    <Card className={className} title="What moved the month" subtitle={`Distributors with the biggest change in sales vs ${s.compare.prev}`}>
      {all.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted">No change to show.</p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-1">
          <div>
            <div className="mb-1 text-xs font-semibold text-good">Grew most</div>
            <ul>{s.movers.up.map((m) => <Row key={m.id} m={m} />)}</ul>
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-bad">Fell most</div>
            <ul>{s.movers.down.length ? s.movers.down.map((m) => <Row key={m.id} m={m} />) : <li className="text-xs text-muted">None fell.</li>}</ul>
          </div>
        </div>
      )}
      <p className="mt-2 text-2xs text-muted">Net change {signedPct(s.headline.mom_pct)} in total sales.</p>
    </Card>
  );
}
