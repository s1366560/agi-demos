import {desktopApiCredential,desktopLaunchCapability} from '../../api/client';
import {desktopApiFetch} from '../../api/cloudRequestBroker';
import type {DesktopRuntimeConfig} from '../../types';
import {createWorkspaceSurfaceClient} from '@business/workspace/ui/desktop/workspace/workspaceSurfaceClient';
export {WorkspaceCollaborationContractError, WORKSPACE_HTTP_MUTATION_ACTIONS} from '@business/workspace/ui/desktop/workspace/workspaceSurfaceClient';
export function createHttpWorkspaceCollaborationClient(config: DesktopRuntimeConfig) {
  const runtime = Object.freeze({...config});
  return createWorkspaceSurfaceClient({
    ...runtime, workspaceId: runtime.apiBaseUrl.trim() ? runtime.workspaceId : '',
    request(path, init) {
      const headers=new Headers(init.headers);
      const credential=desktopApiCredential(runtime);
      if(credential) headers.set('Authorization','Bearer '+credential);
      const launch=desktopLaunchCapability(runtime);
      if(launch) headers.set('X-Agistack-Launch',launch);
      return desktopApiFetch(runtime,path,{...init,headers});
    }
  });
}
