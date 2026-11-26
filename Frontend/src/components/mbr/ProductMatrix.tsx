import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { EChartsOption } from 'echarts';
import { inr, num, pct } from '@/lib/format';
import { baseOption, useChartTokens } from '@/charts/EChart';
import { STATUS } from '@/charts/palette';
import { ChartCard } from '@/components/ChartCard';
import { Card, Segmented, cx } from '@/components/ui';
import { Change, dmy } from './shared';
import type { LeaderRow, ProductCall, ProductCategory, ProductDecision, Scorecard, StyleChange } from './types';

/**
 * MBR page 1, product decisions - built for founders / CEO / directors:
 *   A. the few calls to take this month, each with the ₹ at stake
 *   B. one chart: which categories the month's ₹ change came from
 *   C. one table: every category on one line, with a call
 */
export function ProductMatrixSection({ s }: { s: Scorecard }) {
  const p = s.products;
  if (!p) return null;
  return (
    <>
      <Decisions items={p.decisions} />
      <Pulse s={s} />
      <div className="mt-4 grid gap-4 xl:grid-cols-5">
        <GrowthBridge s={s} className="xl:col-span-3" />
        <StyleMovers gainers={p.gainers.slice(0, 3)} decliners={p.decliners.slice(0, 3)} prev={s.compare.prev} className="xl:col-span-2" />
      </div>
      <CategoryScorecard s={s} />
      {p.leaders && <Leaders s={s} />}
    </>
  );
}

const KIND: Record<ProductDecision['kind'], { label: string; cls: string }> = {
  scale: { label: 'Scale', cls: 'bg-good/10 text-good border-good/30' },
  fix: { label: 'Fix stock', cls: 'bg-bad/10 text-bad border-bad/30' },
  defend: { label: 'Defend', cls: 'bg-warn/10 text-warn border-warn/40' },
  watch: { label: 'Rationalise', cls: 'bg-sunken text-ink2 border-line' },
  launch: { label: 'Launches', cls: 'bg-brand/10 text-brand border-brand/30' },
};

function Decisions({ items }: { items: ProductDecision[] }) {
  if (!items.length) return null;
  return (
    <div className="mb-3">
      <div className="mb-2 text-xs font-medium text-muted">Decisions this month</div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {items.map((d) => {
          const k = d.kind === 'launch' && d.good === false ? { ...KIND.launch, cls: 'bg-warn/10 text-warn border-warn/40' } : KIND[d.kind];
          const body = (
            <>
              <div className="flex items-center justify-between gap-2">
                <span className={cx('rounded border px-1.5 py-0.5 text-2xs font-semibold', k.cls)}>{k.label}</span>
                {d.link && <span className="text-2xs text-muted group-hover:text-brand">Open</span>}
              </div>
              <div className="mt-2 text-sm font-semibold text-ink">{d.title}</div>
              <div className="mt-1 text-xl font-semibold tabular-nums text-ink">{inr(d.value)}</div>
              <div className="text-2xs text-muted">{d.value_label}</div>
              <p className="mt-2 text-xs leading-relaxed text-ink2">{d.reason}</p>
            </>
          );
          return d.link ? (
            <Link key={d.kind} to={d.link} className="card group block p-3.5 transition-colors hover:border-brand">{body}</Link>
          ) : (
            <div key={d.kind} className="card p-3.5">{body}</div>
          );
        })}
      </div>
    </div>
  );
}

function Pulse({ s }: { s: Scorecard }) {
  const q = s.products.pulse;
  const tiles: { label: string; value: string; sub: React.ReactNode; tone?: string }[] = [
    {
      label: 'Styles sold',
      value: num(q.styles_sold),
      sub: <>top 10 make {pct(q.top10_share_pct, 0)} of sales <Change v={q.top10_share_pct !== null && q.top10_prev_share_pct !== null ? q.top10_share_pct - q.top10_prev_share_pct : null} f="pct" up={false} /></>,
    },
    {
      label: 'New launches’ share',
      value: pct(q.new_launch_share_pct, 1),
      sub: <>{inr(q.new_launch_sales)} · {q.new_launches_selling} of {q.new_launches} new styles sold · bar 10%</>,
      tone: (q.new_launch_share_pct ?? 0) >= 10 ? 'text-good' : 'text-warn',
    },
    {
      label: 'Styles per buying retailer',
      value: q.styles_per_retailer === null ? '–' : String(q.styles_per_retailer),
      sub: <>was {q.prev_styles_per_retailer ?? '–'} · range depth</>,
      tone: q.styles_per_retailer !== null && q.prev_styles_per_retailer !== null && q.styles_per_retailer < q.prev_styles_per_retailer ? 'text-warn' : undefined,
    },
    { label: 'Price per unit', value: inr(q.asp), sub: <><Change v={q.asp_change_pct} f="inr" /> vs {s.compare.prev}</> },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      {tiles.map((t) => (
        <div key={t.label} className="card p-3.5">
          <div className="text-xs text-muted">{t.label}</div>
          <div className={cx('mt-0.5 text-xl font-semibold tabular-nums', t.tone ?? 'text-ink')}>{t.value}</div>
          <div className="mt-0.5 text-2xs text-muted">{t.sub}</div>
        </div>
      ))}
    </div>
  );
}

const BRIDGE_ROWS = 8;
const signed = (v: number) => `${v >= 0 ? '+' : '−'}${inr(Math.abs(v))}`;
const shareMove = (c: { prev_share_pct: number | null; share_pct: number }) =>
  c.prev_share_pct === null ? `${pct(c.share_pct, 1)} (new)` : `${pct(c.prev_share_pct, 1)} → ${pct(c.share_pct, 1)}`;

/** The month's ₹ change vs last month, split by category (biggest movers + Other). */
function GrowthBridge({ s, className }: { s: Scorecard; className?: string }) {
  const t = useChartTokens();
  const p = s.products;
  const rows = useMemo(() => {
    const moved = [...p.categories].sort((a, b) => Math.abs(b.change) - Math.abs(a.change));
    const top = moved.slice(0, BRIDGE_ROWS);
    const rest = moved.slice(BRIDGE_ROWS);
    const out: { name: string; change: number; c: ProductCategory | null; contrib: number | null; note: string }[] = top.map((c) => ({
      name: c.name, change: c.change, c, contrib: c.growth_contrib_pct, note: '',
    }));
    if (rest.length) {
      const ch = rest.reduce((a, c) => a + c.change, 0);
      out.push({ name: `Other (${rest.length})`, change: ch, c: null, contrib: p.td_change > 0 ? (ch / p.td_change) * 100 : null, note: rest.map((c) => c.name).join(', ') });
    }
    return out.sort((a, b) => b.change - a.change);
  }, [p.categories, p.td_change]);

  const option = useMemo<EChartsOption>(() => {
    const base = baseOption(t);
    return {
      ...base,
      legend: { show: false },
      grid: { left: 8, right: 120, top: 8, bottom: 8, containLabel: true },
      tooltip: {
        ...(base.tooltip as object),
        trigger: 'item',
        formatter: (x: unknown) => {
          const r = rows[(x as { dataIndex: number }).dataIndex];
          if (!r.c) return `<b>${r.name}</b><br/>Change ${signed(r.change)}<br/><span style="opacity:.7">${r.note}</span>`;
          const c = r.c;
          return `<b>${c.name}</b><br/>${inr(c.prev_sales)} → ${inr(c.sales)} (${c.mom_pct === null ? 'new' : `${c.mom_pct > 0 ? '+' : ''}${c.mom_pct.toFixed(0)}%`})` +
            `<br/>Share of sales ${shareMove(c)}` + (c.top_style ? `<br/>Top style ${c.top_style}` : '');
        },
      },
      xAxis: { type: 'value', axisLabel: { color: t.muted, fontSize: 11, formatter: (v: number) => signed(v) }, splitLine: { lineStyle: { color: t.grid } } },
      yAxis: {
        type: 'category', inverse: true, data: rows.map((r) => r.name),
        axisLabel: { color: t.ink2, fontSize: 11 }, axisLine: { lineStyle: { color: t.axis } }, axisTick: { show: false },
      },
      series: [{
        type: 'bar',
        barMaxWidth: 18,
        data: rows.map((r) => ({
          value: r.change,
          itemStyle: { color: r.change >= 0 ? STATUS.good : STATUS.critical, borderRadius: r.change >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4] },
          label: {
            show: true, position: 'right', color: t.ink2, fontSize: 11,
            formatter: `${signed(r.change)}${r.contrib !== null && r.change > 0 ? `  ·  ${r.contrib.toFixed(0)}% of growth` : ''}`,
          },
        })),
      }],
    } as EChartsOption;
  }, [rows, t]);

  const td = p.td_change;
  return (
    <ChartCard
      className={className}
      title="Where this month's change came from"
      subtitle={`Sales ${signed(td)} vs ${s.compare.prev} (${p.td_growth_pct === null ? '–' : `${p.td_growth_pct > 0 ? '+' : ''}${p.td_growth_pct.toFixed(1)}%`}), split by category`}
      option={option}
      height={Math.max(220, rows.length * 32 + 30)}
      table={{
        columns: ['Category', 'Last month', 'This month', 'Change', 'Share of growth'],
        rows: rows.map((r) => [r.name, r.c ? inr(r.c.prev_sales) : '–', r.c ? inr(r.c.sales) : '–', signed(r.change), r.contrib === null ? '–' : `${r.contrib.toFixed(0)}%`]),
      }}
    />
  );
}

/** "OR11 -mens-ribcollar-half-sleeve-t-shirt" -> "Mens ribcollar half sleeve t shirt" */
function cleanName(m: StyleChange) {
  const n = (m.name ?? '').replace(m.style, '').trim().replace(/^[-–\s]+/, '');
  const words = /\s/.test(n) ? n : n.replace(/-/g, ' ');
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : '';
}

function StyleMovers({ gainers, decliners, prev, className }: { gainers: StyleChange[]; decliners: StyleChange[]; prev: string; className?: string }) {
  const max = Math.max(...[...gainers, ...decliners].map((m) => Math.abs(m.change)), 1);
  const Row = ({ m }: { m: StyleChange }) => (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 py-1" title={m.name ?? undefined}>
      <span className="truncate text-sm text-ink">
        <b className="font-semibold">{m.style}</b> <span className="text-xs text-muted">{cleanName(m)}</span>
      </span>
      <span className={cx('text-right text-xs font-medium tabular-nums', m.change > 0 ? 'text-good' : 'text-bad')}>{signed(m.change)}</span>
      <div className="col-span-2 h-1 rounded-full bg-sunken">
        <div className={cx('h-1 rounded-full', m.change > 0 ? 'bg-good' : 'bg-bad')} style={{ width: `${(Math.abs(m.change) / max) * 100}%` }} />
      </div>
    </li>
  );
  return (
    <Card className={className} title="Styles that moved the month" subtitle={`Sales change vs ${prev}`}>
      <div className="mb-1 text-xs font-medium text-good">Gained</div>
      {gainers.length ? <ul>{gainers.map((m) => <Row key={m.style} m={m} />)}</ul> : <p className="text-xs text-muted">None</p>}
      <div className="mb-1 mt-3 text-xs font-medium text-bad">Lost</div>
      {decliners.length ? <ul>{decliners.map((m) => <Row key={m.style} m={m} />)}</ul> : <p className="text-xs text-muted">None</p>}
    </Card>
  );
}

const CALL: Record<ProductCall, { label: string; cls: string }> = {
  scale: { label: 'Scale', cls: 'text-good' },
  defend: { label: 'Defend', cls: 'text-warn' },
  fix: { label: 'Fix stock', cls: 'text-bad' },
  watch: { label: 'Watch', cls: 'text-muted' },
};
const SCORE_ROWS = 10;

function CategoryScorecard({ s }: { s: Scorecard }) {
  const p = s.products;
  const live = p.categories.filter((c) => c.sales > 0);
  const top = live.slice(0, SCORE_ROWS);
  const rest = live.slice(SCORE_ROWS);
  const restSales = rest.reduce((a, c) => a + c.sales, 0);
  const total = live.reduce((a, c) => a + c.sales, 0) || 1;
  const hasStock = p.stock !== null;
  const hasYoy = !!s.compare.last_year;
  return (
    <Card className="mt-4" title="Category scorecard" subtitle={`${s.compare.current} vs ${s.compare.prev}${hasYoy ? ` and ${s.compare.last_year}` : ''} · Category III`} bodyClass="p-0">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[960px] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th className="px-4 py-2 font-medium">Category</th>
              <th className="whitespace-nowrap px-3 py-2 text-right font-medium">Sales</th>
              <th className="whitespace-nowrap px-3 py-2 text-right font-medium" title="Share of total sales, last month → this month">Share of sales</th>
              <th className="whitespace-nowrap px-3 py-2 text-right font-medium">MoM</th>
              <th className="whitespace-nowrap px-3 py-2 text-right font-medium">YoY</th>
              <th className="whitespace-nowrap px-3 py-2 text-right font-medium" title={p.td_change > 0 ? 'Category ₹ change ÷ TD ₹ change' : 'Sales did not grow this month, so the ₹ change is shown'}>{p.td_change > 0 ? 'Share of growth' : '₹ change'}</th>
              <th className="whitespace-nowrap px-3 py-2 text-right font-medium" title="Share of this month's buying retailers who bought the category">Retailer reach</th>
              <th className="whitespace-nowrap px-3 py-2 text-right font-medium" title="Sales ÷ units, change vs last month">Price / unit</th>
              <th className="whitespace-nowrap px-3 py-2 text-right font-medium" title="30-day demand (units × price) on SKU lines now at zero stock at distributors">Stock-outs</th>
              <th className="px-4 py-2 font-medium">Call</th>
            </tr>
          </thead>
          <tbody>
            {top.map((c) => (
              <tr key={c.key} className="border-b border-line/60">
                <td className="px-4 py-2 font-medium text-ink">
                  {c.name}
                  {c.top_style && <span className="block text-2xs font-normal text-muted">top style {c.top_style}</span>}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-ink">{inr(c.sales)}</td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-ink2">
                  {shareMove(c)}
                  <span className="block text-2xs"><Change v={c.share_change_pp} f="pct" /></span>
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right">{c.mom_pct === null ? <span className="text-xs text-muted">new</span> : <Change v={c.mom_pct} f="inr" />}</td>
                <td className="whitespace-nowrap px-3 py-2 text-right"><Change v={c.yoy_pct} f="inr" /></td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-ink2">
                  {c.growth_contrib_pct === null ? <span className="text-muted">{signed(c.change)}</span> : `${c.growth_contrib_pct.toFixed(0)}%`}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-ink2">{pct(c.reach_pct, 0)}<span className="block text-2xs text-muted">{num(c.retailers)} retailers</span></td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-ink2">
                  {inr(c.asp)}
                  <span className="block text-2xs"><Change v={c.asp_change_pct} f="inr" /></span>
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">
                  {c.oos_value === null ? <span className="text-muted">–</span> : c.oos_value ? (
                    <span className="text-bad">{inr(c.oos_value)}<span className="block text-2xs text-muted">{num(c.oos_lines)} lines</span></span>
                  ) : <span className="text-muted">none</span>}
                </td>
                <td className="px-4 py-2" title={c.call_reason}>
                  <span className={cx('text-xs font-semibold', CALL[c.call].cls)}>{CALL[c.call].label}</span>
                  <span className="block max-w-[14rem] text-2xs leading-snug text-muted">{c.call_reason}</span>
                </td>
              </tr>
            ))}
            {rest.length > 0 && (
              <tr className="text-muted" title={rest.map((c) => c.name).join(', ')}>
                <td className="px-4 py-2">Other ({rest.length} categories)</td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">{inr(restSales)}</td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">{pct((restSales / total) * 100, 1)}</td>
                <td colSpan={7} />
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="border-t border-line px-4 py-2 text-2xs text-muted">
        pp = percentage points: the change in a category's share of total sales, not in its sales (Trackpants can grow and still lose share when TD grows faster).
        Call: <b>Scale</b> = growing faster than TD; <b>Defend</b> = a big category ({`≥ ${p.fair_share_pct}%`} of sales) growing slower than TD; <b>Fix stock</b> = losing share while 15%+ of its demand sits at zero stock;
        <b> Watch</b> = small and losing share.
        {hasStock ? ' Stock-outs use live distributor stock and the last 30 days of sales.' : ' Stock-outs are shown for the month in progress only (stock is a live snapshot).'}
        {s.partial ? ` A month in progress is compared on the same days (${s.compare.prev}).` : ''}
      </p>
    </Card>
  );
}

/** Top 10 styles (overall or per category) and top 10 new launches, over the last 30 / 60 days. */
function Leaders({ s }: { s: Scorecard }) {
  const L = s.products.leaders;
  const [days, setDays] = useState(String(L.windows[0]));
  const [cat, setCat] = useState('');
  const w = L[days];
  if (!w) return null;
  const rows = cat ? w.by_category[cat] ?? [] : w.all;
  const catName = w.categories.find((c) => c.key === cat)?.name;
  const range = `${dmy(w.from)} – ${dmy(w.to)} vs ${dmy(w.prev_from)} – ${dmy(w.prev_to)}`;
  const switcher = <Segmented value={days} onChange={setDays} size="xs" options={L.windows.map((d) => ({ value: String(d), label: `${d} days` }))} />;

  return (
    <div className="mt-4 grid gap-4 2xl:grid-cols-2">
      <Card
        title={cat ? `Top 10 ${catName} styles` : 'Top 10 styles'}
        subtitle={`Last ${days} days by sales · ${range}`}
        actions={switcher}
        bodyClass="p-0"
      >
        <div className="flex flex-wrap gap-1.5 border-b border-line px-4 py-2.5">
          <button className={cx('chip text-xs', !cat ? 'border-brand bg-brand/10 text-ink' : 'text-ink2')} onClick={() => setCat('')}>All categories</button>
          {w.categories.slice(0, 12).map((c) => (
            <button key={c.key} className={cx('chip text-xs', cat === c.key ? 'border-brand bg-brand/10 text-ink' : 'text-ink2')}
              onClick={() => setCat(cat === c.key ? '' : c.key)} title={`${inr(c.sales)} · ${c.styles} styles sold`}>
              {c.name}
            </button>
          ))}
          {w.categories.length > 12 && (
            <select className="rounded-md border border-line bg-surface px-2 py-0.5 text-xs" aria-label="More categories"
              value={w.categories.slice(12).some((c) => c.key === cat) ? cat : ''} onChange={(e) => setCat(e.target.value)}>
              <option value="">More…</option>
              {w.categories.slice(12).map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
            </select>
          )}
        </div>
        <LeaderTable rows={rows} mode={cat ? 'category' : 'all'} />
        <p className="border-t border-line px-4 py-2 text-2xs text-muted">
          vs prev = sales change against the {days} days just before. {cat ? 'Share = of the category\'s sales.' : 'Share = of all TD sales in the window.'}
        </p>
      </Card>

      <Card
        title="Top 10 new launches"
        subtitle={`Styles launched in the last ${L.new_launch_days} days, ranked by sales in the last ${days} days`}
        actions={switcher}
        bodyClass="p-0"
      >
        <div className="grid grid-cols-3 divide-x divide-line border-b border-line text-center">
          <div className="px-3 py-2"><div className="text-2xs text-muted">New styles</div><div className="font-semibold tabular-nums text-ink">{num(w.new_launches_count)}</div></div>
          <div className="px-3 py-2"><div className="text-2xs text-muted">Sold in {days} days</div><div className="font-semibold tabular-nums text-ink">{num(w.new_launches_selling)}</div></div>
          <div className="px-3 py-2"><div className="text-2xs text-muted">Their sales</div><div className="font-semibold tabular-nums text-ink">{inr(w.new_launch_sales)} <span className="text-2xs font-normal text-muted">{pct(w.total ? (w.new_launch_sales / w.total) * 100 : null, 1)} of TD</span></div></div>
        </div>
        <LeaderTable rows={w.new_launches} mode="new" />
        <p className="border-t border-line px-4 py-2 text-2xs text-muted">
          Launched = first launch date of the style in the catalogue. ₹ / day = sales ÷ days live in the window, so styles launched a few days ago compare fairly with older ones.
        </p>
      </Card>
    </div>
  );
}

function LeaderTable({ rows, mode }: { rows: LeaderRow[]; mode: 'all' | 'category' | 'new' }) {
  if (!rows.length) return <p className="px-4 py-6 text-sm text-muted">Nothing sold in this window.</p>;
  const max = Math.max(...rows.map((r) => r.sales), 1);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-muted">
            <th className="w-8 px-4 py-2 font-medium">#</th>
            <th className="px-2 py-2 font-medium">Style</th>
            {mode === 'new' ? <th className="px-2 py-2 font-medium">Launched</th> : null}
            <th className="w-40 px-2 py-2 text-right font-medium">Sales</th>
            <th className="px-2 py-2 text-right font-medium">{mode === 'new' ? '₹ / day' : 'vs prev'}</th>
            <th className="px-2 py-2 text-right font-medium">Units</th>
            <th className="px-2 py-2 text-right font-medium">Retailers</th>
            <th className="px-4 py-2 text-right font-medium">{mode === 'category' ? 'Share of cat.' : 'Share of TD'}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.style} className="border-b border-line/60 last:border-0">
              <td className="px-4 py-1.5 text-xs tabular-nums text-muted">{i + 1}</td>
              <td className="max-w-[16rem] px-2 py-1.5" title={r.name ?? undefined}>
                <div className="truncate"><b className="font-semibold text-ink">{r.style}</b> <span className="text-xs text-muted">{cleanName({ style: r.style, name: r.name } as StyleChange)}</span></div>
                {mode !== 'category' && <div className="text-2xs text-muted">{r.category}</div>}
              </td>
              {mode === 'new' ? (
                <td className="whitespace-nowrap px-2 py-1.5 text-xs text-ink2">{dmy(r.launched_on)}<span className="block text-2xs text-muted">{r.days_live} days live</span></td>
              ) : null}
              <td className="px-2 py-1.5">
                <div className="flex items-center justify-end gap-2">
                  <div className="h-1.5 w-16 rounded-full bg-sunken"><div className="h-1.5 rounded-full bg-brand" style={{ width: `${(r.sales / max) * 100}%` }} /></div>
                  <span className="w-16 text-right tabular-nums text-ink">{inr(r.sales)}</span>
                </div>
              </td>
              <td className="whitespace-nowrap px-2 py-1.5 text-right text-xs">
                {mode === 'new' ? <span className="tabular-nums text-ink2">{inr(r.sales_per_day)}</span>
                  : r.vs_prev_pct === null ? <span className="text-muted">new</span> : <Change v={r.vs_prev_pct} f="inr" />}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums text-ink2">{num(r.units)}</td>
              <td className="px-2 py-1.5 text-right tabular-nums text-ink2">{num(r.retailers)}</td>
              <td className="px-4 py-1.5 text-right tabular-nums text-ink2">{pct(mode === 'category' ? r.share_of_category_pct : r.share_of_td_pct, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
