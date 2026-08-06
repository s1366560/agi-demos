import { useCallback, useEffect, useMemo, useSyncExternalStore } from 'react';

import type { ManagementRouteController } from './managementRouteController';
import type { ManagementRoutePresentationModel } from './managementRoutePresentationModel';
import type { ManagementRouteScope } from './managementRouteTypes';

export type ManagementRouteControllerHookState = Readonly<{
  model: ManagementRoutePresentationModel;
  retry: () => void;
}>;

export function useManagementRouteController(
  controller: ManagementRouteController,
  scope: ManagementRouteScope,
): ManagementRouteControllerHookState {
  const stableScope = useMemo<ManagementRouteScope>(
    () =>
      Object.freeze({
        authority: scope.authority,
        tenantId: scope.tenantId,
        projectId: scope.projectId,
      }),
    [scope.authority, scope.projectId, scope.tenantId],
  );
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  const retry = useCallback(() => {
    void controller.retry();
  }, [controller]);

  useEffect(() => {
    void controller.load(stableScope);
    return controller.cancel;
  }, [controller, stableScope]);

  return useMemo(() => ({ model, retry }), [model, retry]);
}
