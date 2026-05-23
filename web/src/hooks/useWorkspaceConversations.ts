/**
 * useWorkspaceConversations — lists conversations filtered by workspace.
 *
 * Uses the workspace-aware ``GET /agent/conversations`` filter so large
 * workspaces are loaded completely instead of relying on the first project page.
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
      activeKey.current = null;
      setConversations([]);
      setLoading(false);
      setError(null);
      return;
    }
    const key = `${projectId}|${workspaceId}`;
    activeKey.current = key;
    setLoading(true);
    setError(null);
    try {
      const items: Conversation[] = [];
      let offset = 0;
      let hasMore = true;

      while (hasMore) {
        const response = await agentService.listConversations(
          projectId,
          'active',
          100,
          offset,
          undefined,
          { workspaceId }
        );
        const pageItems = Array.isArray(response.items) ? response.items : [];
        items.push(
          ...pageItems.filter((conversation) => conversation.workspace_id === workspaceId)
        );

        const nextOffset =
          typeof response.next_offset === 'number'
            ? response.next_offset
            : offset + pageItems.length;
        hasMore = response.has_more && nextOffset > offset;
        offset = nextOffset;
      }

      if (activeKey.current === key) {
        setConversations(items);
      }
    } catch (err) {
      if (activeKey.current === key) {
        setError(err instanceof Error ? err : new Error(String(err)));
      }
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
