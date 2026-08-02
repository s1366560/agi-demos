import {
  CANONICAL_DESKTOP_ROUTE_IDS,
  createDesktopCanonicalRouteCatalog,
  type CanonicalDesktopRouteId,
} from './desktopCanonicalRouteCatalog';
import { NativeUnavailableRoute } from './NativeUnavailableRoute';
import type {
  DesktopImplementedRouteModule,
  DesktopPlannedRouteReasonCode,
  DesktopRouteModule,
  DesktopRouteModuleLoader,
  DesktopUnavailableRouteModule,
} from './desktopRouteModule';
import type {
  DesktopRouteDefinition,
  DesktopRouteLocalPolicy,
  DesktopRouteRegistry,
} from './desktopRouteRegistry';
import { createDesktopRouteRegistry } from './desktopRouteRegistry';

export const DEVICE_APPROVAL_ROUTE_ID = 'device-approval' as const;
export const TENANT_CREATION_ROUTE_ID = 'tenant-creation' as const;
export const PROJECT_OVERVIEW_ROUTE_ID = 'project-project-overview' as const;
export const PROJECT_SEARCH_ROUTE_ID = 'project-project-search' as const;
export const PROJECT_CRON_JOBS_ROUTE_ID =
  'project-project-cron-jobs' as const;
export const TENANT_OVERVIEW_ROUTE_ID = 'tenant-tenant-overview' as const;
export const TENANT_PROJECTS_ROUTE_ID = 'tenant-tenant-projects' as const;
export const TENANT_WORKSPACES_ROUTE_ID = 'tenant-tenant-workspaces' as const;
export const TENANT_TASKS_ROUTE_ID = 'tenant-tenant-tasks' as const;
export const TENANT_RUNTIMES_ROUTE_ID = 'tenant-tenant-runtimes' as const;
export const TENANT_POOL_ROUTE_ID = 'tenant-tenant-pool' as const;
export const TENANT_INSTANCES_ROUTE_ID = 'tenant-tenant-instances' as const;
export const TENANT_CLUSTERS_ROUTE_ID = 'tenant-tenant-clusters' as const;
export const TENANT_DEPLOY_ROUTE_ID = 'tenant-tenant-deploy' as const;
export const TENANT_INSTANCE_TEMPLATES_ROUTE_ID =
  'tenant-tenant-instance-templates' as const;
export const TENANT_DEAD_LETTER_QUEUE_ROUTE_ID = 'tenant-tenant-dead-letter-queue' as const;

const IMPLEMENTED_ROUTE_IDS = new Set<string>([
  PROJECT_OVERVIEW_ROUTE_ID,
  PROJECT_SEARCH_ROUTE_ID,
  PROJECT_CRON_JOBS_ROUTE_ID,
  TENANT_OVERVIEW_ROUTE_ID,
  TENANT_PROJECTS_ROUTE_ID,
  TENANT_WORKSPACES_ROUTE_ID,
  TENANT_TASKS_ROUTE_ID,
  TENANT_RUNTIMES_ROUTE_ID,
  TENANT_POOL_ROUTE_ID,
  TENANT_INSTANCES_ROUTE_ID,
  TENANT_CLUSTERS_ROUTE_ID,
  TENANT_DEPLOY_ROUTE_ID,
  TENANT_INSTANCE_TEMPLATES_ROUTE_ID,
  TENANT_DEAD_LETTER_QUEUE_ROUTE_ID,
  DEVICE_APPROVAL_ROUTE_ID,
  TENANT_CREATION_ROUTE_ID,
]);
const PRODUCTION_ROUTE_ID_SET = new Set<string>([
  ...CANONICAL_DESKTOP_ROUTE_IDS,
  DEVICE_APPROVAL_ROUTE_ID,
  TENANT_CREATION_ROUTE_ID,
]);

export type DesktopProductionRouteRegistryOptions = Readonly<{
  implementedLoaders: Readonly<Record<string, unknown>>;
}>;

export function createDesktopProductionRouteRegistry({
  implementedLoaders,
}: DesktopProductionRouteRegistryOptions): DesktopRouteRegistry<DesktopRouteModule> {
  assertImplementedLoaders(implementedLoaders);

  let registry: DesktopRouteRegistry<DesktopRouteModule> | null = null;
  const loaders = Object.fromEntries(
    CANONICAL_DESKTOP_ROUTE_IDS.map((routeId) => [
      routeId,
      IMPLEMENTED_ROUTE_IDS.has(routeId)
        ? implementedLoader(routeId, implementedLoaders[routeId], () =>
            requiredDefinition(registry, routeId),
          )
        : plannedLoader(routeId, () => requiredDefinition(registry, routeId)),
    ]),
  );
  const canonicalRegistry =
    createDesktopCanonicalRouteCatalog<DesktopRouteModule>(loaders);
  const deviceApprovalDefinition: DesktopRouteDefinition<DesktopRouteModule> = {
    id: DEVICE_APPROVAL_ROUTE_ID,
    path: '/device',
    scope: ['global'],
    navGroup: 'identity-entry',
    capability: DEVICE_APPROVAL_ROUTE_ID,
    requiredPermission: [['authenticated']],
    localPolicy: 'cloud_only',
    loader: implementedLoader(
      DEVICE_APPROVAL_ROUTE_ID,
      implementedLoaders[DEVICE_APPROVAL_ROUTE_ID],
      () => requiredDefinition(registry, DEVICE_APPROVAL_ROUTE_ID),
    ),
  };
  const tenantCreationDefinition: DesktopRouteDefinition<DesktopRouteModule> = {
    id: TENANT_CREATION_ROUTE_ID,
    path: '/tenants/new',
    scope: ['global'],
    navGroup: 'identity-entry',
    capability: TENANT_CREATION_ROUTE_ID,
    requiredPermission: [['authenticated']],
    localPolicy: 'cloud_only',
    loader: implementedLoader(
      TENANT_CREATION_ROUTE_ID,
      implementedLoaders[TENANT_CREATION_ROUTE_ID],
      () => requiredDefinition(registry, TENANT_CREATION_ROUTE_ID),
    ),
  };
  registry = createDesktopRouteRegistry([
    ...canonicalRegistry.definitions,
    deviceApprovalDefinition,
    tenantCreationDefinition,
  ]);
  return registry;
}

function assertImplementedLoaders(
  implementedLoaders: Readonly<Record<string, unknown>>,
): void {
  for (const routeId of Object.keys(implementedLoaders)) {
    if (!PRODUCTION_ROUTE_ID_SET.has(routeId)) {
      throw new Error(`desktop_production_route_loader_unknown:${routeId}`);
    }
    if (!IMPLEMENTED_ROUTE_IDS.has(routeId)) {
      throw new Error(`desktop_production_route_loader_not_implemented:${routeId}`);
    }
  }
  for (const routeId of IMPLEMENTED_ROUTE_IDS) {
    if (!Object.hasOwn(implementedLoaders, routeId)) {
      throw new Error(`desktop_production_route_loader_missing:${routeId}`);
    }
    if (typeof implementedLoaders[routeId] !== 'function') {
      throw new Error(`desktop_production_route_loader_invalid:${routeId}`);
    }
  }
}

function implementedLoader(
  routeId: string,
  input: unknown,
  definition: () => DesktopRouteDefinition<DesktopRouteModule>,
): DesktopRouteModuleLoader {
  const loader = input as DesktopRouteModuleLoader;
  return async () => {
    const module = await loader();
    return requireImplementedModule(module, definition(), routeId);
  };
}

function plannedLoader(
  routeId: CanonicalDesktopRouteId,
  definition: () => DesktopRouteDefinition<DesktopRouteModule>,
): DesktopRouteModuleLoader {
  return async () => createPlannedModule(definition(), routeId);
}

function createPlannedModule(
  definition: DesktopRouteDefinition<DesktopRouteModule>,
  routeId: CanonicalDesktopRouteId,
): DesktopUnavailableRouteModule {
  if (definition.id !== routeId) {
    throw new Error(`desktop_route_definition_identity_mismatch:${routeId}`);
  }
  return Object.freeze({
    routeId,
    disposition: 'planned',
    availability: 'unavailable',
    reasonCode: plannedReasonCode(definition.localPolicy),
    capability: definition.capability,
    localPolicy: definition.localPolicy,
    Surface: NativeUnavailableRoute,
  });
}

function requireImplementedModule(
  input: unknown,
  definition: DesktopRouteDefinition<DesktopRouteModule>,
  routeId: string,
): DesktopImplementedRouteModule {
  if (!isRecord(input)) {
    throw new Error(`desktop_route_module_invalid:${routeId}`);
  }
  if (input.routeId !== routeId) {
    throw new Error(`desktop_route_module_identity_mismatch:${routeId}`);
  }
  if (
    input.disposition !== 'implemented' ||
    input.availability !== 'available' ||
    input.reasonCode !== null ||
    typeof input.Surface !== 'function'
  ) {
    throw new Error(`desktop_route_module_invalid:${routeId}`);
  }
  if (
    input.capability !== definition.capability ||
    input.localPolicy !== definition.localPolicy
  ) {
    throw new Error(`desktop_route_module_contract_mismatch:${routeId}`);
  }
  return input as DesktopImplementedRouteModule;
}

function plannedReasonCode(
  localPolicy: DesktopRouteLocalPolicy,
): DesktopPlannedRouteReasonCode {
  if (localPolicy === 'cloud_only') {
    return 'desktop_native_route_cloud_only_planned';
  }
  if (localPolicy === 'blocked_by_web_contract') {
    return 'desktop_native_route_web_contract_blocked';
  }
  return 'desktop_native_route_planned';
}

function requiredDefinition(
  registry: DesktopRouteRegistry<DesktopRouteModule> | null,
  routeId: string,
): DesktopRouteDefinition<DesktopRouteModule> {
  const definition = registry?.byId.get(routeId);
  if (!definition) {
    throw new Error(`desktop_route_definition_missing:${routeId}`);
  }
  return definition;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
