import type { AuthState, DesktopRuntimeConfig } from '../../types';
import { isIdentityAuthenticated } from '../auth/authContextModel';
import type { CloudProjectOverviewClient } from '../project/projectOverviewClient';
import { createCloudProjectOverviewClient } from '../project/projectOverviewCloudClient';
import {
  createProjectOverviewController,
  type ProjectOverviewController,
  type ProjectOverviewControllerOptions,
} from '../project/projectOverviewController';
import {
  createLocalProjectOverviewClient,
  type LocalProjectOverviewClient,
} from '../project/projectOverviewLocalClient';
import type {
  ProjectOverviewRouteBinding,
  ProjectOverviewRouteContext,
} from '../project/projectOverviewRouteModule';
import type { DeadLetterQueueRouteBinding } from '../governance/deadLetterQueueRouteModule';
import { createDeadLetterQueueController } from '../governance/deadLetterQueueController';
import { createDeadLetterQueueHttpClient } from '../governance/deadLetterQueueHttpClient';
import type { RuntimePoolRouteBinding } from '../runtime-pool/runtimePoolRouteModule';
import { createRuntimePoolController } from '../runtime-pool/runtimePoolController';
import { createRuntimePoolHttpClient } from '../runtime-pool/runtimePoolClient';
import type { RuntimeInstancesRouteBinding } from '../runtime-instances/runtimeInstancesRouteModule';
import { createRuntimeInstancesController } from '../runtime-instances/runtimeInstancesController';
import { createRuntimeInstancesClient } from '../runtime-instances/runtimeInstancesClient';
import type { RuntimeClustersRouteBinding } from '../runtime-clusters/runtimeClustersRouteModule';
import { createRuntimeClustersController } from '../runtime-clusters/runtimeClustersController';
import { createRuntimeClustersClient } from '../runtime-clusters/runtimeClustersClient';
import type { RuntimeDeploymentsRouteBinding } from '../runtime-deployments/runtimeDeploymentsRouteModule';
import { createRuntimeDeploymentsController } from '../runtime-deployments/runtimeDeploymentsController';
import { createRuntimeDeploymentsClient } from '../runtime-deployments/runtimeDeploymentsClient';
import type { InstanceTemplatesRouteBinding } from '../instance-templates/instanceTemplatesRouteModule';
import { createInstanceTemplatesController } from '../instance-templates/instanceTemplatesController';
import { createInstanceTemplatesClient } from '../instance-templates/instanceTemplatesClient';
import type { UnifiedRuntimesRouteBinding } from '../unified-runtimes/unifiedRuntimesRouteModule';
import { createUnifiedRuntimesController } from '../unified-runtimes/unifiedRuntimesController';
import { createUnifiedRuntimesClient } from '../unified-runtimes/unifiedRuntimesClient';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilitySnapshot,
} from '../runtime/capabilitySnapshot';
import type { TenantOverviewRouteBinding } from '../tenant/tenantOverviewRouteModule';
import { createTenantOverviewController } from '../tenant/tenantOverviewController';
import { createTenantOverviewHttpClient } from '../tenant/tenantOverviewHttpClient';
import type { TenantAnalyticsRouteBinding } from '../tenant/tenantAnalyticsRouteModule';
import { createTenantAnalyticsController } from '../tenant/tenantAnalyticsController';
import { createTenantAnalyticsHttpClient } from '../tenant/tenantAnalyticsHttpClient';
import type { TenantProjectsRouteBinding } from '../tenant/tenantProjectsRouteModule';
import { createTenantProjectsController } from '../tenant/tenantProjectsController';
import { createTenantProjectsHttpClient } from '../tenant/tenantProjectsHttpClient';
import type { TenantTasksRouteBinding } from '../tenant/tenantTasksRouteModule';
import { createTenantTasksController } from '../tenant/tenantTasksController';
import { createTenantTasksHttpClient } from '../tenant/tenantTasksHttpClient';
import type { TenantWorkspacesRouteBinding } from '../tenant/tenantWorkspacesRouteModule';
import { createTenantWorkspacesController } from '../tenant/tenantWorkspacesController';
import { createTenantWorkspacesHttpClient } from '../tenant/tenantWorkspacesHttpClient';
import type { DesktopRouteContext } from './desktopRouteRegistry';

export type ProjectOverviewRouteRuntimeDependencies = Readonly<{
  createCloudClient?: (
    config: DesktopRuntimeConfig,
  ) => CloudProjectOverviewClient;
  createLocalClient?: (
    config: DesktopRuntimeConfig,
  ) => LocalProjectOverviewClient;
  createController?: (
    options: ProjectOverviewControllerOptions,
  ) => ProjectOverviewController;
}>;

export function desktopRoutePermissionsForContext(
  auth: AuthState,
  context: DesktopRouteContext,
): ReadonlySet<string> {
  const permissions = new Set<string>();
  if (!isIdentityAuthenticated(auth)) {
    permissions.add('anonymous');
    return permissions;
  }

  permissions.add('authenticated');
  const tenantId = context.tenantId;
  if (tenantId !== undefined && auth.tenants.some((tenant) => tenant.id === tenantId)) {
    permissions.add('tenant_member');
  }

  const projectId = context.projectId;
  if (
    tenantId !== undefined &&
    projectId !== undefined &&
    auth.projects.some(
      (project) =>
        project.id === projectId && project.tenant_id === tenantId,
    )
  ) {
    permissions.add('project_member');
  }
  return permissions;
}

export function desktopRouteBasePermissionsForAuth(
  auth: AuthState,
): ReadonlySet<string> {
  return desktopRoutePermissionsForContext(auth, Object.freeze({}));
}

export function resolveDesktopRouteCapability(
  snapshot: DesktopCapabilitySnapshot | null,
  capability: string,
  context: DesktopRouteContext,
): DesktopCapabilityAvailability | null {
  if (snapshot === null || !Object.hasOwn(snapshot.capabilities, capability)) {
    return null;
  }
  const capabilities: Readonly<Record<string, DesktopCapabilityAvailability>> =
    snapshot.capabilities;
  const availability = capabilities[capability] ?? null;
  if (
    availability === null ||
    capability !== 'tenant-tenant-deploy' ||
    context.instanceId === undefined
  ) {
    return availability;
  }
  return Object.freeze({
    ...availability,
    scope: Object.freeze({
      ...availability.scope,
      instance_id: context.instanceId,
    }),
  });
}

export function createProjectOverviewRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: ProjectOverviewRouteContext,
  dependencies: ProjectOverviewRouteRuntimeDependencies = {},
): ProjectOverviewRouteBinding {
  if (
    config.tenantId !== context.tenantId ||
    config.projectId !== context.projectId
  ) {
    throw new Error('project_overview_runtime_scope_mismatch');
  }

  const createCloudClient =
    dependencies.createCloudClient ?? createCloudProjectOverviewClient;
  const createLocalClient =
    dependencies.createLocalClient ?? createLocalProjectOverviewClient;
  const createController =
    dependencies.createController ?? createProjectOverviewController;
  if (config.mode === 'cloud') {
    const scope = Object.freeze({
      authority: config.mode,
      tenantId: context.tenantId,
      projectId: context.projectId,
    });
    const cloudClient = createCloudClient(config);
    return Object.freeze({
      controller: createController({
        authority: 'cloud',
        cloudClient,
        initialScope: scope,
      }),
      scope,
    });
  }

  const scope = Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
    projectId: context.projectId,
  });
  const localClient = createLocalClient(config);
  return Object.freeze({
    controller: createController({
      authority: 'local',
      localClient,
      initialScope: scope,
    }),
    scope,
  });
}

export function createTenantOverviewRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: Readonly<{ tenantId: string }>,
): TenantOverviewRouteBinding {
  if (config.tenantId !== context.tenantId) {
    throw new Error('tenant_overview_runtime_scope_mismatch');
  }
  const scope = Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
  });
  const client = createTenantOverviewHttpClient(config);
  return Object.freeze({
    controller: createTenantOverviewController({
      authority: config.mode,
      client,
      initialScope: scope,
    }),
    scope,
  });
}

export function createTenantAnalyticsRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: Readonly<{ tenantId: string }>,
  tenantPlan: string | null,
): TenantAnalyticsRouteBinding {
  if (config.tenantId !== context.tenantId) {
    throw new Error('tenant_analytics_runtime_scope_mismatch');
  }
  const scope = Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
    period: '30d' as const,
  });
  const client = createTenantAnalyticsHttpClient(config);
  return Object.freeze({
    controller: createTenantAnalyticsController({
      authority: config.mode,
      client,
      initialScope: scope,
    }),
    scope,
    tenantPlan,
  });
}

export function createTenantProjectsRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: Readonly<{ tenantId: string }>,
): TenantProjectsRouteBinding {
  if (config.tenantId !== context.tenantId) {
    throw new Error('tenant_projects_runtime_scope_mismatch');
  }
  const scope = Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
  });
  const client = createTenantProjectsHttpClient(config);
  return Object.freeze({
    controller: createTenantProjectsController({
      authority: config.mode,
      client,
      initialScope: scope,
    }),
    scope,
  });
}

export function createTenantWorkspacesRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: Readonly<{ tenantId: string }>,
): TenantWorkspacesRouteBinding {
  if (
    config.tenantId !== context.tenantId ||
    typeof config.projectId !== 'string' ||
    !config.projectId.trim()
  ) {
    throw new Error('tenant_workspaces_runtime_scope_mismatch');
  }
  const scope = Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
    projectId: config.projectId,
  });
  const client = createTenantWorkspacesHttpClient(config);
  return Object.freeze({
    controller: createTenantWorkspacesController({
      authority: config.mode,
      client,
      initialScope: scope,
    }),
    scope,
  });
}

export function createTenantTasksRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: Readonly<{ tenantId: string }>,
): TenantTasksRouteBinding {
  if (
    config.tenantId !== context.tenantId ||
    typeof config.projectId !== 'string' ||
    !config.projectId.trim()
  ) {
    throw new Error('tenant_tasks_runtime_scope_mismatch');
  }
  const scope = Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
    projectId: config.projectId,
  });
  const client = createTenantTasksHttpClient(config);
  return Object.freeze({
    controller: createTenantTasksController({
      authority: config.mode,
      client,
      initialScope: scope,
    }),
    scope,
  });
}

export function createDeadLetterQueueRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: Readonly<{ tenantId: string }>,
): DeadLetterQueueRouteBinding {
  if (config.tenantId !== context.tenantId) {
    throw new Error('dead_letter_queue_runtime_scope_mismatch');
  }
  const scope = Object.freeze({ authority: config.mode, tenantId: context.tenantId });
  const client = createDeadLetterQueueHttpClient(config);
  return Object.freeze({
    controller: createDeadLetterQueueController({
      authority: config.mode,
      client,
      initialScope: scope,
    }),
    scope,
  });
}

export function createRuntimePoolRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: Readonly<{ tenantId: string }>,
): RuntimePoolRouteBinding {
  if (config.tenantId !== context.tenantId) {
    throw new Error('runtime_pool_runtime_scope_mismatch');
  }
  const scope = Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
  });
  const client = createRuntimePoolHttpClient(config);
  return Object.freeze({
    controller: createRuntimePoolController({
      authority: config.mode,
      client,
      initialScope: scope,
    }),
    scope,
  });
}

export function createRuntimeInstancesRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: Readonly<{ tenantId: string }>,
): RuntimeInstancesRouteBinding {
  if (config.tenantId !== context.tenantId) {
    throw new Error('runtime_instances_runtime_scope_mismatch');
  }
  const scope = Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
  });
  const client = createRuntimeInstancesClient(config);
  return Object.freeze({
    controller: createRuntimeInstancesController({
      authority: config.mode,
      client,
      initialScope: scope,
    }),
    scope,
  });
}

export function createRuntimeClustersRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: Readonly<{ tenantId: string }>,
): RuntimeClustersRouteBinding {
  if (config.tenantId !== context.tenantId) {
    throw new Error('runtime_clusters_runtime_scope_mismatch');
  }
  const scope = Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
  });
  const client = createRuntimeClustersClient(config);
  return Object.freeze({
    controller: createRuntimeClustersController({
      authority: config.mode,
      client,
      initialScope: scope,
    }),
    scope,
  });
}

export function createRuntimeDeploymentsRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: Readonly<{ tenantId: string; instanceId?: string }>,
): RuntimeDeploymentsRouteBinding {
  if (config.tenantId !== context.tenantId) {
    throw new Error('runtime_deployments_runtime_scope_mismatch');
  }
  const scope = Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
    instanceId: context.instanceId ?? null,
  });
  const client = createRuntimeDeploymentsClient(config);
  return Object.freeze({
    controller: createRuntimeDeploymentsController({
      authority: config.mode,
      client,
      initialScope: scope,
    }),
    scope,
  });
}

export function createInstanceTemplatesRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: Readonly<{ tenantId: string }>,
): InstanceTemplatesRouteBinding {
  if (config.tenantId !== context.tenantId) {
    throw new Error('instance_templates_runtime_scope_mismatch');
  }
  const scope = Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
  });
  const client = createInstanceTemplatesClient(config);
  return Object.freeze({
    controller: createInstanceTemplatesController({
      authority: config.mode,
      client,
      initialScope: scope,
    }),
    scope,
  });
}

export function createUnifiedRuntimesRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: Readonly<{ tenantId: string }>,
): UnifiedRuntimesRouteBinding {
  if (
    config.tenantId !== context.tenantId ||
    typeof config.projectId !== 'string' ||
    !config.projectId.trim()
  ) {
    throw new Error('unified_runtimes_runtime_scope_mismatch');
  }
  const scope = Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
    projectId: config.projectId,
  });
  const client = createUnifiedRuntimesClient(config);
  return Object.freeze({
    controller: createUnifiedRuntimesController({
      authority: config.mode,
      client,
      initialScope: scope,
    }),
    scope,
  });
}
