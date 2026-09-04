import type { DesktopRuntimeConfig } from '../../types';
import { createDesktopTenantAuditClientV2, type DesktopTenantAuditOperationsV2 } from '../../plugins/desktopTenantAuditAuthorityModuleV2';
import { createTenantAuditController } from './tenantAuditController';
import type { TenantAuditRouteBinding } from './tenantAuditRouteModule';
import { createDesktopTenantBillingClientV2, type DesktopTenantBillingOperationsV2 } from '../../plugins/desktopTenantBillingAuthorityModuleV2';
import { createTenantBillingController } from './tenantBillingController';
import type { TenantBillingRouteBinding } from './tenantBillingRouteModule';
import { createDesktopTenantGovernanceClientV2, type DesktopTenantGovernanceOperationsV2 } from '../../plugins/desktopTenantGovernanceAuthorityModuleV2';
import { createTenantGovernanceController } from './tenantGovernanceController';
import type { TenantGovernanceRouteBinding } from './tenantGovernanceRouteModule';
import type { TenantAdminRouteContext } from './tenantAdminRouteModuleFactory';
import { createDesktopTenantTrustClientV2, type DesktopTenantTrustOperationsV2 } from '../../plugins/desktopTenantTrustAuthorityModuleV2';
import { createTenantTrustController } from './tenantTrustController';
import type { TenantTrustRouteBinding } from './tenantTrustRouteModule';

export function createTenantGovernanceRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantAdminRouteContext,
  operations: DesktopTenantGovernanceOperationsV2,
): TenantGovernanceRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantGovernanceController({
      client: createDesktopTenantGovernanceClientV2(operations, config),
      initialScope: scope,
    }),
  });
}

export function createTenantBillingRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantAdminRouteContext,
  operations: DesktopTenantBillingOperationsV2,
): TenantBillingRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantBillingController({
      client: createDesktopTenantBillingClientV2(operations, config),
      initialScope: scope,
    }),
  });
}

export function createTenantAuditRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantAdminRouteContext,
  operations: DesktopTenantAuditOperationsV2,
): TenantAuditRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantAuditController({
      client: createDesktopTenantAuditClientV2(operations, config),
      initialScope: scope,
    }),
  });
}

export function createTenantTrustRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantAdminRouteContext,
  operations: DesktopTenantTrustOperationsV2,
): TenantTrustRouteBinding {
  const baseScope = tenantScope(config, context);
  const scope = Object.freeze({
    ...baseScope,
    workspaceId: config.workspaceId,
  });
  return Object.freeze({
    scope,
    controller: createTenantTrustController({
      client: createDesktopTenantTrustClientV2(operations, config),
      initialScope: scope,
    }),
  });
}

function tenantScope(config: DesktopRuntimeConfig, context: TenantAdminRouteContext) {
  return Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
  });
}
