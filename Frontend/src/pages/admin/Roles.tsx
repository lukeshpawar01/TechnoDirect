import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCollection } from '@/api/hooks';
import type { Permission, Role } from '@/api/types';
import { PageHeader } from '@/components/PageHeader';
import { Card, ErrorState, Field, InlineError, LoadingBlock, Modal, Spinner, cx } from '@/components/ui';
import { IconPlus, IconTrash } from '@/components/Icons';
import { del, get, patch, post } from '@/lib/api';

export default function Roles() {
  const qc = useQueryClient();
  const roles = useCollection<Role>('/admin/roles/');
  const perms = useQuery({ queryKey: ['admin', 'permissions'], queryFn: () => get<Permission[]>('/admin/permissions/'), staleTime: Infinity });
  const [draft, setDraft] = useState<Record<number, Set<string>>>({});
  const [creating, setCreating] = useState(false);
  const [newRole, setNewRole] = useState({ name: '', description: '' });

  useEffect(() => {
    if (roles.data) setDraft(Object.fromEntries(roles.data.map((r) => [r.id, new Set(r.permissions)])));
  }, [roles.data]);

  const groups = useMemo(() => {
    const m = new Map<string, Permission[]>();
    (perms.data ?? []).forEach((p) => m.set(p.group, [...(m.get(p.group) ?? []), p]));
    return [...m.entries()];
  }, [perms.data]);

  const dirty = (roles.data ?? []).filter((r) => {
    const d = draft[r.id];
    if (!d) return false;
    return d.size !== r.permissions.length || r.permissions.some((p) => !d.has(p));
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ['collection', '/admin/roles/'] });
  const saveAll = useMutation({
    mutationFn: () => Promise.all(dirty.map((r) => patch(`/admin/roles/${r.id}/`, { permissions: [...draft[r.id]] }))),
    onSuccess: invalidate,
  });
  const create = useMutation({
    mutationFn: () => post('/admin/roles/', { ...newRole, permissions: [] }),
    onSuccess: () => {
      invalidate();
      setCreating(false);
      setNewRole({ name: '', description: '' });
    },
  });
  const remove = useMutation({ mutationFn: (id: number) => del(`/admin/roles/${id}/`), onSuccess: invalidate });

  function toggle(roleId: number, code: string) {
    setDraft((d) => {
      const s = new Set(d[roleId]);
      if (s.has(code)) s.delete(code);
      else s.add(code);
      return { ...d, [roleId]: s };
    });
  }
  function toggleGroup(roleId: number, codes: string[]) {
    setDraft((d) => {
      const s = new Set(d[roleId]);
      const all = codes.every((c) => s.has(c));
      codes.forEach((c) => (all ? s.delete(c) : s.add(c)));
      return { ...d, [roleId]: s };
    });
  }

  const list = roles.data ?? [];

  return (
    <div>
      <PageHeader
        title="Roles & Permissions"
        subtitle="Tick permissions per role; master admins implicitly have everything"
        showBasis={false}
        actions={
          <>
            <button className="btn btn-sm" onClick={() => setCreating(true)}>
              <IconPlus size={13} /> New role
            </button>
            <button className="btn-primary btn-sm" disabled={!dirty.length || saveAll.isPending} onClick={() => saveAll.mutate()}>
              {saveAll.isPending && <Spinner size={12} />} Save {dirty.length ? `(${dirty.length} role${dirty.length > 1 ? 's' : ''})` : ''}
            </button>
          </>
        }
      />
      <InlineError error={saveAll.error ?? remove.error} />
      <Card bodyClass="p-0">
        {roles.isLoading || perms.isLoading ? (
          <LoadingBlock />
        ) : roles.error || perms.error ? (
          <ErrorState error={roles.error ?? perms.error} onRetry={() => { roles.refetch(); perms.refetch(); }} />
        ) : (
          <div className="overflow-auto">
            <table className="w-full border-collapse text-sm">
              <thead className="sticky top-0 z-[1] bg-sunken">
                <tr>
                  <th className="th min-w-[240px]">Permission</th>
                  {list.map((r) => (
                    <th key={r.id} className="th min-w-[120px] text-center align-bottom">
                      <div className="flex items-center justify-center gap-1">
                        <span className={cx(dirty.some((x) => x.id === r.id) && 'text-accent')}>{r.name}</span>
                        <button
                          className="rounded p-0.5 text-muted hover:text-bad"
                          title={`Delete role ${r.name}`}
                          onClick={() => window.confirm(`Delete role "${r.name}"? ${r.user_count} user(s) will lose it.`) && remove.mutate(r.id)}
                        >
                          <IconTrash size={12} />
                        </button>
                      </div>
                      <div className="text-2xs font-normal text-muted">{r.user_count} user{r.user_count === 1 ? '' : 's'}</div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {groups.map(([group, ps]) => (
                  <GroupRows key={group} group={group} perms={ps} roles={list} draft={draft} toggle={toggle} toggleGroup={toggleGroup} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title="New role"
        footer={
          <>
            <button className="btn" onClick={() => setCreating(false)}>Cancel</button>
            <button className="btn-primary" disabled={!newRole.name || create.isPending} onClick={() => create.mutate()}>Create</button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Name"><input className="input" value={newRole.name} onChange={(e) => setNewRole({ ...newRole, name: e.target.value })} placeholder="e.g. Regional manager" /></Field>
          <Field label="Description"><input className="input" value={newRole.description} onChange={(e) => setNewRole({ ...newRole, description: e.target.value })} /></Field>
          <InlineError error={create.error} />
        </div>
      </Modal>
    </div>
  );
}

function GroupRows({ group, perms, roles, draft, toggle, toggleGroup }: {
  group: string;
  perms: Permission[];
  roles: Role[];
  draft: Record<number, Set<string>>;
  toggle: (r: number, c: string) => void;
  toggleGroup: (r: number, codes: string[]) => void;
}) {
  const codes = perms.map((p) => p.code);
  return (
    <>
      <tr className="border-t border-line bg-sunken/50">
        <td className="px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-ink2">{group}</td>
        {roles.map((r) => {
          const s = draft[r.id] ?? new Set();
          const n = codes.filter((c) => s.has(c)).length;
          return (
            <td key={r.id} className="text-center">
              <button className="text-2xs text-muted hover:text-ink" onClick={() => toggleGroup(r.id, codes)}>
                {n === codes.length ? 'Clear all' : 'Select all'}
              </button>
            </td>
          );
        })}
      </tr>
      {perms.map((p) => (
        <tr key={p.code} className="border-t border-line hover:bg-sunken/40">
          <td className="px-3 py-1.5">
            <div className="text-sm">{p.label}</div>
            <div className="font-mono text-2xs text-muted">{p.code}</div>
          </td>
          {roles.map((r) => (
            <td key={r.id} className="text-center">
              <input
                type="checkbox"
                className="h-4 w-4 accent-[rgb(var(--brand))]"
                aria-label={`${p.label} for ${r.name}`}
                checked={draft[r.id]?.has(p.code) ?? false}
                onChange={() => toggle(r.id, p.code)}
              />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}
