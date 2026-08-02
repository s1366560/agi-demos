import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { RuntimePoolScope } from './runtimePoolClient';
import type { RuntimePoolController } from './runtimePoolController';

const ROUTE_ID = 'tenant-tenant-pool' as const;
const LOCAL_POLICY = 'cloud_only' as const;

export type RuntimePoolRouteBinding = Readonly<{
  controller: RuntimePoolController;
  scope: RuntimePoolScope;
}>;
export type RuntimePoolRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string }
>;

export function createRuntimePoolRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: RuntimePoolRouteContext) => RuntimePoolRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('runtime_pool_route_binding_factory_invalid');
  }
  return async () => {
    const [{ RuntimePoolPage }, { useRuntimePoolController }] =
      await Promise.all([
        import('./RuntimePoolPage'),
        import('./useRuntimePoolController'),
      ]);

    function RuntimePoolRouteSurface({ context }: DesktopRouteSurfaceProps) {
      const tenantId = nonEmpty(context.tenantId);
      if (!tenantId) {
        return (
          <RuntimePoolPage
            model={unavailableModel(
              'cloud',
              'unavailable',
              'runtime_pool_route_context_unavailable',
            )}
            controller={inertController}
            onRetry={() => {}}
            autoRefresh={false}
            onAutoRefreshChange={() => {}}
          />
        );
      }
      return (
        <BoundRuntimePoolRoute
          context={Object.freeze({ ...context, tenantId })}
          createBinding={createBinding}
          Page={RuntimePoolPage}
          useController={useRuntimePoolController}
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
      Surface: RuntimePoolRouteSurface,
    });
    return module;
  };
}

function BoundRuntimePoolRoute({
  context,
  createBinding,
  Page,
  useController,
}: Readonly<{
  context: RuntimePoolRouteContext;
  createBinding: (context: RuntimePoolRouteContext) => RuntimePoolRouteBinding;
  Page: typeof import('./RuntimePoolPage').RuntimePoolPage;
  useController: typeof import('./useRuntimePoolController').useRuntimePoolController;
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
          binding.scope.tenantId,
          'runtime_pool_route_binding_scope_mismatch',
        )}
        controller={inertController}
        onRetry={() => {}}
        autoRefresh={false}
        onAutoRefreshChange={() => {}}
      />
    );
  }
  const { model, retry, autoRefresh, setAutoRefresh } = useController(
    binding.controller,
    binding.scope,
  );
  return (
    <Page
      model={model}
      controller={binding.controller}
      onRetry={retry}
      autoRefresh={autoRefresh}
      onAutoRefreshChange={setAutoRefresh}
    />
  );
}

function unavailableModel(
  authority: RuntimePoolScope['authority'],
  tenantId: string,
  reasonCode: string,
) {
  return Object.freeze({
    scope: Object.freeze({ authority, tenantId }),
    authority,
    statusState: 'unavailable' as const,
    instancesState: 'unavailable' as const,
    metricsState: 'unavailable' as const,
    statusReasonCode: reasonCode,
    instancesReasonCode: reasonCode,
    metricsReasonCode: reasonCode,
    mutationState: 'unavailable' as const,
    mutationReasonCode: reasonCode,
    retryStatusVisible: false,
    retryInstancesVisible: false,
    retryMetricsVisible: false,
    busyInstanceKey: null,
    allowedActions: Object.freeze([]),
    status: null,
    instances: Object.freeze([]),
    metrics: null,
    total: 0,
    query: Object.freeze({
      tier: 'all' as const,
      status: 'all' as const,
      page: 1,
      pageSize: 20,
    }),
    lastUpdatedAt: null,
  });
}

const inertController: RuntimePoolController = Object.freeze({
  getSnapshot: () =>
    unavailableModel(
      'cloud',
      'unavailable',
      'runtime_pool_route_context_unavailable',
    ),
  subscribe: () => () => {},
  load: async () => {},
  retry: async () => {},
  setQuery: async () => {},
  pauseInstance: async () => {},
  resumeInstance: async () => {},
  terminateInstance: async () => {},
  cancel: () => {},
  stop: () => {},
});

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}
