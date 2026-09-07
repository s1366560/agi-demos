import { useEffect, useMemo, type ReactNode } from 'react';

import { useCurrentWebPluginGenerationV2 } from '../../plugins/WebPluginGenerationHostV2';
import { logger } from '../../utils/logger';

import { resolveWebUiSlotAuthorityStateV2 } from './webUiSlotAuthorityProjectionV2';
import { WebUiSlotAuthorityContextV2 } from './webUiSlotAuthorityStateV2';

export function WebUiSlotAuthorityProviderV2({
  children,
  enabled,
}: {
  readonly children: ReactNode;
  readonly enabled: boolean;
}) {
  const generation = useCurrentWebPluginGenerationV2();
  const state = useMemo(
    () => resolveWebUiSlotAuthorityStateV2(generation, enabled),
    [enabled, generation]
  );

  useEffect(() => {
    if (state.status === 'unavailable') {
      logger.error('Web plugin UI slot authority is unavailable', state.error);
    }
  }, [state]);

  return (
    <WebUiSlotAuthorityContextV2.Provider value={state}>
      {children}
    </WebUiSlotAuthorityContextV2.Provider>
  );
}
