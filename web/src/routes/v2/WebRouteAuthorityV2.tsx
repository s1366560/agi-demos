import { useEffect, useMemo, type ReactNode } from 'react';

import { useCurrentWebPluginGenerationV2 } from '../../plugins/WebPluginGenerationHostV2';
import { logger } from '../../utils/logger';

import {
  resolveWebRouteAuthorityStateV2,
  WebRouteAuthorityContextV2,
  type WebRouteAuthorityStateV2,
} from './webRouteAuthorityStateV2';

export function WebRouteAuthorityProviderV2({
  children,
  enabled,
}: {
  readonly children: ReactNode | ((state: WebRouteAuthorityStateV2) => ReactNode);
  readonly enabled: boolean;
}) {
  const generation = useCurrentWebPluginGenerationV2();
  const state = useMemo(
    () => resolveWebRouteAuthorityStateV2(generation, enabled),
    [enabled, generation]
  );

  useEffect(() => {
    if (state.status === 'unavailable') {
      logger.error('Web plugin route authority is unavailable', state.error);
    }
  }, [state]);

  const content = typeof children === 'function' ? children(state) : children;
  return (
    <WebRouteAuthorityContextV2.Provider value={state}>
      {content}
    </WebRouteAuthorityContextV2.Provider>
  );
}
