import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { RuntimeDeploymentsController } from './runtimeDeploymentsController';
import type {
  RuntimeDeploymentsModel,
  RuntimeDeploymentsScope,
} from './runtimeDeploymentsTypes';

const ROUTE_ID = 'tenant-tenant-deploy' as const;
const LOCAL_POLICY = 'cloud_only' as const;

export type RuntimeDeploymentsRouteBinding = Readonly<{
  controller: RuntimeDeploymentsController;
  scope: RuntimeDeploymentsScope;
}>;
export type RuntimeDeploymentsRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string }
>;

export function createRuntimeDeploymentsRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding(
    context: RuntimeDeploymentsRouteContext,
  ): RuntimeDeploymentsRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('runtime_deployments_route_binding_factory_invalid');
  }
  return async () => {
    const [{ RuntimeDeploymentsPage }, { useRuntimeDeploymentsController }] =
      await Promise.all([
        import('./RuntimeDeploymentsPage'),
        import('./useRuntimeDeploymentsController'),
      ]);

    function RuntimeDeploymentsRouteSurface({
      context,
    }: DesktopRouteSurfaceProps) {
      const tenantId = nonEmpty(context.tenantId);
      if (!tenantId) {
        return (
          <RuntimeDeploymentsPage
            model={unavailableModel(
              'cloud',
              null,
              'runtime_deployments_route_context_unavailable',
            )}
            onRetry={() => {}}
            onQueryChange={() => {}}
            onInspect={async () => {}}
            onCloseDetail={() => {}}
            onReconnectProgress={async () => {}}
          />
        );
      }
      const instanceId = nullableNonEmpty(context.instanceId);
      return (
        <BoundRuntimeDeploymentsRoute
          context={Object.freeze({
            ...context,
            tenantId,
            ...(instanceId === null ? {} : { instanceId }),
          })}
          createBinding={createBinding}
          Page={RuntimeDeploymentsPage}
          useController={useRuntimeDeploymentsController}
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
      Surface: RuntimeDeploymentsRouteSurface,
    });
    return module;
  };
}

function BoundRuntimeDeploymentsRoute({
  context,
  createBinding,
  Page,
  useController,
}: Readonly<{
  context: RuntimeDeploymentsRouteContext;
  createBinding(
    context: RuntimeDeploymentsRouteContext,
  ): RuntimeDeploymentsRouteBinding;
  Page: typeof import('./RuntimeDeploymentsPage').RuntimeDeploymentsPage;
  useController: typeof import('./useRuntimeDeploymentsController').useRuntimeDeploymentsController;
}>) {
  const binding = useMemo(
    () => createBinding(context),
    [context.tenantId, context.instanceId, createBinding],
  );
  if (
    binding.scope.tenantId !== context.tenantId ||
    binding.scope.instanceId !== (context.instanceId ?? null)
  ) {
    return (
      <Page
        model={unavailableModel(
          binding.scope.authority,
          binding.scope.instanceId,
          'runtime_deployments_route_binding_scope_mismatch',
        )}
        onRetry={() => {}}
        onQueryChange={() => {}}
        onInspect={async () => {}}
        onCloseDetail={() => {}}
        onReconnectProgress={async () => {}}
      />
    );
  }
  const {
    model,
    retry,
    setQuery,
    inspect,
    closeDetail,
    reconnectProgress,
  } = useController(binding.controller, binding.scope);
  return (
    <Page
      model={model}
      onRetry={retry}
      onQueryChange={setQuery}
      onInspect={inspect}
      onCloseDetail={closeDetail}
      onReconnectProgress={reconnectProgress}
    />
  );
}

function unavailableModel(
  authority: RuntimeDeploymentsScope['authority'],
  instanceId: string | null,
  reasonCode: string,
): RuntimeDeploymentsModel {
  return Object.freeze({
    scope: Object.freeze({ authority, tenantId: '', instanceId }),
    authority,
    state: 'unavailable',
    reasonCode,
    retryVisible: false,
    allowedActions: Object.freeze([]),
    deployments: Object.freeze([]),
    total: 0,
    query: Object.freeze({ page: 1, pageSize: 10 }),
    selectedDeployment: null,
    detailState: 'unavailable',
    detailReasonCode: reasonCode,
    progressState: 'unavailable',
    progressReasonCode: reasonCode,
    progressRetryVisible: false,
    lastUpdatedAt: null,
  });
}

function nonEmpty(value: string | undefined): string | null {
  if (!value || value !== value.trim()) return null;
  return value;
}

function nullableNonEmpty(value: string | undefined): string | null {
  return value === undefined ? null : nonEmpty(value);
}
