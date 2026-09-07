import { createContext, useContext, type PropsWithChildren } from 'react';

import { useWebPluginGenerationV2 } from './webPluginGenerationV2';
import {
  WebRendererCompositionContextV2,
  type WebRendererCompositionPortV2,
} from './webRendererCompositionPortV2';

import type {
  RendererPluginGenerationStateV2,
  RuntimeGenerationV2,
} from '@agistack/plugin-runtime';

const WebPluginGenerationContextV2 = createContext<RuntimeGenerationV2 | undefined>(undefined);
const WebPluginGenerationStateContextV2 = createContext<
  RendererPluginGenerationStateV2 | undefined
>(undefined);

export function WebPluginGenerationHostV2({
  composition,
  enabled,
  children,
}: PropsWithChildren<{
  readonly composition: WebRendererCompositionPortV2;
  readonly enabled: boolean;
}>) {
  const state = useWebPluginGenerationV2(enabled);
  return (
    <WebRendererCompositionContextV2.Provider value={composition}>
      <WebPluginGenerationStateContextV2.Provider value={state}>
        <WebPluginGenerationContextV2.Provider value={state.generation}>
          {children}
        </WebPluginGenerationContextV2.Provider>
      </WebPluginGenerationStateContextV2.Provider>
    </WebRendererCompositionContextV2.Provider>
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
