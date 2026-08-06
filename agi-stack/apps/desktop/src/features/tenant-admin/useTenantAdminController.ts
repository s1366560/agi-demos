import { useEffect, useSyncExternalStore } from 'react';

import type { TenantAdminControllerCore } from './tenantAdminController';
import type { TenantAdminScope } from './tenantAdminHttp';

export function useTenantAdminController<TScope extends TenantAdminScope, TModel>(
  controller: TenantAdminControllerCore<TScope, TModel>,
  scope: TScope,
): Readonly<{ model: TModel; retry: () => void }> {
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useEffect(() => {
    void controller.load(scope);
    return () => controller.cancel();
  }, [
    controller,
    scope.authority,
    scope.tenantId,
    'workspaceId' in scope ? scope.workspaceId : null,
  ]);
  return Object.freeze({ model, retry: () => void controller.retry() });
}
