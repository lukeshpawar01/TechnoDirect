import { lazy, Suspense, type ReactNode } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from '@/auth/AuthContext';
import { Layout } from '@/components/Layout';
import { ErrorState, LoadingBlock } from '@/components/ui';
import { ALL_NAV, MAIN_NAV, ADMIN_NAV, allowed } from '@/nav';

const Overview = lazy(() => import('@/pages/Overview'));
const Funnel = lazy(() => import('@/pages/Funnel'));
const Retailers = lazy(() => import('@/pages/Retailers'));
const RetailerDetail = lazy(() => import('@/pages/RetailerDetail'));
const Distributors = lazy(() => import('@/pages/Distributors'));
const DistributorDetail = lazy(() => import('@/pages/DistributorDetail'));
const Territory = lazy(() => import('@/pages/Territory'));
const Orders = lazy(() => import('@/pages/Orders'));
const Products = lazy(() => import('@/pages/Products'));
const Inventory = lazy(() => import('@/pages/Inventory'));
const Retention = lazy(() => import('@/pages/Retention'));
const Loyalty = lazy(() => import('@/pages/Loyalty'));
const BlueOrigin = lazy(() => import('@/pages/BlueOrigin'));
const Settlements = lazy(() => import('@/pages/Settlements'));
const Pnl = lazy(() => import('@/pages/Pnl'));
const Mbr = lazy(() => import('@/pages/Mbr'));
const DataHealth = lazy(() => import('@/pages/DataHealth'));
const Users = lazy(() => import('@/pages/admin/Users'));
const Roles = lazy(() => import('@/pages/admin/Roles'));
const Targets = lazy(() => import('@/pages/admin/Targets'));
const Mappings = lazy(() => import('@/pages/admin/Mappings'));
const Metrics = lazy(() => import('@/pages/admin/Metrics'));
const AuditLog = lazy(() => import('@/pages/admin/AuditLog'));

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading, error, retry } = useAuth();
  // open access: no sign-in, the dashboard loads for everyone
  if (error && !user) {
    return (
      <div className="card mx-auto mt-16 max-w-md p-6">
        <ErrorState error={error} onRetry={retry} />
      </div>
    );
  }
  if (loading || !user) return <LoadingBlock height={400} label="Loading the dashboard…" />;
  return <>{children}</>;
}

/** Route guard by permission (same rule as the sidebar). */
function Guard({ path, children }: { path: string; children: ReactNode }) {
  const { can } = useAuth();
  const item = ALL_NAV.find((n) => path === n.to || path.startsWith(n.to + '/'));
  if (item && !allowed(item, can)) return <Forbidden />;
  return <>{children}</>;
}

function Forbidden() {
  return (
    <div className="card mx-auto mt-16 max-w-md p-8 text-center">
      <h1 className="text-lg font-semibold">You don't have access to this page</h1>
      <p className="mt-2 text-sm text-muted">Ask a master admin to grant your role the required permission.</p>
    </div>
  );
}

function NotFound() {
  return (
    <div className="card mx-auto mt-16 max-w-md p-8 text-center">
      <h1 className="text-lg font-semibold">Page not found</h1>
    </div>
  );
}

function Home() {
  const { can } = useAuth();
  const first = [...MAIN_NAV, ...ADMIN_NAV].find((n) => n.perms.length > 0 && allowed(n, can)) ?? ADMIN_NAV.find((n) => n.perms.length === 0);
  return <Navigate to={first?.to ?? '/admin/metrics'} replace />;
}

const g = (path: string, el: ReactNode) => <Guard path={path}>{el}</Guard>;

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Home />} />
        <Route
          path="*"
          element={
            <Suspense fallback={<LoadingBlock height={400} />}>
              <Routes>
                <Route path="overview" element={g('/overview', <Overview />)} />
                <Route path="funnel" element={g('/funnel', <Funnel />)} />
                <Route path="retailers" element={g('/retailers', <Retailers />)} />
                <Route path="retailers/:id" element={g('/retailers', <RetailerDetail />)} />
                <Route path="distributors" element={g('/distributors', <Distributors />)} />
                <Route path="distributors/:id" element={g('/distributors', <DistributorDetail />)} />
                <Route path="territory" element={g('/territory', <Territory />)} />
                <Route path="orders" element={g('/orders', <Orders />)} />
                <Route path="products" element={g('/products', <Products />)} />
                <Route path="inventory" element={g('/inventory', <Inventory />)} />
                <Route path="retention" element={g('/retention', <Retention />)} />
                <Route path="loyalty" element={g('/loyalty', <Loyalty />)} />
                <Route path="blueorigin" element={g('/blueorigin', <BlueOrigin />)} />
                <Route path="settlements" element={g('/settlements', <Settlements />)} />
                <Route path="pnl" element={g('/pnl', <Pnl />)} />
                <Route path="mbr" element={g('/mbr', <Mbr />)} />
                <Route path="mbr/:page" element={g('/mbr', <Mbr />)} />
                <Route path="data-health" element={g('/data-health', <DataHealth />)} />
                <Route path="admin/users" element={g('/admin/users', <Users />)} />
                <Route path="admin/roles" element={g('/admin/roles', <Roles />)} />
                <Route path="admin/targets" element={g('/admin/targets', <Targets />)} />
                <Route path="admin/mappings" element={g('/admin/mappings', <Mappings />)} />
                <Route path="admin/metrics" element={g('/admin/metrics', <Metrics />)} />
                <Route path="admin/audit-log" element={g('/admin/audit-log', <AuditLog />)} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
          }
        />
      </Route>
    </Routes>
  );
}
