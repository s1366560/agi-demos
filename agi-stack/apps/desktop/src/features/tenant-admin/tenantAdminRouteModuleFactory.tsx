import { useMemo, type ComponentType } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { TenantAdminControllerCore } from './tenantAdminController';
import type { TenantAdminScope } from './tenantAdminHttp';
import { useTenantAdminController } from './useTenantAdminController';

export type TenantAdminRouteContext = Readonly<DesktopRouteContext & { tenantId: string }>;
export type TenantAdminRouteBinding<
  TScope extends TenantAdminScope,
  TModel,
  TController extends TenantAdminControllerCore<TScope, TModel>,
> = Readonly<{ controller: TController; scope: TScope }>;

type TenantAdminPageComponent<TController, TModel> = ComponentType<
  Readonly<{
    model: TModel;
    controller: TController | null;
    onRetry: () => void;
  }>
>;

export function createTenantAdminRouteModuleLoader<
  TScope extends TenantAdminScope,
  TModel,
  TController extends TenantAdminControllerCore<TScope, TModel>,
>({
  routeId,
  createBinding,
  loadPage,
  fallbackScope,
  buildTerminalModel,
  scopeMatches = (context, scope) => context.tenantId === scope.tenantId,
}: Readonly<{
  routeId: string;
  createBinding: (
    context: TenantAdminRouteContext,
  ) => TenantAdminRouteBinding<TScope, TModel, TController>;
  loadPage: () => Promise<TenantAdminPageComponent<TController, TModel>>;
  fallbackScope: (context: DesktopRouteContext) => TScope;
  buildTerminalModel: (scope: TScope, reasonCode: string) => TModel;
  scopeMatches?: (context: TenantAdminRouteContext, scope: TScope) => boolean;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error(`${routeId}:tenant_admin_route_binding_factory_invalid`);
  }
  return async () => {
    const Page = await loadPage();
    function TenantAdminSurface({ context }: DesktopRouteSurfaceProps) {
      const routeContext = normalizeContext(context);
      if (!routeContext) {
        return (
          <Page
            model={buildTerminalModel(
              fallbackScope(context),
              `${routeId}:route_context_unavailable`,
            )}
            controller={null}
            onRetry={() => undefined}
          />
        );
      }
      return (
        <BoundTenantAdminRoute
          routeId={routeId}
          context={routeContext}
          createBinding={createBinding}
          scopeMatches={scopeMatches}
          buildTerminalModel={buildTerminalModel}
          Page={Page}
        />
      );
    }
    const module: DesktopImplementedRouteModule = Object.freeze({
      routeId,
      capability: routeId,
      localPolicy: 'cloud_only',
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      contentPolicy: 'route_content',
      Surface: TenantAdminSurface,
    });
    return module;
  };
}

function BoundTenantAdminRoute<
  TScope extends TenantAdminScope,
  TModel,
  TController extends TenantAdminControllerCore<TScope, TModel>,
>({
  routeId,
  context,
  createBinding,
  scopeMatches,
  buildTerminalModel,
  Page,
}: Readonly<{
  routeId: string;
  context: TenantAdminRouteContext;
  createBinding: (
    context: TenantAdminRouteContext,
  ) => TenantAdminRouteBinding<TScope, TModel, TController>;
  scopeMatches: (context: TenantAdminRouteContext, scope: TScope) => boolean;
  buildTerminalModel: (scope: TScope, reasonCode: string) => TModel;
  Page: TenantAdminPageComponent<TController, TModel>;
}>) {
  const binding = useMemo(() => createBinding(context), [context.tenantId, createBinding]);
  if (!scopeMatches(context, binding.scope)) {
    return (
      <Page
        model={buildTerminalModel(binding.scope, `${routeId}:binding_scope_mismatch`)}
        controller={null}
        onRetry={() => undefined}
      />
    );
  }
  return <TenantAdminControllerSurface binding={binding} Page={Page} />;
}

function TenantAdminControllerSurface<
  TScope extends TenantAdminScope,
  TModel,
  TController extends TenantAdminControllerCore<TScope, TModel>,
>({
  binding,
  Page,
}: Readonly<{
  binding: TenantAdminRouteBinding<TScope, TModel, TController>;
  Page: TenantAdminPageComponent<TController, TModel>;
}>) {
  const { model, retry } = useTenantAdminController(binding.controller, binding.scope);
  return <Page model={model} controller={binding.controller} onRetry={retry} />;
}

function normalizeContext(context: DesktopRouteContext): TenantAdminRouteContext | null {
  if (
    typeof context.tenantId !== 'string' ||
    !context.tenantId ||
    context.tenantId !== context.tenantId.trim()
  ) {
    return null;
  }
  return Object.freeze({ ...context, tenantId: context.tenantId });
}
