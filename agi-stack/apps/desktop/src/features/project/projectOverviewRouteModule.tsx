import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { ProjectOverviewController } from './projectOverviewController';
import {
  buildProjectOverviewPresentation,
  type ProjectOverviewAuthority,
  type ProjectOverviewPresentationScope,
} from './projectOverviewPresentationModel';

const PROJECT_OVERVIEW_ROUTE_ID = 'project-project-overview' as const;
const PROJECT_OVERVIEW_LOCAL_POLICY = 'native_equivalent' as const;
const CONTEXT_UNAVAILABLE_REASON =
  'project_overview_route_context_unavailable';
const BINDING_SCOPE_MISMATCH_REASON =
  'project_overview_route_binding_scope_mismatch';
const FALLBACK_SCOPE_VALUE = 'unavailable';
const noopRetry = (): void => {};

export type ProjectOverviewRouteContext = Readonly<
  DesktopRouteContext & {
    tenantId: string;
    projectId: string;
  }
>;

export type ProjectOverviewRouteBinding = Readonly<{
  controller: ProjectOverviewController;
  scope: ProjectOverviewPresentationScope;
}>;

export type ProjectOverviewRouteModuleOptions = Readonly<{
  createBinding: (
    context: ProjectOverviewRouteContext,
  ) => ProjectOverviewRouteBinding;
}>;

type ProjectOverviewPageComponent = typeof import('./ProjectOverviewPage').ProjectOverviewPage;
type ProjectOverviewControllerHook =
  typeof import('./useProjectOverviewController').useProjectOverviewController;

export function createProjectOverviewRouteModuleLoader({
  createBinding,
}: ProjectOverviewRouteModuleOptions): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('project_overview_route_binding_factory_invalid');
  }

  return async () => {
    const [
      { ProjectOverviewPage },
      { useProjectOverviewController },
    ] = await Promise.all([
      import('./ProjectOverviewPage'),
      import('./useProjectOverviewController'),
    ]);

    function ProjectOverviewRouteSurface({
      context,
    }: DesktopRouteSurfaceProps) {
      const routeContext = normalizeProjectOverviewContext(context);
      if (!routeContext) {
        return (
          <ProjectOverviewPage
            model={unavailableModel(
              fallbackScope(context),
              CONTEXT_UNAVAILABLE_REASON,
            )}
            onRetry={noopRetry}
          />
        );
      }
      return (
        <BoundProjectOverviewRoute
          context={routeContext}
          createBinding={createBinding}
          ProjectOverviewPage={ProjectOverviewPage}
          useProjectOverviewController={useProjectOverviewController}
        />
      );
    }

    const module: DesktopImplementedRouteModule = Object.freeze({
      routeId: PROJECT_OVERVIEW_ROUTE_ID,
      capability: PROJECT_OVERVIEW_ROUTE_ID,
      localPolicy: PROJECT_OVERVIEW_LOCAL_POLICY,
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      Surface: ProjectOverviewRouteSurface,
    });
    return module;
  };
}

function BoundProjectOverviewRoute({
  context,
  createBinding,
  ProjectOverviewPage,
  useProjectOverviewController,
}: Readonly<{
  context: ProjectOverviewRouteContext;
  createBinding: ProjectOverviewRouteModuleOptions['createBinding'];
  ProjectOverviewPage: ProjectOverviewPageComponent;
  useProjectOverviewController: ProjectOverviewControllerHook;
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
  if (!bindingScopeMatches(context, binding.scope)) {
    return (
      <ProjectOverviewPage
        model={unavailableModel(
          contextScope(binding.scope.authority, context),
          BINDING_SCOPE_MISMATCH_REASON,
        )}
        onRetry={noopRetry}
      />
    );
  }
  return (
    <ProjectOverviewControllerSurface
      binding={binding}
      ProjectOverviewPage={ProjectOverviewPage}
      useProjectOverviewController={useProjectOverviewController}
    />
  );
}

function ProjectOverviewControllerSurface({
  binding,
  ProjectOverviewPage,
  useProjectOverviewController,
}: Readonly<{
  binding: ProjectOverviewRouteBinding;
  ProjectOverviewPage: ProjectOverviewPageComponent;
  useProjectOverviewController: ProjectOverviewControllerHook;
}>) {
  const { model, retry } = useProjectOverviewController(
    binding.controller,
    binding.scope,
  );
  return <ProjectOverviewPage model={model} onRetry={retry} />;
}

function normalizeProjectOverviewContext(
  context: DesktopRouteContext,
): ProjectOverviewRouteContext | null {
  const tenantId = nonEmptyContextValue(context.tenantId);
  const projectId = nonEmptyContextValue(context.projectId);
  if (!tenantId || !projectId) return null;
  return Object.freeze({
    tenantId,
    projectId,
    ...(context.workspaceId === undefined
      ? {}
      : { workspaceId: context.workspaceId }),
    ...(context.instanceId === undefined
      ? {}
      : { instanceId: context.instanceId }),
  });
}

function bindingScopeMatches(
  context: ProjectOverviewRouteContext,
  scope: ProjectOverviewPresentationScope,
): boolean {
  return (
    scope.tenantId === context.tenantId &&
    scope.projectId === context.projectId
  );
}

function fallbackScope(
  context: DesktopRouteContext,
): ProjectOverviewPresentationScope {
  return contextScope('cloud', {
    tenantId: nonEmptyContextValue(context.tenantId) ?? FALLBACK_SCOPE_VALUE,
    projectId: nonEmptyContextValue(context.projectId) ?? FALLBACK_SCOPE_VALUE,
  });
}

function contextScope(
  authority: ProjectOverviewAuthority,
  context: Pick<ProjectOverviewRouteContext, 'tenantId' | 'projectId'>,
): ProjectOverviewPresentationScope {
  return Object.freeze({
    authority,
    tenantId: context.tenantId,
    projectId: context.projectId,
  });
}

function unavailableModel(
  scope: ProjectOverviewPresentationScope,
  reasonCode: string,
) {
  return buildProjectOverviewPresentation({
    kind: 'unavailable',
    scope,
    reasonCode,
    retryable: false,
  });
}

function nonEmptyContextValue(value: string | undefined): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
}
