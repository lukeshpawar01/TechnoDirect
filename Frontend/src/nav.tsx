import type { ReactNode } from 'react';
import {
  IconBook,
  IconBox,
  IconCart,
  IconFunnel,
  IconGift,
  IconHome,
  IconLayers,
  IconLink,
  IconList,
  IconMap,
  IconPulse,
  IconRepeat,
  IconShield,
  IconStore,
  IconTarget,
  IconTruck,
  IconUsers,
} from './components/Icons';

/** Filters of the global top bar. Each page lists the ones its data actually responds to. */
export type TopFilter = 'date' | 'region' | 'state' | 'asm' | 'distributor' | 'category';
export const ALL_TOP_FILTERS: TopFilter[] = ['date', 'region', 'state', 'asm', 'distributor', 'category'];
const NO_CATEGORY: TopFilter[] = ['date', 'region', 'state', 'asm', 'distributor'];

export interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  /** any of these permissions grants access; empty = any signed-in user */
  perms: string[];
  /** top-bar filters shown on this page (default: all) */
  filters?: TopFilter[];
}

export const MAIN_NAV: NavItem[] = [
  { to: '/overview', label: 'Executive Overview', icon: <IconHome />, perms: ['view_overview'] },
  { to: '/funnel', label: 'Retailer Funnel', icon: <IconFunnel />, perms: ['view_funnel'], filters: NO_CATEGORY },
  { to: '/retailers', label: 'Retailers', icon: <IconStore />, perms: ['view_funnel', 'view_retention'], filters: NO_CATEGORY },
  { to: '/distributors', label: 'Distributors', icon: <IconTruck />, perms: ['view_distributors'] },
  { to: '/territory', label: 'Territory', icon: <IconMap />, perms: ['view_territory'] },
  { to: '/orders', label: 'Orders & Fulfilment', icon: <IconCart />, perms: ['view_orders'] },
  // Category I is in the top bar AND the module row here (same `category` key, so they stay in sync)
  { to: '/products', label: 'Products', icon: <IconLayers />, perms: ['view_products'] },
  // stock is a current snapshot: no date range
  { to: '/inventory', label: 'Inventory', icon: <IconBox />, perms: ['view_inventory'], filters: ['region', 'state', 'asm', 'distributor', 'category'] },
  { to: '/retention', label: 'Retention & Growth', icon: <IconRepeat />, perms: ['view_retention'], filters: NO_CATEGORY },
  { to: '/loyalty', label: 'Loyalty Points', icon: <IconGift />, perms: ['view_loyalty'], filters: NO_CATEGORY },
  { to: '/data-health', label: 'Data Health', icon: <IconPulse />, perms: ['view_data_health'] },
];

export const ADMIN_NAV: NavItem[] = [
  { to: '/admin/users', label: 'Users', icon: <IconUsers />, perms: ['manage_users'] },
  { to: '/admin/roles', label: 'Roles & Permissions', icon: <IconShield />, perms: ['manage_users'] },
  { to: '/admin/targets', label: 'Targets', icon: <IconTarget />, perms: ['manage_targets'] },
  { to: '/admin/mappings', label: 'Mappings', icon: <IconLink />, perms: ['manage_mappings'] },
  { to: '/admin/metrics', label: 'Metric Dictionary', icon: <IconBook />, perms: [] },
  { to: '/admin/audit-log', label: 'Audit Log', icon: <IconList />, perms: ['manage_users'] },
];

export const ALL_NAV = [...MAIN_NAV, ...ADMIN_NAV];

/** Nav item owning a path (detail pages such as /distributors/12 belong to /distributors). */
export function navItemFor(pathname: string): NavItem | undefined {
  return ALL_NAV.find((n) => pathname === n.to || pathname.startsWith(n.to + '/'));
}

export function allowed(item: Pick<NavItem, 'perms'>, can: (p: string) => boolean) {
  return item.perms.length === 0 || item.perms.some(can);
}
