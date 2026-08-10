import {
  CANONICAL_DESKTOP_ROUTE_IDS,
  createDesktopCanonicalRouteCatalog,
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
  DesktopRouteStructuralReadiness,
} from './desktopRouteRegistry';
import { createDesktopRouteRegistry } from './desktopRouteRegistry';

export const DEVICE_APPROVAL_ROUTE_ID = 'device-approval' as const;
export const TENANT_CREATION_ROUTE_ID = 'tenant-creation' as const;
export const INVITATION_ACCEPTANCE_ROUTE_ID = 'invitation-acceptance' as const;
export const PROJECT_OVERVIEW_ROUTE_ID = 'project-project-overview' as const;
export const PROJECT_SEARCH_ROUTE_ID = 'project-project-search' as const;
export const PROJECT_WORKSPACES_ROUTE_ID = 'project-project-workspaces' as const;
export const PROJECT_BLACKBOARD_ROUTE_ID = 'project-blackboard-dynamic-project-blackboard' as const;
export const PROJECT_TEAM_ROUTE_ID = 'project-project-team' as const;
export const PROJECT_MEMORIES_ROUTE_ID = 'project-project-memories' as const;
export const PROJECT_ENTITIES_ROUTE_ID = 'project-project-entities' as const;
export const PROJECT_COMMUNITIES_ROUTE_ID = 'project-project-communities' as const;
export const PROJECT_GRAPH_ROUTE_ID = 'project-project-graph' as const;
export const PROJECT_AGENT_DASHBOARD_ROUTE_ID = 'project-agent-dashboard' as const;
export const PROJECT_AGENT_LOGS_ROUTE_ID = 'project-agent-logs' as const;
export const PROJECT_AGENT_PATTERNS_ROUTE_ID = 'project-agent-patterns' as const;
export const PROJECT_SCHEMA_ROUTE_ID = 'project-project-schema' as const;
export const PROJECT_MAINTENANCE_ROUTE_ID = 'project-project-maintenance' as const;
export const PROJECT_SETTINGS_ROUTE_ID = 'project-project-settings' as const;
export const PROJECT_CRON_JOBS_ROUTE_ID = 'project-project-cron-jobs' as const;
export const PROJECT_SUPPORT_ROUTE_ID = 'project-support' as const;
export const BACKEND_STORES_ROUTE_ID = 'backend-stores' as const;
export const PROJECT_PLAYBOOKS_ROUTE_ID = 'project-playbooks' as const;
export const TENANT_OVERVIEW_ROUTE_ID = 'tenant-tenant-overview' as const;
export const TENANT_PROJECTS_ROUTE_ID = 'tenant-tenant-projects' as const;
export const TENANT_WORKSPACES_ROUTE_ID = 'tenant-tenant-workspaces' as const;
export const TENANT_TASKS_ROUTE_ID = 'tenant-tenant-tasks' as const;
export const TENANT_ANALYTICS_ROUTE_ID = 'tenant-tenant-analytics' as const;
export const TENANT_AGENT_DASHBOARD_ROUTE_ID = 'tenant-tenant-agent-configuration' as const;
export const TENANT_AGENT_BINDINGS_ROUTE_ID = 'tenant-tenant-agent-bindings' as const;
export const TENANT_AGENT_DEFINITIONS_ROUTE_ID = 'tenant-tenant-agent-definitions' as const;
export const TENANT_SKILLS_ROUTE_ID = 'tenant-tenant-skills' as const;
export const TENANT_EVOLUTION_ROUTE_ID = 'tenant-tenant-evolution' as const;
export const TENANT_PLUGINS_ROUTE_ID = 'tenant-tenant-plugins' as const;
export const TENANT_MCP_SERVERS_ROUTE_ID = 'tenant-tenant-mcp-servers' as const;
export const TENANT_TEMPLATES_ROUTE_ID = 'tenant-tenant-templates' as const;
export const TENANT_PROVIDERS_ROUTE_ID = 'tenant-tenant-providers' as const;
export const TENANT_USERS_ROUTE_ID = 'tenant-tenant-users' as const;
export const TENANT_AUDIT_LOGS_ROUTE_ID = 'tenant-tenant-audit-logs' as const;
export const TENANT_TRUST_POLICIES_ROUTE_ID = 'tenant-tenant-trust-policies' as const;
export const TENANT_BILLING_ROUTE_ID = 'tenant-tenant-billing' as const;
export const TENANT_RUNTIMES_ROUTE_ID = 'tenant-tenant-runtimes' as const;
export const TENANT_POOL_ROUTE_ID = 'tenant-tenant-pool' as const;
export const TENANT_INSTANCES_ROUTE_ID = 'tenant-tenant-instances' as const;
export const TENANT_CLUSTERS_ROUTE_ID = 'tenant-tenant-clusters' as const;
export const TENANT_DEPLOY_ROUTE_ID = 'tenant-tenant-deploy' as const;
export const TENANT_INSTANCE_TEMPLATES_ROUTE_ID = 'tenant-tenant-instance-templates' as const;
export const TENANT_DEAD_LETTER_QUEUE_ROUTE_ID = 'tenant-tenant-dead-letter-queue' as const;
export const TENANT_PATTERNS_ROUTE_ID = 'tenant-tenant-patterns' as const;
export const TENANT_ACP_ROUTE_ID = 'tenant-tenant-acp' as const;
export const TENANT_WEBHOOKS_ROUTE_ID = 'tenant-tenant-webhooks' as const;
export const TENANT_GENES_ROUTE_ID = 'tenant-tenant-genes' as const;
export const TENANT_EVENTS_ROUTE_ID = 'tenant-tenant-events' as const;
export const TENANT_DECISION_RECORDS_ROUTE_ID = 'tenant-tenant-decision-records' as const;
export const TENANT_ORGANIZATION_SETTINGS_ROUTE_ID = 'tenant-tenant-org-settings' as const;
export const TENANT_SETTINGS_ROUTE_ID = 'tenant-tenant-settings' as const;
export const PROJECT_CHANNELS_ROUTE_ID = 'project-project-channels' as const;

export const DESKTOP_PRODUCTION_ROUTE_IDS = Object.freeze([
  ...CANONICAL_DESKTOP_ROUTE_IDS,
  PROJECT_SUPPORT_ROUTE_ID,
  BACKEND_STORES_ROUTE_ID,
  PROJECT_PLAYBOOKS_ROUTE_ID,
  DEVICE_APPROVAL_ROUTE_ID,
  TENANT_CREATION_ROUTE_ID,
  INVITATION_ACCEPTANCE_ROUTE_ID,
]);

export const DESKTOP_IMPLEMENTED_ROUTE_IDS = DESKTOP_PRODUCTION_ROUTE_IDS;
const IMPLEMENTED_ROUTE_IDS = new Set<string>(DESKTOP_IMPLEMENTED_ROUTE_IDS);
const PRODUCTION_ROUTE_ID_SET = new Set<string>(DESKTOP_PRODUCTION_ROUTE_IDS);
const DESKTOP_PRODUCTION_ROUTE_LOADER_IDENTITY = Symbol('desktop-production-route-loader-identity');

type DesktopProductionRouteLoaderIdentity = Readonly<{
  kind: 'implemented-route-module';
  routeId: string;
}>;

type DesktopProductionRouteLoaderWithIdentity = DesktopRouteModuleLoader &
  Readonly<{
    [DESKTOP_PRODUCTION_ROUTE_LOADER_IDENTITY]: DesktopProductionRouteLoaderIdentity;
  }>;

export type DesktopProductionRouteRegistryOptions = Readonly<{
  implementedLoaders: Readonly<Record<string, unknown>>;
}>;

export function registerDesktopProductionRouteLoader(
  routeId: string,
  loader: DesktopRouteModuleLoader,
): DesktopRouteModuleLoader {
  assertImplementedLoaders({ [routeId]: loader });
  const registeredLoader = async () => loader();
  Object.defineProperty(registeredLoader, DESKTOP_PRODUCTION_ROUTE_LOADER_IDENTITY, {
    configurable: false,
    enumerable: false,
    writable: false,
    value: Object.freeze({
      kind: 'implemented-route-module',
      routeId,
    } satisfies DesktopProductionRouteLoaderIdentity),
  });
  return Object.freeze(registeredLoader);
}

export function registerDesktopProductionRouteLoaders(
  loaders: Readonly<Record<string, DesktopRouteModuleLoader>>,
): Readonly<Record<string, DesktopRouteModuleLoader>> {
  assertImplementedLoaders(loaders);
  return Object.freeze(
    Object.fromEntries(
      Object.entries(loaders).map(([routeId, loader]) => [
        routeId,
        registerDesktopProductionRouteLoader(routeId, loader),
      ]),
    ),
  );
}

export function createDesktopProductionRouteRegistry({
  implementedLoaders,
}: DesktopProductionRouteRegistryOptions): DesktopRouteRegistry<DesktopRouteModule> {
  assertImplementedLoaders(implementedLoaders);

  let registry: DesktopRouteRegistry<DesktopRouteModule> | null = null;
  const loaders = Object.fromEntries(
    CANONICAL_DESKTOP_ROUTE_IDS.map((routeId) => [
      routeId,
      productionLoader(routeId, implementedLoaders, () => requiredDefinition(registry, routeId)),
    ]),
  );
  const canonicalRegistry = createDesktopCanonicalRouteCatalog<DesktopRouteModule>(loaders);
  const deviceApprovalDefinition: DesktopRouteDefinition<DesktopRouteModule> = {
    id: DEVICE_APPROVAL_ROUTE_ID,
    path: '/device',
    scope: ['global'],
    navGroup: 'identity-entry',
    capability: DEVICE_APPROVAL_ROUTE_ID,
    requiredPermission: [['authenticated']],
    localPolicy: 'cloud_only',
    structuralReadiness: structuralReadiness(DEVICE_APPROVAL_ROUTE_ID, implementedLoaders),
    loader: productionLoader(DEVICE_APPROVAL_ROUTE_ID, implementedLoaders, () =>
      requiredDefinition(registry, DEVICE_APPROVAL_ROUTE_ID),
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
    structuralReadiness: structuralReadiness(TENANT_CREATION_ROUTE_ID, implementedLoaders),
    loader: productionLoader(TENANT_CREATION_ROUTE_ID, implementedLoaders, () =>
      requiredDefinition(registry, TENANT_CREATION_ROUTE_ID),
    ),
  };
  const invitationAcceptanceDefinition: DesktopRouteDefinition<DesktopRouteModule> = {
    id: INVITATION_ACCEPTANCE_ROUTE_ID,
    path: '/invite',
    scope: ['global'],
    navGroup: 'identity-entry',
    capability: INVITATION_ACCEPTANCE_ROUTE_ID,
    requiredPermission: [['anonymous'], ['authenticated']],
    localPolicy: 'cloud_only',
    structuralReadiness: structuralReadiness(INVITATION_ACCEPTANCE_ROUTE_ID, implementedLoaders),
    loader: productionLoader(INVITATION_ACCEPTANCE_ROUTE_ID, implementedLoaders, () =>
      requiredDefinition(registry, INVITATION_ACCEPTANCE_ROUTE_ID),
    ),
  };
  const projectSupportDefinition: DesktopRouteDefinition<DesktopRouteModule> = {
    id: PROJECT_SUPPORT_ROUTE_ID,
    path: '/tenant/:tenantId/project/:projectId/support',
    scope: ['tenant', 'project'],
    navGroup: 'project-operations',
    capability: PROJECT_SUPPORT_ROUTE_ID,
    requiredPermission: [['authenticated', 'tenant_member']],
    localPolicy: 'cloud_only',
    structuralReadiness: structuralReadiness(PROJECT_SUPPORT_ROUTE_ID, implementedLoaders),
    loader: productionLoader(PROJECT_SUPPORT_ROUTE_ID, implementedLoaders, () =>
      requiredDefinition(registry, PROJECT_SUPPORT_ROUTE_ID),
    ),
  };
  const backendStoresDefinition: DesktopRouteDefinition<DesktopRouteModule> = {
    id: BACKEND_STORES_ROUTE_ID,
    path: '/tenant/:tenantId/backend-stores',
    scope: ['tenant'],
    navGroup: 'tenant-governance-management',
    capability: BACKEND_STORES_ROUTE_ID,
    requiredPermission: [['authenticated', 'tenant_admin']],
    localPolicy: 'cloud_only',
    structuralReadiness: structuralReadiness(BACKEND_STORES_ROUTE_ID, implementedLoaders),
    loader: productionLoader(BACKEND_STORES_ROUTE_ID, implementedLoaders, () =>
      requiredDefinition(registry, BACKEND_STORES_ROUTE_ID),
    ),
  };
  const projectPlaybooksDefinition: DesktopRouteDefinition<DesktopRouteModule> = {
    id: PROJECT_PLAYBOOKS_ROUTE_ID,
    path: '/tenant/:tenantId/project/:projectId/playbooks',
    scope: ['tenant', 'project'],
    navGroup: 'project-operations',
    capability: PROJECT_PLAYBOOKS_ROUTE_ID,
    requiredPermission: [['authenticated', 'tenant_member']],
    localPolicy: 'cloud_only',
    structuralReadiness: structuralReadiness(PROJECT_PLAYBOOKS_ROUTE_ID, implementedLoaders),
    loader: productionLoader(PROJECT_PLAYBOOKS_ROUTE_ID, implementedLoaders, () =>
      requiredDefinition(registry, PROJECT_PLAYBOOKS_ROUTE_ID),
    ),
  };
  registry = createDesktopRouteRegistry([
    ...canonicalRegistry.definitions.map((definition) => ({
      ...definition,
      structuralReadiness: structuralReadiness(definition.id, implementedLoaders),
    })),
    projectSupportDefinition,
    backendStoresDefinition,
    projectPlaybooksDefinition,
    deviceApprovalDefinition,
    tenantCreationDefinition,
    invitationAcceptanceDefinition,
  ]);
  return registry;
}

function assertImplementedLoaders(implementedLoaders: Readonly<Record<string, unknown>>): void {
  for (const routeId of Object.keys(implementedLoaders)) {
    if (!PRODUCTION_ROUTE_ID_SET.has(routeId)) {
      throw new Error(`desktop_production_route_loader_unknown:${routeId}`);
    }
    if (!IMPLEMENTED_ROUTE_IDS.has(routeId)) {
      throw new Error(`desktop_production_route_loader_not_implemented:${routeId}`);
    }
    if (typeof implementedLoaders[routeId] !== 'function') {
      throw new Error(`desktop_production_route_loader_invalid:${routeId}`);
    }
  }
}

function productionLoader(
  routeId: string,
  implementedLoaders: Readonly<Record<string, unknown>>,
  definition: () => DesktopRouteDefinition<DesktopRouteModule>,
): DesktopRouteModuleLoader {
  if (hasImplementedLoaderBinding(routeId, implementedLoaders)) {
    return implementedLoader(routeId, implementedLoaders[routeId], definition);
  }
  return plannedLoader(routeId, definition);
}

function structuralReadiness(
  routeId: string,
  implementedLoaders: Readonly<Record<string, unknown>>,
): DesktopRouteStructuralReadiness {
  if (!IMPLEMENTED_ROUTE_IDS.has(routeId)) {
    return Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_route_structural_loader_missing',
    });
  }
  if (!hasImplementedLoaderBinding(routeId, implementedLoaders)) {
    return Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_route_structural_app_binding_missing',
    });
  }
  if (!hasRegisteredLoaderIdentity(routeId, implementedLoaders[routeId])) {
    return Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_route_structural_loader_missing',
    });
  }
  return Object.freeze({ status: 'ready' });
}

function hasImplementedLoaderBinding(
  routeId: string,
  implementedLoaders: Readonly<Record<string, unknown>>,
): boolean {
  return IMPLEMENTED_ROUTE_IDS.has(routeId) && Object.hasOwn(implementedLoaders, routeId);
}

function hasRegisteredLoaderIdentity(routeId: string, input: unknown): boolean {
  if (typeof input !== 'function') return false;
  const identity = (input as Partial<DesktopProductionRouteLoaderWithIdentity>)[
    DESKTOP_PRODUCTION_ROUTE_LOADER_IDENTITY
  ];
  return (
    identity?.kind === 'implemented-route-module' &&
    identity.routeId === routeId &&
    IMPLEMENTED_ROUTE_IDS.has(identity.routeId)
  );
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
  routeId: string,
  definition: () => DesktopRouteDefinition<DesktopRouteModule>,
): DesktopRouteModuleLoader {
  return async () => createPlannedModule(definition(), routeId);
}

function createPlannedModule(
  definition: DesktopRouteDefinition<DesktopRouteModule>,
  routeId: string,
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
  if (input.capability !== definition.capability || input.localPolicy !== definition.localPolicy) {
    throw new Error(`desktop_route_module_contract_mismatch:${routeId}`);
  }
  return input as DesktopImplementedRouteModule;
}

function plannedReasonCode(localPolicy: DesktopRouteLocalPolicy): DesktopPlannedRouteReasonCode {
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
