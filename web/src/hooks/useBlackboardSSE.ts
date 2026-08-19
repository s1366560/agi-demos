import { useEffect } from 'react';

import { useAuthStore } from '@/stores/auth';
import { useWorkspaceStore } from '@/stores/workspace';

import { unifiedEventService } from '@/services/unifiedEventService';

import { classifyWorkspaceEventType } from '@/components/blackboard/blackboardSurfaceContract';

/**
 * Subscribes to SSE events for a given workspace and routes them
 * to the appropriate workspace store handlers.
 *
 * The bridge subscribes to Redis streams with "$" (new entries only), so
 * events published between the initial surface fetch and the subscription
 * going live are lost. When the backend acknowledges the subscription, the
 * unified event service replays it as a synthetic `workspace_subscribed`
 * event, which triggers a surface refetch to reconcile the gap. `scope`
 * provides the tenant/project ids needed for that refetch.
 */
export function useBlackboardSSE(
  workspaceId: string | null,
  scope?: { tenantId?: string | undefined; projectId?: string | undefined }
): void {
  const token = useAuthStore((state) => state.token);
  const tenantId = scope?.tenantId;
  const projectId = scope?.projectId;

  useEffect(() => {
    if (!workspaceId || !token) {
      return;
    }

    const store = useWorkspaceStore.getState();
    const unsubscribe = unifiedEventService.subscribeWorkspace(workspaceId, (event) => {
      const type = event.type;
      const data = event.data as Record<string, unknown>;

      if (type === 'workspace_subscribed') {
        // The subscription is live; refetch the authoritative surface so
        // events missed before it are reconciled.
        if (data.workspace_id === workspaceId && tenantId && projectId) {
          store.loadWorkspaceSurface(tenantId, projectId, workspaceId).catch(() => {
            // Load failure is exposed via state.error.
          });
        }
        return;
      }

      const channel = classifyWorkspaceEventType(type);

      switch (channel) {
        case 'presence':
          store.handlePresenceEvent({ type, data });
          break;
        case 'agent_status':
          store.handleAgentStatusEvent({ type, data });
          break;
        case 'task':
          store.handleTaskEvent({ type, data });
          break;
        case 'plan':
          store.handlePlanEvent({ type, data });
          break;
        case 'blackboard':
          store.handleBlackboardEvent({ type, data });
          break;
        case 'chat':
          store.handleChatEvent({ type, data });
          break;
        case 'member':
          store.handleMemberEvent({ type, data });
          break;
        case 'lifecycle':
          store.handleWorkspaceLifecycleEvent({ type, data });
          break;
        case 'agent_binding':
          store.handleAgentBindingEvent({ type, data });
          break;
        case 'topology':
          store.handleTopologyEvent({ type, data });
          break;
        case 'ignore':
          break;
      }
    });

    return () => {
      unsubscribe();
    };
  }, [workspaceId, token, tenantId, projectId]);
}
