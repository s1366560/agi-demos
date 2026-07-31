import { useCallback, useEffect, useSyncExternalStore } from 'react';

import type { TenantTasksScope } from './tenantTasksClient';
import type {
  TenantTasksController,
  TenantTasksViewState,
} from './tenantTasksController';

export const TENANT_TASKS_REFRESH_INTERVAL_MS = 5_000;

export function tenantTasksAutoRefreshAllowed(
  visibilityState: string,
  state: TenantTasksViewState,
  busyAction: string | null,
): boolean {
  return (
    visibilityState === 'visible' &&
    state !== 'loading' &&
    state !== 'scope_switch' &&
    busyAction === null
  );
}

export function useTenantTasksController(
  controller: TenantTasksController,
  scope: TenantTasksScope,
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
  useEffect(() => {
    const interval = window.setInterval(() => {
      const current = controller.getSnapshot();
      if (
        tenantTasksAutoRefreshAllowed(
          document.visibilityState,
          current.state,
          current.busyAction,
        )
      ) {
        void controller.retry();
      }
    }, TENANT_TASKS_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [controller]);
  const retry = useCallback(() => {
    void controller.retry();
  }, [controller]);
  return { model: snapshot, retry };
}
