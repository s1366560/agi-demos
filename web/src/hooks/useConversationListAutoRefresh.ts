import { useEffect } from 'react';

import { useConversationsStore } from '@/stores/agent/conversationsStore';
import { useAgentV3Store } from '@/stores/agentV3';
import { useAuthStore } from '@/stores/auth';

import { unifiedEventService, type UnifiedEvent } from '@/services/unifiedEventService';

import { logger } from '../utils/logger';

const EVENT_REFRESH_DEBOUNCE_MS = 300;
const VISIBILITY_REFRESH_STALE_MS = 60000;
const MIN_CONVERSATION_REFRESH_LIMIT = 10;
const MAX_CONVERSATION_REFRESH_LIMIT = 25;

type ConversationCreatedPayload = {
  conversation_id?: string | undefined;
  id?: string | undefined;
  project_id?: string | undefined;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function getConversationCreatedPayload(event: UnifiedEvent): ConversationCreatedPayload {
  if (!isRecord(event.data)) {
    return {};
  }
  return {
    conversation_id:
      typeof event.data.conversation_id === 'string' ? event.data.conversation_id : undefined,
    id: typeof event.data.id === 'string' ? event.data.id : undefined,
    project_id: typeof event.data.project_id === 'string' ? event.data.project_id : undefined,
  };
}

function getProjectId(event: UnifiedEvent): string | undefined {
  const payload = getConversationCreatedPayload(event);
  if (typeof event.project_id === 'string') {
    return event.project_id;
  }
  return payload.project_id;
}

function getConversationId(event: UnifiedEvent): string | undefined {
  const payload = getConversationCreatedPayload(event);
  if (payload.conversation_id) {
    return payload.conversation_id;
  }
  return payload.id;
}

function isConversationAlreadyLoaded(conversationId: string | undefined): boolean {
  if (!conversationId) {
    return false;
  }
  return useConversationsStore
    .getState()
    .conversations.some((conversation) => conversation.id === conversationId);
}

function getRefreshLimit(): number {
  return Math.min(
    Math.max(useConversationsStore.getState().conversations.length, MIN_CONVERSATION_REFRESH_LIMIT),
    MAX_CONVERSATION_REFRESH_LIMIT
  );
}

/**
 * Keeps the `/agent-workspace` conversation list fresh when other tabs/users
 * create sessions in the selected project.
 */
export function useConversationListAutoRefresh(projectId: string | null): void {
  const token = useAuthStore((state) => state.token);

  useEffect(() => {
    if (!projectId || !token) {
      return;
    }

    let refreshTimer: number | undefined;
    let refreshController: AbortController | undefined;
    let lastRefreshAt = Date.now();

    const refreshConversations = () => {
      refreshController?.abort();
      const controller = new AbortController();
      refreshController = controller;
      lastRefreshAt = Date.now();

      void useAgentV3Store
        .getState()
        .loadConversations(projectId, {
          force: true,
          silent: true,
          limit: getRefreshLimit(),
          signal: controller.signal,
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) {
            return;
          }
          logger.debug('[useConversationListAutoRefresh] Refresh failed', error);
        });
    };

    const scheduleRefresh = () => {
      if (refreshTimer) {
        window.clearTimeout(refreshTimer);
      }
      refreshTimer = window.setTimeout(() => {
        refreshTimer = undefined;
        refreshConversations();
      }, EVENT_REFRESH_DEBOUNCE_MS);
    };

    const unsubscribe = unifiedEventService.subscribeProject(projectId, (event) => {
      if (event.type !== 'conversation_created') {
        return;
      }
      if (getProjectId(event) !== projectId) {
        return;
      }
      if (isConversationAlreadyLoaded(getConversationId(event))) {
        return;
      }
      scheduleRefresh();
    });

    const refreshVisibleStaleList = () => {
      if (document.visibilityState !== 'visible') {
        return;
      }
      if (Date.now() - lastRefreshAt < VISIBILITY_REFRESH_STALE_MS) {
        return;
      }
      refreshConversations();
    };

    document.addEventListener('visibilitychange', refreshVisibleStaleList);

    return () => {
      unsubscribe();
      if (refreshTimer) {
        window.clearTimeout(refreshTimer);
      }
      document.removeEventListener('visibilitychange', refreshVisibleStaleList);
      refreshController?.abort();
    };
  }, [projectId, token]);
}
