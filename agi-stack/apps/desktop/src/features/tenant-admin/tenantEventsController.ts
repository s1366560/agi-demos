import {
  createTenantManagementController,
  type TenantManagementControllerCore,
} from './tenantManagementController';
import type { TenantManagementScope } from './tenantManagementHttp';
import type { TenantEventFilters, TenantEventsClient } from './tenantEventsClient';
import {
  buildTenantEventsPresentation,
  type TenantEventsViewModel,
} from './tenantEventsPresentationModel';

export type TenantEventsController = TenantManagementControllerCore<
  TenantManagementScope,
  TenantEventsViewModel
> &
  Readonly<{
    setFilters: (filters: TenantEventFilters) => Promise<void>;
    setPage: (page: number) => Promise<void>;
  }>;

export function createTenantEventsController({
  client,
  initialScope,
}: Readonly<{
  client: TenantEventsClient;
  initialScope: TenantManagementScope;
}>): TenantEventsController {
  let filters: TenantEventFilters = Object.freeze({ page: 1, pageSize: 20 });
  const core = createTenantManagementController({
    initialScope,
    reasonPrefix: 'tenant_events',
    loadAuthority: (scope, options) => client.load(scope, { ...options, filters }),
    isEmpty: (data) => data.events.length === 0,
    buildPresentation: buildTenantEventsPresentation,
  });
  return Object.freeze({
    ...core,
    async setFilters(next) {
      filters = Object.freeze({ ...next, page: next.page ?? 1, pageSize: next.pageSize ?? 20 });
      await core.load(initialScope);
    },
    async setPage(page) {
      filters = Object.freeze({ ...filters, page });
      await core.load(initialScope);
    },
  });
}
