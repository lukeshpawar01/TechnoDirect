import { useLocation, useNavigate } from 'react-router-dom';
import { useAnalytics } from '@/api/hooks';
import { linkWithFilters, useFilters } from '@/lib/filters';
import { date, inr, num } from '@/lib/format';
import { DataTable } from './DataTable';
import { Drawer } from './ui';

export type ConversionKind = 'new' | 'bo' | 'gps';
export interface ConversionDrillSpec {
  groupBy: string;
  id: number | null;
  name: string;
  kind: ConversionKind;
}
interface Row {
  retailer_id: number;
  retailer: string;
  phone: string | null;
  city: string;
  state: string | null;
  tier: string;
  bo_existing: boolean;
  bo_distributor: string | null;
  bo_asm: string | null;
  first_order: string | null;
  first_order_date: string | null;
  first_order_value: number;
  td_distributor: string | null;
  signed_up: string | null;
}

const TITLE: Record<ConversionKind, string> = {
  new: 'New retailers (first-ever TD order)',
  bo: 'BlueOrigin retailers converted to TD',
  gps: 'BlueOrigin Gold / Platinum / Silver converted to TD',
};
const HINT: Record<ConversionKind, string> = {
  new: 'First-ever TD order in the period, by the territory of that order',
  bo: 'Bought offline in BlueOrigin before the period, first TD order in the period - by their BlueOrigin territory',
  gps: 'The Gold / Platinum / Silver ones among the BlueOrigin conversions',
};

/** Side panel: the retailers behind a New / BO -> TD / BO G/P/S number on the Region & ASM scorecard. */
export function ConversionDrill({ spec, onClose }: { spec: ConversionDrillSpec | null; onClose: () => void }) {
  const { searchParams } = useFilters();
  const nav = useNavigate();
  const loc = useLocation();
  const q = useAnalytics<{ rows: Row[] }>(
    '/territory/retailers/',
    { group_by: spec?.groupBy, id: spec ? (spec.id ?? 'none') : undefined, kind: spec?.kind },
    { enabled: !!spec },
  );
  const rows = q.data?.data?.rows;

  return (
    <Drawer open={!!spec} onClose={onClose} width={1100} title={spec ? `${TITLE[spec.kind]} · ${spec.name}` : ''}>
      {spec && (
        <>
          <p className="mb-3 text-xs text-ink2">
            {rows ? `${num(rows.length)} retailers` : 'Loading…'} · {HINT[spec.kind]} · click a row for the retailer profile
          </p>
          <DataTable
            rows={rows}
            loading={q.isLoading}
            fetching={q.isFetching}
            error={q.error}
            onRetry={() => q.refetch()}
            rowKey={(r) => r.retailer_id}
            dense
            exportName={`${spec.kind}_retailers_${spec.name}`.toLowerCase().replace(/[^a-z0-9]+/g, '_')}
            onRowClick={(r) => nav(linkWithFilters(`/retailers/${r.retailer_id}`, searchParams), { state: { from: loc.pathname + loc.search, fromLabel: 'Region & ASM Performance' } })}
            columns={[
              { key: 'retailer', header: 'Retailer', render: (r) => <div><div className="text-ink">{r.retailer}</div><div className="text-xs text-muted">{[r.city, r.state].filter(Boolean).join(', ')}</div></div>, value: (r) => r.retailer },
              { key: 'phone', header: 'Phone' },
              { key: 'tier', header: 'BO tier' },
              { key: 'bo_distributor', header: 'BO distributor', render: (r) => r.bo_distributor ?? '–' },
              { key: 'bo_asm', header: 'BO ASM', render: (r) => r.bo_asm ?? '–' },
              { key: 'td_distributor', header: 'TD distributor (1st order)', render: (r) => r.td_distributor ?? '–' },
              { key: 'first_order_date', header: 'First TD order', render: (r) => (r.first_order_date ? `${date(r.first_order_date)} · #${r.first_order}` : '–'), value: (r) => r.first_order_date },
              { key: 'first_order_value', header: 'Order value', align: 'right', render: (r) => inr(r.first_order_value), value: (r) => r.first_order_value },
              { key: 'signed_up', header: 'Signed up', render: (r) => date(r.signed_up) },
            ]}
          />
        </>
      )}
    </Drawer>
  );
}
