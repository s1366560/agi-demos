import { createContext, useContext, type PropsWithChildren } from 'react';

import type { RuntimeGenerationV2 } from '@agistack/plugin-runtime';

import { useWebPluginGenerationV2 } from './webPluginGenerationV2';

const WebPluginGenerationContextV2 = createContext<RuntimeGenerationV2 | undefined>(undefined);

export function WebPluginGenerationHostV2({
  enabled,
  children,
}: PropsWithChildren<{ readonly enabled: boolean }>) {
  const generation = useWebPluginGenerationV2(enabled);
  return (
    <WebPluginGenerationContextV2.Provider value={generation}>
      {children}
    </WebPluginGenerationContextV2.Provider>
  );
}

export function useCurrentWebPluginGenerationV2(): RuntimeGenerationV2 | undefined {
  return useContext(WebPluginGenerationContextV2);
}
