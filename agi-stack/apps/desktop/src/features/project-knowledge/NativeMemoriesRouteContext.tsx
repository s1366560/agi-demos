import { createContext, useContext } from 'react';

import type {
  NativeKnowledgeClient,
  NativeKnowledgeProcessingClient,
  NativeKnowledgeProcessingCommandClient,
} from './nativeKnowledgeContracts';
import type { NativeMemoriesAuthority } from './nativeMemoriesController';
import type { ProjectMemoriesClient } from './projectMemoriesClient';

export type NativeMemoriesRouteBinding = Readonly<{
  authority: NativeMemoriesAuthority;
  client: NativeKnowledgeClient;
  listClient: ProjectMemoriesClient;
  processingClient?: NativeKnowledgeProcessingClient;
  processingCommandClient?: NativeKnowledgeProcessingCommandClient;
}>;
const NativeMemoriesContext = createContext<NativeMemoriesRouteBinding | null>(null);
export const NativeMemoriesRouteContextProvider = NativeMemoriesContext.Provider;

export function useNativeMemoriesRouteBinding(): NativeMemoriesRouteBinding | null {
  return useContext(NativeMemoriesContext);
}
