import { createElement } from 'react';
import type {
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import { useNativeMemoriesRouteBinding } from './NativeMemoriesRouteContext';
import {
  createProjectKnowledgeRouteModuleLoader,
  type ProjectKnowledgeRouteBinding,
  type ProjectKnowledgeRouteContext,
} from './projectKnowledgeRouteModule';
import { PROJECT_COMMUNITIES_ROUTE_ID } from './projectCommunitiesClient';

export type ProjectCommunitiesRouteContext = ProjectKnowledgeRouteContext;
export type ProjectCommunitiesRouteBinding = ProjectKnowledgeRouteBinding;
export function createProjectCommunitiesRouteModuleLoader(
  options: Readonly<{
    createBinding: (context: ProjectCommunitiesRouteContext) => ProjectCommunitiesRouteBinding;
  }>,
): DesktopRouteModuleLoader {
  const loadCloud = createProjectKnowledgeRouteModuleLoader({
    routeId: PROJECT_COMMUNITIES_ROUTE_ID,
    contextUnavailableReason: 'project_communities_route_context_unavailable',
    bindingScopeMismatchReason: 'project_communities_route_binding_scope_mismatch',
    ...options,
  });
  return async () => {
    const [cloud, { NativeKnowledgeCommunitiesRouteSurface }] = await Promise.all([
      loadCloud(),
      import('./NativeKnowledgeCommunitiesRouteSurface'),
    ]);
    function CommunitiesRouteSurface(props: DesktopRouteSurfaceProps) {
      const binding = useNativeMemoriesRouteBinding();
      return createElement(
        binding?.authority.scope.authority === 'local'
          ? NativeKnowledgeCommunitiesRouteSurface
          : cloud.Surface,
        props,
      );
    }
    return Object.freeze({ ...cloud, Surface: CommunitiesRouteSurface });
  };
}
