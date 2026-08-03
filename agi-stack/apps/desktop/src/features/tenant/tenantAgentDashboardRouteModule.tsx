import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { TenantAgentDashboardScope } from './tenantAgentDashboardClient';
import {
  createUnavailableTenantAgentDashboardView,
  type TenantAgentDashboardController,
} from './tenantAgentDashboardController';

const ROUTE_ID = 'tenant-tenant-agent-configuration' as const;
const noopRetry = (): void => {};

export type TenantAgentDashboardRouteBinding = Readonly<{
  controller: TenantAgentDashboardController;
  scope: TenantAgentDashboardScope;
}>;

export type TenantAgentDashboardRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string }
>;

export function createTenantAgentDashboardRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (
    context: TenantAgentDashboardRouteContext,
  ) => TenantAgentDashboardRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('tenant_agent_dashboard_route_binding_factory_invalid');
  }
  return async () => {
    const [{ TenantAgentDashboardPage }, { useTenantAgentDashboardController }] =
      await Promise.all([
        import('./TenantAgentDashboardPage'),
        import('./useTenantAgentDashboardController'),
      ]);

    function TenantAgentDashboardRouteSurface({
      context,
    }: DesktopRouteSurfaceProps) {
      const tenantId = nonEmpty(context.tenantId);
      if (!tenantId) {
        return (
          <TenantAgentDashboardPage
            model={createUnavailableTenantAgentDashboardView(
              { authority: 'cloud', tenantId: 'unavailable' },
              'tenant_agent_dashboard_route_context_unavailable',
            )}
            controller={null}
            onRetry={noopRetry}
          />
        );
      }
      const routeContext = Object.freeze({ ...context, tenantId });
      return (
        <BoundTenantAgentDashboardRoute
          context={routeContext}
          createBinding={createBinding}
          Page={TenantAgentDashboardPage}
          useController={useTenantAgentDashboardController}
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
      Surface: TenantAgentDashboardRouteSurface,
    });
    return module;
  };
}

function BoundTenantAgentDashboardRoute({
  context,
  createBinding,
  Page,
  useController,
}: Readonly<{
  context: TenantAgentDashboardRouteContext;
  createBinding: (
    context: TenantAgentDashboardRouteContext,
  ) => TenantAgentDashboardRouteBinding;
  Page: typeof import('./TenantAgentDashboardPage').TenantAgentDashboardPage;
  useController: typeof import('./useTenantAgentDashboardController').useTenantAgentDashboardController;
}>) {
  const binding = useMemo(
    () => createBinding(context),
    [context.tenantId, createBinding],
  );
  if (binding.scope.tenantId !== context.tenantId) {
    return (
      <Page
        model={createUnavailableTenantAgentDashboardView(
          binding.scope,
          'tenant_agent_dashboard_route_binding_scope_mismatch',
        )}
        controller={null}
        onRetry={noopRetry}
      />
    );
  }
  const { model, retry } = useController(binding.controller, binding.scope);
  return <Page model={model} controller={binding.controller} onRetry={retry} />;
}

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}
