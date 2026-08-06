import { useEffect, useSyncExternalStore } from 'react';

import type { ProjectAgentScope } from './projectAgentClient';
import type { ProjectAgentController } from './projectAgentController';

export function useProjectAgentController(
  controller: ProjectAgentController,
  scope: ProjectAgentScope,
) {
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useEffect(() => {
    void controller.load(scope);
    return controller.stop;
  }, [controller, scope.authority, scope.projectId, scope.tenantId]);
  return Object.freeze({ model, retry: controller.retry });
}
