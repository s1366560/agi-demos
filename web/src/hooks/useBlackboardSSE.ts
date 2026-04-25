import { useEffect } from 'react';

import { useWorkspaceStore } from '@/stores/workspace';

import { unifiedEventService } from '@/services/unifiedEventService';

import { classifyWorkspaceEventType } from '@/components/blackboard/blackboardSurfaceContract';

/**
 * Subscribes to SSE events for a given workspace and routes them
 * to the appropriate workspace store handlers.
 */
export function useBlackboardSSE(workspaceId: string | null): void {
  useEffect(() => {
    if (!workspaceId) {
      return;
    }

    const store = useWorkspaceStore.getState();
    const unsubscribe = unifiedEventService.subscribeWorkspace(workspaceId, (event) => {
      const type = event.type;
      const data = event.data as Record<string, unknown>;
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
  }, [workspaceId]);
}
