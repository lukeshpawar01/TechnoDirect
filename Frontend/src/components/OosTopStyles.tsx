import { Fragment, useMemo, useState } from 'react';
import { useAnalytics, useFilterOptions } from '@/api/hooks';
import { Card, ErrorState, cx } from '@/components/ui';
import { IconChevron, IconChevronDown, IconDownload } from '@/components/Icons';
import { num } from '@/lib/format';

interface OosDistributor {
  distributor_id: number; distributor: string; state: string | null; region: string | null;
  asm: string | null; rsm: string | null; sizes: string[]; units_sold: number;
}
interface OosStyle {
  style: string; name: string | null; category: string | null; units_sold: number;
  distributors_carrying: number; distributors_oos: number; distributors_oos_with_demand: number; oos_lines: number;
  distributors: OosDistributor[];
}
interface OosStylesData {
  styles: OosStyle[];
  by_category: { category: string; styles: number; distributors: number; units_sold: number }[];
  sold_days: number;
}

type Scope = { region: string; rsm: string; state: string; asm: string };
const EMPTY: Scope = { region: '', rsm: '', state: '', asm: '' };

/**
 * Inventory: top-selling styles that are out of stock, and at which distributors.
 * Its own small Region / RSM / State / ASM filter (on top of the page filters); click a style for its distributors.
 */
export function OosTopStyles({ soldDays }: { soldDays: string }) {
  const [scope, setScope] = useState<Scope>(EMPTY);
  const [open, setOpen] = useState<string | null>(null);
  const [cat, setCat] = useState('');
  const o = useFilterOptions().data;
  const params = Object.fromEntries(Object.entries(scope).filter(([, v]) => v));
  const q = useAnalytics<OosStylesData>('/inventory/oos-styles/', { sold_days: soldDays, ...params });
  const d = q.data?.data;
  const styles = useMemo(() => (d?.styles ?? []).filter((s) => !cat || (s.category ?? 'Uncategorised') === cat), [d, cat]);
  const maxUnits = Math.max(...styles.map((s) => s.units_sold), 1);

  // narrow the lists to the region / RSM picked, so the dropdowns stay short
  const rsms = (o?.rsms ?? []).filter((r) => !scope.region || String(r.region_id) === scope.region);
  const states = (o?.states ?? []).filter((s) => !scope.region || String(s.region_id) === scope.region);
  const asms = (o?.asms ?? []).filter((a) => (!scope.region || String(a.region_id) === scope.region) && (!scope.rsm || String(a.rsm_id) === scope.rsm));
  const set = (k: keyof Scope, v: string) => {
    setOpen(null);
    setScope((s) => (k === 'region' ? { ...EMPTY, region: v } : k === 'rsm' ? { ...s, rsm: v, asm: '' } : { ...s, [k]: v }));
  };
  const sel = (k: keyof Scope, label: string, items: { id: number; name: string }[]) => (
    <select
      aria-label={label}
      className={cx('rounded-md border bg-surface px-2 py-1 text-xs', scope[k] ? 'border-brand text-ink' : 'border-line text-ink2')}
      value={scope[k]}
      onChange={(e) => set(k, e.target.value)}
    >
      <option value="">{label}: all</option>
      {items.map((i) => <option key={i.id} value={String(i.id)}>{i.name}</option>)}
    </select>
  );

  const download = () => {
    const head = ['Style', 'Article', 'Category', `Units sold (${soldDays} d)`, 'Distributor', 'Region', 'State', 'RSM', 'ASM', 'Sizes at zero', 'Distributor units sold'];
    const rows = styles.flatMap((s) => s.distributors.map((x) => [s.style, s.name ?? '', s.category ?? '', s.units_sold, x.distributor, x.region ?? '', x.state ?? '', x.rsm ?? '', x.asm ?? '', x.sizes.join(' '), x.units_sold]));
    const csv = [head, ...rows].map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\r\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' }));
    a.download = `oos_top_styles_${soldDays}d.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <Card
      className="mt-4"
      title="Out-of-stock top styles"
      subtitle={`Best sellers of the last ${soldDays} days with sizes at zero stock, and the distributors that are out. Click a style for its distributors.`}
      actions={
        <div className="flex flex-wrap items-center gap-1.5">
          {sel('region', 'Region', o?.regions ?? [])}
          {sel('rsm', 'RSM', rsms)}
          {sel('state', 'State', states)}
          {sel('asm', 'ASM', asms)}
          {Object.values(scope).some(Boolean) && <button className="btn btn-sm" onClick={() => { setScope(EMPTY); setOpen(null); }}>Clear</button>}
          <button className="btn btn-sm" onClick={download} disabled={!styles.length} title="Download style × distributor rows as CSV"><IconDownload size={13} /> CSV</button>
        </div>
      }
      bodyClass="p-0"
    >
      {q.error && !q.data ? (
        <div className="p-4"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>
      ) : (
        <>
          {d && d.by_category.length > 0 && (
            <div className="flex flex-wrap gap-1.5 border-b border-line px-4 py-2.5">
              <button className={cx('chip text-xs', !cat ? 'border-brand bg-brand/10 text-ink' : 'text-ink2')} onClick={() => setCat('')}>All categories</button>
              {d.by_category.map((c) => (
                <button
                  key={c.category}
                  className={cx('chip text-xs', cat === c.category ? 'border-brand bg-brand/10 text-ink' : 'text-ink2')}
                  onClick={() => { setCat(cat === c.category ? '' : c.category); setOpen(null); }}
                  title={`${c.styles} styles out at ${c.distributors} distributors; ${num(c.units_sold)} units sold`}
                >
                  {c.category} <span className="tabular-nums text-muted">{c.styles}</span>
                </button>
              ))}
            </div>
          )}
          <div className="max-h-[36rem] overflow-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="sticky top-0 z-[1] bg-surface">
                <tr className="border-b border-line text-left text-xs text-muted">
                  <th className="px-4 py-2 font-medium">Style</th>
                  <th className="px-3 py-2 font-medium">Category</th>
                  <th className="px-3 py-2 text-right font-medium">Units sold ({soldDays} d)</th>
                  <th className="w-64 px-3 py-2 font-medium" title="Distributors carrying the style with at least one size at zero">Out of stock at</th>
                  <th className="px-4 py-2 text-right font-medium" title="Out-of-stock distributors that sold this style in the window">Of them selling it</th>
                </tr>
              </thead>
              <tbody>
                {q.isLoading && <tr><td colSpan={5} className="px-4 py-8 text-center text-sm text-muted">Loading…</td></tr>}
                {!q.isLoading && styles.length === 0 && (
                  <tr><td colSpan={5} className="px-4 py-8 text-center text-sm text-muted">No top seller is out of stock for this selection.</td></tr>
                )}
                {styles.map((s) => {
                  const isOpen = open === s.style;
                  const share = s.distributors_carrying ? (s.distributors_oos / s.distributors_carrying) * 100 : 0;
                  return (
                    <Fragment key={s.style}>
                      <tr className={cx('cursor-pointer border-b border-line/60 hover:bg-sunken/40', isOpen && 'bg-sunken/40')} onClick={() => setOpen(isOpen ? null : s.style)}>
                        <td className="px-4 py-2">
                          <div className="flex items-center gap-1.5">
                            {isOpen ? <IconChevronDown size={13} className="text-muted" /> : <IconChevron size={13} className="text-muted" />}
                            <span className="font-semibold text-ink">{s.style}</span>
                            <span className="truncate text-xs text-muted" title={s.name ?? undefined}>{(s.name ?? '').replace(s.style, '').trim()}</span>
                          </div>
                        </td>
                        <td className="px-3 py-2 text-xs text-ink2">{s.category ?? '–'}</td>
                        <td className="px-3 py-2">
                          <div className="flex items-center justify-end gap-2">
                            <div className="h-1.5 w-20 rounded-full bg-sunken"><div className="h-1.5 rounded-full bg-brand" style={{ width: `${(s.units_sold / maxUnits) * 100}%` }} /></div>
                            <span className="w-14 text-right tabular-nums text-ink">{num(s.units_sold)}</span>
                          </div>
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 flex-1 rounded-full bg-sunken"><div className={cx('h-1.5 rounded-full', share >= 50 ? 'bg-bad' : 'bg-warn')} style={{ width: `${share}%` }} /></div>
                            <span className="w-28 whitespace-nowrap text-right text-xs tabular-nums text-ink2">{s.distributors_oos} of {s.distributors_carrying} distributors</span>
                          </div>
                        </td>
                        <td className={cx('px-4 py-2 text-right tabular-nums', s.distributors_oos_with_demand ? 'font-semibold text-bad' : 'text-muted')}>{s.distributors_oos_with_demand}</td>
                      </tr>
                      {isOpen && (
                        <tr className="border-b border-line bg-sunken/20">
                          <td colSpan={5} className="px-4 py-2">
                            <table className="w-full text-xs">
                              <thead>
                                <tr className="text-left text-muted">
                                  <th className="py-1 pl-5 pr-2 font-medium">Distributor</th>
                                  <th className="px-2 py-1 font-medium">State</th>
                                  <th className="px-2 py-1 font-medium">Region</th>
                                  <th className="px-2 py-1 font-medium">RSM</th>
                                  <th className="px-2 py-1 font-medium">ASM</th>
                                  <th className="px-2 py-1 font-medium">Sizes at zero</th>
                                  <th className="px-2 py-1 text-right font-medium">Sold here ({soldDays} d)</th>
                                </tr>
                              </thead>
                              <tbody>
                                {s.distributors.map((x) => (
                                  <tr key={x.distributor_id} className="border-t border-line/50">
                                    <td className="py-1.5 pl-5 pr-2 font-medium text-ink">{x.distributor}</td>
                                    <td className="px-2 py-1.5 text-ink2">{x.state ?? '–'}</td>
                                    <td className="px-2 py-1.5 text-ink2">{x.region ?? '–'}</td>
                                    <td className="px-2 py-1.5 text-ink2">{x.rsm ?? '–'}</td>
                                    <td className="px-2 py-1.5 text-ink2">{x.asm ?? '–'}</td>
                                    <td className="px-2 py-1.5">
                                      <div className="flex flex-wrap gap-1">
                                        {x.sizes.map((z) => <span key={z} className="rounded border border-bad/40 bg-bad/10 px-1 text-[11px] text-bad">{z}</span>)}
                                      </div>
                                    </td>
                                    <td className={cx('px-2 py-1.5 text-right tabular-nums', x.units_sold ? 'font-semibold text-ink' : 'text-muted')}>{num(x.units_sold)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="border-t border-line px-4 py-2 text-2xs text-muted">
            Top {d?.styles.length ?? 0} styles by units sold in the selection. "Out of stock at" counts distributors that stock the style with at least one size at zero; "of them selling it" are the ones that sold it in the last {soldDays} days, so each stock-out costs orders there.
          </p>
        </>
      )}
    </Card>
  );
}
