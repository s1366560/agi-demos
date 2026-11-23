import { useCallback, useEffect, useSyncExternalStore } from 'react';

import type { RuntimeClustersController } from './runtimeClustersController';
import type {
  RuntimeClustersQuery,
  RuntimeClustersScope,
} from './runtimeClustersTypes';

export function useRuntimeClustersController(
  controller: RuntimeClustersController,
  scope: RuntimeClustersScope,
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
    (query: RuntimeClustersQuery) => {
      void controller.setQuery(query);
    },
    [controller],
  );
  const setFilters = useCallback(
    (query: RuntimeClustersQuery) => {
      void controller.setFilters(query);
    },
    [controller],
  );
  const inspectHealth = useCallback(
    (clusterId: string) => controller.inspectHealth(clusterId),
    [controller],
  );
  const closeHealth = useCallback(
    () => controller.closeHealth(),
    [controller],
  );
  return { model, retry, setQuery, setFilters, inspectHealth, closeHealth };
}
