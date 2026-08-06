import {
  createTenantAdminController,
  type TenantAdminControllerCore,
} from './tenantAdminController';
import type { TenantAdminScope } from './tenantAdminHttp';
import type { TenantAuditClient, TenantAuditQuery } from './tenantAuditClient';
import {
  buildTenantAuditPresentation,
  type TenantAuditViewModel,
} from './tenantAuditPresentationModel';

export type TenantAuditController = TenantAdminControllerCore<
  TenantAdminScope,
  TenantAuditViewModel
> &
  Readonly<{ setQuery: (query: TenantAuditQuery) => Promise<void> }>;

export function createTenantAuditController({
  client,
  initialScope,
  initialQuery = {},
}: Readonly<{
  client: TenantAuditClient;
  initialScope: TenantAdminScope;
  initialQuery?: TenantAuditQuery;
}>): TenantAuditController {
  let activeScope = initialScope;
  let activeQuery = initialQuery;
  const core = createTenantAdminController({
    initialScope,
    reasonPrefix: 'tenant_audit',
    loadAuthority: (scope, options) => client.load(scope, activeQuery, options),
    isEmpty: (data) => data.entries.length === 0,
    buildPresentation: buildTenantAuditPresentation,
  });
  return Object.freeze({
    ...core,
    async load(scope) {
      activeScope = scope;
      await core.load(scope);
    },
    async setQuery(query) {
      activeQuery = Object.freeze({ ...query });
      await core.load(activeScope);
    },
  });
}
