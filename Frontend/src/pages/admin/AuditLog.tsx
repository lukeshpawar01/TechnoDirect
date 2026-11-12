import { useEffect, useState } from 'react';
import { usePagedList } from '@/api/hooks';
import type { AuditEntry } from '@/api/types';
import { DataTable } from '@/components/DataTable';
import { PageHeader } from '@/components/PageHeader';
import { Card, Drawer } from '@/components/ui';
import { IconSearch } from '@/components/Icons';
import { dateTime, titleCase } from '@/lib/format';

function Json({ v }: { v: unknown }) {
  if (v === null || v === undefined) return <span className="text-xs text-muted">–</span>;
  return <pre className="max-h-80 overflow-auto rounded-md bg-sunken p-2 text-2xs leading-relaxed">{JSON.stringify(v, null, 2)}</pre>;
}

/** Keys whose values differ between before/after. */
function changedKeys(a: unknown, b: unknown): string[] {
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object') return [];
  const ao = a as Record<string, unknown>;
  const bo = b as Record<string, unknown>;
  return [...new Set([...Object.keys(ao), ...Object.keys(bo)])].filter((k) => JSON.stringify(ao[k]) !== JSON.stringify(bo[k]));
}

export default function AuditLog() {
  const [page, setPage] = useState(1);
  const [ordering, setOrdering] = useState('-at');
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [open, setOpen] = useState<AuditEntry | null>(null);
  useEffect(() => {
    const h = setTimeout(() => setDebounced(search), 350);
    return () => clearTimeout(h);
  }, [search]);
  useEffect(() => setPage(1), [debounced]);

  const q = usePagedList<AuditEntry>('/admin/audit-log/', { page, page_size: 50, ordering, search: debounced || undefined }, { global: false });
  const changed = open ? changedKeys(open.before, open.after) : [];

  return (
    <div>
      <PageHeader title="Audit Log" subtitle="Every change to users, roles, targets, mappings and metrics" showBasis={false} />
      <Card>
        <DataTable
          rows={q.data?.results}
          loading={q.isLoading}
          fetching={q.isFetching}
          error={q.error}
          onRetry={() => q.refetch()}
          rowKey={(r) => r.id}
          onRowClick={setOpen}
          exportName="audit_log"
          exportPath="/admin/audit-log/"
          exportParams={{ search: debounced || undefined }}
          server={{ count: q.data?.count ?? 0, page, pageSize: 50, onPage: setPage, ordering, onOrdering: setOrdering }}
          toolbar={
            <div className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1">
              <IconSearch size={13} className="text-muted" />
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="User, action, object…" className="w-52 bg-transparent text-xs outline-none placeholder:text-muted" aria-label="Search audit log" />
            </div>
          }
          columns={[
            { key: 'at', header: 'When', render: (r) => dateTime(r.at) },
            { key: 'user_email', header: 'User' },
            { key: 'action', header: 'Action', render: (r) => <span className="font-medium">{titleCase(r.action)}</span> },
            { key: 'object_type', header: 'Object', render: (r) => `${titleCase(r.object_type)}${r.object_id != null ? ` #${r.object_id}` : ''}` },
            { key: 'reason', header: 'Reason', render: (r) => <span className="text-xs text-ink2">{r.reason || '–'}</span> },
          ]}
        />
      </Card>
      <Drawer open={!!open} onClose={() => setOpen(null)} title={open ? `${titleCase(open.action)} · ${titleCase(open.object_type)}` : ''}>
        {open && (
          <div className="space-y-4 text-sm">
            <div className="text-xs text-muted">
              {dateTime(open.at)} · {open.user_email}
              {open.reason ? ` · ${open.reason}` : ''}
            </div>
            {changed.length > 0 && (
              <div>
                <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Changed fields</h4>
                <div className="flex flex-wrap gap-1">{changed.map((k) => <span key={k} className="chip bg-warn-bg text-warn">{k}</span>)}</div>
              </div>
            )}
            <div>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Before</h4>
              <Json v={open.before} />
            </div>
            <div>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">After</h4>
              <Json v={open.after} />
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
