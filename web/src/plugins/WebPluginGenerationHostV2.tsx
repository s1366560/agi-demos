import { createContext, useContext, type PropsWithChildren } from 'react';

import type {
  RendererPluginGenerationStateV2,
  RuntimeGenerationV2,
} from '@agistack/plugin-runtime';

import { useWebPluginGenerationV2 } from './webPluginGenerationV2';

const WebPluginGenerationContextV2 = createContext<RuntimeGenerationV2 | undefined>(undefined);
const WebPluginGenerationStateContextV2 = createContext<
  RendererPluginGenerationStateV2 | undefined
>(undefined);

export function WebPluginGenerationHostV2({
  enabled,
  children,
}: PropsWithChildren<{ readonly enabled: boolean }>) {
  const state = useWebPluginGenerationV2(enabled);
  return (
    <WebPluginGenerationStateContextV2.Provider value={state}>
      <WebPluginGenerationContextV2.Provider value={state.generation}>
        {children}
      </WebPluginGenerationContextV2.Provider>
    </WebPluginGenerationStateContextV2.Provider>
  );
}

export function useCurrentWebPluginGenerationV2(): RuntimeGenerationV2 | undefined {
  return useContext(WebPluginGenerationContextV2);
}

export function useCurrentWebPluginGenerationStateV2():
  | RendererPluginGenerationStateV2
  | undefined {
  return useContext(WebPluginGenerationStateContextV2);
}
