import { useEffect, useMemo, useSyncExternalStore } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { ProjectKnowledgeScope } from '../project-knowledge/projectKnowledgeClient';
import { ProjectPlaybooksPage } from './ProjectPlaybooksPage';
import type {
  ProjectPlaybooksController,
  ProjectPlaybooksViewModel,
} from './projectPlaybooksController';
import { PROJECT_PLAYBOOKS_ROUTE_ID } from './projectPlaybooksClient';
import type { ProjectPlaybooksEventSource } from './projectPlaybooksEventSource';

export type ProjectPlaybooksRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string; projectId: string }
>;
export type ProjectPlaybooksRouteBinding = Readonly<{
  controller: ProjectPlaybooksController;
  events: ProjectPlaybooksEventSource;
  scope: ProjectKnowledgeScope;
}>;

export function createProjectPlaybooksRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding(context: ProjectPlaybooksRouteContext): ProjectPlaybooksRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('project_playbooks_route_binding_factory_invalid');
  }
  return async () => {
    function ProjectPlaybooksSurface({ context }: DesktopRouteSurfaceProps) {
      const routeContext = normalizeContext(context);
      if (!routeContext) {
        return (
          <ProjectPlaybooksPage
            model={unavailableModel(
              fallbackScope(context),
              'project_playbooks_route_context_unavailable',
            )}
            onRetry={() => undefined}
          />
        );
      }
      return <BoundProjectPlaybooksRoute context={routeContext} createBinding={createBinding} />;
    }
    return Object.freeze({
      routeId: PROJECT_PLAYBOOKS_ROUTE_ID,
      capability: PROJECT_PLAYBOOKS_ROUTE_ID,
      localPolicy: 'cloud_only',
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      contentPolicy: 'route_content',
      Surface: ProjectPlaybooksSurface,
    }) satisfies DesktopImplementedRouteModule;
  };
}

function BoundProjectPlaybooksRoute({
  context,
  createBinding,
}: Readonly<{
  context: ProjectPlaybooksRouteContext;
  createBinding(context: ProjectPlaybooksRouteContext): ProjectPlaybooksRouteBinding;
}>) {
  const binding = useMemo(
    () => createBinding(context),
    [context.tenantId, context.projectId, createBinding],
  );
  if (!sameScope(context, binding.scope)) {
    return (
      <ProjectPlaybooksPage
        model={unavailableModel(binding.scope, 'project_playbooks_route_binding_scope_mismatch')}
        onRetry={() => undefined}
      />
    );
  }
  return <ControllerSurface binding={binding} />;
}

function ControllerSurface({ binding }: Readonly<{ binding: ProjectPlaybooksRouteBinding }>) {
  const model = useSyncExternalStore(
    binding.controller.subscribe,
    binding.controller.getSnapshot,
    binding.controller.getSnapshot,
  );
  useEffect(() => {
    const unsubscribe = binding.events.subscribe(binding.scope, () => {
      void binding.controller.retry();
    });
    void binding.controller.load(binding.scope);
    return () => {
      unsubscribe();
      binding.controller.stop();
    };
  }, [
    binding.controller,
    binding.events,
    binding.scope.tenantId,
    binding.scope.projectId,
  ]);
  return <ProjectPlaybooksPage model={model} onRetry={() => void binding.controller.retry()} />;
}

function normalizeContext(context: DesktopRouteContext): ProjectPlaybooksRouteContext | null {
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
  scope: ProjectKnowledgeScope,
  reasonCode: string,
): ProjectPlaybooksViewModel {
  return Object.freeze({
    routeId: PROJECT_PLAYBOOKS_ROUTE_ID,
    state: 'unavailable',
    scope,
    reasonCode,
    retryVisible: false,
    allowedActions: Object.freeze([]),
    playbooks: Object.freeze([]),
    verdicts: Object.freeze([]),
  });
}

function sameScope(context: ProjectPlaybooksRouteContext, scope: ProjectKnowledgeScope): boolean {
  return (
    scope.authority === 'cloud' &&
    context.tenantId === scope.tenantId &&
    context.projectId === scope.projectId
  );
}

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}
