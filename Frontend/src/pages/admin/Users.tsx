import { useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCollection, useFilterOptions } from '@/api/hooks';
import type { AdminUser, Role, Scope } from '@/api/types';
import { DataTable } from '@/components/DataTable';
import { MultiSelect } from '@/components/MultiSelect';
import { PageHeader } from '@/components/PageHeader';
import { Badge, Card, Field, InlineError, Modal } from '@/components/ui';
import { IconKey, IconPlus } from '@/components/Icons';
import { del, patch, post } from '@/lib/api';
import { dateTime } from '@/lib/format';

const EMPTY_SCOPE: Scope = { all: true, regions: [], states: [], asms: [], distributors: [] };

type Draft = { id?: number; email: string; full_name: string; password: string; role_id: number | null; is_active: boolean; scope: Scope };

function scopeSummary(s: Scope | undefined): string {
  if (!s || s.all) return 'All data';
  const parts = [
    s.regions.length && `${s.regions.length} region${s.regions.length > 1 ? 's' : ''}`,
    s.states.length && `${s.states.length} state${s.states.length > 1 ? 's' : ''}`,
    s.asms.length && `${s.asms.length} ASM${s.asms.length > 1 ? 's' : ''}`,
    s.distributors.length && `${s.distributors.length} distributor${s.distributors.length > 1 ? 's' : ''}`,
  ].filter(Boolean);
  return parts.length ? parts.join(', ') : 'No data (empty scope)';
}

export default function Users() {
  const qc = useQueryClient();
  const users = useCollection<AdminUser>('/admin/users/');
  const roles = useCollection<Role>('/admin/roles/');
  const opts = useFilterOptions();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [reset, setReset] = useState<AdminUser | null>(null);
  const [newPw, setNewPw] = useState('');
  const [search, setSearch] = useState('');

  const roleName = useMemo(() => new Map((roles.data ?? []).map((r) => [r.id, r.name])), [roles.data]);
  const invalidate = () => qc.invalidateQueries({ queryKey: ['collection', '/admin/users/'] });

  const save = useMutation({
    mutationFn: async (d: Draft) => {
      const body: Record<string, unknown> = { email: d.email, full_name: d.full_name, role_id: d.role_id, is_active: d.is_active, scope: d.scope };
      if (d.id) return patch(`/admin/users/${d.id}/`, body);
      return post('/admin/users/', { ...body, password: d.password });
    },
    onSuccess: () => {
      invalidate();
      setDraft(null);
    },
  });
  const toggle = useMutation({ mutationFn: (u: AdminUser) => patch(`/admin/users/${u.id}/`, { is_active: !u.is_active }), onSuccess: invalidate });
  const remove = useMutation({ mutationFn: (u: AdminUser) => del(`/admin/users/${u.id}/`), onSuccess: invalidate });
  const resetPw = useMutation({
    mutationFn: ({ id, pw }: { id: number; pw: string }) => post(`/admin/users/${id}/reset-password/`, { new_password: pw }),
    onSuccess: () => {
      setReset(null);
      setNewPw('');
    },
  });

  const rows = (users.data ?? []).filter((u) => !search || `${u.email} ${u.full_name}`.toLowerCase().includes(search.toLowerCase()));
  const o = opts.data;
  const setScope = (patchS: Partial<Scope>) => draft && setDraft({ ...draft, scope: { ...draft.scope, ...patchS } });
  const ids = (v: string[]) => v.map(Number);
  const strs = (v: number[]) => v.map(String);

  return (
    <div>
      <PageHeader
        title="Users"
        subtitle="Create users, assign roles and data scope"
        showBasis={false}
        actions={
          <button className="btn-primary btn-sm" onClick={() => setDraft({ email: '', full_name: '', password: '', role_id: roles.data?.[0]?.id ?? null, is_active: true, scope: { ...EMPTY_SCOPE } })}>
            <IconPlus size={13} /> New user
          </button>
        }
      />
      <Card>
        <DataTable
          rows={rows}
          loading={users.isLoading}
          error={users.error}
          onRetry={() => users.refetch()}
          rowKey={(r) => r.id}
          exportName="users"
          exportPath="/admin/users/"
          initialSort={{ key: 'full_name', dir: 'asc' }}
          toolbar={<input className="input w-56 py-1 text-xs" placeholder="Search name or email…" value={search} onChange={(e) => setSearch(e.target.value)} />}
          columns={[
            { key: 'full_name', header: 'Name', render: (u) => <span className="font-medium">{u.full_name || '–'}</span> },
            { key: 'email', header: 'Email' },
            { key: 'role_id', header: 'Role', value: (u) => roleName.get(u.role_id ?? -1) ?? '', render: (u) => roleName.get(u.role_id ?? -1) ?? <span className="text-muted">No role</span> },
            { key: 'scope', header: 'Data scope', value: (u) => scopeSummary(u.scope), render: (u) => <span className="text-xs text-ink2">{scopeSummary(u.scope)}</span> },
            { key: 'is_active', header: 'Status', value: (u) => (u.is_active ? 'Active' : 'Inactive'), render: (u) => <Badge tone={u.is_active ? 'good' : 'neutral'} icon={u.is_active}>{u.is_active ? 'Active' : 'Inactive'}</Badge> },
            { key: 'last_login', header: 'Last login', render: (u) => dateTime(u.last_login) },
            {
              key: 'actions',
              header: '',
              sortable: false,
              noExport: true,
              align: 'right',
              render: (u) => (
                <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                  <button className="btn btn-sm" onClick={() => setDraft({ id: u.id, email: u.email, full_name: u.full_name, password: '', role_id: u.role_id, is_active: u.is_active, scope: u.scope ?? { ...EMPTY_SCOPE } })}>Edit</button>
                  <button className="btn btn-sm" onClick={() => setReset(u)} title="Reset password"><IconKey size={12} /></button>
                  <button className="btn btn-sm" onClick={() => toggle.mutate(u)}>{u.is_active ? 'Deactivate' : 'Activate'}</button>
                  <button className="btn btn-sm text-bad" onClick={() => window.confirm(`Delete ${u.email}? This cannot be undone.`) && remove.mutate(u)}>Delete</button>
                </div>
              ),
            },
          ]}
        />
        <InlineError error={toggle.error ?? remove.error} />
      </Card>

      <Modal
        open={!!draft}
        onClose={() => setDraft(null)}
        title={draft?.id ? 'Edit user' : 'New user'}
        wide
        footer={
          <>
            <button className="btn" onClick={() => setDraft(null)}>Cancel</button>
            <button className="btn-primary" disabled={save.isPending || !draft?.email || (!draft?.id && draft.password.length < 8)} onClick={() => draft && save.mutate(draft)}>
              {draft?.id ? 'Save changes' : 'Create user'}
            </button>
          </>
        }
      >
        {draft && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Full name"><input className="input" value={draft.full_name} onChange={(e) => setDraft({ ...draft, full_name: e.target.value })} /></Field>
              <Field label="Email"><input className="input" type="email" value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} /></Field>
              {!draft.id && (
                <Field label="Initial password" hint="At least 8 characters. The user can change it after signing in.">
                  <input className="input" type="password" autoComplete="new-password" value={draft.password} onChange={(e) => setDraft({ ...draft, password: e.target.value })} />
                </Field>
              )}
              <Field label="Role">
                <select className="input" value={draft.role_id ?? ''} onChange={(e) => setDraft({ ...draft, role_id: e.target.value ? Number(e.target.value) : null })}>
                  <option value="">No role</option>
                  {(roles.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                </select>
              </Field>
              <label className="flex items-center gap-2 pt-5 text-sm">
                <input type="checkbox" checked={draft.is_active} onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })} /> Active
              </label>
            </div>
            <fieldset className="rounded-md border border-line p-3">
              <legend className="px-1 text-xs font-semibold text-ink2">Data scope</legend>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={draft.scope.all} onChange={(e) => setScope({ all: e.target.checked })} /> All data (no restriction)
              </label>
              {!draft.scope.all && (
                <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <MultiSelect width="w-full" label="Regions" placeholder="None" options={(o?.regions ?? []).map((x) => ({ value: String(x.id), label: x.name }))} value={strs(draft.scope.regions)} onChange={(v) => setScope({ regions: ids(v) })} />
                  <MultiSelect width="w-full" label="States" placeholder="None" options={(o?.states ?? []).map((x) => ({ value: String(x.id), label: x.name }))} value={strs(draft.scope.states)} onChange={(v) => setScope({ states: ids(v) })} />
                  <MultiSelect width="w-full" label="ASMs" placeholder="None" options={(o?.asms ?? []).map((x) => ({ value: String(x.id), label: x.name }))} value={strs(draft.scope.asms)} onChange={(v) => setScope({ asms: ids(v) })} />
                  <MultiSelect width="w-full" label="Distributors" placeholder="None" options={(o?.distributors ?? []).map((x) => ({ value: String(x.id), label: x.name }))} value={strs(draft.scope.distributors)} onChange={(v) => setScope({ distributors: ids(v) })} />
                  <p className="text-2xs text-muted sm:col-span-2">The user sees data matching any selected region, state, ASM or distributor. Current: {scopeSummary(draft.scope)}.</p>
                </div>
              )}
            </fieldset>
            <InlineError error={save.error} />
          </div>
        )}
      </Modal>

      <Modal
        open={!!reset}
        onClose={() => setReset(null)}
        title={`Reset password · ${reset?.email ?? ''}`}
        footer={
          <>
            <button className="btn" onClick={() => setReset(null)}>Cancel</button>
            <button className="btn-primary" disabled={newPw.length < 8 || resetPw.isPending} onClick={() => reset && resetPw.mutate({ id: reset.id, pw: newPw })}>Reset password</button>
          </>
        }
      >
        <Field label="New password" hint="At least 8 characters. Share it with the user securely.">
          <input className="input" type="password" autoComplete="new-password" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
        </Field>
        <div className="mt-2"><InlineError error={resetPw.error} /></div>
      </Modal>
    </div>
  );
}
