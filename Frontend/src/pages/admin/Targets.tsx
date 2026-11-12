import { useRef, useState } from 'react';
import dayjs from 'dayjs';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCollection, useFilterOptions } from '@/api/hooks';
import type { ScopeType, Target, TargetMetric, UploadResult } from '@/api/types';
import { DataTable } from '@/components/DataTable';
import { PageHeader } from '@/components/PageHeader';
import { Badge, Card, Field, InlineError, Modal, Spinner } from '@/components/ui';
import { IconDownload, IconPlus, IconUpload } from '@/components/Icons';
import { del, download, errorMessage, patch, post } from '@/lib/api';
import { date, inr, monthLabel, num, titleCase } from '@/lib/format';

const METRICS: TargetMetric[] = ['sales', 'orders', 'new_retailers', 'active_retailers'];
const SCOPES: ScopeType[] = ['overall', 'region', 'state', 'asm', 'distributor'];

function fmtTarget(t: Pick<Target, 'metric' | 'value'>) {
  return t.metric === 'sales' ? inr(t.value) : num(t.value);
}

function InlineValue({ t, onSave }: { t: Target; onSave: (v: number) => Promise<unknown> }) {
  const [editing, setEditing] = useState(false);
  const [v, setV] = useState(String(t.value));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!editing)
    return (
      <button className="rounded px-1 hover:bg-sunken hover:underline" title="Click to edit" onClick={(e) => { e.stopPropagation(); setV(String(t.value)); setEditing(true); }}>
        {fmtTarget(t)}
      </button>
    );
  async function commit() {
    const n = Number(v);
    if (!Number.isFinite(n) || n < 0) return setErr('Enter a positive number');
    if (n === t.value) return setEditing(false);
    setBusy(true);
    try {
      await onSave(n);
      setEditing(false);
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <span className="inline-flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
      <input
        autoFocus
        className="input w-32 py-0.5 text-right text-xs"
        value={v}
        inputMode="decimal"
        onChange={(e) => { setV(e.target.value); setErr(null); }}
        onKeyDown={(e) => { if (e.key === 'Enter') void commit(); if (e.key === 'Escape') setEditing(false); }}
        onBlur={() => void commit()}
        aria-label="Target value"
      />
      {busy && <Spinner size={12} />}
      {err && <span className="text-2xs text-bad">{err}</span>}
    </span>
  );
}

export default function Targets() {
  const qc = useQueryClient();
  const [month, setMonth] = useState(dayjs().format('YYYY-MM'));
  const [metric, setMetric] = useState<string>('');
  const targets = useCollection<Target>('/masters/targets/', { month: month || undefined, metric: metric || undefined });
  const opts = useFilterOptions();
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ month: dayjs().format('YYYY-MM'), scope_type: 'overall' as ScopeType, scope_id: '', metric: 'sales' as TargetMetric, value: '', effective_from: dayjs().format('YYYY-MM-DD'), notes: '' });
  const [upload, setUpload] = useState<UploadResult | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const invalidate = () => qc.invalidateQueries({ queryKey: ['collection', '/masters/targets/'] });
  const save = useMutation({ mutationFn: ({ id, value }: { id: number; value: number }) => patch(`/masters/targets/${id}/`, { value }), onSuccess: invalidate });
  const remove = useMutation({ mutationFn: (id: number) => del(`/masters/targets/${id}/`), onSuccess: invalidate });
  const create = useMutation({
    mutationFn: () =>
      post('/masters/targets/', {
        month: form.month,
        scope_type: form.scope_type,
        scope_id: form.scope_type === 'overall' ? null : Number(form.scope_id),
        metric: form.metric,
        value: Number(form.value),
        effective_from: form.effective_from,
        notes: form.notes,
      }),
    onSuccess: () => {
      invalidate();
      setAdding(false);
    },
  });
  const uploadM = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append('file', file);
      // Browser sets multipart Content-Type with boundary for FormData.
      return post<UploadResult>('/masters/targets/upload/', fd);
    },
    onSuccess: (r) => {
      setUpload(r);
      invalidate();
    },
  });
  const template = useMutation({ mutationFn: () => download('/masters/targets/template/', undefined, 'targets_template.xlsx') });

  const o = opts.data;
  const scopeOptions: { id: number; name: string }[] =
    form.scope_type === 'region' ? (o?.regions ?? []) : form.scope_type === 'state' ? (o?.states ?? []) : form.scope_type === 'asm' ? (o?.asms ?? []) : form.scope_type === 'distributor' ? (o?.distributors ?? []) : [];

  return (
    <div>
      <PageHeader
        title="Targets"
        subtitle="Monthly targets by scope · versioned and audited · click a value to edit"
        showBasis={false}
        actions={
          <>
            <button className="btn btn-sm" onClick={() => template.mutate()} disabled={template.isPending}>
              {template.isPending ? <Spinner size={12} /> : <IconDownload size={13} />} Excel template
            </button>
            <button className="btn btn-sm" onClick={() => fileRef.current?.click()} disabled={uploadM.isPending}>
              {uploadM.isPending ? <Spinner size={12} /> : <IconUpload size={13} />} Upload
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx,.xls,.csv"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) uploadM.mutate(f);
                e.target.value = '';
              }}
            />
            <button className="btn-primary btn-sm" onClick={() => setAdding(true)}>
              <IconPlus size={13} /> Add target
            </button>
          </>
        }
      />

      <InlineError error={template.error ?? uploadM.error ?? save.error ?? remove.error} />

      {upload && (
        <Card className="mb-4" title="Upload result" actions={<button className="btn btn-sm" onClick={() => setUpload(null)}>Dismiss</button>}>
          <div className="flex flex-wrap gap-2 text-sm">
            <Badge tone="good" icon>{num(upload.created)} created</Badge>
            <Badge tone="brand">{num(upload.updated)} updated</Badge>
            <Badge tone={upload.errors.length ? 'bad' : 'neutral'} icon={!!upload.errors.length}>{num(upload.errors.length)} rows with errors</Badge>
          </div>
          {upload.errors.length > 0 && (
            <div className="mt-3 max-h-60 overflow-auto rounded-md border border-line">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-sunken"><tr><th className="th w-20">Row</th><th className="th">Error</th></tr></thead>
                <tbody>
                  {upload.errors.map((e, i) => (
                    <tr key={i} className="border-t border-line"><td className="px-3 py-1.5 tabular">{e.row}</td><td className="px-3 py-1.5 text-bad">{e.message}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      <Card>
        <DataTable
          rows={targets.data}
          loading={targets.isLoading}
          error={targets.error}
          onRetry={() => targets.refetch()}
          rowKey={(r) => r.id}
          exportName={`targets_${month || 'all'}`}
          exportPath="/masters/targets/"
          exportParams={{ month: month || undefined, metric: metric || undefined }}
          initialSort={{ key: 'scope_type', dir: 'asc' }}
          pageSize={50}
          toolbar={
            <>
              <input type="month" className="input w-40 py-1 text-xs" value={month} onChange={(e) => setMonth(e.target.value)} aria-label="Month" />
              <select className="rounded-md border border-line bg-surface px-2 py-1 text-xs" value={metric} onChange={(e) => setMetric(e.target.value)} aria-label="Metric">
                <option value="">All metrics</option>
                {METRICS.map((m) => <option key={m} value={m}>{titleCase(m)}</option>)}
              </select>
            </>
          }
          columns={[
            { key: 'month', header: 'Month', render: (r) => monthLabel(r.month) },
            { key: 'scope_type', header: 'Scope', render: (r) => titleCase(r.scope_type) },
            { key: 'scope_name', header: 'Name', render: (r) => <span className="font-medium">{r.scope_name || 'All India'}</span> },
            { key: 'metric', header: 'Metric', render: (r) => titleCase(r.metric) },
            { key: 'value', header: 'Target', align: 'right', render: (r) => <InlineValue t={r} onSave={(value) => save.mutateAsync({ id: r.id, value })} /> },
            { key: 'effective_from', header: 'Effective from', render: (r) => date(r.effective_from) },
            { key: 'notes', header: 'Notes', render: (r) => <span className="text-xs text-ink2">{r.notes || '–'}</span> },
            {
              key: 'del',
              header: '',
              sortable: false,
              noExport: true,
              render: (r) => (
                <button className="btn btn-sm text-bad" onClick={() => window.confirm('Delete this target?') && remove.mutate(r.id)}>
                  Delete
                </button>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        open={adding}
        onClose={() => setAdding(false)}
        title="Add target"
        footer={
          <>
            <button className="btn" onClick={() => setAdding(false)}>Cancel</button>
            <button className="btn-primary" disabled={create.isPending || !form.value || (form.scope_type !== 'overall' && !form.scope_id)} onClick={() => create.mutate()}>Save</button>
          </>
        }
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Month"><input type="month" className="input" value={form.month} onChange={(e) => setForm({ ...form, month: e.target.value })} /></Field>
          <Field label="Metric">
            <select className="input" value={form.metric} onChange={(e) => setForm({ ...form, metric: e.target.value as TargetMetric })}>
              {METRICS.map((m) => <option key={m} value={m}>{titleCase(m)}</option>)}
            </select>
          </Field>
          <Field label="Scope type">
            <select className="input" value={form.scope_type} onChange={(e) => setForm({ ...form, scope_type: e.target.value as ScopeType, scope_id: '' })}>
              {SCOPES.map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
            </select>
          </Field>
          <Field label="Scope">
            <select className="input" value={form.scope_id} disabled={form.scope_type === 'overall'} onChange={(e) => setForm({ ...form, scope_id: e.target.value })}>
              <option value="">{form.scope_type === 'overall' ? 'All India' : 'Select…'}</option>
              {scopeOptions.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </Field>
          <Field label={form.metric === 'sales' ? 'Target value (₹)' : 'Target value'} hint={form.metric === 'sales' && form.value ? inr(Number(form.value)) : undefined}>
            <input className="input" inputMode="decimal" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
          </Field>
          <Field label="Effective from"><input type="date" className="input" value={form.effective_from} onChange={(e) => setForm({ ...form, effective_from: e.target.value })} /></Field>
          <div className="sm:col-span-2"><Field label="Notes"><input className="input" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field></div>
        </div>
        <div className="mt-3"><InlineError error={create.error} /></div>
      </Modal>
    </div>
  );
}
