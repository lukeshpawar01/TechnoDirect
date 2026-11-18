import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { usePagedList } from '@/api/hooks';
import type { RetailerRow } from '@/api/types';
import { DataTable } from '@/components/DataTable';
import { RfmDot } from '@/components/RfmPanel';
import { Drawer } from '@/components/ui';
import { linkWithFilters, useFilters } from '@/lib/filters';
import { date, inr, num, titleCase } from '@/lib/format';

/** What a number / bar stands for: a title for the panel and the /retailers/ parameters that select its retailers. */
export interface RetailersDrillSpec {
  title: string;
  subtitle?: string;
  params: Record<string, string>;
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');

/**
 * Drill-down panel: the retailers behind one number, bar or row (Retailer Funnel), with the page's filters applied,
 * downloadable as CSV / XLSX with exactly the same selection. Click a row for the retailer profile.
 */
export function RetailersDrill({ spec, onClose, fromLabel }: { spec: RetailersDrillSpec | null; onClose: () => void; fromLabel: string }) {
  const [page, setPage] = useState(1);
  const [ordering, setOrdering] = useState('-lifetime_sales');
  const { apiParams, searchParams } = useFilters();
  const nav = useNavigate();
  const loc = useLocation();
  const key = spec ? JSON.stringify(spec.params) : '';

  useEffect(() => {
    setPage(1);
    setOrdering('-lifetime_sales');
  }, [key]);

  const open = !!spec;
  const list = usePagedList<RetailerRow & { lifetime_orders?: number; lifetime_sales?: number }>(
    '/retailers/',
    { ...(spec?.params ?? {}), page, page_size: 25, ordering },
    { enabled: open },
  );

  return (
    <Drawer open={open} onClose={onClose} width={1100} title={spec?.title ?? ''}>
      {spec && (
        <>
          <p className="mb-3 text-xs text-ink2">
            {list.data ? `${num(list.data.count)} retailers` : 'Loading…'}
            {spec.subtitle ? ` · ${spec.subtitle}` : ''} · click a row for the retailer profile
          </p>
          <DataTable
            rows={list.data?.results}
            loading={list.isLoading}
            fetching={list.isFetching}
            error={list.error}
            onRetry={() => list.refetch()}
            rowKey={(r) => r.id}
            dense
            onRowClick={(r) => nav(linkWithFilters(`/retailers/${r.id}`, searchParams), { state: { from: loc.pathname + loc.search, fromLabel } })}
            exportName={`retailers_${slug(spec.title)}`}
            exportPath="/retailers/"
            exportParams={{ ...apiParams, ...spec.params }}
            server={{ count: list.data?.count ?? 0, page, pageSize: 25, onPage: setPage, ordering, onOrdering: setOrdering }}
            emptyTitle="No retailers for this selection"
            columns={[
              { key: 'name', header: 'Retailer', render: (r) => <span className="font-medium">{r.name}</span> },
              { key: 'phone', header: 'Phone', sortable: false },
              { key: 'state', header: 'State' },
              { key: 'distributor', header: 'Distributor' },
              { key: 'asm', header: 'ASM' },
              { key: 'kyc_status', header: 'KYC', render: (r) => titleCase(r.kyc_status) },
              {
                key: 'rfm_label',
                header: 'RFM segment',
                sortable: false,
                render: (r) => (
                  <span className="flex items-center gap-1.5 whitespace-nowrap text-xs">
                    <RfmDot segment={r.rfm_segment ?? 'prospect'} />
                    {r.rfm_label ?? '–'}
                  </span>
                ),
              },
              { key: 'first_order_date', header: 'First order', render: (r) => date(r.first_order_date) },
              { key: 'last_order_date', header: 'Last order', render: (r) => date(r.last_order_date) },
              { key: 'lifetime_orders', header: 'Orders (all time)', align: 'right', render: (r) => num(r.lifetime_orders ?? null) },
              { key: 'lifetime_sales', header: 'Sales (all time)', align: 'right', render: (r) => inr(r.lifetime_sales ?? null) },
            ]}
          />
        </>
      )}
    </Drawer>
  );
}
