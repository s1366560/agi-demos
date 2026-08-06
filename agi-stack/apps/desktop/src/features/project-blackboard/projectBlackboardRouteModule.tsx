import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { ProjectBlackboardScope } from './projectBlackboardClient';
import type { ProjectBlackboardController } from './projectBlackboardController';
import { buildProjectBlackboardPresentation } from './projectBlackboardPresentationModel';

const ROUTE_ID = 'project-blackboard-dynamic-project-blackboard' as const;
const noop = (): void => {};

export type ProjectBlackboardRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string; projectId: string; workspaceId: string }
>;
export type ProjectBlackboardRouteBinding = Readonly<{
  controller: ProjectBlackboardController;
  scope: ProjectBlackboardScope;
}>;

export function buildProjectBlackboardCanonicalPath(
  context: Readonly<{
    tenantId: string;
    projectId: string;
    workspaceId: string;
  }>,
): string {
  return (
    `/tenant/${encodeURIComponent(context.tenantId)}` +
    `/project/${encodeURIComponent(context.projectId)}` +
    `/blackboard?workspaceId=${encodeURIComponent(context.workspaceId)}`
  );
}

export function createProjectBlackboardRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: ProjectBlackboardRouteContext) => ProjectBlackboardRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('project_blackboard_route_binding_factory_invalid');
  }
  return async () => {
    const [{ ProjectBlackboardPage }, { useProjectBlackboardController }] = await Promise.all([
      import('./ProjectBlackboardPage'),
      import('./useProjectBlackboardController'),
    ]);
    function ProjectBlackboardRouteSurface({ context }: DesktopRouteSurfaceProps) {
      const routeContext = normalizeContext(context);
      if (!routeContext) {
        return (
          <ProjectBlackboardPage
            model={unavailableModel(
              fallbackScope(context),
              'project_blackboard_route_context_unavailable',
            )}
            onRetry={noop}
          />
        );
      }
      return (
        <BoundRoute
          context={routeContext}
          createBinding={createBinding}
          Page={ProjectBlackboardPage}
          useController={useProjectBlackboardController}
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
      Surface: ProjectBlackboardRouteSurface,
    }) satisfies DesktopImplementedRouteModule;
  };
}

function BoundRoute({ context, createBinding, Page, useController }: Readonly<{
  context: ProjectBlackboardRouteContext;
  createBinding: (context: ProjectBlackboardRouteContext) => ProjectBlackboardRouteBinding;
  Page: typeof import('./ProjectBlackboardPage').ProjectBlackboardPage;
  useController: typeof import('./useProjectBlackboardController').useProjectBlackboardController;
}>) {
  const binding = useMemo(
    () => createBinding(context),
    [context.projectId, context.tenantId, context.workspaceId, createBinding],
  );
  if (!sameContext(context, binding.scope)) {
    return (
      <Page
        model={unavailableModel(binding.scope, 'project_blackboard_route_binding_scope_mismatch')}
        onRetry={noop}
      />
    );
  }
  const { model, retry } = useController(binding.controller, binding.scope);
  return <Page model={model} onRetry={retry} />;
}

function normalizeContext(context: DesktopRouteContext): ProjectBlackboardRouteContext | null {
  const tenantId = nonEmpty(context.tenantId);
  const projectId = nonEmpty(context.projectId);
  const workspaceId = nonEmpty(context.workspaceId);
  return tenantId && projectId && workspaceId
    ? Object.freeze({ ...context, tenantId, projectId, workspaceId })
    : null;
}

function fallbackScope(context: DesktopRouteContext): ProjectBlackboardScope {
  return Object.freeze({
    authority: 'cloud',
    tenantId: nonEmpty(context.tenantId) ?? 'unavailable',
    projectId: nonEmpty(context.projectId) ?? 'unavailable',
    workspaceId: nonEmpty(context.workspaceId) ?? 'unavailable',
  });
}

function unavailableModel(scope: ProjectBlackboardScope, reasonCode: string) {
  return buildProjectBlackboardPresentation({
    kind: 'failure',
    scope,
    state: 'unavailable',
    reasonCode,
    retryable: false,
  });
}

function sameContext(context: ProjectBlackboardRouteContext, scope: ProjectBlackboardScope) {
  return (
    context.tenantId === scope.tenantId &&
    context.projectId === scope.projectId &&
    context.workspaceId === scope.workspaceId
  );
}

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}
