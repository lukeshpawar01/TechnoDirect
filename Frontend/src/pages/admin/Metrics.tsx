import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCollection } from '@/api/hooks';
import type { MetricDef } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { DataTable } from '@/components/DataTable';
import { PageHeader } from '@/components/PageHeader';
import { Card, Field, InlineError, Modal } from '@/components/ui';
import { patch } from '@/lib/api';

export default function Metrics() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const q = useCollection<MetricDef>('/masters/metrics/');
  const [edit, setEdit] = useState<MetricDef | null>(null);
  const [search, setSearch] = useState('');
  const editable = can('manage_metrics');

  // Contract: PATCH /masters/metrics/ with the metric's `code` in the body.
  const save = useMutation({
    mutationFn: (m: MetricDef) => patch('/masters/metrics/', m),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['collection', '/masters/metrics/'] });
      setEdit(null);
    },
  });

  const rows = (q.data ?? []).filter((m) => !search || `${m.code} ${m.name} ${m.definition}`.toLowerCase().includes(search.toLowerCase()));

  return (
    <div>
      <PageHeader title="Metric Dictionary" subtitle="How every number on this dashboard is defined" showBasis={false} />
      <Card>
        <DataTable
          rows={rows}
          loading={q.isLoading}
          error={q.error}
          onRetry={() => q.refetch()}
          rowKey={(r) => r.code}
          exportName="metric_dictionary"
          initialSort={{ key: 'name', dir: 'asc' }}
          pageSize={50}
          onRowClick={editable ? (r) => setEdit({ ...r }) : undefined}
          toolbar={<input className="input w-60 py-1 text-xs" placeholder="Search metrics…" value={search} onChange={(e) => setSearch(e.target.value)} />}
          columns={[
            { key: 'name', header: 'Metric', render: (r) => (<div><div className="font-medium">{r.name}</div><div className="font-mono text-2xs text-muted">{r.code}</div></div>) },
            { key: 'definition', header: 'Definition', render: (r) => <div className="max-w-md whitespace-normal text-xs text-ink2">{r.definition}</div> },
            { key: 'formula', header: 'Formula', render: (r) => <div className="max-w-xs whitespace-normal font-mono text-2xs">{r.formula}</div> },
            { key: 'source', header: 'Source' },
            { key: 'owner', header: 'Owner' },
            { key: 'refresh', header: 'Refresh' },
          ]}
        />
        {editable && <p className="mt-2 text-2xs text-muted">Click a row to edit. Changes are audited.</p>}
      </Card>
      <Modal
        open={!!edit}
        onClose={() => setEdit(null)}
        title={`Edit metric · ${edit?.code ?? ''}`}
        wide
        footer={
          <>
            <button className="btn" onClick={() => setEdit(null)}>Cancel</button>
            <button className="btn-primary" disabled={save.isPending} onClick={() => edit && save.mutate(edit)}>Save</button>
          </>
        }
      >
        {edit && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Name"><input className="input" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <Field label="Owner"><input className="input" value={edit.owner} onChange={(e) => setEdit({ ...edit, owner: e.target.value })} /></Field>
            <div className="sm:col-span-2"><Field label="Definition"><textarea className="input min-h-[80px]" value={edit.definition} onChange={(e) => setEdit({ ...edit, definition: e.target.value })} /></Field></div>
            <div className="sm:col-span-2"><Field label="Formula"><textarea className="input min-h-[60px] font-mono text-xs" value={edit.formula} onChange={(e) => setEdit({ ...edit, formula: e.target.value })} /></Field></div>
            <Field label="Source"><input className="input" value={edit.source} onChange={(e) => setEdit({ ...edit, source: e.target.value })} /></Field>
            <Field label="Refresh"><input className="input" value={edit.refresh} onChange={(e) => setEdit({ ...edit, refresh: e.target.value })} /></Field>
            <div className="sm:col-span-2"><InlineError error={save.error} /></div>
          </div>
        )}
      </Modal>
    </div>
  );
}
