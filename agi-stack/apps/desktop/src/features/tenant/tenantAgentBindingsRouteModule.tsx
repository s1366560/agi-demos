import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { TenantAgentBindingsScope } from './tenantAgentBindingsClient';
import {
  createUnavailableTenantAgentBindingsView,
  type TenantAgentBindingsController,
} from './tenantAgentBindingsController';

const ROUTE_ID = 'tenant-tenant-agent-bindings' as const;
const noopRetry = (): void => {};

export type TenantAgentBindingsRouteBinding = Readonly<{
  controller: TenantAgentBindingsController;
  scope: TenantAgentBindingsScope;
}>;

export type TenantAgentBindingsRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string }
>;

export function createTenantAgentBindingsRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (
    context: TenantAgentBindingsRouteContext,
  ) => TenantAgentBindingsRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('tenant_agent_bindings_route_binding_factory_invalid');
  }
  return async () => {
    const [{ TenantAgentBindingsPage }, { useTenantAgentBindingsController }] =
      await Promise.all([
        import('./TenantAgentBindingsPage'),
        import('./useTenantAgentBindingsController'),
      ]);

    function TenantAgentBindingsRouteSurface({
      context,
    }: DesktopRouteSurfaceProps) {
      const tenantId = nonEmpty(context.tenantId);
      if (!tenantId) {
        return (
          <TenantAgentBindingsPage
            model={createUnavailableTenantAgentBindingsView(
              { authority: 'cloud', tenantId: 'unavailable' },
              'tenant_agent_bindings_route_context_unavailable',
            )}
            controller={null}
            onRetry={noopRetry}
          />
        );
      }
      const routeContext = Object.freeze({ ...context, tenantId });
      return (
        <BoundTenantAgentBindingsRoute
          context={routeContext}
          createBinding={createBinding}
          Page={TenantAgentBindingsPage}
          useController={useTenantAgentBindingsController}
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
      Surface: TenantAgentBindingsRouteSurface,
    });
    return module;
  };
}

function BoundTenantAgentBindingsRoute({
  context,
  createBinding,
  Page,
  useController,
}: Readonly<{
  context: TenantAgentBindingsRouteContext;
  createBinding: (
    context: TenantAgentBindingsRouteContext,
  ) => TenantAgentBindingsRouteBinding;
  Page: typeof import('./TenantAgentBindingsPage').TenantAgentBindingsPage;
  useController: typeof import('./useTenantAgentBindingsController').useTenantAgentBindingsController;
}>) {
  const binding = useMemo(
    () => createBinding(context),
    [context.tenantId, createBinding],
  );
  if (binding.scope.tenantId !== context.tenantId) {
    return (
      <Page
        model={createUnavailableTenantAgentBindingsView(
          binding.scope,
          'tenant_agent_bindings_route_binding_scope_mismatch',
        )}
        controller={null}
        onRetry={noopRetry}
      />
    );
  }
  const { model, retry } = useController(binding.controller, binding.scope);
  return (
    <Page
      model={model}
      controller={binding.controller}
      onRetry={retry}
    />
  );
}

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}
