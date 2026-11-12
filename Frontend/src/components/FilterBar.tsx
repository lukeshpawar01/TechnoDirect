import { useMemo } from 'react';
import { useFilterOptions } from '@/api/hooks';
import { PRESETS, SEGMENTS, useFilters, type Preset } from '@/lib/filters';
import { MultiSelect } from './MultiSelect';
import { IconX } from './Icons';

/**
 * Global filter bar — one row above everything it scopes. State lives in the URL
 * so any view (and every drill-down) is a shareable link.
 */
export function FilterBar({ showSegment = true }: { showSegment?: boolean }) {
  const { filters, update, reset } = useFilters();
  const opts = useFilterOptions();
  const o = opts.data;

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
    filters.region.length + filters.state.length + filters.asm.length + filters.distributor.length + filters.category.length + (filters.segment ? 1 : 0) + (filters.payment_status ? 1 : 0) > 0 ||
    filters.preset !== 'mtd';

  return (
    <div className="flex flex-wrap items-center gap-2" aria-label="Global filters">
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
        {PRESETS.map((p) => (
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
      <MultiSelect label="Region" options={regionOpts} value={filters.region} onChange={(v) => update({ region: v })} disabled={opts.isLoading} width="w-36" />
      <MultiSelect label="State" options={stateOpts} value={filters.state} onChange={(v) => update({ state: v })} disabled={opts.isLoading} width="w-36" />
      <MultiSelect label="ASM" options={asmOpts} value={filters.asm} onChange={(v) => update({ asm: v })} disabled={opts.isLoading} width="w-36" />
      <MultiSelect label="Distributor" options={distOpts} value={filters.distributor} onChange={(v) => update({ distributor: v })} disabled={opts.isLoading} width="w-44" />
      <MultiSelect label="Category" options={catOpts} value={filters.category} onChange={(v) => update({ category: v })} disabled={opts.isLoading} width="w-40" />
      {showSegment && (
        <MultiSelect
          label="Segment"
          single
          options={SEGMENTS}
          value={filters.segment ? [filters.segment] : []}
          onChange={(v) => update({ segment: v[0] })}
          width="w-40"
        />
      )}
      <MultiSelect
        label="Payment"
        single
        options={(o?.payment_statuses ?? []).map((s) => ({ value: s, label: s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ') }))}
        value={filters.payment_status ? [filters.payment_status] : []}
        onChange={(v) => update({ payment_status: v[0] })}
        disabled={opts.isLoading}
        width="w-36"
      />
      {active && (
        <button className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs text-ink2 hover:bg-sunken hover:text-ink" onClick={reset}>
          <IconX size={12} /> Reset
        </button>
      )}
      {opts.error ? <span className="text-xs text-bad">Filter options unavailable</span> : null}
    </div>
  );
}
