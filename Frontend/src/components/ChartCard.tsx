import { useState, type ReactNode } from 'react';
import type { EChartsOption } from 'echarts';
import { EChart } from '@/charts/EChart';
import { Card, EmptyState, ErrorState, LoadingBlock, cx } from './ui';
import { IconChart, IconTable } from './Icons';

export interface ChartTable {
  columns: string[];
  rows: (string | number)[][];
}

/**
 * A chart with its accessible table twin (every value reachable without the tooltip).
 */
export function ChartCard({
  title,
  subtitle,
  option,
  table,
  height = 280,
  loading,
  error,
  onRetry,
  empty,
  emptyHint,
  actions,
  className,
  onClick,
  footer,
  dim,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  option: EChartsOption | null;
  table?: ChartTable;
  height?: number;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  empty?: boolean;
  emptyHint?: string;
  actions?: ReactNode;
  className?: string;
  onClick?: Parameters<typeof EChart>[0]['onClick'];
  footer?: ReactNode;
  dim?: boolean;
}) {
  const [view, setView] = useState<'chart' | 'table'>('chart');
  const toggle = table ? (
    <button
      className="rounded p-1 text-muted hover:bg-sunken hover:text-ink"
      onClick={() => setView(view === 'chart' ? 'table' : 'chart')}
      title={view === 'chart' ? 'Show as table' : 'Show as chart'}
      aria-label={view === 'chart' ? 'Show as table' : 'Show as chart'}
    >
      {view === 'chart' ? <IconTable /> : <IconChart />}
    </button>
  ) : null;

  let body: ReactNode;
  if (loading) body = <LoadingBlock height={height} />;
  else if (error) body = <ErrorState error={error} onRetry={onRetry} />;
  else if (empty || !option) body = <EmptyState height={height} hint={emptyHint} />;
  else if (view === 'table' && table)
    body = (
      <div className="overflow-auto rounded-md border border-line" style={{ maxHeight: height }}>
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-sunken">
            <tr>
              {table.columns.map((c, i) => (
                <th key={c} className={cx('th', i > 0 && 'text-right')}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular">
            {table.rows.map((r, i) => (
              <tr key={i} className="border-t border-line">
                {r.map((v, j) => (
                  <td key={j} className={cx('px-3 py-1.5', j > 0 && 'text-right')}>
                    {v}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  else body = <EChart option={option} height={height} onClick={onClick} ariaLabel={typeof title === 'string' ? title : undefined} />;

  return (
    <Card
      title={title}
      subtitle={subtitle}
      className={className}
      actions={
        <>
          {actions}
          {toggle}
        </>
      }
    >
      <div className={cx('transition-opacity', dim && 'opacity-60')}>{body}</div>
      {footer && <div className="mt-3">{footer}</div>}
    </Card>
  );
}
