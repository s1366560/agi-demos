import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { InstanceTemplatesController } from './instanceTemplatesController';
import type {
  InstanceTemplatesModel,
  InstanceTemplatesScope,
} from './instanceTemplatesTypes';

const ROUTE_ID = 'tenant-tenant-instance-templates' as const;
const LOCAL_POLICY = 'native_equivalent' as const;

export type InstanceTemplatesRouteBinding = Readonly<{
  controller: InstanceTemplatesController;
  scope: InstanceTemplatesScope;
}>;
export type InstanceTemplatesRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string }
>;

export function createInstanceTemplatesRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding(
    context: InstanceTemplatesRouteContext,
  ): InstanceTemplatesRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('instance_templates_route_binding_factory_invalid');
  }
  return async () => {
    const [{ InstanceTemplatesPage }, { useInstanceTemplatesController }] =
      await Promise.all([
        import('./InstanceTemplatesPage'),
        import('./useInstanceTemplatesController'),
      ]);

    function InstanceTemplatesRouteSurface({
      context,
    }: DesktopRouteSurfaceProps) {
      const tenantId = nonEmpty(context.tenantId);
      if (!tenantId) {
        return (
          <InstanceTemplatesPage
            model={unavailableModel(
              'cloud',
              'instance_templates_route_context_unavailable',
            )}
            onRetry={() => {}}
            onQueryChange={() => {}}
            onFiltersChange={() => {}}
            onInspect={async () => {}}
            onCloseDetail={() => {}}
            onCreate={async () => {}}
            onDelete={async () => {}}
            onPublish={async () => {}}
            onClone={async () => {}}
          />
        );
      }
      return (
        <BoundInstanceTemplatesRoute
          context={Object.freeze({ ...context, tenantId })}
          createBinding={createBinding}
          Page={InstanceTemplatesPage}
          useController={useInstanceTemplatesController}
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
      Surface: InstanceTemplatesRouteSurface,
    });
    return module;
  };
}

function BoundInstanceTemplatesRoute({
  context,
  createBinding,
  Page,
  useController,
}: Readonly<{
  context: InstanceTemplatesRouteContext;
  createBinding(
    context: InstanceTemplatesRouteContext,
  ): InstanceTemplatesRouteBinding;
  Page: typeof import('./InstanceTemplatesPage').InstanceTemplatesPage;
  useController: typeof import('./useInstanceTemplatesController').useInstanceTemplatesController;
}>) {
  const binding = useMemo(
    () => createBinding(context),
    [context.tenantId, createBinding],
  );
  if (binding.scope.tenantId !== context.tenantId) {
    return (
      <Page
        model={unavailableModel(
          binding.scope.authority,
          'instance_templates_route_binding_scope_mismatch',
        )}
        onRetry={() => {}}
        onQueryChange={() => {}}
        onFiltersChange={() => {}}
        onInspect={async () => {}}
        onCloseDetail={() => {}}
        onCreate={async () => {}}
        onDelete={async () => {}}
        onPublish={async () => {}}
        onClone={async () => {}}
      />
    );
  }
  const {
    model,
    retry,
    setQuery,
    setFilters,
    inspect,
    closeDetail,
    create,
    remove,
    publish,
    clone,
  } = useController(binding.controller, binding.scope);
  return (
    <Page
      model={model}
      onRetry={retry}
      onQueryChange={setQuery}
      onFiltersChange={setFilters}
      onInspect={inspect}
      onCloseDetail={closeDetail}
      onCreate={create}
      onDelete={remove}
      onPublish={publish}
      onClone={clone}
    />
  );
}

function unavailableModel(
  authority: InstanceTemplatesScope['authority'],
  reasonCode: string,
): InstanceTemplatesModel {
  return Object.freeze({
    scope: Object.freeze({ authority, tenantId: '' }),
    authority,
    state: 'unavailable',
    reasonCode,
    retryVisible: false,
    allowedActions: Object.freeze([]),
    templates: Object.freeze([]),
    visibleTemplates: Object.freeze([]),
    total: 0,
    query: Object.freeze({
      page: 1,
      pageSize: 20,
      search: '',
      status: 'all',
    }),
    selectedTemplate: null,
    detailState: 'unavailable',
    detailReasonCode: reasonCode,
    items: Object.freeze([]),
    mutationState: 'unavailable',
    mutationReasonCode: reasonCode,
    lastUpdatedAt: null,
  });
}

function nonEmpty(value: string | undefined): string | null {
  if (!value || value !== value.trim()) return null;
  return value;
}
