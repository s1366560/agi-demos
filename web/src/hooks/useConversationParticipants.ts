/**
 * useConversationParticipants — Track B P2-3 phase-2.
 *
 * Reactive hook around ``participantsService``. Shared by the roster
 * panel (``ConversationParticipantsPanel``), the @mention picker
 * (``MentionPicker``), and the HITL center.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  participantsService,
  type AddParticipantRequest,
  type RosterResponse,
} from '../services/participantsService';

export interface UseConversationParticipantsResult {
  roster: RosterResponse | null;
  loading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
  addParticipant: (payload: AddParticipantRequest) => Promise<RosterResponse | null>;
  removeParticipant: (agentId: string) => Promise<RosterResponse | null>;
  setCoordinator: (agentId: string | null) => Promise<RosterResponse | null>;
  setFocusedAgent: (agentId: string | null) => Promise<RosterResponse | null>;
}

export function useConversationParticipants(
  conversationId: string | null | undefined
): UseConversationParticipantsResult {
  const [roster, setRoster] = useState<RosterResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);
  const activeConversationId = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    if (!conversationId) {
      setRoster(null);
      return;
    }
    activeConversationId.current = conversationId;
    setLoading(true);
    setError(null);
    try {
      const next = await participantsService.listRoster(conversationId);
      if (activeConversationId.current === conversationId) {
        setRoster(next);
      }
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    void refresh();
    return () => {
      activeConversationId.current = null;
    };
  }, [refresh]);

  const addParticipant = useCallback(
    async (payload: AddParticipantRequest) => {
      if (!conversationId) return null;
      const next = await participantsService.addParticipant(conversationId, payload);
      setRoster(next);
      return next;
    },
    [conversationId]
  );

  const removeParticipant = useCallback(
    async (agentId: string) => {
      if (!conversationId) return null;
      const next = await participantsService.removeParticipant(conversationId, agentId);
      setRoster(next);
      return next;
    },
    [conversationId]
  );

  const setCoordinator = useCallback(
    async (agentId: string | null) => {
      if (!conversationId) return null;
      const next = await participantsService.setCoordinator(conversationId, agentId);
      setRoster(next);
      return next;
    },
    [conversationId]
  );

  const setFocusedAgent = useCallback(
    async (agentId: string | null) => {
      if (!conversationId) return null;
      const next = await participantsService.setFocusedAgent(conversationId, agentId);
      setRoster(next);
      return next;
    },
    [conversationId]
  );

  return {
    roster,
    loading,
    error,
    refresh,
    addParticipant,
    removeParticipant,
    setCoordinator,
    setFocusedAgent,
  };
}
