import type {
  TenantApprovalDecision,
  TenantDecisionFilters,
  TenantDecisionRecordsClient,
} from './tenantDecisionRecordsClient';
import {
  buildTenantDecisionRecordsPresentation,
  type TenantDecisionRecordsViewModel,
} from './tenantDecisionRecordsPresentationModel';
import {
  createTenantManagementController,
  type TenantManagementControllerCore,
} from './tenantManagementController';
import type { TenantManagementWorkspaceScope } from './tenantManagementHttp';

export type TenantDecisionRecordsController = TenantManagementControllerCore<
  TenantManagementWorkspaceScope,
  TenantDecisionRecordsViewModel
> &
  Readonly<{
    setFilters: (filters: TenantDecisionFilters) => Promise<void>;
    resolveApproval: (recordId: string, decision: TenantApprovalDecision) => Promise<void>;
  }>;

export function createTenantDecisionRecordsController({
  client,
  initialScope,
}: Readonly<{
  client: TenantDecisionRecordsClient;
  initialScope: TenantManagementWorkspaceScope;
}>): TenantDecisionRecordsController {
  let filters: TenantDecisionFilters = Object.freeze({});
  const core = createTenantManagementController({
    initialScope,
    reasonPrefix: 'tenant_decisions',
    loadAuthority: (scope, options) => client.load(scope, { ...options, filters }),
    isEmpty: (data) => data.records.length === 0,
    buildPresentation: buildTenantDecisionRecordsPresentation,
  });
  return Object.freeze({
    ...core,
    async setFilters(next) {
      filters = Object.freeze({ ...next });
      await core.load(initialScope);
    },
    resolveApproval: (recordId, decision) =>
      core.runAction('resolve-approval', async (scope, signal) => {
        await client.resolveApproval(scope, recordId, decision, { signal });
      }),
  });
}
