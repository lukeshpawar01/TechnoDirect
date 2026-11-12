import { useEffect, useMemo, useRef, useState } from 'react';
import type { ProductTree, ProductTreeRow } from '@/api/types';
import { useChartTokens } from '@/charts/EChart';
import { inr, num, pct } from '@/lib/format';
import { cx, EmptyState, LoadingBlock } from './ui';

/**
 * Power-BI-style decomposition tree: Total → Category I → Category II → Category III → Style.
 * Click a node to drill into the next level, click it again (or the × in the column header) to collapse.
 * Bars are scaled to the largest node in their own column, so each column reads as a ranking.
 */

type LevelKey = 'l1' | 'l2' | 'l3' | 'style';
const LEVELS: LevelKey[] = ['l1', 'l2', 'l3', 'style'];

interface Node {
  key: string;
  label: string;
  amount: number;
  quantity: number;
  orders: number;
  styleName?: string;
}

const COL_W = 168;
const GAP = 72;
const ROW_H = 64;
const HEADER_H = 58;
const BAR_H = 12;
const PAGE = 8;

function rollup(rows: ProductTreeRow[], level: LevelKey, path: string[]): Node[] {
  const m = new Map<string, Node>();
  for (const r of rows) {
    let ok = true;
    for (let i = 0; i < path.length; i++) if (r[LEVELS[i]] !== path[i]) ok = false;
    if (!ok) continue;
    const k = r[level];
    const n = m.get(k) ?? { key: k, label: k, amount: 0, quantity: 0, orders: 0, styleName: level === 'style' ? r.name : undefined };
    n.amount += r.amount;
    n.quantity += r.quantity;
    n.orders += r.orders;
    m.set(k, n);
  }
  return [...m.values()].sort((a, b) => b.amount - a.amount);
}

/** Default drill path: follow the biggest node down to Category III (matches how the review deck reads). */
function defaultPath(rows: ProductTreeRow[]): string[] {
  const path: string[] = [];
  for (let i = 0; i < 3; i++) {
    const top = rollup(rows, LEVELS[i], path)[0];
    if (!top) break;
    path.push(top.key);
  }
  return path;
}

interface Hover {
  col: number;
  node: Node;
  parentAmount: number;
  x: number;
  y: number;
}

export function DecompositionTree({ data, loading, valueLabel = 'Total line amount' }: { data?: ProductTree; loading?: boolean; valueLabel?: string }) {
  const t = useChartTokens();
  const rows = useMemo(() => data?.rows ?? [], [data]);
  const labels = useMemo(() => {
    const m: Record<string, string> = { l1: 'Category I', l2: 'Category II', l3: 'Category III', style: 'Style' };
    data?.levels.forEach((l) => (m[l.key] = l.label));
    return m;
  }, [data]);

  const [path, setPath] = useState<string[]>([]);
  const [depth, setDepth] = useState(0); // number of level columns shown (0..4)
  const [shown, setShown] = useState<number[]>([PAGE, PAGE, PAGE, PAGE]);
  const [hover, setHover] = useState<Hover | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  // (Re)initialise when the data set changes; keep the user's path if it still exists.
  useEffect(() => {
    if (!rows.length) return;
    setPath((prev) => {
      const valid: string[] = [];
      for (let i = 0; i < prev.length; i++) {
        if (rollup(rows, LEVELS[i], valid).some((n) => n.key === prev[i])) valid.push(prev[i]);
        else break;
      }
      if (valid.length) return valid;
      const d = defaultPath(rows);
      setDepth(Math.min(4, d.length + 1));
      return d;
    });
  }, [rows]);

  const columns = useMemo(
    () => Array.from({ length: depth }, (_, k) => (path.length >= k ? rollup(rows, LEVELS[k], path.slice(0, k)) : [])),
    [rows, path, depth],
  );

  if (loading && !data) return <LoadingBlock height={420} />;
  if (!rows.length) return <EmptyState title="No product sales in this period" height={300} />;

  const total: Node = { key: '__total', label: valueLabel, amount: data?.total.amount ?? 0, quantity: data?.total.quantity ?? 0, orders: 0 };

  // ---- geometry --------------------------------------------------------------------------
  const visibleCounts = columns.map((c, k) => Math.min(c.length, shown[k]));
  const maxRows = Math.max(5, ...visibleCounts);
  const bodyH = maxRows * ROW_H + 28; // +28 for the "show more" chevron
  const height = HEADER_H + bodyH;
  const colX = (k: number) => k * (COL_W + GAP); // k = 0 is Total
  const width = colX(depth) + COL_W + 8;

  const totalY = HEADER_H + (bodyH - 28 - ROW_H) / 2;
  const colTop: number[] = [];
  const nodeYs: number[][] = [];
  let parentMid = totalY + BAR_H / 2;
  columns.forEach((nodes, k) => {
    const n = visibleCounts[k];
    const block = n * ROW_H;
    const ideal = parentMid - BAR_H / 2 - (block - ROW_H) / 2;
    const top = Math.max(HEADER_H, Math.min(ideal, HEADER_H + bodyH - 28 - block));
    colTop[k] = top;
    nodeYs[k] = Array.from({ length: n }, (_, i) => top + i * ROW_H);
    const selIdx = nodes.slice(0, n).findIndex((x) => x.key === path[k]);
    parentMid = selIdx >= 0 ? nodeYs[k][selIdx] + BAR_H / 2 : parentMid;
  });

  // ---- interactions ----------------------------------------------------------------------
  const resetShown = (fromCol: number) => setShown((s) => s.map((v, i) => (i >= fromCol ? PAGE : v)));
  const clickNode = (k: number, node: Node) => {
    setHover(null);
    if (path[k] === node.key) {
      setPath(path.slice(0, k));
      setDepth(k + 1);
    } else {
      setPath([...path.slice(0, k), node.key]);
      setDepth(Math.min(4, k + 2));
    }
    resetShown(k + 1);
  };
  const clickTotal = () => {
    setHover(null);
    if (depth > 0) {
      setPath([]);
      setDepth(0);
    } else setDepth(1);
    resetShown(0);
  };
  const closeCol = (k: number) => {
    setPath(path.slice(0, k));
    setDepth(k);
    resetShown(k);
  };

  // ---- links -----------------------------------------------------------------------------
  const links: { d: string; active: boolean }[] = [];
  let fromX = colX(0) + COL_W;
  let fromY = totalY + BAR_H / 2;
  columns.forEach((nodes, k) => {
    const x = colX(k + 1);
    nodeYs[k].forEach((y, i) => {
      const toY = y + BAR_H / 2;
      const mx = (fromX + x) / 2;
      links.push({ d: `M${fromX},${fromY} C${mx},${fromY} ${mx},${toY} ${x},${toY}`, active: nodes[i].key === path[k] });
    });
    const selIdx = nodes.slice(0, visibleCounts[k]).findIndex((n) => n.key === path[k]);
    if (selIdx < 0) return;
    fromX = x + COL_W;
    fromY = nodeYs[k][selIdx] + BAR_H / 2;
  });

  const barColor = t.series[0];

  const nodeEl = (k: number, node: Node, x: number, y: number, max: number, parentAmount: number, onClick: () => void, selected: boolean) => (
    <button
      key={`${k}-${node.key}`}
      type="button"
      onClick={onClick}
      onMouseEnter={(e) => {
        const r = boxRef.current?.getBoundingClientRect();
        const b = e.currentTarget.getBoundingClientRect();
        if (r) setHover({ col: k, node, parentAmount, x: b.right - r.left + (boxRef.current?.scrollLeft ?? 0), y: b.top - r.top });
      }}
      onMouseLeave={() => setHover(null)}
      onFocus={(e) => {
        const r = boxRef.current?.getBoundingClientRect();
        const b = e.currentTarget.getBoundingClientRect();
        if (r) setHover({ col: k, node, parentAmount, x: b.right - r.left + (boxRef.current?.scrollLeft ?? 0), y: b.top - r.top });
      }}
      onBlur={() => setHover(null)}
      aria-pressed={selected}
      aria-label={`${node.label}: ${inr(node.amount, { compact: false })}`}
      className="group absolute text-left focus:outline-none"
      style={{ left: x, top: y, width: COL_W }}
    >
      <div className="relative w-full overflow-hidden rounded-[2px] bg-sunken group-focus-visible:ring-2 group-focus-visible:ring-brand" style={{ height: BAR_H }}>
        <div className="h-full transition-[width] duration-300" style={{ width: `${max ? Math.max(1.5, (node.amount / max) * 100) : 0}%`, background: barColor, opacity: selected ? 1 : 0.85 }} />
      </div>
      <div className={cx('mt-1 truncate text-[13px] leading-tight text-ink', selected && 'font-semibold')} title={node.label}>
        {node.label}
      </div>
      <div className="text-2xs tabular-nums text-muted">{inr(node.amount, { compact: false })}</div>
    </button>
  );

  return (
    <div ref={boxRef} className="relative overflow-x-auto overflow-y-hidden pb-1" onMouseLeave={() => setHover(null)}>
      <div className="relative" style={{ width, height }}>
        <svg className="pointer-events-none absolute inset-0" width={width} height={height} aria-hidden>
          {links.map((l, i) => (
            <path key={i} d={l.d} fill="none" stroke={l.active ? barColor : t.grid} strokeWidth={l.active ? 2 : 1} />
          ))}
        </svg>

        {/* column headers */}
        {columns.map((_, k) => (
          <div key={`h${k}`} className="absolute" style={{ left: colX(k + 1), top: 4, width: COL_W }}>
            <div className="flex items-center justify-between border-b-2 border-brand pb-0.5">
              <span className="text-[13px] font-medium text-ink">{labels[LEVELS[k]]}</span>
              <button type="button" onClick={() => closeCol(k)} className="px-1 text-muted hover:text-ink" aria-label={`Remove ${labels[LEVELS[k]]}`} title="Remove this level">
                ×
              </button>
            </div>
            <div className="mt-0.5 truncate text-2xs text-muted">{path[k] ?? ' '}</div>
          </div>
        ))}

        {/* total */}
        <button
          type="button"
          onClick={clickTotal}
          className="absolute text-left focus:outline-none"
          style={{ left: 0, top: totalY, width: COL_W }}
          aria-expanded={depth > 0}
          onMouseEnter={(e) => {
            const r = boxRef.current?.getBoundingClientRect();
            const b = e.currentTarget.getBoundingClientRect();
            if (r) setHover({ col: -1, node: total, parentAmount: total.amount, x: b.right - r.left, y: b.top - r.top });
          }}
          onMouseLeave={() => setHover(null)}
        >
          <div className="w-full rounded-[2px]" style={{ height: BAR_H, background: barColor }} />
          <div className="mt-1 text-[13px] font-semibold leading-tight text-ink">{valueLabel}</div>
          <div className="text-2xs tabular-nums text-muted">{inr(total.amount, { compact: false })}</div>
        </button>

        {/* level columns */}
        {columns.map((nodes, k) => {
          const max = nodes[0]?.amount ?? 0;
          const parentAmount = k === 0 ? total.amount : columns[k - 1].find((n) => n.key === path[k - 1])?.amount ?? total.amount;
          const n = visibleCounts[k];
          return (
            <div key={`c${k}`}>
              {nodes.slice(0, n).map((node, i) =>
                nodeEl(k, node, colX(k + 1), nodeYs[k][i], max, parentAmount, () => clickNode(k, node), path[k] === node.key),
              )}
              {nodes.length > n && (
                <button
                  type="button"
                  onClick={() => setShown((s) => s.map((v, i) => (i === k ? v + PAGE : v)))}
                  className="absolute text-xs text-muted hover:text-ink"
                  style={{ left: colX(k + 1), top: colTop[k] + n * ROW_H - 4, width: COL_W }}
                  title={`Show ${Math.min(PAGE, nodes.length - n)} more`}
                >
                  ▾ {nodes.length - n} more
                </button>
              )}
            </div>
          );
        })}

        {hover && (
          <div
            role="tooltip"
            className="pointer-events-none absolute z-10 min-w-[220px] rounded-md border border-line bg-surface px-3 py-2 text-xs shadow-lg"
            style={{ left: Math.min(hover.x + 10, width - 230), top: Math.max(0, hover.y - 8) }}
          >
            <table className="w-full">
              <tbody>
                {hover.col >= 0 && (
                  <tr>
                    <td className="pr-3 text-right text-muted">{labels[LEVELS[hover.col]]}</td>
                    <td className="font-medium text-ink">{hover.node.label}</td>
                  </tr>
                )}
                {hover.node.styleName && (
                  <tr>
                    <td className="pr-3 text-right text-muted">Article</td>
                    <td className="text-ink">{hover.node.styleName}</td>
                  </tr>
                )}
                <tr>
                  <td className="pr-3 text-right text-muted">{valueLabel}</td>
                  <td className="tabular-nums text-ink">{inr(hover.node.amount, { compact: false })}</td>
                </tr>
                <tr>
                  <td className="pr-3 text-right text-muted">Quantity Sold</td>
                  <td className="tabular-nums text-ink">{num(hover.node.quantity)}</td>
                </tr>
                {hover.col >= 0 && (
                  <>
                    <tr>
                      <td className="pr-3 text-right text-muted">Share of parent</td>
                      <td className="tabular-nums text-ink">{pct(hover.parentAmount ? (hover.node.amount / hover.parentAmount) * 100 : null)}</td>
                    </tr>
                    <tr>
                      <td className="pr-3 text-right text-muted">Share of total</td>
                      <td className="tabular-nums text-ink">{pct(total.amount ? (hover.node.amount / total.amount) * 100 : null)}</td>
                    </tr>
                    <tr>
                      <td className="pr-3 text-right text-muted">Realisation / pc</td>
                      <td className="tabular-nums text-ink">{hover.node.quantity ? inr(hover.node.amount / hover.node.quantity, { compact: false }) : '–'}</td>
                    </tr>
                  </>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
