/**
 * useWorkspaceConversations — lists conversations filtered by workspace.
 *
 * Uses the existing ``GET /agent/conversations`` endpoint (filtered by
 * project) and filters client-side by ``workspace_id``. Workspaces
 * typically hold a small number of conversations, so this is adequate
 * without a dedicated backend filter.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { agentService } from '@/services/agentService';
import type { Conversation } from '@/types/agent/core';

export interface UseWorkspaceConversationsResult {
  conversations: Conversation[];
  loading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
}

export function useWorkspaceConversations(
  projectId: string | null | undefined,
  workspaceId: string | null | undefined
): UseWorkspaceConversationsResult {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const activeKey = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    if (!projectId || !workspaceId) {
      setConversations([]);
      return;
    }
    const key = `${projectId}|${workspaceId}`;
    activeKey.current = key;
    setLoading(true);
    setError(null);
    try {
      const response = await agentService.listConversations(projectId, 'active', 100, 0);
      if (activeKey.current === key) {
        const items = Array.isArray(response.items) ? response.items : [];
        setConversations(items.filter((c) => c.workspace_id === workspaceId));
      }
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      if (activeKey.current === key) setLoading(false);
    }
  }, [projectId, workspaceId]);

  useEffect(() => {
    void refresh();
    return () => {
      activeKey.current = null;
    };
  }, [refresh]);

  return { conversations, loading, error, refresh };
}
