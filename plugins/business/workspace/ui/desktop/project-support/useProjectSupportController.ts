import { useEffect, useSyncExternalStore } from 'react';

import type {
  ProjectSupportController,
  ProjectSupportViewModel,
} from './projectSupportController';
import type { ProjectSupportScope } from './projectSupportTypes';

export function useProjectSupportController(
  controller: ProjectSupportController,
  scope: ProjectSupportScope,
): Readonly<{
  model: ProjectSupportViewModel;
  retry: () => Promise<void>;
}> {
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useEffect(() => {
    void controller.load(scope);
    return controller.stop;
  }, [controller, scope.authority, scope.tenantId, scope.projectId]);
  return { model, retry: controller.retry };
}
