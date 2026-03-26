import { useCallback, useEffect, useRef } from 'react';

import { useWorkspaceStore } from '@/stores/workspace';

interface UseWorkspaceWebSocketOptions {
  workspaceId: string | null;
  enabled?: boolean;
  sendMessage: (message: Record<string, unknown>) => void;
}

export function useWorkspaceWebSocket({
  workspaceId,
  enabled = true,
  sendMessage,
}: UseWorkspaceWebSocketOptions) {
  const subscribedRef = useRef<string | null>(null);

  const subscribe = useCallback(() => {
    if (!workspaceId || !enabled) return;
    sendMessage({ type: 'subscribe_workspace', workspace_id: workspaceId });
    sendMessage({
      type: 'workspace_presence_join',
      workspace_id: workspaceId,
      display_name: 'User',
    });
    subscribedRef.current = workspaceId;
  }, [workspaceId, enabled, sendMessage]);

  const unsubscribe = useCallback(() => {
    if (!subscribedRef.current) return;
    const id = subscribedRef.current;
    sendMessage({ type: 'workspace_presence_leave', workspace_id: id });
    sendMessage({ type: 'unsubscribe_workspace', workspace_id: id });
    subscribedRef.current = null;
    useWorkspaceStore.getState().clearPresence();
  }, [sendMessage]);

  useEffect(() => {
    subscribe();
    return () => {
      unsubscribe();
    };
  }, [subscribe, unsubscribe]);

  const handleMessage = useCallback((message: Record<string, unknown>) => {
    const type = message.type as string;
    if (!type || !message.workspace_id) return;

    const store = useWorkspaceStore.getState();

    if (type.startsWith('workspace.presence.')) {
      store.handlePresenceEvent({
        type,
        data: message.data as Record<string, unknown>,
      });
    } else if (type.startsWith('workspace.agent_status.')) {
      store.handleAgentStatusEvent({
        type,
        data: message.data as Record<string, unknown>,
      });
    } else if (type.startsWith('workspace_task_') || type === 'workspace_task_assigned') {
      store.handleTaskEvent({
        type,
        data: message.data as Record<string, unknown>,
      });
    } else if (type.startsWith('blackboard_')) {
      store.handleBlackboardEvent({
        type,
        data: message.data as Record<string, unknown>,
      });
    } else if (type === 'workspace_message_created') {
      store.handleChatEvent({
        type,
        data: message.data as Record<string, unknown>,
      });
    } else if (type === 'workspace_member_joined' || type === 'workspace_member_left') {
      store.handleMemberEvent({
        type,
        data: message.data as Record<string, unknown>,
      });
    } else if (type === 'workspace_updated' || type === 'workspace_deleted') {
      store.handleWorkspaceLifecycleEvent({
        type,
        data: message.data as Record<string, unknown>,
      });
    } else if (type === 'workspace_agent_bound' || type === 'workspace_agent_unbound') {
      store.handleAgentBindingEvent({
        type,
        data: message.data as Record<string, unknown>,
      });
    } else if (type === 'topology_updated' || type.startsWith('workspace.topology.')) {
      store.handleTopologyEvent({
        type,
        data: message.data as Record<string, unknown>,
      });
    }
  }, []);

  return { handleMessage, subscribe, unsubscribe };
}
