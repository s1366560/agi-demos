import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';

import type { RuntimePoolScope } from './runtimePoolClient';
import type { RuntimePoolController } from './runtimePoolController';

export const RUNTIME_POOL_REFRESH_INTERVAL_MS = 15_000;

export function runtimePoolAutoRefreshAllowed(
  visibilityState: string,
  busyInstanceKey: string | null,
): boolean {
  return visibilityState === 'visible' && busyInstanceKey === null;
}

export function useRuntimePoolController(
  controller: RuntimePoolController,
  scope: RuntimePoolScope,
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
  }, [controller, scope.authority, scope.tenantId]);
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = window.setInterval(() => {
      const current = controller.getSnapshot();
      if (
        runtimePoolAutoRefreshAllowed(
          document.visibilityState,
          current.busyInstanceKey,
        )
      ) {
        void controller.retry();
      }
    }, RUNTIME_POOL_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [autoRefresh, controller]);
  const retry = useCallback(() => {
    void controller.retry();
  }, [controller]);

  return { model, retry, autoRefresh, setAutoRefresh };
}
