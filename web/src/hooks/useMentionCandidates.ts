/**
 * useMentionCandidates — Phase-5 G8.
 *
 * Reactive hook around the unified
 * ``GET /agent/conversations/{id}/mention-candidates`` endpoint.
 * When the conversation is workspace-linked, candidates come from the
 * workspace agent roster (with display_name / label / status);
 * otherwise they fall back to ``conversation.participant_agents``.
 *
 * Agent-First: the result is a bounded set; filtering is done in UI as
 * a substring match over the set, never as a classifier over prose.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  participantsService,
  type MentionCandidate,
  type MentionCandidatesResponse,
} from '../services/participantsService';

export interface UseMentionCandidatesResult {
  candidates: MentionCandidate[];
  source: 'workspace' | 'conversation' | null;
  workspaceId: string | null;
  loading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
}

export function useMentionCandidates(
  conversationId: string | null | undefined,
  options?: { enabled?: boolean; includeInactive?: boolean }
): UseMentionCandidatesResult {
  const enabled = options?.enabled ?? true;
  const includeInactive = options?.includeInactive ?? false;
  const [state, setState] = useState<MentionCandidatesResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);
  const activeConversationId = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    if (!conversationId || !enabled) {
      setState(null);
      return;
    }
    activeConversationId.current = conversationId;
    setLoading(true);
    setError(null);
    try {
      const next = await participantsService.listMentionCandidates(conversationId, {
        includeInactive,
      });
      if (activeConversationId.current === conversationId) {
        setState(next);
      }
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [conversationId, enabled, includeInactive]);

  useEffect(() => {
    void refresh();
    return () => {
      activeConversationId.current = null;
    };
  }, [refresh]);

  return {
    candidates: state?.candidates ?? [],
    source: state?.source ?? null,
    workspaceId: state?.workspace_id ?? null,
    loading,
    error,
    refresh,
  };
}
