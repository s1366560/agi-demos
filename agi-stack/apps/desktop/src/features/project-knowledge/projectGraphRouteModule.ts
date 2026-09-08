import { createElement } from 'react';
import { useNativeMemoriesRouteBinding } from './NativeMemoriesRouteContext';
import type {
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
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
    const { NativeKnowledgeGraphRouteSurface } = await import('./NativeKnowledgeGraphRouteSurface');
    const CloudSurface = createProjectGraphRouteSurface(options.createBinding);
    function GraphRouteSurface(props: DesktopRouteSurfaceProps) {
      const binding = useNativeMemoriesRouteBinding();
      return createElement(
        binding?.authority.scope.authority === 'local'
          ? NativeKnowledgeGraphRouteSurface
          : CloudSurface,
        props,
      );
    }
    return Object.freeze({
      routeId: PROJECT_GRAPH_ROUTE_ID,
      capability: PROJECT_GRAPH_ROUTE_ID,
      localPolicy: 'native_equivalent',
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      Surface: GraphRouteSurface,
    }) satisfies DesktopImplementedRouteModule;
  };
}
