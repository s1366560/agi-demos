import type { NativeCloudAuthClient } from '../../api/nativeCloudAuthClient';
import type { NativeKnowledgeCloudConnectionClient } from './nativeKnowledgeCloudConnectionClient';
import type { NativeKnowledgeProcessingInputsClient } from './nativeKnowledgeProcessingInputs';
import { createContext, useContext } from 'react';

import type {
  NativeKnowledgeClient,
  NativeKnowledgeProcessingClient,
  NativeKnowledgeProcessingCommandClient,
} from './nativeKnowledgeContracts';
import type { NativeMemoriesAuthority } from '@business/knowledge/ui/desktop/project-knowledge/nativeMemoriesController';
import type { ProjectMemoriesClient } from '@business/knowledge/ui/desktop/project-knowledge/projectMemoriesClient';

export type NativeMemoriesRouteBinding = Readonly<{
  authority: NativeMemoriesAuthority;
  connectionClient?: NativeKnowledgeCloudConnectionClient;
  cloudAuthClient?: NativeCloudAuthClient | null;
  client: NativeKnowledgeClient;
  listClient: ProjectMemoriesClient;
  processingClient?: NativeKnowledgeProcessingClient;
  processingInputsClient?: NativeKnowledgeProcessingInputsClient;
  processingCommandClient?: NativeKnowledgeProcessingCommandClient;
}>;
const NativeMemoriesContext = createContext<NativeMemoriesRouteBinding | null>(null);
export const NativeMemoriesRouteContextProvider = NativeMemoriesContext.Provider;

export function useNativeMemoriesRouteBinding(): NativeMemoriesRouteBinding | null {
  return useContext(NativeMemoriesContext);
}
