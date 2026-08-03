import { useEffect, useSyncExternalStore } from 'react';

import type {
  TenantAgentDashboardController,
  TenantAgentDashboardViewModel,
} from './tenantAgentDashboardController';
import type { TenantAgentDashboardScope } from './tenantAgentDashboardClient';

export function useTenantAgentDashboardController(
  controller: TenantAgentDashboardController,
  scope: TenantAgentDashboardScope,
): Readonly<{ model: TenantAgentDashboardViewModel; retry: () => void }> {
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useEffect(() => {
    void controller.load(scope).catch(() => undefined);
    return () => controller.cancel();
  }, [controller, scope.authority, scope.tenantId]);
  return {
    model,
    retry: () => {
      void controller.retry().catch(() => undefined);
    },
  };
}
