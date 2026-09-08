import type {
  DesktopRouteModuleLoader,
  DesktopImplementedRouteModule,
} from '../navigation/desktopRouteModule';
import type { ProjectKnowledgeRouteContext } from './projectKnowledgeRouteModule';
import type { ProjectKnowledgeScope } from './projectKnowledgeClient';
import type { ProjectGraphController } from './projectGraphController';
import { PROJECT_GRAPH_ROUTE_ID } from './projectGraphClient';

export type ProjectGraphRouteContext = ProjectKnowledgeRouteContext;
export type ProjectGraphRouteBinding = Readonly<{
  controller: ProjectGraphController;
  scope: ProjectKnowledgeScope;
}>;
export function createProjectGraphRouteModuleLoader(
  options: Readonly<{
    createBinding: (context: ProjectGraphRouteContext) => ProjectGraphRouteBinding;
  }>,
): DesktopRouteModuleLoader {
  if (typeof options.createBinding !== 'function')
    throw new Error('project_graph_route_binding_factory_invalid');
  return async () => {
    const { createProjectGraphRouteSurface } = await import('./ProjectGraphRouteSurface');
    return Object.freeze({
      routeId: PROJECT_GRAPH_ROUTE_ID,
      capability: PROJECT_GRAPH_ROUTE_ID,
      localPolicy: 'native_equivalent',
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      Surface: createProjectGraphRouteSurface(options.createBinding),
    }) satisfies DesktopImplementedRouteModule;
  };
}
