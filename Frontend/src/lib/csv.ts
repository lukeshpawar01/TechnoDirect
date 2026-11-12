import { saveBlob } from './api';

function cell(v: unknown): string {
  if (v === null || v === undefined) return '';
  const s = typeof v === 'object' ? JSON.stringify(v) : String(v);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(headers: string[], rows: unknown[][]): string {
  return [headers.map(cell).join(','), ...rows.map((r) => r.map(cell).join(','))].join('\r\n');
}

/** Client-side CSV (UTF-8 BOM so Excel renders ₹ correctly). */
export function downloadCsv(name: string, headers: string[], rows: unknown[][]) {
  const blob = new Blob(['﻿' + toCsv(headers, rows)], { type: 'text/csv;charset=utf-8' });
  saveBlob(blob, name.endsWith('.csv') ? name : `${name}.csv`);
}
