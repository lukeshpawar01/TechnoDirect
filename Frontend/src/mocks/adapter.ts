/**
 * Axios adapter that serves contract-shaped sample data (VITE_USE_MOCKS=true).
 * Lazy-loaded from lib/api.ts, so none of this ships in a real build's main path.
 */
import { AxiosError, AxiosHeaders, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';
import dayjs from 'dayjs';
import { toCsv } from '@/lib/csv';
import * as D from './data';

type Handler = (ctx: { q: D.Q; body: Record<string, unknown>; m: RegExpMatchArray; method: string }) => unknown;

const routes: [string, RegExp, Handler][] = [];
const on = (method: string, pattern: RegExp, h: Handler) => routes.push([method, pattern, h]);

const env = <T,>(data: T, q: D.Q) => ({ data, meta: D.meta(q) });
const MOCK_EMAIL = 'td.mock.email';

function audit(action: string, object_type: string, object_id: unknown, before: unknown, after: unknown) {
  let email = 'admin@technosport.in';
  try {
    email = localStorage.getItem(MOCK_EMAIL) ?? email;
  } catch {
    /* ignore */
  }
  D.db.audit.unshift({ id: Date.now(), at: dayjs().format('YYYY-MM-DDTHH:mm:ssZ'), user_email: email, action, object_type, object_id: object_id as number, before, after, reason: null });
}

function paginate<T>(rows: T[], q: D.Q) {
  const size = Number(q.page_size ?? 50);
  const page = Number(q.page ?? 1);
  const start = (page - 1) * size;
  return { count: rows.length, next: start + size < rows.length ? `?page=${page + 1}` : null, previous: page > 1 ? `?page=${page - 1}` : null, results: rows.slice(start, start + size), meta: D.meta(q) };
}

function order<T>(rows: T[], ordering?: string): T[] {
  if (!ordering) return rows;
  const desc = ordering.startsWith('-');
  const k = ordering.replace(/^-/, '') as keyof T;
  return [...rows].sort((a, b) => {
    const x = a[k] as unknown;
    const y = b[k] as unknown;
    if (x === y) return 0;
    if (x === null || x === undefined) return 1;
    if (y === null || y === undefined) return -1;
    const c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y));
    return desc ? -c : c;
  });
}

function crud(path: string, key: keyof typeof D.db, objectType: string) {
  const list = () => D.db[key] as unknown as Record<string, unknown>[];
  on('get', new RegExp(`^${path}$`), ({ q }) => paginate(list(), { ...q, page_size: q.page_size ?? '1000' }));
  on('post', new RegExp(`^${path}$`), ({ body }) => {
    const arr = list();
    const id = Math.max(0, ...arr.map((x) => Number(x.id) || 0)) + 1;
    const row = { id, ...body };
    arr.push(row);
    audit('create', objectType, id, null, row);
    return row;
  });
  on('patch', new RegExp(`^${path}(\\d+)/$`), ({ body, m }) => {
    const row = list().find((x) => x.id === Number(m[1]));
    if (!row) throw 404;
    const before = { ...row };
    Object.assign(row, body);
    audit('update', objectType, row.id, before, row);
    return row;
  });
  on('delete', new RegExp(`^${path}(\\d+)/$`), ({ m }) => {
    const arr = list();
    const i = arr.findIndex((x) => x.id === Number(m[1]));
    if (i < 0) throw 404;
    audit('delete', objectType, m[1], arr[i], null);
    arr.splice(i, 1);
    return null;
  });
}

// ------------------------------------------------------------------ auth
on('post', /^\/auth\/token\/$/, ({ body }) => {
  if (!body.email || !body.password) throw 400;
  try {
    localStorage.setItem(MOCK_EMAIL, String(body.email));
  } catch {
    /* ignore */
  }
  return { access: `mock-access-${Date.now()}`, refresh: `mock-refresh-${Date.now()}` };
});
on('post', /^\/auth\/token\/refresh\/$/, () => ({ access: `mock-access-${Date.now()}` }));
on('get', /^\/auth\/me\/$/, () => {
  let email = 'admin@technosport.in';
  try {
    email = localStorage.getItem(MOCK_EMAIL) ?? email;
  } catch {
    /* ignore */
  }
  return D.me(email);
});
on('post', /^\/auth\/change-password\/$/, ({ body }) => {
  if (String(body.new_password ?? '').length < 8) throw 400;
  return { detail: 'Password changed.' };
});

// ------------------------------------------------------------------ meta & analytics
on('get', /^\/meta\/filters\/$/, () => D.filterOptions);
on('get', /^\/overview\/$/, ({ q }) => env(D.overview(q), q));
on('get', /^\/funnel\/$/, ({ q }) => env(D.funnel(q), q));
on('get', /^\/distributors\/$/, ({ q }) => env(D.distributors(q), q));
on('get', /^\/distributors\/(\d+)\/$/, ({ q, m }) => {
  const d = D.distributorDetail(Number(m[1]), q);
  if (!d) throw 404;
  return env(d, q);
});
on('get', /^\/territory\/$/, ({ q }) => env(D.territory(q), q));
on('get', /^\/orders\/summary\/$/, ({ q }) => env(D.ordersSummary(q), q));
on('get', /^\/orders\/$/, ({ q }) => {
  let rows = D.ORDERS;
  if (q.order_status) rows = rows.filter((o) => o.status === q.order_status);
  if (q.payment_status) rows = rows.filter((o) => o.payment_status === q.payment_status);
  if (q.distributor) {
    const ids = q.distributor.split(',').map(Number);
    rows = rows.filter((o) => ids.includes(o.distributor_id));
  }
  if (q.search) {
    const s = q.search.toLowerCase();
    rows = rows.filter((o) => `${o.display_id} ${o.retailer} ${o.awb ?? ''}`.toLowerCase().includes(s));
  }
  if (q.preset === 'custom' && q.date_from && q.date_to) rows = rows.filter((o) => o.placed_at.slice(0, 10) >= q.date_from! && o.placed_at.slice(0, 10) <= q.date_to!);
  return paginate(order(rows, q.ordering), q);
});
on('get', /^\/orders\/(\d+)\/$/, ({ q, m }) => {
  const o = D.orderDetail(Number(m[1]));
  if (!o) throw 404;
  return env(o, q);
});
on('get', /^\/retailers\/$/, ({ q }) => {
  let rows = D.RETAILERS;
  const seg = q.segment;
  if (seg === 'never_ordered') rows = rows.filter((x) => x.orders === 0 && x.kyc_status === 'approved');
  else if (seg?.startsWith('inactive_')) {
    const n = Number(seg.split('_')[1]);
    rows = rows.filter((x) => x.days_since_last_order !== null && x.days_since_last_order >= n);
  } else if (seg === 'inactive') rows = rows.filter((x) => x.segment === 'inactive');
  else if (seg === 'repeat') rows = rows.filter((x) => x.orders > 1);
  else if (seg) rows = rows.filter((x) => x.segment === seg);
  if (q.warm) rows = rows.filter((x) => String(!!x.warm_match) === q.warm);
  if (q.distributor) {
    const ids = q.distributor.split(',').map(Number);
    rows = rows.filter((x) => ids.includes(x.distributor_id));
  }
  if (q.state) {
    const ids = q.state.split(',').map(Number);
    rows = rows.filter((x) => ids.includes(x.state_id));
  }
  if (q.search) {
    const s = q.search.toLowerCase();
    rows = rows.filter((x) => `${x.name} ${x.city} ${x.phone}`.toLowerCase().includes(s));
  }
  return paginate(order(rows, q.ordering), q);
});
on('get', /^\/retailers\/(\d+)\/$/, ({ q, m }) => {
  const r = D.retailerDetail(Number(m[1]));
  if (!r) throw 404;
  return env(r, q);
});
on('get', /^\/products\/$/, ({ q }) => env(D.products(q), q));
on('get', /^\/products\/tree\/$/, ({ q }) => env(D.productTree(q), q));
on('get', /^\/inventory\/$/, ({ q }) => env(D.inventory(), q));
on('get', /^\/inventory\/items\/$/, ({ q }) => {
  let rows = D.INVENTORY_ITEMS;
  if (q.stock_status) rows = rows.filter((x) => x.status === q.stock_status);
  if (q.search) {
    const s = q.search.toLowerCase();
    rows = rows.filter((x) => `${x.sku} ${x.style} ${x.name}`.toLowerCase().includes(s));
  }
  return paginate(order(rows, q.ordering), q);
});
on('get', /^\/retention\/$/, ({ q }) => env(D.retention(q), q));
on('get', /^\/data-health\/$/, ({ q }) => env(D.dataHealth(), q));
on('post', /^\/data-health\/sync\/$/, ({ body }) => {
  audit('trigger_sync', 'sync_run', null, null, body);
  return { detail: `Refresh queued for ${String(body.source ?? 'all')} sources. This usually takes 3–5 minutes.`, status: 'queued' };
});

// ------------------------------------------------------------------ admin
on('get', /^\/admin\/permissions\/$/, () => D.PERMISSIONS);
crud('/admin/users/', 'users', 'user');
on('post', /^\/admin\/users\/(\d+)\/reset-password\/$/, ({ m }) => {
  audit('reset_password', 'user', m[1], null, null);
  return { detail: 'Password reset.' };
});
crud('/admin/roles/', 'roles', 'role');
on('get', /^\/admin\/audit-log\/$/, ({ q }) => {
  let rows = D.db.audit;
  if (q.search) {
    const s = q.search.toLowerCase();
    rows = rows.filter((x) => `${x.user_email} ${x.action} ${x.object_type}`.toLowerCase().includes(s));
  }
  return paginate(order(rows, q.ordering ?? '-at'), q);
});

on('get', /^\/masters\/targets\/template\/$/, () => new Blob(['﻿month,scope_type,scope_code,metric,value,effective_from,notes\r\n2026-12,overall,,sales,32000000,2026-12-01,\r\n'], { type: 'text/csv' }));
on('post', /^\/masters\/targets\/upload\/$/, () => ({
  created: 12,
  updated: 4,
  errors: [
    { row: 7, message: 'Unknown state "Maharastra" — did you mean "Maharashtra"?' },
    { row: 15, message: 'value must be a positive number' },
  ],
}));
on('get', /^\/masters\/targets\/$/, ({ q }) => {
  let rows = D.db.targets;
  if (q.month) rows = rows.filter((x) => x.month === q.month);
  if (q.metric) rows = rows.filter((x) => x.metric === q.metric);
  return paginate(rows, { ...q, page_size: q.page_size ?? '1000' });
});
on('post', /^\/masters\/targets\/$/, ({ body }) => {
  const id = Math.max(0, ...D.db.targets.map((x) => x.id)) + 1;
  const st = body.scope_type as string;
  const lists: Record<string, { id: number; name: string }[]> = { region: D.REGIONS, state: D.STATES, asm: D.ASMS, distributor: D.DISTRIBUTORS };
  const row = { id, ...body, scope_name: st === 'overall' ? '' : (lists[st]?.find((x) => x.id === body.scope_id)?.name ?? '') } as unknown as (typeof D.db.targets)[number];
  D.db.targets.push(row);
  audit('create', 'target', id, null, row);
  return row;
});
crud('/masters/targets/', 'targets', 'target');
crud('/masters/asms/', 'asms', 'asm');
crud('/masters/pincodes/', 'pincodes', 'pincode');
crud('/masters/regions/', 'regions', 'region');
crud('/masters/states/', 'states', 'state');
crud('/masters/reconciliation/', 'reconciliation', 'mis_reference');
on('get', /^\/masters\/metrics\/$/, () => D.db.metrics);
on('patch', /^\/masters\/metrics\/$/, ({ body }) => {
  const row = D.db.metrics.find((x) => x.code === body.code);
  if (!row) throw 404;
  const before = { ...row };
  Object.assign(row, body);
  audit('update', 'metric', row.code, before, row);
  return row;
});

// ------------------------------------------------------------------ export helper
function toExport(payload: unknown, fmt: string, path: string): Blob {
  let rows: Record<string, unknown>[] = [];
  const p = payload as Record<string, unknown>;
  const data = (p && typeof p === 'object' && 'data' in p ? p.data : p) as Record<string, unknown> | unknown[];
  if (Array.isArray(data)) rows = data as Record<string, unknown>[];
  else if (data && Array.isArray((data as Record<string, unknown>).results)) rows = (data as { results: Record<string, unknown>[] }).results;
  else if (data && Array.isArray((data as Record<string, unknown>).rows)) rows = (data as { rows: Record<string, unknown>[] }).rows;
  else if (data && typeof data === 'object') {
    const firstArr = Object.values(data).find(Array.isArray) as Record<string, unknown>[] | undefined;
    rows = firstArr ?? [];
  }
  const headers = rows.length ? Object.keys(rows[0]) : ['empty'];
  void path;
  void fmt;
  return new Blob(['﻿' + toCsv(headers, rows.map((r) => headers.map((h) => r[h])))], { type: 'text/csv' });
}

// ------------------------------------------------------------------ adapter
const sleep = (ms: number) => new Promise((res) => setTimeout(res, ms));

export async function mockAdapter(config: InternalAxiosRequestConfig): Promise<AxiosResponse> {
  await sleep(180 + Math.random() * 320);
  const method = (config.method ?? 'get').toLowerCase();
  const url = (config.url ?? '').replace(/^https?:\/\/[^/]+/, '').replace(/^\/api/, '').split('?')[0];
  const q: D.Q = {};
  Object.entries((config.params ?? {}) as Record<string, unknown>).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q[k] = String(v);
  });
  let body: Record<string, unknown> = {};
  if (typeof config.data === 'string') {
    try {
      body = JSON.parse(config.data);
    } catch {
      /* not json */
    }
  }
  const respond = (status: number, data: unknown, headers: Record<string, string> = {}): AxiosResponse => ({
    data,
    status,
    statusText: String(status),
    headers: new AxiosHeaders(headers),
    config,
    request: {},
  });
  const fail = (status: number, data: unknown) => {
    const res = respond(status, data);
    throw new AxiosError(`Request failed with status code ${status}`, status >= 500 ? AxiosError.ERR_BAD_RESPONSE : AxiosError.ERR_BAD_REQUEST, config, {}, res);
  };

  const authed = !!String(config.headers?.Authorization ?? '').replace('Bearer', '').trim();
  if (!url.startsWith('/auth/token') && !authed) return fail(401, { detail: 'Authentication credentials were not provided.' });

  for (const [mth, re, h] of routes) {
    if (mth !== method) continue;
    const m = url.match(re);
    if (!m) continue;
    try {
      const out = h({ q, body, m, method });
      if (out instanceof Blob) return respond(200, out, { 'content-disposition': `attachment; filename="${url.split('/').filter(Boolean).join('_')}.csv"` });
      if (q.export) {
        const blob = toExport(out, q.export, url);
        return respond(200, blob, { 'content-disposition': `attachment; filename="${url.split('/').filter(Boolean).join('_')}_${D.NOW.format('YYYYMMDD')}.csv"` });
      }
      return respond(method === 'post' ? 201 : method === 'delete' ? 204 : 200, out);
    } catch (e) {
      if (typeof e === 'number') return fail(e, { detail: e === 404 ? 'Not found.' : 'Invalid request.' });
      throw e;
    }
  }
  return fail(404, { detail: `Mock: no route for ${method.toUpperCase()} ${url}` });
}
