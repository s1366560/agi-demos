import { useCallback, useEffect, useSyncExternalStore } from 'react';

import type { ProjectWorkspacesScope } from './projectWorkspacesClient';
import type { ProjectWorkspacesController } from './projectWorkspacesController';

export function useProjectWorkspacesController(
  controller: ProjectWorkspacesController,
  scope: ProjectWorkspacesScope,
) {
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useEffect(() => {
    void controller.load(scope);
    return () => controller.stop();
  }, [controller, scope.authority, scope.projectId, scope.tenantId]);
  return {
    model,
    retry: useCallback(() => void controller.retry(), [controller]),
  };
}
