import type { DesktopRuntimeConfig } from '../../types';
import { createTenantAuditClient } from './tenantAuditClient';
import { createTenantAuditController } from './tenantAuditController';
import type { TenantAuditRouteBinding } from './tenantAuditRouteModule';
import { createTenantBillingClient } from './tenantBillingClient';
import { createTenantBillingController } from './tenantBillingController';
import type { TenantBillingRouteBinding } from './tenantBillingRouteModule';
import { createTenantGovernanceClient } from './tenantGovernanceClient';
import { createTenantGovernanceController } from './tenantGovernanceController';
import type { TenantGovernanceRouteBinding } from './tenantGovernanceRouteModule';
import type { TenantAdminRouteContext } from './tenantAdminRouteModuleFactory';
import { createTenantTrustClient } from './tenantTrustClient';
import { createTenantTrustController } from './tenantTrustController';
import type { TenantTrustRouteBinding } from './tenantTrustRouteModule';

export function createTenantGovernanceRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantAdminRouteContext,
): TenantGovernanceRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantGovernanceController({
      client: createTenantGovernanceClient(config),
      initialScope: scope,
    }),
  });
}

export function createTenantBillingRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantAdminRouteContext,
): TenantBillingRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantBillingController({
      client: createTenantBillingClient(config),
      initialScope: scope,
    }),
  });
}

export function createTenantAuditRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantAdminRouteContext,
): TenantAuditRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantAuditController({
      client: createTenantAuditClient(config),
      initialScope: scope,
    }),
  });
}

export function createTenantTrustRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantAdminRouteContext,
): TenantTrustRouteBinding {
  const baseScope = tenantScope(config, context);
  const scope = Object.freeze({
    ...baseScope,
    workspaceId: config.workspaceId,
  });
  return Object.freeze({
    scope,
    controller: createTenantTrustController({
      client: createTenantTrustClient(config),
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
