import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { TenantTasksScope } from './tenantTasksClient';
import type { TenantTasksController } from './tenantTasksController';

const ROUTE_ID = 'tenant-tenant-tasks' as const;
const LOCAL_POLICY = 'native_equivalent' as const;
const noopRetry = (): void => {};

export type TenantTasksRouteBinding = Readonly<{
  controller: TenantTasksController;
  scope: TenantTasksScope;
}>;

export type TenantTasksRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string }
>;

export function createTenantTasksRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: TenantTasksRouteContext) => TenantTasksRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('tenant_tasks_route_binding_factory_invalid');
  }
  return async () => {
    const [{ TenantTasksPage }, { useTenantTasksController }] =
      await Promise.all([
        import('./TenantTasksPage'),
        import('./useTenantTasksController'),
      ]);

    function TenantTasksRouteSurface({ context }: DesktopRouteSurfaceProps) {
      const tenantId = nonEmpty(context.tenantId);
      if (!tenantId) {
        return (
          <TenantTasksPage
            model={unavailableModel('cloud', 'unavailable', 'unavailable')}
            controller={inertController}
            onRetry={noopRetry}
          />
        );
      }
      return (
        <BoundTenantTasksRoute
          context={Object.freeze({ ...context, tenantId })}
          createBinding={createBinding}
          Page={TenantTasksPage}
          useController={useTenantTasksController}
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
      Surface: TenantTasksRouteSurface,
    });
    return module;
  };
}

function BoundTenantTasksRoute({
  context,
  createBinding,
  Page,
  useController,
}: Readonly<{
  context: TenantTasksRouteContext;
  createBinding: (context: TenantTasksRouteContext) => TenantTasksRouteBinding;
  Page: typeof import('./TenantTasksPage').TenantTasksPage;
  useController: typeof import('./useTenantTasksController').useTenantTasksController;
}>) {
  const binding = useMemo(
    () => createBinding(context),
    [context.tenantId, createBinding],
  );
  if (
    binding.scope.tenantId !== context.tenantId ||
    !nonEmpty(binding.scope.projectId)
  ) {
    return (
      <Page
        model={unavailableModel(
          binding.scope.authority,
          binding.scope.tenantId,
          binding.scope.projectId,
          'tenant_tasks_route_binding_scope_mismatch',
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
  authority: TenantTasksScope['authority'],
  tenantId: string,
  projectId: string,
  reasonCode = 'tenant_tasks_route_context_unavailable',
) {
  return Object.freeze({
    state: 'unavailable' as const,
    scope: Object.freeze({ authority, tenantId, projectId }),
    authority,
    reasonCode,
    retryVisible: false,
    busyAction: null,
    allowedActions: Object.freeze([]),
    stats: Object.freeze({
      total: 0,
      pending: 0,
      processing: 0,
      completed: 0,
      failed: 0,
      throughputPerMinute: 0,
      errorRate: 0,
    }),
    queue: Object.freeze({ current: 0, history: Object.freeze([]) }),
    tasks: Object.freeze([]),
    total: 0,
    limit: 50,
    offset: 0,
    hasMore: false,
    query: Object.freeze({ search: '', status: 'all', limit: 50, offset: 0 }),
    lastUpdatedAt: null,
  });
}

const inertController: TenantTasksController = Object.freeze({
  getSnapshot: () => unavailableModel('cloud', 'unavailable', 'unavailable'),
  subscribe: () => () => {},
  load: async () => {},
  retry: async () => {},
  setQuery: async () => {},
  retryTask: async () => {},
  stopTask: async () => {},
  retryPending: async () => {},
  cancel: () => {},
  stop: () => {},
});

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}
