import { useCallback, useEffect, useSyncExternalStore } from 'react';

import type { TenantManagementControllerCore } from './tenantManagementController';
import type { TenantManagementScope } from './tenantManagementHttp';

export function useTenantManagementController<
  TScope extends TenantManagementScope,
  TModel,
>(controller: TenantManagementControllerCore<TScope, TModel>, scope: TScope) {
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useEffect(() => {
    void controller.load(scope);
    return () => controller.cancel();
  }, [controller, scope]);
  const retry = useCallback(() => {
    void controller.retry();
  }, [controller]);
  return Object.freeze({ model, retry });
}
