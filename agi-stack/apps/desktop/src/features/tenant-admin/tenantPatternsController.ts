import {
  createTenantManagementController,
  type TenantManagementControllerCore,
} from './tenantManagementController';
import type { TenantManagementScope } from './tenantManagementHttp';
import type { TenantPatternsClient } from './tenantPatternsClient';
import {
  buildTenantPatternsPresentation,
  type TenantPatternsViewModel,
} from './tenantPatternsPresentationModel';

export type TenantPatternsController = TenantManagementControllerCore<
  TenantManagementScope,
  TenantPatternsViewModel
> &
  Readonly<{ deletePattern: (patternId: string) => Promise<void> }>;

export function createTenantPatternsController({
  client,
  initialScope,
}: Readonly<{
  client: TenantPatternsClient;
  initialScope: TenantManagementScope;
}>): TenantPatternsController {
  const core = createTenantManagementController({
    initialScope,
    reasonPrefix: 'tenant_patterns',
    loadAuthority: client.load,
    isEmpty: (data) => data.patterns.length === 0,
    buildPresentation: buildTenantPatternsPresentation,
  });
  return Object.freeze({
    ...core,
    deletePattern: (patternId) =>
      core.runAction('delete', (scope, signal) =>
        client.deletePattern(scope, patternId, { signal }),
      ),
  });
}
