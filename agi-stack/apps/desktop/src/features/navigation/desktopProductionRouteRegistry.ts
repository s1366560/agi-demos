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

export const PROJECT_OVERVIEW_ROUTE_ID = 'project-project-overview' as const;
export const PROJECT_SEARCH_ROUTE_ID = 'project-project-search' as const;
export const PROJECT_CRON_JOBS_ROUTE_ID =
  'project-project-cron-jobs' as const;

const IMPLEMENTED_ROUTE_IDS = new Set<CanonicalDesktopRouteId>([
  PROJECT_OVERVIEW_ROUTE_ID,
  PROJECT_SEARCH_ROUTE_ID,
  PROJECT_CRON_JOBS_ROUTE_ID,
]);
const CANONICAL_ROUTE_ID_SET = new Set<string>(CANONICAL_DESKTOP_ROUTE_IDS);

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
  registry = createDesktopCanonicalRouteCatalog<DesktopRouteModule>(loaders);
  return registry;
}

function assertImplementedLoaders(
  implementedLoaders: Readonly<Record<string, unknown>>,
): void {
  for (const routeId of Object.keys(implementedLoaders)) {
    if (!CANONICAL_ROUTE_ID_SET.has(routeId)) {
      throw new Error(`desktop_production_route_loader_unknown:${routeId}`);
    }
    if (!IMPLEMENTED_ROUTE_IDS.has(routeId as CanonicalDesktopRouteId)) {
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
  routeId: CanonicalDesktopRouteId,
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
  routeId: CanonicalDesktopRouteId,
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
  routeId: CanonicalDesktopRouteId,
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
