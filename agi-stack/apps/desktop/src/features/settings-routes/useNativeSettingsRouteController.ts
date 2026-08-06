import { useCallback, useEffect, useSyncExternalStore } from 'react';

import type { NativeSettingsRouteController } from './nativeSettingsRouteController';

export function useNativeSettingsRouteController<TScope, TModel>(
  controller: NativeSettingsRouteController<TScope, TModel>,
  scope: TScope,
) {
  const model = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useEffect(() => {
    void controller.load(scope);
    return controller.cancel;
  }, [controller, scope]);
  return {
    model,
    retry: useCallback(() => void controller.retry(), [controller]),
  };
}
