import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { UnifiedRuntimesController } from './unifiedRuntimesController';
import type { UnifiedRuntimesScope } from './unifiedRuntimesTypes';

const ROUTE_ID = 'tenant-tenant-runtimes' as const;
const LOCAL_POLICY = 'native_equivalent' as const;

export type UnifiedRuntimesRouteBinding = Readonly<{
  controller: UnifiedRuntimesController;
  scope: UnifiedRuntimesScope;
}>;
export type UnifiedRuntimesRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string }
>;

export function createUnifiedRuntimesRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (
    context: UnifiedRuntimesRouteContext,
  ) => UnifiedRuntimesRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('unified_runtimes_route_binding_factory_invalid');
  }
  return async () => {
    const [{ UnifiedRuntimesPage }, { useUnifiedRuntimesController }] =
      await Promise.all([
        import('./UnifiedRuntimesPage'),
        import('./useUnifiedRuntimesController'),
      ]);

    function UnifiedRuntimesRouteSurface({
      context,
    }: DesktopRouteSurfaceProps) {
      const tenantId = nonEmpty(context.tenantId);
      if (!tenantId) {
        return (
          <UnifiedRuntimesPage
            model={unavailableModel(
              'cloud',
              'unavailable',
              'unified_runtimes_route_context_unavailable',
            )}
            onRetry={() => {}}
            autoRefresh={false}
            onAutoRefreshChange={() => {}}
          />
        );
      }
      return (
        <BoundUnifiedRuntimesRoute
          context={Object.freeze({ ...context, tenantId })}
          createBinding={createBinding}
          Page={UnifiedRuntimesPage}
          useController={useUnifiedRuntimesController}
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
      Surface: UnifiedRuntimesRouteSurface,
    });
    return module;
  };
}

function BoundUnifiedRuntimesRoute({
  context,
  createBinding,
  Page,
  useController,
}: Readonly<{
  context: UnifiedRuntimesRouteContext;
  createBinding: (
    context: UnifiedRuntimesRouteContext,
  ) => UnifiedRuntimesRouteBinding;
  Page: typeof import('./UnifiedRuntimesPage').UnifiedRuntimesPage;
  useController: typeof import('./useUnifiedRuntimesController').useUnifiedRuntimesController;
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
          binding.scope.projectId,
          'unified_runtimes_route_binding_scope_mismatch',
        )}
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
      onRetry={retry}
      autoRefresh={autoRefresh}
      onAutoRefreshChange={setAutoRefresh}
    />
  );
}

function unavailableModel(
  authority: UnifiedRuntimesScope['authority'],
  projectId: string,
  reasonCode: string,
) {
  return Object.freeze({
    scope: Object.freeze({
      authority,
      tenantId: 'unavailable',
      projectId,
    }),
    authority,
    availability: 'unavailable' as const,
    reasonCode,
    poolState: 'unavailable' as const,
    sandboxState: 'unavailable' as const,
    sidecarState: 'unavailable' as const,
    capabilitiesState: 'unavailable' as const,
    poolReasonCode: reasonCode,
    sandboxReasonCode: reasonCode,
    sidecarReasonCode: reasonCode,
    capabilitiesReasonCode: reasonCode,
    retryPoolVisible: false,
    retrySandboxVisible: false,
    retrySidecarVisible: false,
    retryCapabilitiesVisible: false,
    allowedActions: Object.freeze([]),
    poolStatus: null,
    rows: Object.freeze([]),
    lastUpdatedAt: null,
  });
}

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}
