import { useCallback, useEffect, useSyncExternalStore } from 'react';

import type { TenantWorkspacesScope } from '@business/workspace/ui/desktop/tenant/tenantWorkspacesClient';
import type { TenantWorkspacesController } from '@business/workspace/ui/desktop/tenant/tenantWorkspacesController';

export function useTenantWorkspacesController(
  controller: TenantWorkspacesController,
  scope: TenantWorkspacesScope,
) {
  const snapshot = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useEffect(() => {
    void controller.load(scope);
    return () => controller.stop();
  }, [controller, scope.authority, scope.tenantId, scope.projectId]);
  const retry = useCallback(() => {
    void controller.retry();
  }, [controller]);
  return { model: snapshot, retry };
}
