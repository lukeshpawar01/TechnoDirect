import axios, { AxiosError, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios';
import type { Envelope, Meta, Paginated } from '@/api/types';
import { freshnessStore } from './freshnessStore';

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000/api';
export const USE_MOCKS = String(import.meta.env.VITE_USE_MOCKS ?? '').toLowerCase() === 'true';

// ----------------------------------------------------------- token storage
const ACCESS = 'td.access';
const REFRESH = 'td.refresh';

export const tokens = {
  get access() {
    try {
      return localStorage.getItem(ACCESS);
    } catch {
      return null;
    }
  },
  get refresh() {
    try {
      return localStorage.getItem(REFRESH);
    } catch {
      return null;
    }
  },
  set(access: string, refresh?: string) {
    try {
      localStorage.setItem(ACCESS, access);
      if (refresh) localStorage.setItem(REFRESH, refresh);
    } catch {
      /* storage blocked */
    }
  },
  clear() {
    try {
      localStorage.removeItem(ACCESS);
      localStorage.removeItem(REFRESH);
    } catch {
      /* storage blocked */
    }
  },
};

/** Called when the session can't be recovered (refresh failed). */
let onAuthLost: () => void = () => {};
export function setOnAuthLost(fn: () => void) {
  onAuthLost = fn;
}

// ----------------------------------------------------------- axios instance
export const api = axios.create({
  baseURL: API_BASE_URL.replace(/\/$/, ''),
  timeout: 60_000,
  // DRF expects repeated keys as comma-separated strings (contract) — we pre-join.
  paramsSerializer: { indexes: null },
});

if (USE_MOCKS) {
  // Lazy-loaded so the mock data never ships unless enabled.
  const adapterPromise = import('@/mocks/adapter').then((m) => m.mockAdapter);
  api.defaults.adapter = async (config) => (await adapterPromise)(config);
}

api.interceptors.request.use((config) => {
  const t = tokens.access;
  if (t && !config.headers.has('Authorization')) config.headers.set('Authorization', `Bearer ${t}`);
  return config;
});

// Capture freshness from any analytics envelope so the top bar can show it on every page.
api.interceptors.response.use((res) => {
  const body = res.data as { meta?: Meta } | undefined;
  if (body && typeof body === 'object' && body.meta && Array.isArray(body.meta.freshness)) {
    freshnessStore.set(body.meta);
  }
  return res;
});

// ---- refresh-on-401 with a single in-flight refresh shared by concurrent requests
let refreshing: Promise<string> | null = null;

async function refreshAccess(): Promise<string> {
  const refresh = tokens.refresh;
  if (!refresh) throw new Error('No refresh token');
  const res = await api.post<{ access: string; refresh?: string }>(
    '/auth/token/refresh/',
    { refresh },
    { headers: { Authorization: '' }, _skipAuthRetry: true } as AxiosRequestConfig,
  );
  tokens.set(res.data.access, res.data.refresh);
  return res.data.access;
}

api.interceptors.response.use(undefined, async (error: AxiosError) => {
  const cfg = error.config as (InternalAxiosRequestConfig & { _retried?: boolean; _skipAuthRetry?: boolean }) | undefined;
  const status = error.response?.status;
  if (!cfg || status !== 401 || cfg._retried || cfg._skipAuthRetry || cfg.url?.includes('/auth/token/')) {
    return Promise.reject(error);
  }
  cfg._retried = true;
  try {
    refreshing = refreshing ?? refreshAccess().finally(() => {
      refreshing = null;
    });
    const access = await refreshing;
    cfg.headers.set('Authorization', `Bearer ${access}`);
    return api(cfg);
  } catch (e) {
    tokens.clear();
    onAuthLost();
    return Promise.reject(error);
  }
});

// ----------------------------------------------------------- helpers
export type Params = Record<string, string | number | boolean | null | undefined>;

function clean(params?: Params): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {};
  if (!params) return out;
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    out[k] = v;
  }
  return out;
}

export async function get<T>(path: string, params?: Params): Promise<T> {
  const res = await api.get<T>(path, { params: clean(params) });
  return res.data;
}

/** Analytics endpoints return {data, meta}; tolerate a bare payload too. */
export async function getEnvelope<T>(path: string, params?: Params): Promise<Envelope<T>> {
  const body = await get<unknown>(path, params);
  if (body && typeof body === 'object' && 'data' in (body as object)) {
    const b = body as { data: T; meta?: Meta };
    return { data: b.data, meta: b.meta ?? null };
  }
  return { data: body as T, meta: null };
}

/** Lists may be paginated ({results}) or a bare array; normalise to Paginated. */
export async function getList<T>(path: string, params?: Params): Promise<Paginated<T>> {
  const body = await get<unknown>(path, params);
  return asPaginated<T>(body);
}

export function asPaginated<T>(body: unknown): Paginated<T> {
  if (Array.isArray(body)) return { count: body.length, next: null, previous: null, results: body as T[] };
  if (body && typeof body === 'object') {
    const b = body as Partial<Paginated<T>> & { data?: unknown };
    if (Array.isArray(b.results)) return { count: b.count ?? b.results.length, next: b.next ?? null, previous: b.previous ?? null, results: b.results, meta: b.meta };
    if (b.data !== undefined) return asPaginated<T>(b.data);
  }
  return { count: 0, next: null, previous: null, results: [] };
}

export async function post<T>(path: string, body?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const res = await api.post<T>(path, body, config);
  return res.data;
}
export async function patch<T>(path: string, body?: unknown): Promise<T> {
  const res = await api.patch<T>(path, body);
  return res.data;
}
export async function del(path: string): Promise<void> {
  await api.delete(path);
}

/** Download a file (export / template). Uses Content-Disposition filename when present. */
export async function download(path: string, params: Params | undefined, fallbackName: string): Promise<void> {
  const res = await api.get<Blob>(path, { params: clean(params), responseType: 'blob' });
  const cd = String(res.headers['content-disposition'] ?? '');
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  const name = m ? decodeURIComponent(m[1]) : fallbackName;
  saveBlob(res.data, name);
}

export function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Human-readable message out of a DRF error response. */
export function errorMessage(e: unknown): string {
  if (axios.isAxiosError(e)) {
    const d = e.response?.data as unknown;
    if (d && typeof d === 'object' && !(d instanceof Blob)) {
      const o = d as Record<string, unknown>;
      if (typeof o.detail === 'string') return o.detail;
      const parts = Object.entries(o).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(' ') : String(v)}`);
      if (parts.length) return parts.join(' · ');
    }
    if (e.response?.status === 403) return 'You do not have permission to view this.';
    if (e.response?.status === 404) return 'Not found.';
    if (!e.response) return 'Cannot reach the server. Check your connection or VITE_API_BASE_URL.';
    return `Request failed (${e.response.status}).`;
  }
  return e instanceof Error ? e.message : 'Something went wrong.';
}
