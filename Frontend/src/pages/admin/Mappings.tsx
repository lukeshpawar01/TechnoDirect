import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCollection, useFilterOptions } from '@/api/hooks';
import type { FilterOptions } from '@/api/types';
import { DataTable, type Column } from '@/components/DataTable';
import { PageHeader } from '@/components/PageHeader';
import { Badge, Card, Field, InlineError, Modal, Tabs } from '@/components/ui';
import { IconPlus } from '@/components/Icons';
import { del, patch, post } from '@/lib/api';
import { num } from '@/lib/format';

type Row = Record<string, unknown> & { id: number };

interface FieldDef {
  key: string;
  label: string;
  type?: 'text' | 'number' | 'bool' | 'select' | 'email';
  options?: (o: FilterOptions | undefined) => { value: string; label: string }[];
  /** display column for select fields, e.g. state_id → state_name */
  display?: string;
  required?: boolean;
  hint?: string;
}

interface MasterDef {
  key: string;
  label: string;
  path: string;
  description: string;
  fields: FieldDef[];
}

const regionOpts = (o?: FilterOptions) => (o?.regions ?? []).map((x) => ({ value: String(x.id), label: x.name }));
const stateOpts = (o?: FilterOptions) => (o?.states ?? []).map((x) => ({ value: String(x.id), label: x.name }));
const asmOpts = (o?: FilterOptions) => (o?.asms ?? []).map((x) => ({ value: String(x.id), label: x.name }));

const MASTERS: MasterDef[] = [
  {
    key: 'asms',
    label: 'ASMs',
    path: '/masters/asms/',
    description: 'Area sales managers and their region.',
    fields: [
      { key: 'name', label: 'Name', required: true },
      { key: 'code', label: 'Code' },
      { key: 'email', label: 'Email', type: 'email' },
      { key: 'phone', label: 'Phone' },
      { key: 'region_id', label: 'Region', type: 'select', options: regionOpts, display: 'region_name', required: true },
      { key: 'is_active', label: 'Active', type: 'bool' },
    ],
  },
  {
    key: 'pincodes',
    label: 'Pincodes',
    path: '/masters/pincodes/',
    description: 'Pincode → state → ASM mapping used to attribute retailers.',
    fields: [
      { key: 'pincode', label: 'Pincode', required: true },
      { key: 'city', label: 'City / district' },
      { key: 'state_id', label: 'State', type: 'select', options: stateOpts, display: 'state_name', required: true },
      { key: 'asm_id', label: 'ASM', type: 'select', options: asmOpts, display: 'asm_name' },
    ],
  },
  {
    key: 'regions',
    label: 'Regions',
    path: '/masters/regions/',
    description: 'Sales regions.',
    fields: [
      { key: 'name', label: 'Name', required: true },
      { key: 'code', label: 'Code' },
    ],
  },
  {
    key: 'states',
    label: 'States',
    path: '/masters/states/',
    description: 'States and the region they roll up to.',
    fields: [
      { key: 'name', label: 'Name', required: true },
      { key: 'code', label: 'Code' },
      { key: 'region_id', label: 'Region', type: 'select', options: regionOpts, display: 'region_name', required: true },
    ],
  },
  {
    key: 'reconciliation',
    label: 'MIS reconciliation',
    path: '/masters/reconciliation/',
    description: 'Reference values from the existing MIS; Data Health compares the dashboard against these (1% tolerance).',
    fields: [
      { key: 'metric', label: 'Metric', required: true, hint: 'e.g. sales, orders, active_retailers' },
      { key: 'period', label: 'Period', required: true, hint: 'YYYY-MM' },
      { key: 'mis_value', label: 'MIS value', type: 'number', required: true },
      { key: 'notes', label: 'Notes' },
    ],
  },
];

function MasterTable({ def }: { def: MasterDef }) {
  const qc = useQueryClient();
  const q = useCollection<Row>(def.path);
  const opts = useFilterOptions();
  const [edit, setEdit] = useState<Record<string, unknown> | null>(null);
  const [search, setSearch] = useState('');
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['collection', def.path] });
    qc.invalidateQueries({ queryKey: ['meta', 'filters'] });
  };

  const save = useMutation({
    mutationFn: (r: Record<string, unknown>) => {
      const body: Record<string, unknown> = {};
      def.fields.forEach((f) => {
        const v = r[f.key];
        body[f.key] = f.type === 'number' || (f.type === 'select' && v !== '' && v != null) ? (v === '' || v == null ? null : Number(v)) : f.type === 'bool' ? !!v : (v ?? '');
      });
      return r.id ? patch(`${def.path}${r.id}/`, body) : post(def.path, body);
    },
    onSuccess: () => {
      invalidate();
      setEdit(null);
    },
  });
  const remove = useMutation({ mutationFn: (id: number) => del(`${def.path}${id}/`), onSuccess: invalidate });

  const labelFor = (f: FieldDef, r: Row) => {
    if (f.display && r[f.display]) return String(r[f.display]);
    if (f.options) return f.options(opts.data).find((o) => o.value === String(r[f.key]))?.label ?? (r[f.key] == null ? '–' : String(r[f.key]));
    return null;
  };

  const columns: Column<Row>[] = [
    ...def.fields.map<Column<Row>>((f) => ({
      key: f.key,
      header: f.label,
      align: f.type === 'number' ? 'right' : undefined,
      value: (r) => labelFor(f, r) ?? r[f.key],
      render: (r) => {
        const v = r[f.key];
        if (f.type === 'bool') return <Badge tone={v ? 'good' : 'neutral'}>{v ? 'Yes' : 'No'}</Badge>;
        if (f.type === 'number') return num(typeof v === 'number' ? v : Number(v));
        return labelFor(f, r) ?? (v == null || v === '' ? '–' : String(v));
      },
    })),
    {
      key: '_actions',
      header: '',
      sortable: false,
      noExport: true,
      align: 'right',
      render: (r) => (
        <div className="flex justify-end gap-1">
          <button className="btn btn-sm" onClick={() => setEdit({ ...r })}>Edit</button>
          <button className="btn btn-sm text-bad" onClick={() => window.confirm('Delete this row? This is audited.') && remove.mutate(r.id)}>Delete</button>
        </div>
      ),
    },
  ];

  const rows = (q.data ?? []).filter((r) => !search || JSON.stringify(r).toLowerCase().includes(search.toLowerCase()));
  const missingRequired = edit ? def.fields.some((f) => f.required && (edit[f.key] === '' || edit[f.key] == null)) : true;

  return (
    <>
      <p className="mb-3 text-xs text-muted">{def.description} Every change is versioned in the audit log.</p>
      <DataTable
        rows={rows}
        loading={q.isLoading}
        error={q.error}
        onRetry={() => q.refetch()}
        rowKey={(r) => r.id}
        exportName={def.key}
        exportPath={def.path}
        pageSize={50}
        toolbar={
          <>
            <input className="input w-52 py-1 text-xs" placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)} />
            <button className="btn-primary btn-sm" onClick={() => setEdit(Object.fromEntries(def.fields.map((f) => [f.key, f.type === 'bool' ? true : ''])))}>
              <IconPlus size={13} /> Add
            </button>
          </>
        }
        columns={columns}
      />
      <InlineError error={remove.error} />
      <Modal
        open={!!edit}
        onClose={() => setEdit(null)}
        title={`${edit?.id ? 'Edit' : 'Add'} · ${def.label}`}
        footer={
          <>
            <button className="btn" onClick={() => setEdit(null)}>Cancel</button>
            <button className="btn-primary" disabled={save.isPending || missingRequired} onClick={() => edit && save.mutate(edit)}>Save</button>
          </>
        }
      >
        {edit && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {def.fields.map((f) => (
              <div key={f.key}>
                {f.type === 'bool' ? (
                  <label className="flex items-center gap-2 pt-5 text-sm">
                    <input type="checkbox" checked={!!edit[f.key]} onChange={(e) => setEdit({ ...edit, [f.key]: e.target.checked })} /> {f.label}
                  </label>
                ) : f.type === 'select' ? (
                  <Field label={`${f.label}${f.required ? ' *' : ''}`}>
                    <select className="input" value={edit[f.key] == null ? '' : String(edit[f.key])} onChange={(e) => setEdit({ ...edit, [f.key]: e.target.value })}>
                      <option value="">Select…</option>
                      {f.options?.(opts.data).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                  </Field>
                ) : (
                  <Field label={`${f.label}${f.required ? ' *' : ''}`} hint={f.hint}>
                    <input
                      className="input"
                      type={f.type === 'email' ? 'email' : 'text'}
                      inputMode={f.type === 'number' ? 'decimal' : undefined}
                      value={edit[f.key] == null ? '' : String(edit[f.key])}
                      onChange={(e) => setEdit({ ...edit, [f.key]: e.target.value })}
                    />
                  </Field>
                )}
              </div>
            ))}
            <div className="sm:col-span-2"><InlineError error={save.error} /></div>
          </div>
        )}
      </Modal>
    </>
  );
}

export default function Mappings() {
  const [tab, setTab] = useState(MASTERS[0].key);
  const def = MASTERS.find((m) => m.key === tab) ?? MASTERS[0];
  return (
    <div>
      <PageHeader title="Mappings" subtitle="Master data that drives attribution and reconciliation" showBasis={false} />
      <Card bodyClass="p-0">
        <div className="px-4 pt-2">
          <Tabs value={tab} onChange={setTab} tabs={MASTERS.map((m) => ({ value: m.key, label: m.label }))} />
        </div>
        <div className="p-4">
          <MasterTable key={def.key} def={def} />
        </div>
      </Card>
    </div>
  );
}
