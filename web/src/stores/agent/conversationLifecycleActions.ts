/**
 * Conversation lifecycle actions extracted from agentV3.ts.
 *
 * Contains loadConversations, loadMoreConversations, deleteConversation,
 * renameConversation, and createNewConversation actions.
 */

import { agentService } from '../../services/agentService';
import { createDefaultConversationState } from '../../types/conversationState';
import { deleteConversationState } from '../../utils/conversationDB';
import { logger } from '../../utils/logger';
import { tabSync } from '../../utils/tabSync';

import { useConversationsStore } from './conversationsStore';
import { clearDeltaBuffers, deleteDeltaBuffer } from './deltaBuffers';
import { useExecutionStore } from './executionStore';
import { useAgentHITLStore } from './hitlStore';
import { touchConversation, cancelPendingSave, removeFromAccessOrder } from './persistence';
import { useStreamingStore } from './streamingStore';
import { useTimelineStore } from './timelineStore';

import type { AgentV3State, LoadConversationsOptions } from './types';
import type { ConversationState } from '../../types/conversationState';
import type { StoreApi } from 'zustand';

function isAbortSignal(
  value: AbortSignal | LoadConversationsOptions | undefined
): value is AbortSignal {
  return (
    typeof value === 'object' && 'aborted' in value && typeof value.addEventListener === 'function'
  );
}

function normalizeLoadOptions(
  signalOrOptions: AbortSignal | LoadConversationsOptions | undefined
): LoadConversationsOptions {
  if (isAbortSignal(signalOrOptions)) {
    return { signal: signalOrOptions };
  }
  return signalOrOptions ?? {};
}

export interface ConversationLifecycleDeps {
  get: () => {
    activeConversationId: string | null;
    conversations: AgentV3State['conversations'];
    conversationStates: Map<string, ConversationState>;
    hasMoreConversations: boolean;
  };
  set: StoreApi<AgentV3State>['setState'];
  resetCanvasForConversationScope: () => void;
}

const inFlightConversationLoads = new Map<string, Promise<void>>();
const DEFAULT_CONVERSATION_REFRESH_LIMIT = 10;
const MAX_IMPLICIT_FORCE_REFRESH_LIMIT = 25;

function resolveConversationRefreshLimit(
  currentConversations: AgentV3State['conversations'],
  options: LoadConversationsOptions
): number | undefined {
  if (options.limit !== undefined) {
    return options.limit;
  }
  if (!options.force) {
    return undefined;
  }
  return Math.min(
    Math.max(currentConversations.length, DEFAULT_CONVERSATION_REFRESH_LIMIT),
    MAX_IMPLICIT_FORCE_REFRESH_LIMIT
  );
}

function conversationLoadKey(projectId: string, options: LoadConversationsOptions): string {
  return [
    projectId,
    options.force ? 'force' : 'cached',
    options.silent ? 'silent' : 'visible',
    String(options.limit ?? 'default'),
  ].join(':');
}

function sameConversationSnapshot(
  left: AgentV3State['conversations'],
  right: AgentV3State['conversations']
): boolean {
  if (left === right) {
    return true;
  }
  if (left.length !== right.length) {
    return false;
  }
  return left.every((conversation, index) => {
    const other = right[index];
    return (
      other?.id === conversation.id &&
      other.project_id === conversation.project_id &&
      other.updated_at === conversation.updated_at &&
      other.status === conversation.status
    );
  });
}

export function createConversationLifecycleActions(deps: ConversationLifecycleDeps) {
  const { get, set, resetCanvasForConversationScope } = deps;

  return {
    loadConversations: async (
      projectId: string,
      signalOrOptions?: AbortSignal | LoadConversationsOptions
    ): Promise<void> => {
      const options = normalizeLoadOptions(signalOrOptions);
      const loadKey = conversationLoadKey(projectId, options);
      const inFlightLoad = inFlightConversationLoads.get(loadKey);
      if (inFlightLoad) {
        try {
          await inFlightLoad;
        } catch {
          // The owner call logs non-silent failures below; duplicate callers only coalesce.
        }
        return;
      }

      // Prevent duplicate calls for the same project
      const currentConvos = get().conversations;
      const conversationListState = useConversationsStore.getState();
      if (!options.force && conversationListState.conversationListProjectId === projectId) {
        const currentState = get() as ReturnType<ConversationLifecycleDeps['get']> & {
          conversationsTotal?: number | undefined;
        };
        if (
          sameConversationSnapshot(
            currentState.conversations,
            conversationListState.conversations
          ) &&
          currentState.hasMoreConversations === conversationListState.hasMoreConversations &&
          currentState.conversationsTotal === conversationListState.conversationsTotal
        ) {
          return;
        }
        set({
          conversations: conversationListState.conversations,
          hasMoreConversations: conversationListState.hasMoreConversations,
          conversationsTotal: conversationListState.conversationsTotal,
        });
        return;
      }

      logger.debug(`[agentV3] loadConversations called for project: ${projectId}`);

      const loadPromise = (async () => {
        // Delegate to conversationsStore for API call + list management
        const limit = resolveConversationRefreshLimit(currentConvos, options);
        await useConversationsStore.getState().listConversations(projectId, undefined, limit, {
          signal: options.signal,
          silent: options.silent,
        });
        // If the request was aborted (e.g. user switched projects), stop here.
        if (options.signal?.aborted) {
          return;
        }
        // Sync back to agentV3 state (strangler fig dual-write)
        const convState = useConversationsStore.getState();
        if (convState.conversationListProjectId !== projectId) {
          return;
        }
        set({
          conversations: convState.conversations,
          hasMoreConversations: convState.hasMoreConversations,
          conversationsTotal: convState.conversationsTotal,
        });
        logger.debug(
          `[agentV3] Loaded ${String(convState.conversations.length)} conversations via conversationsStore`
        );
      })();

      inFlightConversationLoads.set(loadKey, loadPromise);

      try {
        await loadPromise;
      } catch (error) {
        if (options.signal?.aborted || (error as { name?: string }).name === 'CanceledError') {
          return;
        }
        if (options.silent) {
          logger.debug('[agentV3] Silent conversation refresh failed', error);
          return;
        }
        console.error('[agentV3] Failed to list conversations', error);
      } finally {
        if (inFlightConversationLoads.get(loadKey) === loadPromise) {
          inFlightConversationLoads.delete(loadKey);
        }
      }
    },

    loadMoreConversations: async (projectId: string): Promise<void> => {
      const state = get();
      if (!state.hasMoreConversations) return;

      try {
        await useConversationsStore.getState().loadMoreConversations(projectId);
        const convState = useConversationsStore.getState();
        if (convState.conversationListProjectId !== projectId) {
          return;
        }
        set({
          conversations: convState.conversations,
          hasMoreConversations: convState.hasMoreConversations,
          conversationsTotal: convState.conversationsTotal,
        });
        logger.debug(`[agentV3] Loaded more conversations via conversationsStore`);
      } catch (error) {
        console.error('[agentV3] Failed to load more conversations', error);
      }
    },

    deleteConversation: async (conversationId: string, projectId: string): Promise<void> => {
      try {
        // Delegate API call + list filtering to conversationsStore
        await useConversationsStore.getState().deleteConversation(conversationId, projectId);

        agentService.unsubscribe(conversationId);
        clearDeltaBuffers(conversationId);
        deleteDeltaBuffer(conversationId);
        cancelPendingSave(conversationId);
        removeFromAccessOrder(conversationId);

        const wasActive = get().activeConversationId === conversationId;
        set((state) => {
          const newStates = new Map(state.conversationStates);
          newStates.delete(conversationId);

          return {
            conversations: useConversationsStore.getState().conversations,
            conversationStates: newStates,
            activeConversationId:
              state.activeConversationId === conversationId ? null : state.activeConversationId,
          };
        });

        // Reset sub-stores if we deleted the active conversation
        if (wasActive) {
          useTimelineStore.getState().setAgentTimeline([]);
          useTimelineStore.getState().setAgentMessages([]);
          useStreamingStore.getState().resetAgentStreaming();
          useExecutionStore.getState().resetAgentExecution();
        }

        deleteConversationState(conversationId).catch(console.error);
        tabSync.broadcastConversationDeleted(conversationId);
      } catch (error) {
        console.error('Failed to delete conversation', error);
        useStreamingStore.getState().setAgentError('Failed to delete conversation');
      }
    },

    renameConversation: async (
      conversationId: string,
      projectId: string,
      title: string
    ): Promise<void> => {
      try {
        await useConversationsStore.getState().renameConversation(conversationId, projectId, title);
        set({ conversations: useConversationsStore.getState().conversations });
        tabSync.broadcastConversationRenamed(conversationId, title);
      } catch (error) {
        console.error('Failed to rename conversation', error);
        useStreamingStore.getState().setAgentError('Failed to rename conversation');
      }
    },

    createNewConversation: async (projectId: string): Promise<string | null> => {
      set({ isCreatingConversation: true });
      try {
        const newConv = await useConversationsStore
          .getState()
          .createConversation(projectId, 'New Conversation');
        resetCanvasForConversationScope();

        const newConvState = createDefaultConversationState();

        touchConversation(newConv.id);
        set((state) => {
          const newStates = new Map(state.conversationStates);
          newStates.set(newConv.id, newConvState);

          return {
            conversations: useConversationsStore.getState().conversations,
            conversationStates: newStates,
            activeConversationId: newConv.id,
          };
        });

        useTimelineStore.getState().setAgentTimeline([]);
        useTimelineStore.getState().setAgentMessages([]);
        useStreamingStore.getState().resetAgentStreaming();
        useExecutionStore.getState().resetAgentExecution();
        useAgentHITLStore.getState().syncFromConversation({
          pendingClarification: null,
          pendingDecision: null,
          pendingEnvVarRequest: null,
          pendingPermission: null,
          doomLoopDetected: null,
          costTracking: null,
          suggestions: [],
          pinnedEventIds: new Set(),
        });

        return newConv.id;
      } catch (error) {
        console.error('Failed to create conversation', error);
        useStreamingStore.getState().setAgentError('Failed to create conversation');
        return null;
      } finally {
        set({ isCreatingConversation: false });
      }
    },
  };
}
