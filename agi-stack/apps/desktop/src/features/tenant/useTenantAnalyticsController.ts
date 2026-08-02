import { useCallback, useEffect, useMemo, useSyncExternalStore } from 'react';

import type { TenantAnalyticsScope } from './tenantAnalyticsClient';
import type { TenantAnalyticsController } from './tenantAnalyticsController';

export function useTenantAnalyticsController(
  controller: TenantAnalyticsController,
  scope: TenantAnalyticsScope,
) {
  const stableScope = useMemo(
    () =>
      Object.freeze({
        authority: scope.authority,
        tenantId: scope.tenantId,
        period: scope.period,
      }),
    [scope.authority, scope.tenantId, scope.period],
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
