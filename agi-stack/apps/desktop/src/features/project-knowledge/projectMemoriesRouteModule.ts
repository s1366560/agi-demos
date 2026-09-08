import { useCloudMemoryRouteBinding } from './CloudMemoryRouteContext';
import { createElement } from 'react';

import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import {
  createProjectKnowledgeRouteModuleLoader,
  type ProjectKnowledgeRouteBinding,
  type ProjectKnowledgeRouteContext,
} from './projectKnowledgeRouteModule';
import { PROJECT_MEMORIES_ROUTE_ID } from './projectMemoriesClient';
import { useNativeMemoriesRouteBinding } from './NativeMemoriesRouteContext';
import type { DesktopRouteSurfaceProps } from '../navigation/desktopRouteModule';

export type ProjectMemoriesRouteContext = ProjectKnowledgeRouteContext;
export type ProjectMemoriesRouteBinding = ProjectKnowledgeRouteBinding;
export function createProjectMemoriesRouteModuleLoader(
  options: Readonly<{
    createBinding: (context: ProjectMemoriesRouteContext) => ProjectMemoriesRouteBinding;
  }>,
): DesktopRouteModuleLoader {
  const loadCloud = createProjectKnowledgeRouteModuleLoader({
    routeId: PROJECT_MEMORIES_ROUTE_ID,
    contextUnavailableReason: 'project_memories_route_context_unavailable',
    bindingScopeMismatchReason: 'project_memories_route_binding_scope_mismatch',
    ...options,
  });
  return async () => {
    const [cloud, { NativeMemoriesRouteSurface }, { CloudMemoryRouteSurface }] = await Promise.all([
      loadCloud(),
      import('./NativeMemoriesRouteSurface'),
      import('./CloudMemoryRouteSurface'),
    ]);
    function MemoriesRouteSurface(props: DesktopRouteSurfaceProps) {
      const binding = useNativeMemoriesRouteBinding();
      const cloudBinding = useCloudMemoryRouteBinding();
      return createElement(
        binding?.authority.scope.authority === 'local'
          ? NativeMemoriesRouteSurface
          : cloudBinding
            ? CloudMemoryRouteSurface
            : cloud.Surface,
        props,
      );
    }
    return Object.freeze({ ...cloud, Surface: MemoriesRouteSurface });
  };
}
