import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { ManagementRouteController } from './managementRouteController';
import {
  buildManagementRoutePresentation,
  type ManagementRoutePresentationModel,
} from './managementRoutePresentationModel';
import type {
  ManagementRouteCapability,
  ManagementRouteContent,
  ManagementRouteScope,
} from './managementRouteTypes';

export type ManagementRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string }
>;

export type ManagementRouteBinding = Readonly<{
  controller: ManagementRouteController;
  scope: ManagementRouteScope;
  Content: ManagementRouteContent;
}>;

export type ManagementRouteModuleOptions = Readonly<{
  capability: ManagementRouteCapability;
  createBinding: (context: ManagementRouteContext) => ManagementRouteBinding;
}>;

type ManagementRoutePageComponent =
  typeof import('./ManagementRoutePage').ManagementRoutePage;
type ManagementRouteControllerHook =
  typeof import('./useManagementRouteController').useManagementRouteController;

const LOCAL_POLICY = 'native_equivalent' as const;

export function createManagementRouteModuleLoader({
  capability,
  createBinding,
}: ManagementRouteModuleOptions): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error(`${capability}:management_route_binding_factory_invalid`);
  }
  return async () => {
    const [{ ManagementRoutePage }, { useManagementRouteController }] =
      await Promise.all([
        import('./ManagementRoutePage'),
        import('./useManagementRouteController'),
      ]);

    function ManagementRouteSurface({
      context,
    }: DesktopRouteSurfaceProps) {
      const routeContext = normalizeRouteContext(context);
      if (!routeContext) {
        return (
          <ManagementRoutePage
            model={unavailableModel(
              capability,
              context,
              `${capability}:route_context_unavailable`,
            )}
            onRetry={() => undefined}
          />
        );
      }
      return (
        <BoundManagementRoute
          context={routeContext}
          capability={capability}
          createBinding={createBinding}
          ManagementRoutePage={ManagementRoutePage}
          useManagementRouteController={useManagementRouteController}
        />
      );
    }

    const module: DesktopImplementedRouteModule = Object.freeze({
      routeId: capability,
      capability,
      localPolicy: LOCAL_POLICY,
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      contentPolicy: 'route_content',
      Surface: ManagementRouteSurface,
    });
    return module;
  };
}

function BoundManagementRoute({
  context,
  capability,
  createBinding,
  ManagementRoutePage,
  useManagementRouteController,
}: Readonly<{
  context: ManagementRouteContext;
  capability: ManagementRouteCapability;
  createBinding: ManagementRouteModuleOptions['createBinding'];
  ManagementRoutePage: ManagementRoutePageComponent;
  useManagementRouteController: ManagementRouteControllerHook;
}>) {
  const binding = useMemo(
    () => createBinding(context),
    [
      context.instanceId,
      context.projectId,
      context.tenantId,
      context.workspaceId,
      createBinding,
    ],
  );
  if (binding.scope.tenantId !== context.tenantId) {
    return (
      <ManagementRoutePage
        model={terminalModel(
          capability,
          binding.scope,
          `${capability}:binding_scope_mismatch`,
        )}
        onRetry={() => undefined}
      />
    );
  }
  return (
    <ManagementControllerSurface
      binding={binding}
      ManagementRoutePage={ManagementRoutePage}
      useManagementRouteController={useManagementRouteController}
    />
  );
}

function ManagementControllerSurface({
  binding,
  ManagementRoutePage,
  useManagementRouteController,
}: Readonly<{
  binding: ManagementRouteBinding;
  ManagementRoutePage: ManagementRoutePageComponent;
  useManagementRouteController: ManagementRouteControllerHook;
}>) {
  const { model, retry } = useManagementRouteController(
    binding.controller,
    binding.scope,
  );
  if (model.state === 'ready' || model.state === 'empty') {
    return <binding.Content />;
  }
  return <ManagementRoutePage model={model} onRetry={retry} />;
}

function normalizeRouteContext(
  context: DesktopRouteContext,
): ManagementRouteContext | null {
  const tenantId = exactIdentifier(context.tenantId);
  if (!tenantId) return null;
  return Object.freeze({
    tenantId,
    ...(context.projectId === undefined
      ? {}
      : { projectId: context.projectId }),
    ...(context.workspaceId === undefined
      ? {}
      : { workspaceId: context.workspaceId }),
    ...(context.instanceId === undefined
      ? {}
      : { instanceId: context.instanceId }),
  });
}

function unavailableModel(
  capability: ManagementRouteCapability,
  context: DesktopRouteContext,
  reasonCode: string,
): ManagementRoutePresentationModel {
  const tenantId = exactIdentifier(context.tenantId) ?? 'unavailable';
  return terminalModel(
    capability,
    { authority: 'cloud', tenantId, projectId: null },
    reasonCode,
  );
}

function terminalModel(
  capability: ManagementRouteCapability,
  scope: ManagementRouteScope,
  reasonCode: string,
): ManagementRoutePresentationModel {
  return buildManagementRoutePresentation({
    kind: 'terminal',
    capability,
    scope,
    state: 'unavailable',
    reasonCode,
    retryable: false,
  });
}

function exactIdentifier(value: unknown): string | null {
  if (typeof value !== 'string' || value.length === 0 || value !== value.trim()) {
    return null;
  }
  return value;
}
