import { useCallback, useEffect, useSyncExternalStore } from 'react';

import type { ProjectBlackboardScope } from './projectBlackboardClient';
import type { ProjectBlackboardController } from './projectBlackboardController';

export function useProjectBlackboardController(
  controller: ProjectBlackboardController,
  scope: ProjectBlackboardScope,
) {
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useEffect(() => {
    void controller.load(scope);
    return () => controller.stop();
  }, [controller, scope.authority, scope.projectId, scope.tenantId, scope.workspaceId]);
  return {
    model,
    retry: useCallback(() => void controller.retry(), [controller]),
  };
}
