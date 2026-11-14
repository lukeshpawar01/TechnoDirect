import { useMemo } from 'react';
import { useFilterOptions } from '@/api/hooks';
import { PRESETS, useFilters, type Preset } from '@/lib/filters';
import { ALL_TOP_FILTERS, type TopFilter } from '@/nav';
import { MultiSelect } from './MultiSelect';
import { IconX } from './Icons';

const PRESET_GROUPS = PRESETS.filter((p) => !('hidden' in p && p.hidden)).reduce<{ group: string; items: { value: string; label: string }[] }[]>(
  (acc, p) => {
    const last = acc[acc.length - 1];
    if (last && last.group === p.group) last.items.push(p);
    else acc.push({ group: p.group, items: [p] });
    return acc;
  },
  [],
);

/** FY quarter presets whose first day is still in the future (IST date of this browser). */
const QUARTER_FIRST_MONTH: Record<string, number> = { q1: 4, q2: 7, q3: 10, q4: 1 };
function notStartedQuarters(now = new Date()): Set<string> {
  const ist = new Date(now.getTime() + (330 + now.getTimezoneOffset()) * 60_000);
  const y = ist.getFullYear();
  const m = ist.getMonth() + 1;
  const fyStart = m >= 4 ? y : y - 1;
  const out = new Set<string>();
  for (const [q, first] of Object.entries(QUARTER_FIRST_MONTH)) {
    const start = new Date(first >= 4 ? fyStart : fyStart + 1, first - 1, 1);
    if (start > ist) out.add(q);
  }
  return out;
}

const TOP_KEYS: Record<TopFilter, string[]> = {
  date: ['preset', 'date_from', 'date_to'],
  region: ['region'],
  state: ['state'],
  asm: ['asm'],
  distributor: ['distributor'],
  category: ['category'],
};

/**
 * Global filter bar — "when & where", one row above everything it scopes. State lives in the URL and follows
 * you across pages. Each page shows only the filters its data responds to (`visible`, from nav.tsx);
 * page-specific filters live in the module row (ModuleFilters).
 */
export function FilterBar({ visible = ALL_TOP_FILTERS }: { visible?: TopFilter[] }) {
  const { filters, update, reset } = useFilters();
  const opts = useFilterOptions();
  const o = opts.data;
  const show = new Set(visible);
  const future = useMemo(() => notStartedQuarters(), []);

  const regionSet = new Set(filters.region);
  const stateSet = new Set(filters.state);

  const regionOpts = useMemo(() => (o?.regions ?? []).map((r) => ({ value: String(r.id), label: r.name })), [o]);
  // Cascade: states/ASMs narrow by region, distributors by state (or region via state).
  const stateOpts = useMemo(
    () => (o?.states ?? []).filter((s) => regionSet.size === 0 || regionSet.has(String(s.region_id))).map((s) => ({ value: String(s.id), label: s.name })),
    [o, filters.region.join()], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const asmOpts = useMemo(
    () => (o?.asms ?? []).filter((a) => regionSet.size === 0 || regionSet.has(String(a.region_id))).map((a) => ({ value: String(a.id), label: a.name })),
    [o, filters.region.join()], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const distOpts = useMemo(() => {
    const allowedStates = stateSet.size ? stateSet : regionSet.size ? new Set(stateOpts.map((s) => s.value)) : null;
    return (o?.distributors ?? []).filter((d) => !allowedStates || allowedStates.has(String(d.state_id))).map((d) => ({ value: String(d.id), label: d.name }));
  }, [o, filters.state.join(), stateOpts]); // eslint-disable-line react-hooks/exhaustive-deps
  const catOpts = useMemo(() => (o?.categories ?? []).map((c) => ({ value: c.code, label: c.name })), [o]);

  const active =
    (show.has('date') && filters.preset !== 'mtd') ||
    (show.has('region') && filters.region.length > 0) ||
    (show.has('state') && filters.state.length > 0) ||
    (show.has('asm') && filters.asm.length > 0) ||
    (show.has('distributor') && filters.distributor.length > 0) ||
    (show.has('category') && filters.category.length > 0);

  return (
    <div className="flex flex-wrap items-center gap-2" aria-label="Global filters">
      {show.has('date') && (
        <>
          <label className="sr-only" htmlFor="preset">
            Date range
          </label>
          <select
            id="preset"
            value={filters.preset}
            onChange={(e) => {
              const p = e.target.value as Preset;
              if (p === 'custom') {
                const today = new Date().toISOString().slice(0, 10);
                update({ preset: p, date_from: filters.date_from ?? today.slice(0, 8) + '01', date_to: filters.date_to ?? today });
              } else update({ preset: p, date_from: undefined, date_to: undefined });
            }}
            className="rounded-md border border-brand/50 bg-surface px-2 py-1.5 text-xs font-medium text-ink"
          >
            {PRESET_GROUPS.map((g) => (
              <optgroup key={g.group} label={g.group}>
                {g.items.map((p) => (
                  <option key={p.value} value={p.value} disabled={future.has(p.value)}>
                    {p.label}
                    {future.has(p.value) ? ' (not started)' : ''}
                  </option>
                ))}
              </optgroup>
            ))}
            {/* an old link may carry a hidden preset (e.g. qtd): keep it selectable so the select isn't blank */}
            {PRESETS.filter((p) => 'hidden' in p && p.hidden && p.value === filters.preset).map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
          {filters.preset === 'custom' && (
            <div className="flex items-center gap-1 text-xs">
              <input type="date" aria-label="From date" className="input w-[8.5rem] py-1 text-xs" value={filters.date_from ?? ''} max={filters.date_to} onChange={(e) => update({ date_from: e.target.value })} />
              <span className="text-muted">to</span>
              <input type="date" aria-label="To date" className="input w-[8.5rem] py-1 text-xs" value={filters.date_to ?? ''} min={filters.date_from} onChange={(e) => update({ date_to: e.target.value })} />
            </div>
          )}
        </>
      )}
      {show.has('region') && <MultiSelect label="Region" options={regionOpts} value={filters.region} onChange={(v) => update({ region: v })} disabled={opts.isLoading} width="w-36" />}
      {show.has('state') && <MultiSelect label="State" options={stateOpts} value={filters.state} onChange={(v) => update({ state: v })} disabled={opts.isLoading} width="w-36" />}
      {show.has('asm') && <MultiSelect label="ASM" options={asmOpts} value={filters.asm} onChange={(v) => update({ asm: v })} disabled={opts.isLoading} width="w-36" />}
      {show.has('distributor') && <MultiSelect label="Distributor" options={distOpts} value={filters.distributor} onChange={(v) => update({ distributor: v })} disabled={opts.isLoading} width="w-44" />}
      {show.has('category') && <MultiSelect label="Category" options={catOpts} value={filters.category} onChange={(v) => update({ category: v, cat_l2: undefined, cat_l3: undefined })} disabled={opts.isLoading} width="w-40" />}
      {active && (
        <button
          className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs text-ink2 hover:bg-sunken hover:text-ink"
          onClick={() => reset(visible.flatMap((f) => TOP_KEYS[f]))}
          title="Clear the filters shown in this bar"
        >
          <IconX size={12} /> Reset
        </button>
      )}
      {opts.error ? <span className="text-xs text-bad">Filter options unavailable</span> : null}
    </div>
  );
}
