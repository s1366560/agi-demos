import { useCallback, useEffect, useSyncExternalStore } from 'react';

import type { RuntimeDeploymentsController } from './runtimeDeploymentsController';
import type {
  RuntimeDeploymentsQuery,
  RuntimeDeploymentsScope,
} from './runtimeDeploymentsTypes';

export function useRuntimeDeploymentsController(
  controller: RuntimeDeploymentsController,
  scope: RuntimeDeploymentsScope,
) {
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useEffect(() => {
    void controller.load(scope);
    return () => controller.stop();
  }, [
    controller,
    scope.authority,
    scope.tenantId,
    scope.instanceId,
  ]);
  const retry = useCallback(() => {
    void controller.retry();
  }, [controller]);
  const setQuery = useCallback(
    (query: RuntimeDeploymentsQuery) => {
      void controller.setQuery(query);
    },
    [controller],
  );
  const inspect = useCallback(
    (deploymentId: string) => controller.inspect(deploymentId),
    [controller],
  );
  const closeDetail = useCallback(
    () => controller.closeDetail(),
    [controller],
  );
  const reconnectProgress = useCallback(
    () => controller.reconnectProgress(),
    [controller],
  );
  return {
    model,
    retry,
    setQuery,
    inspect,
    closeDetail,
    reconnectProgress,
  };
}
