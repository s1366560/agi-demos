import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { TenantAnalyticsScope } from './tenantAnalyticsClient';
import type { TenantAnalyticsController } from './tenantAnalyticsController';
import { buildTenantAnalyticsPresentation } from './tenantAnalyticsPresentationModel';

const ROUTE_ID = 'tenant-tenant-analytics' as const;
const noopRetry = (): void => {};

export type TenantAnalyticsRouteBinding = Readonly<{
  controller: TenantAnalyticsController;
  scope: TenantAnalyticsScope;
  tenantPlan: string | null;
}>;

export type TenantAnalyticsRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string }
>;

export function createTenantAnalyticsRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (
    context: TenantAnalyticsRouteContext,
  ) => TenantAnalyticsRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('tenant_analytics_route_binding_factory_invalid');
  }
  return async () => {
    const [{ TenantAnalyticsPage }, { useTenantAnalyticsController }] =
      await Promise.all([
        import('./TenantAnalyticsPage'),
        import('./useTenantAnalyticsController'),
      ]);

    function TenantAnalyticsRouteSurface({
      context,
    }: DesktopRouteSurfaceProps) {
      const tenantId = nonEmpty(context.tenantId);
      if (!tenantId) {
        return (
          <TenantAnalyticsPage
            model={buildTenantAnalyticsPresentation({
              kind: 'unavailable',
              scope: {
                authority: 'cloud',
                tenantId: 'unavailable',
                period: '30d',
              },
              reasonCode: 'tenant_analytics_route_context_unavailable',
              retryable: false,
            })}
            tenantPlan={null}
            onRetry={noopRetry}
          />
        );
      }
      const routeContext = Object.freeze({ ...context, tenantId });
      return (
        <BoundTenantAnalyticsRoute
          context={routeContext}
          createBinding={createBinding}
          Page={TenantAnalyticsPage}
          useController={useTenantAnalyticsController}
        />
      );
    }

    const module: DesktopImplementedRouteModule = Object.freeze({
      routeId: ROUTE_ID,
      capability: ROUTE_ID,
      localPolicy: 'native_equivalent',
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      Surface: TenantAnalyticsRouteSurface,
    });
    return module;
  };
}

function BoundTenantAnalyticsRoute({
  context,
  createBinding,
  Page,
  useController,
}: Readonly<{
  context: TenantAnalyticsRouteContext;
  createBinding: (
    context: TenantAnalyticsRouteContext,
  ) => TenantAnalyticsRouteBinding;
  Page: typeof import('./TenantAnalyticsPage').TenantAnalyticsPage;
  useController: typeof import('./useTenantAnalyticsController').useTenantAnalyticsController;
}>) {
  const binding = useMemo(
    () => createBinding(context),
    [context.tenantId, createBinding],
  );
  if (binding.scope.tenantId !== context.tenantId) {
    return (
      <Page
        model={buildTenantAnalyticsPresentation({
          kind: 'unavailable',
          scope: binding.scope,
          reasonCode: 'tenant_analytics_route_binding_scope_mismatch',
          retryable: false,
        })}
        tenantPlan={binding.tenantPlan}
        onRetry={noopRetry}
      />
    );
  }
  const { model, retry } = useController(binding.controller, binding.scope);
  return (
    <Page
      model={model}
      tenantPlan={binding.tenantPlan}
      onRetry={retry}
    />
  );
}

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}
