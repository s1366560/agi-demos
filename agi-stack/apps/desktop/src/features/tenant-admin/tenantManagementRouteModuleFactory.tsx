import { useMemo, type ComponentType } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type {
  DesktopRouteContext,
  DesktopRouteLocalPolicy,
} from '../navigation/desktopRouteRegistry';
import type { TenantManagementControllerCore } from './tenantManagementController';
import type { TenantManagementScope } from './tenantManagementHttp';
import { useTenantManagementController } from './useTenantManagementController';

export type TenantManagementRouteContext = Readonly<DesktopRouteContext & { tenantId: string }>;
export type TenantManagementRouteBinding<
  TScope extends TenantManagementScope,
  TModel,
  TController extends TenantManagementControllerCore<TScope, TModel>,
> = Readonly<{ controller: TController; scope: TScope }>;

type TenantManagementPageComponent<TController, TModel> = ComponentType<
  Readonly<{
    model: TModel;
    controller: TController | null;
    onRetry: () => void;
  }>
>;

export function createTenantManagementRouteModuleLoader<
  TScope extends TenantManagementScope,
  TModel,
  TController extends TenantManagementControllerCore<TScope, TModel>,
>({
  routeId,
  localPolicy,
  createBinding,
  loadPage,
  fallbackScope,
  buildTerminalModel,
  scopeMatches = (context, scope) => context.tenantId === scope.tenantId,
}: Readonly<{
  routeId: string;
  localPolicy: Extract<DesktopRouteLocalPolicy, 'cloud_only' | 'native_equivalent'>;
  createBinding: (
    context: TenantManagementRouteContext,
  ) => TenantManagementRouteBinding<TScope, TModel, TController>;
  loadPage: () => Promise<TenantManagementPageComponent<TController, TModel>>;
  fallbackScope: (context: DesktopRouteContext) => TScope;
  buildTerminalModel: (scope: TScope, reasonCode: string) => TModel;
  scopeMatches?: (context: TenantManagementRouteContext, scope: TScope) => boolean;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error(`${routeId}:tenant_management_route_binding_factory_invalid`);
  }
  return async () => {
    const Page = await loadPage();
    function TenantManagementSurface({ context }: DesktopRouteSurfaceProps) {
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
        <BoundTenantManagementRoute
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
      localPolicy,
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      contentPolicy: 'route_content',
      Surface: TenantManagementSurface,
    });
    return module;
  };
}

function BoundTenantManagementRoute<
  TScope extends TenantManagementScope,
  TModel,
  TController extends TenantManagementControllerCore<TScope, TModel>,
>({
  routeId,
  context,
  createBinding,
  scopeMatches,
  buildTerminalModel,
  Page,
}: Readonly<{
  routeId: string;
  context: TenantManagementRouteContext;
  createBinding: (
    context: TenantManagementRouteContext,
  ) => TenantManagementRouteBinding<TScope, TModel, TController>;
  scopeMatches: (context: TenantManagementRouteContext, scope: TScope) => boolean;
  buildTerminalModel: (scope: TScope, reasonCode: string) => TModel;
  Page: TenantManagementPageComponent<TController, TModel>;
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
  return <TenantManagementControllerSurface binding={binding} Page={Page} />;
}

function TenantManagementControllerSurface<
  TScope extends TenantManagementScope,
  TModel,
  TController extends TenantManagementControllerCore<TScope, TModel>,
>({
  binding,
  Page,
}: Readonly<{
  binding: TenantManagementRouteBinding<TScope, TModel, TController>;
  Page: TenantManagementPageComponent<TController, TModel>;
}>) {
  const { model, retry } = useTenantManagementController(binding.controller, binding.scope);
  return <Page model={model} controller={binding.controller} onRetry={retry} />;
}

function normalizeContext(context: DesktopRouteContext): TenantManagementRouteContext | null {
  if (
    typeof context.tenantId !== 'string' ||
    !context.tenantId ||
    context.tenantId !== context.tenantId.trim()
  ) {
    return null;
  }
  return Object.freeze({ ...context, tenantId: context.tenantId });
}
