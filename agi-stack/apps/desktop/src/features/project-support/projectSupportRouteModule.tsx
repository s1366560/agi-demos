import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type {
  ProjectSupportController,
  ProjectSupportViewModel,
} from './projectSupportController';
import type { ProjectSupportScope } from './projectSupportTypes';

const ROUTE_ID = 'project-support' as const;
const LOCAL_POLICY = 'cloud_only' as const;
const noopRetry = (): void => {};

export type ProjectSupportRouteBinding = Readonly<{
  controller: ProjectSupportController;
  scope: ProjectSupportScope;
}>;

export type ProjectSupportRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string; projectId: string }
>;

export function createProjectSupportRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (
    context: ProjectSupportRouteContext,
  ) => ProjectSupportRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('project_support_route_binding_factory_invalid');
  }
  return async () => {
    const [{ ProjectSupportPage }, { useProjectSupportController }] =
      await Promise.all([
        import('./ProjectSupportPage'),
        import('./useProjectSupportController'),
      ]);

    function ProjectSupportRouteSurface({
      context,
    }: DesktopRouteSurfaceProps) {
      const tenantId = nonEmpty(context.tenantId);
      const projectId = nonEmpty(context.projectId);
      if (!tenantId || !projectId) {
        return (
          <ProjectSupportPage
            model={unavailableModel(
              'cloud',
              tenantId ?? 'unavailable',
              projectId ?? 'unavailable',
              'project_support_route_context_unavailable',
            )}
            controller={inertController}
            onRetry={noopRetry}
          />
        );
      }
      return (
        <BoundProjectSupportRoute
          context={Object.freeze({ ...context, tenantId, projectId })}
          createBinding={createBinding}
          Page={ProjectSupportPage}
          useController={useProjectSupportController}
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
      Surface: ProjectSupportRouteSurface,
    });
    return module;
  };
}

function BoundProjectSupportRoute({
  context,
  createBinding,
  Page,
  useController,
}: Readonly<{
  context: ProjectSupportRouteContext;
  createBinding: (
    context: ProjectSupportRouteContext,
  ) => ProjectSupportRouteBinding;
  Page: typeof import('./ProjectSupportPage').ProjectSupportPage;
  useController: typeof import('./useProjectSupportController').useProjectSupportController;
}>) {
  const binding = useMemo(
    () => createBinding(context),
    [context.tenantId, context.projectId, createBinding],
  );
  if (
    binding.scope.tenantId !== context.tenantId ||
    binding.scope.projectId !== context.projectId
  ) {
    return (
      <Page
        model={unavailableModel(
          binding.scope.authority,
          binding.scope.tenantId,
          binding.scope.projectId,
          'project_support_route_binding_scope_mismatch',
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
  authority: ProjectSupportScope['authority'],
  tenantId: string,
  projectId: string,
  reasonCode: string,
): ProjectSupportViewModel {
  return Object.freeze({
    state: 'unavailable',
    scope: Object.freeze({ authority, tenantId, projectId }),
    authority,
    reasonCode,
    retryVisible: false,
    busyAction: null,
    allowedActions: Object.freeze([]),
    tickets: Object.freeze([]),
    total: 0,
    limit: 25,
    offset: 0,
    hasMore: false,
  });
}

const inertController: ProjectSupportController = Object.freeze({
  getSnapshot: () =>
    unavailableModel(
      'cloud',
      'unavailable',
      'unavailable',
      'project_support_route_context_unavailable',
    ),
  subscribe: () => () => {},
  load: async () => {},
  retry: async () => {},
  create: async () => {},
  close: async () => {},
  goToOffset: async () => {},
  cancel: () => {},
  stop: () => {},
});

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}
