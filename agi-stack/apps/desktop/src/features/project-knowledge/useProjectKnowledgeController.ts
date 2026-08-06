import { useEffect, useSyncExternalStore } from 'react';

import type { ProjectKnowledgeScope } from './projectKnowledgeClient';
import type { ProjectKnowledgeController } from './projectKnowledgeController';

export function useProjectKnowledgeController(
  controller: ProjectKnowledgeController,
  scope: ProjectKnowledgeScope,
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
