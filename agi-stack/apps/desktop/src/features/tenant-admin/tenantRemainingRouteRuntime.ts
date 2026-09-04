import type { DesktopRuntimeConfig } from '../../types';
import { createTenantAcpClient } from './tenantAcpClient';
import { createTenantAcpController } from './tenantAcpController';
import type { TenantAcpRouteBinding } from './tenantAcpRouteModule';
import { createDesktopTenantDecisionRecordsClientV2, type DesktopTenantDecisionRecordsOperationsV2 } from '../../plugins/desktopTenantDecisionRecordsAuthorityModuleV2';
import { createTenantDecisionRecordsController } from './tenantDecisionRecordsController';
import type { TenantDecisionRecordsRouteBinding } from './tenantDecisionRecordsRouteModule';
import { createDesktopTenantEventsClientV2, type DesktopTenantEventsOperationsV2 } from '../../plugins/desktopTenantEventsAuthorityModuleV2';
import { createDesktopTenantPatternsClientV2, type DesktopTenantPatternsOperationsV2 } from '../../plugins/desktopTenantPatternsAuthorityModuleV2';
import { createTenantEventsController } from './tenantEventsController';
import type { TenantEventsRouteBinding } from './tenantEventsRouteModule';
import { createTenantGenesClient } from './tenantGenesClient';
import { createTenantGenesController } from './tenantGenesController';
import type { TenantGenesRouteBinding } from './tenantGenesRouteModule';
import type { TenantManagementRouteContext } from './tenantManagementRouteModuleFactory';
import { createTenantOrganizationSettingsClient } from './tenantOrganizationSettingsClient';
import { createTenantOrganizationSettingsController } from './tenantOrganizationSettingsController';
import type {
  TenantOrganizationSettingsRouteBinding,
} from './tenantOrganizationSettingsRouteModule';
import { createTenantPatternsController } from './tenantPatternsController';
import type { TenantPatternsRouteBinding } from './tenantPatternsRouteModule';
import { createTenantSettingsClient } from './tenantSettingsClient';
import { createTenantSettingsController } from './tenantSettingsController';
import type { TenantSettingsRouteBinding } from './tenantSettingsRouteModule';
import { createTenantWebhooksClient } from './tenantWebhooksClient';
import { createTenantWebhooksController } from './tenantWebhooksController';
import type { TenantWebhooksRouteBinding } from './tenantWebhooksRouteModule';

export function createTenantPatternsRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantManagementRouteContext,
  operations: DesktopTenantPatternsOperationsV2,
): TenantPatternsRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantPatternsController({
      client: createDesktopTenantPatternsClientV2(operations, config),
      initialScope: scope,
    }),
  });
}

export function createTenantAcpRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantManagementRouteContext,
): TenantAcpRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantAcpController({
      client: createTenantAcpClient(config),
      initialScope: scope,
    }),
  });
}

export function createTenantWebhooksRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantManagementRouteContext,
): TenantWebhooksRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantWebhooksController({
      client: createTenantWebhooksClient(config),
      initialScope: scope,
    }),
  });
}

export function createTenantGenesRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantManagementRouteContext,
): TenantGenesRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantGenesController({
      client: createTenantGenesClient(config),
      initialScope: scope,
    }),
  });
}

export function createTenantEventsRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantManagementRouteContext,
  operations: DesktopTenantEventsOperationsV2,
): TenantEventsRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantEventsController({
      client: createDesktopTenantEventsClientV2(operations, config),
      initialScope: scope,
    }),
  });
}

export function createTenantDecisionRecordsRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantManagementRouteContext,
  operations: DesktopTenantDecisionRecordsOperationsV2,
): TenantDecisionRecordsRouteBinding {
  const scope = Object.freeze({
    ...tenantScope(config, context),
    workspaceId: config.workspaceId,
  });
  return Object.freeze({
    scope,
    controller: createTenantDecisionRecordsController({
      client: createDesktopTenantDecisionRecordsClientV2(operations, config),
      initialScope: scope,
    }),
  });
}

export function createTenantOrganizationSettingsRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantManagementRouteContext,
): TenantOrganizationSettingsRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantOrganizationSettingsController({
      client: createTenantOrganizationSettingsClient(config),
      initialScope: scope,
    }),
  });
}

export function createTenantSettingsRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantManagementRouteContext,
): TenantSettingsRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantSettingsController({
      client: createTenantSettingsClient(config),
      initialScope: scope,
    }),
  });
}

function tenantScope(config: DesktopRuntimeConfig, context: TenantManagementRouteContext) {
  return Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
  });
}
