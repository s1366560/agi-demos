import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { ProjectWorkspacesScope } from './projectWorkspacesClient';
import type { ProjectWorkspacesController } from './projectWorkspacesController';
import { buildProjectWorkspacesPresentation } from './projectWorkspacesPresentationModel';

const ROUTE_ID = 'project-project-workspaces' as const;
const noop = (): void => {};

export type ProjectWorkspacesRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string; projectId: string }
>;

export type ProjectWorkspacesRouteBinding = Readonly<{
  controller: ProjectWorkspacesController;
  scope: ProjectWorkspacesScope;
  openBlackboard: (workspaceId: string) => void;
}>;

export function createProjectWorkspacesRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: ProjectWorkspacesRouteContext) => ProjectWorkspacesRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('project_workspaces_route_binding_factory_invalid');
  }
  return async () => {
    const [{ ProjectWorkspacesPage }, { useProjectWorkspacesController }] = await Promise.all([
      import('./ProjectWorkspacesPage'),
      import('./useProjectWorkspacesController'),
    ]);
    function ProjectWorkspacesRouteSurface({ context }: DesktopRouteSurfaceProps) {
      const routeContext = normalizeContext(context);
      if (!routeContext) {
        return (
          <ProjectWorkspacesPage
            model={unavailableModel(fallbackScope(context), 'project_workspaces_route_context_unavailable')}
            controller={inertController}
            onRetry={noop}
            onOpenBlackboard={noop}
          />
        );
      }
      return (
        <BoundRoute
          context={routeContext}
          createBinding={createBinding}
          Page={ProjectWorkspacesPage}
          useController={useProjectWorkspacesController}
        />
      );
    }
    return Object.freeze({
      routeId: ROUTE_ID,
      capability: ROUTE_ID,
      localPolicy: 'native_equivalent',
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      Surface: ProjectWorkspacesRouteSurface,
    }) satisfies DesktopImplementedRouteModule;
  };
}

function BoundRoute({ context, createBinding, Page, useController }: Readonly<{
  context: ProjectWorkspacesRouteContext;
  createBinding: (context: ProjectWorkspacesRouteContext) => ProjectWorkspacesRouteBinding;
  Page: typeof import('./ProjectWorkspacesPage').ProjectWorkspacesPage;
  useController: typeof import('./useProjectWorkspacesController').useProjectWorkspacesController;
}>) {
  const binding = useMemo(
    () => createBinding(context),
    [context.projectId, context.tenantId, createBinding],
  );
  if (
    binding.scope.tenantId !== context.tenantId ||
    binding.scope.projectId !== context.projectId
  ) {
    return (
      <Page
        model={unavailableModel(binding.scope, 'project_workspaces_route_binding_scope_mismatch')}
        controller={inertController}
        onRetry={noop}
        onOpenBlackboard={noop}
      />
    );
  }
  const { model, retry } = useController(binding.controller, binding.scope);
  return (
    <Page
      model={model}
      controller={binding.controller}
      onRetry={retry}
      onOpenBlackboard={binding.openBlackboard}
    />
  );
}

function normalizeContext(context: DesktopRouteContext): ProjectWorkspacesRouteContext | null {
  const tenantId = nonEmpty(context.tenantId);
  const projectId = nonEmpty(context.projectId);
  return tenantId && projectId ? Object.freeze({ ...context, tenantId, projectId }) : null;
}

function fallbackScope(context: DesktopRouteContext): ProjectWorkspacesScope {
  return Object.freeze({
    authority: 'cloud',
    tenantId: nonEmpty(context.tenantId) ?? 'unavailable',
    projectId: nonEmpty(context.projectId) ?? 'unavailable',
  });
}

function unavailableModel(scope: ProjectWorkspacesScope, reasonCode: string) {
  return buildProjectWorkspacesPresentation({
    kind: 'failure',
    scope,
    state: 'unavailable',
    reasonCode,
    retryable: false,
  });
}

const inertController: ProjectWorkspacesController = Object.freeze({
  getSnapshot: () => unavailableModel(fallbackScope({}), 'project_workspaces_route_context_unavailable'),
  subscribe: () => () => {},
  load: async () => {},
  retry: async () => {},
  create: async () => {},
  cancel: noop,
  stop: noop,
});

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}
