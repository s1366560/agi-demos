import { useCallback, useEffect, useMemo, useSyncExternalStore } from 'react';

import type { TenantOverviewScope } from './tenantOverviewClient';
import type { TenantOverviewController } from './tenantOverviewController';

export function useTenantOverviewController(
  controller: TenantOverviewController,
  scope: TenantOverviewScope,
) {
  const stableScope = useMemo(
    () => Object.freeze({ authority: scope.authority, tenantId: scope.tenantId }),
    [scope.authority, scope.tenantId],
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
