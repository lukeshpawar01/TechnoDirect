import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '@/auth/AuthContext';
import { get, post } from '@/lib/api';
import { date } from '@/lib/format';
import { Badge, Card, InlineError, Skeleton } from './ui';

interface Row {
  id: number;
  kind: string;
  kind_label: string;
  distributor: string | null;
  asm: string | null;
  start: string | null;
  end: string | null;
  value: { alias?: string; merged?: string };
  given_on: string;
  said: string;
  status: 'active' | 'confirmed' | 'replaced' | 'removed';
  status_label: string;
  closed_on: string | null;
  closed_reason: string;
  conflict: string;
}

const TONE = { active: 'neutral', confirmed: 'good', replaced: 'warn', removed: 'neutral' } as const;

function what(r: Row): string {
  if (r.kind === 'distributor_alias') return `also called "${r.value.alias}"`;
  if (r.kind === 'distributor_merge') return `"${r.value.merged}" merged into it`;
  const when = r.start ? ` · ${date(r.start, 'MMM YYYY')} – ${r.end ? date(r.end, 'MMM YYYY') : 'now'}` : '';
  return `ASM ${r.asm ?? 'vacant'}${when}`;
}

/**
 * Mappings given by hand (in chat), with no sheet or file behind them. They work like any mapping until proper data
 * (ASM tracker, workbook, incentive sheet) covers them, which closes them automatically.
 */
export function ManualMappings() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [showClosed, setShowClosed] = useState(false);
  const q = useQuery({ queryKey: ['manual-mappings'], queryFn: () => get<{ rows: Row[]; active: number }>('/masters/manual-mappings/') });
  const remove = useMutation({
    mutationFn: (id: number) => post<Row>('/masters/manual-mappings/', { id, undo: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['manual-mappings'] });
      qc.invalidateQueries({ queryKey: ['analytics'] });
    },
  });
  const rows = (q.data?.rows ?? []).filter((r) => showClosed || r.status === 'active');
  const closed = (q.data?.rows ?? []).length - (q.data?.active ?? 0);

  return (
    <Card
      className="mt-4"
      title="Mappings given by hand"
      subtitle="Given in chat, with no sheet or file behind them. They count on the dashboard until proper data covers them, then close by themselves."
      actions={
        closed > 0 ? (
          <button className="text-xs text-ink2 hover:text-ink" onClick={() => setShowClosed((v) => !v)}>
            {showClosed ? 'Hide closed' : `Show ${closed} closed`}
          </button>
        ) : null
      }
    >
      {q.isLoading ? (
        <Skeleton className="h-40" />
      ) : !rows.length ? (
        <p className="py-4 text-sm text-ink2">No mappings given by hand are in use.</p>
      ) : (
        <div className="overflow-x-auto">
          {remove.error && <InlineError error={remove.error} />}
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-line text-xs text-muted">
                <th className="py-2 pr-2 text-left font-medium">Distributor</th>
                <th className="px-2 py-2 text-left font-medium">Mapping</th>
                <th className="px-2 py-2 text-left font-medium">Given</th>
                <th className="px-2 py-2 text-left font-medium">Status</th>
                <th className="py-2 pl-2" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-line/60 align-top">
                  <td className="py-2 pr-2 text-ink">{r.distributor ?? '–'}</td>
                  <td className="px-2 py-2">
                    <div className="text-ink">{what(r)}</div>
                    <div className="text-xs text-muted">{r.kind_label}</div>
                  </td>
                  <td className="px-2 py-2">
                    <div className="text-xs text-ink2">{date(r.given_on)}</div>
                    {r.said && <div className="max-w-xs text-xs italic text-muted">“{r.said}”</div>}
                  </td>
                  <td className="px-2 py-2">
                    <Badge tone={TONE[r.status]}>{r.status === 'active' ? 'In use' : r.status_label}</Badge>
                    {r.conflict && <div className="mt-1 max-w-xs text-xs text-warn">{r.conflict}</div>}
                    {r.closed_reason && <div className="mt-1 max-w-xs text-xs text-muted">{r.closed_reason}</div>}
                  </td>
                  <td className="py-2 pl-2 text-right">
                    {r.status === 'active' && can('manage_targets') && (
                      <button
                        className="rounded-md px-2 py-1 text-xs text-ink2 hover:bg-sunken hover:text-ink disabled:opacity-50"
                        disabled={remove.isPending}
                        onClick={() => {
                          if (window.confirm(`Remove this mapping and undo it on the dashboard?\n\n${r.distributor}: ${what(r)}`)) remove.mutate(r.id);
                        }}
                      >
                        Remove
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
