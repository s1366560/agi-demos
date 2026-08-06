import { useMemo } from 'react';
import type { ComponentType } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type {
  DesktopRouteContext,
  DesktopRouteLocalPolicy,
} from '../navigation/desktopRouteRegistry';
import type { NativeSettingsRouteController } from './nativeSettingsRouteController';
import type { NativeSettingsRoutePageModel } from './NativeSettingsRoutePage';
import type { NativeSettingsRouteScope } from './nativeSettingsRoutePresentation';

export type NativeSettingsRouteContentProps<TModel, TController> = Readonly<{
  model: TModel;
  controller: TController;
}>;

export type NativeSettingsRouteBinding<TScope, TModel, TController> = Readonly<{
  controller: TController;
  scope: TScope;
}>;

export function createNativeSettingsRouteModuleLoader<
  TContext extends DesktopRouteContext,
  TScope extends NativeSettingsRouteScope,
  TModel extends NativeSettingsRoutePageModel,
  TController extends NativeSettingsRouteController<TScope, TModel>,
>({
  routeId,
  localPolicy,
  createBinding,
  normalizeContext,
  fallbackScope,
  scopeMatches,
  contextKey,
  unavailableModel,
  loadContent,
}: Readonly<{
  routeId: string;
  localPolicy: DesktopRouteLocalPolicy;
  createBinding: (context: TContext) => NativeSettingsRouteBinding<TScope, TModel, TController>;
  normalizeContext: (context: DesktopRouteContext) => TContext | null;
  fallbackScope: (context: DesktopRouteContext) => TScope;
  scopeMatches: (context: TContext, scope: TScope) => boolean;
  contextKey: (context: TContext) => string;
  unavailableModel: (scope: TScope, reasonCode: string) => TModel;
  loadContent: () => Promise<ComponentType<NativeSettingsRouteContentProps<TModel, TController>>>;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error(`${routeId}:native_route_binding_factory_invalid`);
  }
  return async () => {
    const [{ NativeSettingsRoutePage }, { useNativeSettingsRouteController }, Content] =
      await Promise.all([
        import('./NativeSettingsRoutePage'),
        import('./useNativeSettingsRouteController'),
        loadContent(),
      ]);

    function NativeSettingsRouteSurface({ context }: DesktopRouteSurfaceProps) {
      const routeContext = normalizeContext(context);
      if (!routeContext) {
        return (
          <NativeSettingsRoutePage
            model={unavailableModel(fallbackScope(context), `${routeId}:route_context_unavailable`)}
            onRetry={() => undefined}
          />
        );
      }
      return (
        <BoundNativeSettingsRoute
          context={routeContext}
          createBinding={createBinding}
          scopeMatches={scopeMatches}
          contextKey={contextKey}
          unavailableModel={unavailableModel}
          Page={NativeSettingsRoutePage}
          useController={useNativeSettingsRouteController}
          Content={Content}
        />
      );
    }

    return Object.freeze({
      routeId,
      capability: routeId,
      localPolicy,
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      contentPolicy: 'route_content',
      Surface: NativeSettingsRouteSurface,
    }) satisfies DesktopImplementedRouteModule;
  };
}

function BoundNativeSettingsRoute<
  TContext extends DesktopRouteContext,
  TScope extends NativeSettingsRouteScope,
  TModel extends NativeSettingsRoutePageModel,
  TController extends NativeSettingsRouteController<TScope, TModel>,
>({
  context,
  createBinding,
  scopeMatches,
  contextKey,
  unavailableModel,
  Page,
  useController,
  Content,
}: Readonly<{
  context: TContext;
  createBinding: (context: TContext) => NativeSettingsRouteBinding<TScope, TModel, TController>;
  scopeMatches: (context: TContext, scope: TScope) => boolean;
  contextKey: (context: TContext) => string;
  unavailableModel: (scope: TScope, reasonCode: string) => TModel;
  Page: typeof import('./NativeSettingsRoutePage').NativeSettingsRoutePage;
  useController: typeof import('./useNativeSettingsRouteController').useNativeSettingsRouteController;
  Content: ComponentType<NativeSettingsRouteContentProps<TModel, TController>>;
}>) {
  const key = contextKey(context);
  const binding = useMemo(() => createBinding(context), [createBinding, key]);
  if (!scopeMatches(context, binding.scope)) {
    return (
      <Page
        model={unavailableModel(
          binding.scope,
          `${binding.controller.getSnapshot().capability}:binding_scope_mismatch`,
        )}
        onRetry={() => undefined}
      />
    );
  }
  return (
    <NativeSettingsControllerSurface
      binding={binding}
      Page={Page}
      useController={useController}
      Content={Content}
    />
  );
}

function NativeSettingsControllerSurface<
  TScope extends NativeSettingsRouteScope,
  TModel extends NativeSettingsRoutePageModel,
  TController extends NativeSettingsRouteController<TScope, TModel>,
>({
  binding,
  Page,
  useController,
  Content,
}: Readonly<{
  binding: NativeSettingsRouteBinding<TScope, TModel, TController>;
  Page: typeof import('./NativeSettingsRoutePage').NativeSettingsRoutePage;
  useController: typeof import('./useNativeSettingsRouteController').useNativeSettingsRouteController;
  Content: ComponentType<NativeSettingsRouteContentProps<TModel, TController>>;
}>) {
  const { model, retry } = useController(binding.controller, binding.scope);
  if (model.state === 'ready' || model.state === 'empty' || model.state === 'degraded') {
    return <Content model={model} controller={binding.controller} />;
  }
  return <Page model={model} onRetry={retry} />;
}
