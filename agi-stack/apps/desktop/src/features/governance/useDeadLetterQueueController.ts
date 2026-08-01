import { useCallback, useEffect, useSyncExternalStore } from 'react';

import type { DeadLetterQueueScope } from './deadLetterQueueClient';
import type { DeadLetterQueueController } from './deadLetterQueueController';

export const DEAD_LETTER_QUEUE_REFRESH_INTERVAL_MS = 30_000;

export function deadLetterQueueAutoRefreshAllowed(
  visibilityState: string,
  busyAction: string | null,
): boolean {
  return visibilityState === 'visible' && busyAction === null;
}

export function useDeadLetterQueueController(
  controller: DeadLetterQueueController,
  scope: DeadLetterQueueScope,
) {
  const snapshot = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useEffect(() => {
    void controller.load(scope);
    return () => controller.stop();
  }, [controller, scope.authority, scope.tenantId]);
  useEffect(() => {
    const interval = window.setInterval(() => {
      const current = controller.getSnapshot();
      if (deadLetterQueueAutoRefreshAllowed(document.visibilityState, current.busyAction)) {
        void controller.retry();
      }
    }, DEAD_LETTER_QUEUE_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [controller]);
  const retry = useCallback(() => {
    void controller.retry();
  }, [controller]);
  return { model: snapshot, retry };
}
