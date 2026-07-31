import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { TenantWorkspacesScope } from './tenantWorkspacesClient';
import type { TenantWorkspacesController } from './tenantWorkspacesController';

const ROUTE_ID = 'tenant-tenant-workspaces' as const;
const LOCAL_POLICY = 'native_equivalent' as const;
const noopRetry = (): void => {};

export type TenantWorkspacesRouteBinding = Readonly<{
  controller: TenantWorkspacesController;
  scope: TenantWorkspacesScope;
}>;

export type TenantWorkspacesRouteContext = Readonly<DesktopRouteContext & { tenantId: string }>;

export function createTenantWorkspacesRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: TenantWorkspacesRouteContext) => TenantWorkspacesRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('tenant_workspaces_route_binding_factory_invalid');
  }
  return async () => {
    const [{ TenantWorkspacesPage }, { useTenantWorkspacesController }] = await Promise.all([
      import('./TenantWorkspacesPage'),
      import('./useTenantWorkspacesController'),
    ]);

    function TenantWorkspacesRouteSurface({ context }: DesktopRouteSurfaceProps) {
      const tenantId = nonEmpty(context.tenantId);
      if (!tenantId) {
        return (
          <TenantWorkspacesPage
            model={unavailableModel('cloud', 'unavailable', 'unavailable')}
            controller={inertController}
            onRetry={noopRetry}
          />
        );
      }
      return (
        <BoundTenantWorkspacesRoute
          context={Object.freeze({ ...context, tenantId })}
          createBinding={createBinding}
          Page={TenantWorkspacesPage}
          useController={useTenantWorkspacesController}
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
      Surface: TenantWorkspacesRouteSurface,
    });
    return module;
  };
}

function BoundTenantWorkspacesRoute({
  context,
  createBinding,
  Page,
  useController,
}: Readonly<{
  context: TenantWorkspacesRouteContext;
  createBinding: (context: TenantWorkspacesRouteContext) => TenantWorkspacesRouteBinding;
  Page: typeof import('./TenantWorkspacesPage').TenantWorkspacesPage;
  useController: typeof import('./useTenantWorkspacesController').useTenantWorkspacesController;
}>) {
  const binding = useMemo(() => createBinding(context), [context.tenantId, createBinding]);
  if (binding.scope.tenantId !== context.tenantId || !nonEmpty(binding.scope.projectId)) {
    return (
      <Page
        model={unavailableModel(
          binding.scope.authority,
          binding.scope.tenantId,
          binding.scope.projectId,
          'tenant_workspaces_route_binding_scope_mismatch',
        )}
        controller={inertController}
        onRetry={noopRetry}
      />
    );
  }
  const { model, retry } = useController(binding.controller, binding.scope);
  return <Page model={model} controller={binding.controller} onRetry={retry} />;
}

function unavailableModel(
  authority: TenantWorkspacesScope['authority'],
  tenantId: string,
  projectId: string,
  reasonCode = 'tenant_workspaces_route_context_unavailable',
) {
  return Object.freeze({
    state: 'unavailable' as const,
    scope: Object.freeze({ authority, tenantId, projectId }),
    authority,
    reasonCode,
    retryVisible: false,
    busyAction: null,
    allowedActions: Object.freeze([]),
    workspaces: Object.freeze([]),
  });
}

const inertController: TenantWorkspacesController = Object.freeze({
  getSnapshot: () => unavailableModel('cloud', 'unavailable', 'unavailable'),
  subscribe: () => () => {},
  load: async () => {},
  retry: async () => {},
  create: async () => {},
  cancel: () => {},
  stop: () => {},
});

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}
