import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { RuntimeClustersController } from './runtimeClustersController';
import type {
  RuntimeClustersModel,
  RuntimeClustersScope,
} from './runtimeClustersTypes';

const ROUTE_ID = 'tenant-tenant-clusters' as const;
const LOCAL_POLICY = 'cloud_only' as const;

export type RuntimeClustersRouteBinding = Readonly<{
  controller: RuntimeClustersController;
  scope: RuntimeClustersScope;
}>;
export type RuntimeClustersRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string }
>;

export function createRuntimeClustersRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding(context: RuntimeClustersRouteContext): RuntimeClustersRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('runtime_clusters_route_binding_factory_invalid');
  }
  return async () => {
    const [{ RuntimeClustersPage }, { useRuntimeClustersController }] =
      await Promise.all([
        import('./RuntimeClustersPage'),
        import('./useRuntimeClustersController'),
      ]);

    function RuntimeClustersRouteSurface({
      context,
    }: DesktopRouteSurfaceProps) {
      const tenantId = nonEmpty(context.tenantId);
      if (!tenantId) {
        return (
          <RuntimeClustersPage
            model={unavailableModel(
              'cloud',
              'runtime_clusters_route_context_unavailable',
            )}
            onRetry={() => {}}
            onQueryChange={() => {}}
            onFiltersChange={() => {}}
            onInspectHealth={async () => {}}
            onCloseHealth={() => {}}
          />
        );
      }
      return (
        <BoundRuntimeClustersRoute
          context={Object.freeze({ ...context, tenantId })}
          createBinding={createBinding}
          Page={RuntimeClustersPage}
          useController={useRuntimeClustersController}
        />
      );
    }

    const module: DesktopImplementedRouteModule = Object.freeze({
      routeId: ROUTE_ID,
      capability: ROUTE_ID,
      localPolicy: LOCAL_POLICY,
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      Surface: RuntimeClustersRouteSurface,
    });
    return module;
  };
}

function BoundRuntimeClustersRoute({
  context,
  createBinding,
  Page,
  useController,
}: Readonly<{
  context: RuntimeClustersRouteContext;
  createBinding(context: RuntimeClustersRouteContext): RuntimeClustersRouteBinding;
  Page: typeof import('./RuntimeClustersPage').RuntimeClustersPage;
  useController: typeof import('./useRuntimeClustersController').useRuntimeClustersController;
}>) {
  const binding = useMemo(
    () => createBinding(context),
    [context.tenantId, createBinding],
  );
  if (binding.scope.tenantId !== context.tenantId) {
    return (
      <Page
        model={unavailableModel(
          binding.scope.authority,
          'runtime_clusters_route_binding_scope_mismatch',
        )}
        onRetry={() => {}}
        onQueryChange={() => {}}
        onFiltersChange={() => {}}
        onInspectHealth={async () => {}}
        onCloseHealth={() => {}}
      />
    );
  }
  const {
    model,
    retry,
    setQuery,
    setFilters,
    inspectHealth,
    closeHealth,
  } = useController(binding.controller, binding.scope);
  return (
    <Page
      model={model}
      onRetry={retry}
      onQueryChange={setQuery}
      onFiltersChange={setFilters}
      onInspectHealth={inspectHealth}
      onCloseHealth={closeHealth}
    />
  );
}

function unavailableModel(
  authority: RuntimeClustersScope['authority'],
  reasonCode: string,
): RuntimeClustersModel {
  return Object.freeze({
    scope: Object.freeze({ authority, tenantId: 'unavailable' }),
    authority,
    state: 'unavailable',
    reasonCode,
    healthState: 'unavailable',
    healthReasonCode: reasonCode,
    selectedClusterId: null,
    retryVisible: false,
    allowedActions: Object.freeze([]),
    clusters: Object.freeze([]),
    visibleClusters: Object.freeze([]),
    health: null,
    total: 0,
    query: Object.freeze({
      page: 1,
      pageSize: 20,
      search: '',
      status: 'all',
    }),
    lastUpdatedAt: null,
  });
}

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}
