import { useCallback, useEffect, useSyncExternalStore } from 'react';

import type { RuntimeInstancesController } from './runtimeInstancesController';
import type {
  RuntimeInstancesQuery,
  RuntimeInstancesScope,
} from './runtimeInstancesTypes';

export function useRuntimeInstancesController(
  controller: RuntimeInstancesController,
  scope: RuntimeInstancesScope,
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
  const retry = useCallback(() => {
    void controller.retry();
  }, [controller]);
  const setQuery = useCallback(
    (query: RuntimeInstancesQuery) => {
      void controller.setQuery(query);
    },
    [controller],
  );
  const restart = useCallback(
    (instanceId: string) => controller.restart(instanceId),
    [controller],
  );
  const deleteInstance = useCallback(
    (instanceId: string) => controller.delete(instanceId),
    [controller],
  );
  return { model, retry, setQuery, restart, deleteInstance };
}
