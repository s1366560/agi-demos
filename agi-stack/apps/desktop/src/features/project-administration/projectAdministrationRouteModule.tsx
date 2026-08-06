import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { DesktopRouteContext } from '../navigation/desktopRouteRegistry';
import type { ProjectAdministrationScope } from './projectAdministrationClient';
import type { ProjectAdministrationController } from './projectAdministrationController';
import type { ProjectAdministrationViewModelBase } from './projectAdministrationPresentationModel';

const noop = (): void => {};
export type ProjectAdministrationRouteContext = Readonly<
  DesktopRouteContext & { tenantId: string; projectId: string }
>;
export type ProjectAdministrationRouteBinding = Readonly<{
  controller: ProjectAdministrationController;
  scope: ProjectAdministrationScope;
}>;

export function createProjectAdministrationRouteModuleLoader({
  routeId,
  contextUnavailableReason,
  bindingScopeMismatchReason,
  createBinding,
}: Readonly<{
  routeId: string;
  contextUnavailableReason: string;
  bindingScopeMismatchReason: string;
  createBinding: (
    context: ProjectAdministrationRouteContext,
  ) => ProjectAdministrationRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('project_administration_route_binding_factory_invalid');
  }
  return async () => {
    const [{ ProjectAdministrationPage }, { useProjectAdministrationController }] =
      await Promise.all([
        import('./ProjectAdministrationPage'),
        import('./useProjectAdministrationController'),
      ]);
    function ProjectAdministrationRouteSurface({ context }: DesktopRouteSurfaceProps) {
      const routeContext = normalizeContext(context);
      if (!routeContext) {
        return (
          <ProjectAdministrationPage
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
          Page={ProjectAdministrationPage}
          useController={useProjectAdministrationController}
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
      contentPolicy: 'route_content',
      Surface: ProjectAdministrationRouteSurface,
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
  context: ProjectAdministrationRouteContext;
  createBinding: (
    context: ProjectAdministrationRouteContext,
  ) => ProjectAdministrationRouteBinding;
  bindingScopeMismatchReason: string;
  Page: typeof import('./ProjectAdministrationPage').ProjectAdministrationPage;
  useController: typeof import('./useProjectAdministrationController').useProjectAdministrationController;
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

function normalizeContext(
  context: DesktopRouteContext,
): ProjectAdministrationRouteContext | null {
  const tenantId = nonEmpty(context.tenantId);
  const projectId = nonEmpty(context.projectId);
  return tenantId && projectId ? Object.freeze({ ...context, tenantId, projectId }) : null;
}

function fallbackScope(context: DesktopRouteContext): ProjectAdministrationScope {
  return Object.freeze({
    authority: 'cloud',
    tenantId: nonEmpty(context.tenantId) ?? 'unavailable',
    projectId: nonEmpty(context.projectId) ?? 'unavailable',
  });
}

function unavailableModel(
  routeId: string,
  scope: ProjectAdministrationScope,
  reasonCode: string,
): ProjectAdministrationViewModelBase {
  return Object.freeze({
    routeId,
    state: 'unavailable',
    scope,
    reasonCode,
    retryVisible: false,
    busyAction: null,
    allowedActions: Object.freeze([]),
    items: Object.freeze([]),
  });
}

function sameScope(
  context: ProjectAdministrationRouteContext,
  scope: ProjectAdministrationScope,
): boolean {
  return context.tenantId === scope.tenantId && context.projectId === scope.projectId;
}

function nonEmpty(value: string | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}
