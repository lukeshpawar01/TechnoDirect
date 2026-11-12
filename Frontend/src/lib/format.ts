import dayjs from 'dayjs';

const nf0 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 });

const isNum = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);

/** 3 significant figures, no trailing zeros beyond what's meaningful: 2.95, 46.4, 123 */
function sig3(n: number): string {
  const abs = Math.abs(n);
  const digits = abs >= 100 ? 0 : abs >= 10 ? 1 : 2;
  return n.toFixed(digits);
}

/** Compact Indian number: 1.25 Cr, 46.4 L, 41,230 */
export function compactIN(n: number | null | undefined): string {
  if (!isNum(n)) return '–';
  const abs = Math.abs(n);
  if (abs >= 1e7) return `${sig3(n / 1e7)} Cr`;
  if (abs >= 1e5) return `${sig3(n / 1e5)} L`;
  return nf0.format(Math.round(n));
}

/** ₹ money. compact=true → ₹2.95 Cr / ₹46.4 L / ₹41,230 */
export function inr(n: number | null | undefined, opts: { compact?: boolean; decimals?: number } = {}): string {
  if (!isNum(n)) return '–';
  const { compact = true, decimals } = opts;
  const sign = n < 0 ? '−' : '';
  const abs = Math.abs(n);
  if (compact) return `${sign}₹${compactIN(abs)}`;
  const f = decimals != null ? new Intl.NumberFormat('en-IN', { maximumFractionDigits: decimals, minimumFractionDigits: decimals }) : nf0;
  return `${sign}₹${f.format(abs)}`;
}

/** Axis tick money label: ₹0, ₹50 L, ₹1 Cr, ₹1.5 Cr */
export function inrAxis(n: number): string {
  const abs = Math.abs(n);
  const sign = n < 0 ? '−' : '';
  if (abs === 0) return '₹0';
  if (abs >= 1e7) return `${sign}₹${+(abs / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `${sign}₹${+(abs / 1e5).toFixed(1)} L`;
  if (abs >= 1e3) return `${sign}₹${+(abs / 1e3).toFixed(1)}K`;
  return `${sign}₹${abs}`;
}

/** Plain count with en-IN grouping: 12,34,567 */
export function num(n: number | null | undefined, decimals = 0): string {
  if (!isNum(n)) return '–';
  if (decimals === 1) return nf1.format(n);
  if (decimals === 2) return nf2.format(n);
  return nf0.format(n);
}

/** Axis tick count label: 0 / 1,000 / 10K / 1 L */
export function numAxis(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1e5) return `${+(n / 1e5).toFixed(1)} L`;
  if (abs >= 1e4) return `${+(n / 1e3).toFixed(0)}K`;
  return nf0.format(n);
}

/** Percent where input is already a percent number (37.2 → "37.2%") */
export function pct(n: number | null | undefined, decimals = 1): string {
  if (!isNum(n)) return '–';
  return `${n.toFixed(decimals)}%`;
}

/** Signed percent delta: +12.4% / −3.1% */
export function signedPct(n: number | null | undefined, decimals = 1): string {
  if (!isNum(n)) return '–';
  const s = n > 0 ? '+' : n < 0 ? '−' : '±';
  return `${s}${Math.abs(n).toFixed(decimals)}%`;
}

/**
 * Shares in the contract are percentages (0–100). Defensive: if a backend
 * sends a ratio (0–1) we scale it, so "share" renders correctly either way.
 */
export function asPct(n: number | null | undefined): number | null {
  if (!isNum(n)) return null;
  return Math.abs(n) <= 1 && n !== 0 ? n * 100 : n;
}

export function hours(h: number | null | undefined): string {
  if (!isNum(h)) return '–';
  if (h >= 48) return `${(h / 24).toFixed(1)} d`;
  return `${h.toFixed(h < 10 ? 1 : 0)} h`;
}

export function date(d: string | null | undefined, fmt = 'DD MMM YYYY'): string {
  if (!d) return '–';
  const x = dayjs(d);
  return x.isValid() ? x.format(fmt) : String(d);
}

export function dateTime(d: string | null | undefined): string {
  return date(d, 'DD MMM YYYY, HH:mm');
}

/** "2026-08" → "Aug-26" (the review deck convention) */
export function monthLabel(m: string): string {
  const x = dayjs(m.length === 7 ? `${m}-01` : m);
  return x.isValid() ? x.format('MMM-YY') : m;
}

export function relTime(d: string | null | undefined): string {
  if (!d) return 'never';
  const mins = dayjs().diff(dayjs(d), 'minute');
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const h = Math.floor(mins / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.floor(h / 24)} d ago`;
}

export function titleCase(s: string | null | undefined): string {
  if (!s) return '–';
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
