import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { ProjectKnowledgeScope } from './projectKnowledgeClient';
import type { ProjectKnowledgeController } from './projectKnowledgeController';
import type { ProjectKnowledgeViewModel } from './projectKnowledgePresentationModel';

const noop = (): void => {};
export type ProjectKnowledgeRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string; projectId: string }
>;
export type ProjectKnowledgeRouteBinding = Readonly<{
  controller: ProjectKnowledgeController;
  scope: ProjectKnowledgeScope;
}>;

export function createProjectKnowledgeRouteModuleLoader({
  routeId,
  contextUnavailableReason,
  bindingScopeMismatchReason,
  createBinding,
}: Readonly<{
  routeId: string;
  contextUnavailableReason: string;
  bindingScopeMismatchReason: string;
  createBinding: (context: ProjectKnowledgeRouteContext) => ProjectKnowledgeRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('project_knowledge_route_binding_factory_invalid');
  }
  return async () => {
    const [{ ProjectKnowledgePage }, { useProjectKnowledgeController }] = await Promise.all([
      import('./ProjectKnowledgePage'),
      import('./useProjectKnowledgeController'),
    ]);
    function ProjectKnowledgeRouteSurface({ context }: DesktopRouteSurfaceProps) {
      const routeContext = normalizeContext(context);
      if (!routeContext) {
        return (
          <ProjectKnowledgePage
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
          Page={ProjectKnowledgePage}
          useController={useProjectKnowledgeController}
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
      Surface: ProjectKnowledgeRouteSurface,
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
  context: ProjectKnowledgeRouteContext;
  createBinding: (context: ProjectKnowledgeRouteContext) => ProjectKnowledgeRouteBinding;
  bindingScopeMismatchReason: string;
  Page: typeof import('./ProjectKnowledgePage').ProjectKnowledgePage;
  useController: typeof import('./useProjectKnowledgeController').useProjectKnowledgeController;
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

function normalizeContext(context: DesktopRouteContext): ProjectKnowledgeRouteContext | null {
  const tenantId = nonEmpty(context.tenantId);
  const projectId = nonEmpty(context.projectId);
  return tenantId && projectId ? Object.freeze({ ...context, tenantId, projectId }) : null;
}

function fallbackScope(context: DesktopRouteContext): ProjectKnowledgeScope {
  return Object.freeze({
    authority: 'cloud',
    tenantId: nonEmpty(context.tenantId) ?? 'unavailable',
    projectId: nonEmpty(context.projectId) ?? 'unavailable',
  });
}

function unavailableModel(
  routeId: string,
  scope: ProjectKnowledgeScope,
  reasonCode: string,
): ProjectKnowledgeViewModel {
  return Object.freeze({
    routeId,
    state: 'unavailable',
    scope,
    reasonCode,
    retryVisible: false,
    allowedActions: Object.freeze([]),
    items: Object.freeze([]),
    total: 0,
  });
}

function sameScope(context: ProjectKnowledgeRouteContext, scope: ProjectKnowledgeScope): boolean {
  return context.tenantId === scope.tenantId && context.projectId === scope.projectId;
}

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}
