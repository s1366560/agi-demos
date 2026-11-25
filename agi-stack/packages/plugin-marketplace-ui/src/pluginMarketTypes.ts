import type { ReactNode } from 'react';
import type { PackagePage, PageTarget } from '../../plugin-slots/src/richPage';
import type { MarketplaceTransport } from './client';

export type MarketView = 'all' | 'installed' | 'updates';
export type Localized = Partial<Record<'zh' | 'en', string>>;
export interface Installation {
  plugin_id: string;
  desired_revision: number;
  installed_version: string | null;
  running_version: string | null;
  actual_digest: string | null;
  failure?: string | null;
  targets?: string[];
  pages?: PackagePage[];
  signed_slot_targets?: PageTarget[];
  commands?: string[];
}
export interface CatalogItem {
  package_name: string | null;
  plugin_id: string;
  display_name: Localized;
  description: Localized;
  icon: string | null;
  targets: string[];
  latest_version: string | null;
  update_available: boolean;
  installation: Installation | null;
}
export interface Catalog {
  can_manage: boolean;
  source: string | null;
  source_error: string | null;
  total: number;
  items: CatalogItem[];
}
export interface VerifiedRelease {
  version: string;
  digest: string;
  permissions: string[];
  pages: PackagePage[];
  commands: string[];
  targets: string[];
}
export interface MarketDetail extends CatalogItem {
  can_execute: boolean;
  can_manage: boolean;
  source: string | null;
  source_error: string | null;
  versions: string[];
  release: VerifiedRelease | null;
  current_permissions: string[];
  previous_version: string | null;
  desired_revision: number;
  release_error: string | null;
}
export interface PluginMarketProps {
  tenantId: string;
  projectId: string | null;
  target: PageTarget;
  canManage?: boolean;
  transport: MarketplaceTransport;
  locale?: string;
  pluginId: string | null;
  onSelect(pluginId: string | null): void;
  onOpen(path: string): void;
  importArchive?(): Promise<string | null>;
  declarativePage?(installation: Installation, canExecute: boolean): ReactNode;
  deviceSettings?(
    pluginId: string,
    digest: string | null,
    release?: { packageName: string; version: string }
  ): ReactNode;
  onActivated?(installation: Installation): void;
  onChanged?(): void;
}
export const MARKET_BASE = '/api/v1/platform-plugins/v2/optional-business';

export const TENANT_MARKET_BASE = '/api/v1/tenant-packages';

export function packageBase(projectId: string | null) {
  return projectId === null ? TENANT_MARKET_BASE : MARKET_BASE;
}

export function packageScope(tenantId: string, projectId: string | null): Record<string, string> {
  return projectId === null ? { tenant_id: tenantId } : { tenant_id: tenantId, project_id: projectId };
}
