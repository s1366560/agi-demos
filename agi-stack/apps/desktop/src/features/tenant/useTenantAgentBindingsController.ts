import { useEffect, useSyncExternalStore } from 'react';

import type { TenantAgentBindingsScope } from './tenantAgentBindingsClient';
import type { TenantAgentBindingsController } from './tenantAgentBindingsController';

export function useTenantAgentBindingsController(
  controller: TenantAgentBindingsController,
  scope: TenantAgentBindingsScope,
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
  };
}
