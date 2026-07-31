import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { TenantOverviewScope } from './tenantOverviewClient';
import type { TenantOverviewController } from './tenantOverviewController';
import { buildTenantOverviewPresentation } from './tenantOverviewPresentationModel';

const ROUTE_ID = 'tenant-tenant-overview' as const;
const LOCAL_POLICY = 'native_equivalent' as const;
const noopRetry = (): void => {};

export type TenantOverviewRouteBinding = Readonly<{
  controller: TenantOverviewController;
  scope: TenantOverviewScope;
}>;

export type TenantOverviewRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string }
>;

export function createTenantOverviewRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: TenantOverviewRouteContext) => TenantOverviewRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('tenant_overview_route_binding_factory_invalid');
  }
  return async () => {
    const [{ TenantOverviewPage }, { useTenantOverviewController }] = await Promise.all([
      import('./TenantOverviewPage'),
      import('./useTenantOverviewController'),
    ]);

    function TenantOverviewRouteSurface({ context }: DesktopRouteSurfaceProps) {
      const tenantId = nonEmpty(context.tenantId);
      if (!tenantId) {
        return (
          <TenantOverviewPage
            model={buildTenantOverviewPresentation({
              kind: 'unavailable',
              scope: { authority: 'cloud', tenantId: 'unavailable' },
              reasonCode: 'tenant_overview_route_context_unavailable',
              retryable: false,
            })}
            onRetry={noopRetry}
          />
        );
      }
      const routeContext = Object.freeze({ ...context, tenantId });
      return (
        <BoundTenantOverviewRoute
          context={routeContext}
          createBinding={createBinding}
          Page={TenantOverviewPage}
          useController={useTenantOverviewController}
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
      Surface: TenantOverviewRouteSurface,
    });
    return module;
  };
}

function BoundTenantOverviewRoute({
  context,
  createBinding,
  Page,
  useController,
}: Readonly<{
  context: TenantOverviewRouteContext;
  createBinding: (context: TenantOverviewRouteContext) => TenantOverviewRouteBinding;
  Page: typeof import('./TenantOverviewPage').TenantOverviewPage;
  useController: typeof import('./useTenantOverviewController').useTenantOverviewController;
}>) {
  const binding = useMemo(() => createBinding(context), [context.tenantId, createBinding]);
  if (binding.scope.tenantId !== context.tenantId) {
    return (
      <Page
        model={buildTenantOverviewPresentation({
          kind: 'unavailable',
          scope: binding.scope,
          reasonCode: 'tenant_overview_route_binding_scope_mismatch',
          retryable: false,
        })}
        onRetry={noopRetry}
      />
    );
  }
  const { model, retry } = useController(binding.controller, binding.scope);
  return <Page model={model} onRetry={retry} />;
}

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}
