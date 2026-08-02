import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';

import type { UnifiedRuntimesController } from './unifiedRuntimesController';
import type { UnifiedRuntimesScope } from './unifiedRuntimesTypes';

export const UNIFIED_RUNTIMES_REFRESH_INTERVAL_MS = 15_000;

export function unifiedRuntimesAutoRefreshAllowed(
  visibilityState: string,
): boolean {
  return visibilityState === 'visible';
}

export function useUnifiedRuntimesController(
  controller: UnifiedRuntimesController,
  scope: UnifiedRuntimesScope,
) {
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  const [autoRefresh, setAutoRefresh] = useState(true);

  useEffect(() => {
    void controller.load(scope);
    return () => controller.stop();
  }, [
    controller,
    scope.authority,
    scope.projectId,
    scope.tenantId,
  ]);
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = window.setInterval(() => {
      if (unifiedRuntimesAutoRefreshAllowed(document.visibilityState)) {
        void controller.retry(scope);
      }
    }, UNIFIED_RUNTIMES_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [autoRefresh, controller, scope.authority, scope.projectId, scope.tenantId]);
  const retry = useCallback(() => {
    void controller.retry(scope);
  }, [controller, scope]);

  return { model, retry, autoRefresh, setAutoRefresh };
}
