import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { TenantProjectsScope } from './tenantProjectsClient';
import type { TenantProjectsController } from './tenantProjectsController';

const ROUTE_ID = 'tenant-tenant-projects' as const;
const LOCAL_POLICY = 'native_equivalent' as const;
const noopRetry = (): void => {};

export type TenantProjectsRouteBinding = Readonly<{
  controller: TenantProjectsController;
  scope: TenantProjectsScope;
}>;

export type TenantProjectsRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string }
>;

export function createTenantProjectsRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: TenantProjectsRouteContext) => TenantProjectsRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('tenant_projects_route_binding_factory_invalid');
  }
  return async () => {
    const [{ TenantProjectsPage }, { useTenantProjectsController }] = await Promise.all([
      import('./TenantProjectsPage'),
      import('./useTenantProjectsController'),
    ]);

    function TenantProjectsRouteSurface({ context }: DesktopRouteSurfaceProps) {
      const tenantId = nonEmpty(context.tenantId);
      if (!tenantId) {
        return (
          <TenantProjectsPage
            model={unavailableModel('cloud', 'unavailable')}
            controller={inertController}
            onRetry={noopRetry}
          />
        );
      }
      return (
        <BoundTenantProjectsRoute
          context={Object.freeze({ ...context, tenantId })}
          createBinding={createBinding}
          Page={TenantProjectsPage}
          useController={useTenantProjectsController}
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
      Surface: TenantProjectsRouteSurface,
    });
    return module;
  };
}

function BoundTenantProjectsRoute({
  context,
  createBinding,
  Page,
  useController,
}: Readonly<{
  context: TenantProjectsRouteContext;
  createBinding: (context: TenantProjectsRouteContext) => TenantProjectsRouteBinding;
  Page: typeof import('./TenantProjectsPage').TenantProjectsPage;
  useController: typeof import('./useTenantProjectsController').useTenantProjectsController;
}>) {
  const binding = useMemo(() => createBinding(context), [context.tenantId, createBinding]);
  if (binding.scope.tenantId !== context.tenantId) {
    return (
      <Page
        model={unavailableModel(
          binding.scope.authority,
          binding.scope.tenantId,
          'tenant_projects_route_binding_scope_mismatch',
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
  authority: TenantProjectsScope['authority'],
  tenantId: string,
  reasonCode = 'tenant_projects_route_context_unavailable',
) {
  return Object.freeze({
    state: 'unavailable' as const,
    scope: Object.freeze({ authority, tenantId }),
    authority,
    reasonCode,
    retryVisible: false,
    busyAction: null,
    allowedActions: Object.freeze([]),
    projects: Object.freeze([]),
    total: 0,
    page: 1,
    pageSize: 20,
    ownerIds: Object.freeze([]),
  });
}

const inertController: TenantProjectsController = Object.freeze({
  getSnapshot: () => unavailableModel('cloud', 'unavailable'),
  subscribe: () => () => {},
  load: async () => {},
  retry: async () => {},
  create: async () => {},
  update: async () => {},
  delete: async () => {},
  cancel: () => {},
  stop: () => {},
});

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}
