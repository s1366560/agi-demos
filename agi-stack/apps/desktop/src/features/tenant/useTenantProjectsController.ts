import { useEffect, useSyncExternalStore } from 'react';

import type { TenantProjectsScope } from './tenantProjectsClient';
import type { TenantProjectsController } from './tenantProjectsController';

export function useTenantProjectsController(
  controller: TenantProjectsController,
  scope: TenantProjectsScope,
) {
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useEffect(() => {
    void controller.load(scope);
    return () => controller.stop();
  }, [controller, scope.authority, scope.tenantId]);
  return {
    model,
    retry: controller.retry,
    create: controller.create,
    update: controller.update,
    delete: controller.delete,
  };
}
