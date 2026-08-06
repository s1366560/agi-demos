import { useEffect, useSyncExternalStore } from 'react';

import type { ProjectAdministrationScope } from './projectAdministrationClient';
import type { ProjectAdministrationController } from './projectAdministrationController';

export function useProjectAdministrationController(
  controller: ProjectAdministrationController,
  scope: ProjectAdministrationScope,
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
