import { createContext, useContext } from 'react';
import type { CloudMemoryClient } from './cloudMemoryClient';
import type { CloudMemoryUiAuthority } from './cloudMemoryUiAuthority';
import type { ProjectMemoriesClient } from './projectMemoriesClient';

export type CloudMemoryRouteBinding = Readonly<{
  authority: CloudMemoryUiAuthority;
  listClient: ProjectMemoriesClient;
  client?: CloudMemoryClient;
}>;
const CloudMemoryContext = createContext<CloudMemoryRouteBinding | null>(null);
export const CloudMemoryRouteContextProvider = CloudMemoryContext.Provider;
export function useCloudMemoryRouteBinding(): CloudMemoryRouteBinding | null {
  return useContext(CloudMemoryContext);
}
