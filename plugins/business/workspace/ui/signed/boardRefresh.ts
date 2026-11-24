import { useEffect } from 'react';
import { useWorkspaceStore } from '../web/stores/workspace';

export function useBlackboardSSE(
  workspace: string | null,
  scope?: { tenantId?: string; projectId?: string },
) {
  const tenant = scope?.tenantId;
  const project = scope?.projectId;
  useEffect(() => {
    if (!workspace || !tenant || !project) return;
    const controller = new AbortController();
    let last: number | undefined;
    let timer: ReturnType<typeof setTimeout>;
    async function check() {
      try {
        const result = (await window.memstack.invoke(
          'blackboard-read',
          { resource: 'collaboration/authority', workspace_id: workspace },
          { signal: controller.signal },
        )) as { data: { revision: number } };
        if (controller.signal.aborted) return;
        if (last !== undefined && last !== result.data.revision)
          await useWorkspaceStore.getState().loadWorkspaceSurface(tenant!, project!, workspace!);
        last = result.data.revision;
      } catch {
        /* Recheck on the next interval while this workspace remains mounted. */
      }
      if (!controller.signal.aborted) timer = setTimeout(check, 3000);
    }
    void check();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [workspace, tenant, project]);
}
export const unifiedEventService = {
  onStatusChange(listener: (status: string) => void) {
    const online = () => listener('connected'),
      offline = () => listener('disconnected');
    window.addEventListener('online', online);
    window.addEventListener('offline', offline);
    listener(navigator.onLine ? 'connected' : 'disconnected');
    return () => {
      window.removeEventListener('online', online);
      window.removeEventListener('offline', offline);
    };
  },
};
