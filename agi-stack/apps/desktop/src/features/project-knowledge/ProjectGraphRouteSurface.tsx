import { useLayoutEffect, useMemo, useSyncExternalStore } from 'react';
import type { DesktopRouteSurfaceProps } from '../navigation/desktopRouteModule';
import type { ProjectGraphRouteBinding, ProjectGraphRouteContext } from './projectGraphRouteModule';
import { ProjectGraphPage } from './ProjectGraphPage';
import { useI18n } from '../../i18n';
import './ProjectGraphPage.css';

export function createProjectGraphRouteSurface(
  createBinding: (context: ProjectGraphRouteContext) => ProjectGraphRouteBinding,
) {
  return function ProjectGraphRouteSurface({ context }: DesktopRouteSurfaceProps) {
    const tenantId = context.tenantId?.trim();
    const projectId = context.projectId?.trim();
    if (!tenantId || !projectId)
      return <Unavailable reason="project_graph_route_context_unavailable" />;
    return (
      <BoundGraphRoute
        context={{ ...context, tenantId, projectId }}
        createBinding={createBinding}
      />
    );
  };
}
function BoundGraphRoute({
  context,
  createBinding,
}: Readonly<{
  context: ProjectGraphRouteContext;
  createBinding: (context: ProjectGraphRouteContext) => ProjectGraphRouteBinding;
}>) {
  const binding = useMemo(
    () => createBinding(context),
    [context.tenantId, context.projectId, createBinding],
  );
  if (binding.scope.tenantId !== context.tenantId || binding.scope.projectId !== context.projectId)
    return <Unavailable reason="project_graph_route_binding_scope_mismatch" />;
  return (
    <GraphBinding
      key={`${binding.scope.authority}:${binding.scope.tenantId}:${binding.scope.projectId}`}
      binding={binding}
    />
  );
}
function GraphBinding({ binding }: Readonly<{ binding: ProjectGraphRouteBinding }>) {
  const { controller, scope } = binding;
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useLayoutEffect(() => {
    void controller.load(scope);
    return controller.stop;
  }, [controller, scope.authority, scope.tenantId, scope.projectId]);
  return <ProjectGraphPage model={model} controller={controller} />;
}
function Unavailable({ reason }: Readonly<{ reason: string }>) {
  const { t } = useI18n();
  return (
    <section className="project-graph-page" data-reason-code={reason}>
      <h1>{t('projectGraph.title')}</h1>
      <p>{t('projectGraph.unavailable')}</p>
    </section>
  );
}
