import { useEffect, useMemo, type ReactNode } from 'react';

import { useCurrentWebPluginGenerationV2 } from '../../plugins/WebPluginGenerationHostV2';
import { logger } from '../../utils/logger';

import {
  resolveWebNavigationAuthorityStateV2,
  WebNavigationAuthorityContextV2,
} from './webNavigationAuthorityStateV2';
import { useWebRouteAuthorityV2 } from './webRouteAuthorityStateV2';

export function WebNavigationAuthorityProviderV2({
  children,
  enabled,
}: {
  readonly children: ReactNode;
  readonly enabled: boolean;
}) {
  const generation = useCurrentWebPluginGenerationV2();
  const routeAuthority = useWebRouteAuthorityV2();
  const state = useMemo(
    () =>
      resolveWebNavigationAuthorityStateV2(
        generation,
        routeAuthority.routeKeys,
        enabled,
        routeAuthority.status === 'ready',
        routeAuthority.status === 'unavailable' ? routeAuthority.error : undefined
      ),
    [enabled, generation, routeAuthority]
  );

  useEffect(() => {
    if (state.status === 'unavailable') {
      logger.error('Web plugin navigation authority is unavailable', state.error);
    }
  }, [state]);

  return (
    <WebNavigationAuthorityContextV2.Provider value={state}>
      {children}
    </WebNavigationAuthorityContextV2.Provider>
  );
}
