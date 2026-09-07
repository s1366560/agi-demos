import type { DesktopRuntimeConfig } from '../../types';
import { createDesktopTenantAcpClientV2, type DesktopTenantAcpOperationsV2 } from '../../plugins/desktopTenantAcpAuthorityModuleV2';
import { createTenantAcpController } from './tenantAcpController';
import type { TenantAcpRouteBinding } from './tenantAcpRouteModule';
import { createDesktopTenantDecisionRecordsClientV2, type DesktopTenantDecisionRecordsOperationsV2 } from '../../plugins/desktopTenantDecisionRecordsAuthorityModuleV2';
import { createTenantDecisionRecordsController } from './tenantDecisionRecordsController';
import type { TenantDecisionRecordsRouteBinding } from './tenantDecisionRecordsRouteModule';
import { createDesktopTenantEventsClientV2, type DesktopTenantEventsOperationsV2 } from '../../plugins/desktopTenantEventsAuthorityModuleV2';
import {
  createDesktopTenantGenesClientV2,
  type DesktopTenantGenesOperationsV2,
} from '../../plugins/desktopTenantGenesAuthorityModuleV2';
import { createDesktopTenantPatternsClientV2, type DesktopTenantPatternsOperationsV2 } from '../../plugins/desktopTenantPatternsAuthorityModuleV2';
import { createTenantEventsController } from './tenantEventsController';
import type { TenantEventsRouteBinding } from './tenantEventsRouteModule';
import { createTenantGenesController } from './tenantGenesController';
import type { TenantGenesRouteBinding } from './tenantGenesRouteModule';
import type { TenantManagementRouteContext } from './tenantManagementRouteModuleFactory';
import {
  createDesktopTenantOrganizationSettingsClientV2,
  type DesktopTenantOrganizationSettingsOperationsV2,
} from '../../plugins/desktopTenantOrganizationSettingsAuthorityModuleV2';
import { createTenantOrganizationSettingsController } from './tenantOrganizationSettingsController';
import type {
  TenantOrganizationSettingsRouteBinding,
} from './tenantOrganizationSettingsRouteModule';
import { createTenantPatternsController } from './tenantPatternsController';
import type { TenantPatternsRouteBinding } from './tenantPatternsRouteModule';
import { createDesktopTenantSettingsClientV2, type DesktopTenantSettingsOperationsV2 } from '../../plugins/desktopTenantSettingsAuthorityModuleV2';
import { createTenantSettingsController } from './tenantSettingsController';
import type { TenantSettingsRouteBinding } from './tenantSettingsRouteModule';
import { createDesktopTenantWebhooksClientV2, type DesktopTenantWebhooksOperationsV2 } from '../../plugins/desktopTenantWebhooksAuthorityModuleV2';
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
  operations: DesktopTenantAcpOperationsV2,
): TenantAcpRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantAcpController({
      client: createDesktopTenantAcpClientV2(operations, config),
      initialScope: scope,
    }),
  });
}

export function createTenantWebhooksRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantManagementRouteContext,
  operations: DesktopTenantWebhooksOperationsV2,
): TenantWebhooksRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantWebhooksController({
      client: createDesktopTenantWebhooksClientV2(operations, config),
      initialScope: scope,
    }),
  });
}

export function createTenantGenesRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantManagementRouteContext,
  operations: DesktopTenantGenesOperationsV2,
): TenantGenesRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantGenesController({
      client: createDesktopTenantGenesClientV2(operations, config),
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
  operations: DesktopTenantOrganizationSettingsOperationsV2,
): TenantOrganizationSettingsRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantOrganizationSettingsController({
      client: createDesktopTenantOrganizationSettingsClientV2(operations, config),
      initialScope: scope,
    }),
  });
}

export function createTenantSettingsRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TenantManagementRouteContext,
  operations: DesktopTenantSettingsOperationsV2,
): TenantSettingsRouteBinding {
  const scope = tenantScope(config, context);
  return Object.freeze({
    scope,
    controller: createTenantSettingsController({
      client: createDesktopTenantSettingsClientV2(operations, config),
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
