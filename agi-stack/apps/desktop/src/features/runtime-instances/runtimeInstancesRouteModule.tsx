import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { RuntimeInstancesController } from './runtimeInstancesController';
import type {
  RuntimeInstancesModel,
  RuntimeInstancesScope,
} from './runtimeInstancesTypes';

const ROUTE_ID = 'tenant-tenant-instances' as const;
const LOCAL_POLICY = 'native_equivalent' as const;

export type RuntimeInstancesRouteBinding = Readonly<{
  controller: RuntimeInstancesController;
  scope: RuntimeInstancesScope;
}>;
export type RuntimeInstancesRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string }
>;

export function createRuntimeInstancesRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding(
    context: RuntimeInstancesRouteContext,
  ): RuntimeInstancesRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('runtime_instances_route_binding_factory_invalid');
  }
  return async () => {
    const [{ RuntimeInstancesPage }, { useRuntimeInstancesController }] =
      await Promise.all([
        import('./RuntimeInstancesPage'),
        import('./useRuntimeInstancesController'),
      ]);

    function RuntimeInstancesRouteSurface({
      context,
    }: DesktopRouteSurfaceProps) {
      const tenantId = nonEmpty(context.tenantId);
      if (!tenantId) {
        return (
          <RuntimeInstancesPage
            model={unavailableModel(
              'cloud',
              'runtime_instances_route_context_unavailable',
            )}
            onRetry={() => {}}
            onQueryChange={() => {}}
            onRestart={async () => {}}
            onDelete={async () => {}}
          />
        );
      }
      return (
        <BoundRuntimeInstancesRoute
          context={Object.freeze({ ...context, tenantId })}
          createBinding={createBinding}
          Page={RuntimeInstancesPage}
          useController={useRuntimeInstancesController}
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
      Surface: RuntimeInstancesRouteSurface,
    });
    return module;
  };
}
function BoundRuntimeInstancesRoute({
  context,
  createBinding,
  Page,
  useController,
}: Readonly<{
  context: RuntimeInstancesRouteContext;
  createBinding(
    context: RuntimeInstancesRouteContext,
  ): RuntimeInstancesRouteBinding;
  Page: typeof import('./RuntimeInstancesPage').RuntimeInstancesPage;
  useController: typeof import('./useRuntimeInstancesController').useRuntimeInstancesController;
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
          'runtime_instances_route_binding_scope_mismatch',
        )}
        onRetry={() => {}}
        onQueryChange={() => {}}
        onRestart={async () => {}}
        onDelete={async () => {}}
      />
    );
  }
  const { model, retry, setQuery, restart, deleteInstance } = useController(
    binding.controller,
    binding.scope,
  );
  return (
    <Page
      model={model}
      onRetry={retry}
      onQueryChange={setQuery}
      onRestart={restart}
      onDelete={deleteInstance}
    />
  );
}

function unavailableModel(
  authority: RuntimeInstancesScope['authority'],
  reasonCode: string,
): RuntimeInstancesModel {
  return Object.freeze({
    scope: Object.freeze({ authority, tenantId: 'unavailable' }),
    authority,
    state: 'unavailable',
    reasonCode,
    mutationState: 'unavailable',
    mutationReasonCode: reasonCode,
    busyInstanceId: null,
    retryVisible: false,
    allowedActions: Object.freeze([]),
    instances: Object.freeze([]),
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
