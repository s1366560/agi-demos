import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { ProjectAgentScope } from './projectAgentClient';
import type { ProjectAgentController } from './projectAgentController';
import type { ProjectAgentViewModel } from './projectAgentPresentationModel';

const noop = (): void => {};
export type ProjectAgentRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string; projectId: string }
>;
export type ProjectAgentRouteBinding = Readonly<{
  controller: ProjectAgentController;
  scope: ProjectAgentScope;
}>;

export function createProjectAgentRouteModuleLoader({
  routeId,
  contextUnavailableReason,
  bindingScopeMismatchReason,
  createBinding,
}: Readonly<{
  routeId: string;
  contextUnavailableReason: string;
  bindingScopeMismatchReason: string;
  createBinding: (context: ProjectAgentRouteContext) => ProjectAgentRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('project_agent_route_binding_factory_invalid');
  }
  return async () => {
    const [{ ProjectAgentPage }, { useProjectAgentController }] = await Promise.all([
      import('./ProjectAgentPage'),
      import('./useProjectAgentController'),
    ]);
    function ProjectAgentRouteSurface({ context }: DesktopRouteSurfaceProps) {
      const routeContext = normalizeContext(context);
      if (!routeContext) {
        return (
          <ProjectAgentPage
            model={unavailableModel(routeId, fallbackScope(context), contextUnavailableReason)}
            onRetry={noop}
          />
        );
      }
      return (
        <BoundRoute
          routeId={routeId}
          context={routeContext}
          createBinding={createBinding}
          bindingScopeMismatchReason={bindingScopeMismatchReason}
          Page={ProjectAgentPage}
          useController={useProjectAgentController}
        />
      );
    }
    return Object.freeze({
      routeId,
      capability: routeId,
      localPolicy: 'native_equivalent',
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      Surface: ProjectAgentRouteSurface,
    }) satisfies DesktopImplementedRouteModule;
  };
}

function BoundRoute({
  routeId,
  context,
  createBinding,
  bindingScopeMismatchReason,
  Page,
  useController,
}: Readonly<{
  routeId: string;
  context: ProjectAgentRouteContext;
  createBinding: (context: ProjectAgentRouteContext) => ProjectAgentRouteBinding;
  bindingScopeMismatchReason: string;
  Page: typeof import('./ProjectAgentPage').ProjectAgentPage;
  useController: typeof import('./useProjectAgentController').useProjectAgentController;
}>) {
  const binding = useMemo(
    () => createBinding(context),
    [context.projectId, context.tenantId, createBinding],
  );
  if (!sameScope(context, binding.scope)) {
    return (
      <Page
        model={unavailableModel(routeId, binding.scope, bindingScopeMismatchReason)}
        onRetry={noop}
      />
    );
  }
  const { model, retry } = useController(binding.controller, binding.scope);
  return <Page model={model} onRetry={retry} />;
}

function normalizeContext(context: DesktopRouteContext): ProjectAgentRouteContext | null {
  const tenantId = nonEmpty(context.tenantId);
  const projectId = nonEmpty(context.projectId);
  return tenantId && projectId ? Object.freeze({ ...context, tenantId, projectId }) : null;
}

function fallbackScope(context: DesktopRouteContext): ProjectAgentScope {
  return Object.freeze({
    authority: 'cloud',
    tenantId: nonEmpty(context.tenantId) ?? 'unavailable',
    projectId: nonEmpty(context.projectId) ?? 'unavailable',
  });
}

function unavailableModel(
  routeId: string,
  scope: ProjectAgentScope,
  reasonCode: string,
): ProjectAgentViewModel {
  return Object.freeze({
    routeId,
    state: 'unavailable',
    scope,
    reasonCode,
    retryVisible: false,
    allowedActions: Object.freeze([]),
    items: Object.freeze([]),
    total: 0,
    metrics: Object.freeze({}),
  });
}

function sameScope(context: ProjectAgentRouteContext, scope: ProjectAgentScope): boolean {
  return context.tenantId === scope.tenantId && context.projectId === scope.projectId;
}

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}
