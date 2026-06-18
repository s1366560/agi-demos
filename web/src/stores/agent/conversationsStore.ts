/**
 * Conversations Store - Split from monolithic agent store.
 *
 * This store manages conversation state for the agent.
 * It handles the core conversation management functionality.
 *
 * State managed:
 * - conversations: List of conversations
 * - currentConversation: Active conversation
 * - conversationsLoading: Loading state
 * - conversationsError: Error state
 * - isNewConversationPending: Flag for new conversation pending state
 *
 * Note: The full setCurrentConversation with state saving/restoration
 * is complex and tightly coupled with timeline/execution state.
 * This store provides a simpler setCurrentConversation for basic switching.
 * The complex switching logic remains in the main agent store.
 *
 * This store was split from agent.ts to improve maintainability
 * and follow single-responsibility principle.
 *
 * Uses Zustand for state management, consistent with the main agent store.
 *
 * @module stores/agent/conversationsStore
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

import { DEFAULT_GENERAL_AGENT_ID } from '../../constants/agent';
import { agentService } from '../../services/agentService';

import type {
  Conversation,
  ConversationStatus,
  CreateConversationRequest,
} from '../../types/agent';

/**
 * Conversations Store State
 */
interface ConversationsState {
  // State
  conversations: Conversation[];
  currentConversation: Conversation | null;
  conversationsLoading: boolean;
  conversationsLoadingMore: boolean;
  conversationsError: string | null;
  isNewConversationPending: boolean;
  hasMoreConversations: boolean;
  conversationsTotal: number;
  conversationsNextOffset: number;
  conversationListProjectId: string | null;

  // Actions
  listConversations: (
    projectId: string,
    status?: ConversationStatus,
    limit?: number,
    signalOrOptions?: AbortSignal | ListConversationsOptions
  ) => Promise<void>;
  loadMoreConversations: (projectId: string, status?: ConversationStatus) => Promise<void>;
  createConversation: (projectId: string, title?: string) => Promise<Conversation>;
  getConversation: (conversationId: string, projectId: string) => Promise<Conversation | null>;
  deleteConversation: (conversationId: string, projectId: string) => Promise<void>;
  renameConversation: (conversationId: string, projectId: string, title: string) => Promise<void>;
  setCurrentConversation: (conversation: Conversation | null) => void;
  generateConversationTitle: () => Promise<void>;
  generateConversationSummary: () => Promise<void>;
  updateCurrentConversation: (conversation: Conversation) => void;
  clearPendingFlag: () => void;
  reset: () => void;
}

interface ListConversationsOptions {
  signal?: AbortSignal | undefined;
  silent?: boolean | undefined;
}

function isAbortSignal(
  value: AbortSignal | ListConversationsOptions | undefined
): value is AbortSignal {
  return (
    typeof value === 'object' && 'aborted' in value && typeof value.addEventListener === 'function'
  );
}

function normalizeListOptions(
  signalOrOptions: AbortSignal | ListConversationsOptions | undefined
): ListConversationsOptions {
  if (isAbortSignal(signalOrOptions)) {
    return { signal: signalOrOptions };
  }
  return signalOrOptions ?? {};
}

/**
 * Initial state for Conversations store
 */
export const initialState = {
  conversations: [],
  currentConversation: null,
  conversationsLoading: false,
  conversationsLoadingMore: false,
  conversationsError: null,
  isNewConversationPending: false,
  hasMoreConversations: false,
  conversationsTotal: 0,
  conversationsNextOffset: 0,
  conversationListProjectId: null,
};

const groupedConversationListOptions = { groupByWorkspace: true };
let listConversationsRequestSequence = 0;
let activeListConversationsRequest: {
  key: string;
  sequence: number;
} | null = null;

function conversationListRequestKey(
  projectId: string,
  status: ConversationStatus | undefined,
  limit: number
): string {
  return `${projectId}:${status ?? 'all'}:${String(limit)}`;
}

function startListConversationsRequest(key: string): number {
  const sequence = listConversationsRequestSequence + 1;
  listConversationsRequestSequence = sequence;
  activeListConversationsRequest = { key, sequence };
  return sequence;
}

function isActiveListConversationsRequest(sequence: number): boolean {
  return activeListConversationsRequest?.sequence === sequence;
}

function finishListConversationsRequest(sequence: number): void {
  if (isActiveListConversationsRequest(sequence)) {
    activeListConversationsRequest = null;
  }
}

function resetListConversationsRequestTracking(): void {
  activeListConversationsRequest = null;
  listConversationsRequestSequence += 1;
}

function conversationActivityTime(conversation: Conversation): number {
  const rawTimestamp = conversation.updated_at || conversation.created_at;
  const time = Date.parse(rawTimestamp);
  return Number.isFinite(time) ? time : 0;
}

function mergeUniqueConversations(
  existing: Conversation[],
  incoming: Conversation[]
): Conversation[] {
  if (existing.length === 0) {
    return incoming;
  }
  if (incoming.length === 0) {
    return existing;
  }

  const incomingIds = new Set(incoming.map((conversation) => conversation.id));
  return [
    ...incoming,
    ...existing
      .filter((conversation) => !incomingIds.has(conversation.id))
      .sort((a, b) => {
        const timeDiff = conversationActivityTime(b) - conversationActivityTime(a);
        return timeDiff !== 0 ? timeDiff : b.id.localeCompare(a.id);
      }),
  ];
}

function appendUniqueConversations(
  existing: Conversation[],
  incoming: Conversation[]
): Conversation[] {
  if (existing.length === 0) {
    return incoming;
  }
  if (incoming.length === 0) {
    return existing;
  }

  const existingIds = new Set(existing.map((conversation) => conversation.id));
  return [...existing, ...incoming.filter((conversation) => !existingIds.has(conversation.id))];
}

function responseNextOffset(
  response: {
    next_offset?: number | null | undefined;
    offset?: number | undefined;
    items: Conversation[];
  },
  fallbackOffset: number
): number {
  if (typeof response.next_offset === 'number') {
    return response.next_offset;
  }
  const responseOffset = typeof response.offset === 'number' ? response.offset : fallbackOffset;
  return responseOffset + response.items.length;
}

/**
 * Conversations Store
 *
 * Zustand store for managing conversations state.
 */
export const useConversationsStore = create<ConversationsState>()(
  devtools(
    (set, get) => ({
      ...initialState,

      /**
       * List conversations for a project
       *
       * @param projectId - The project ID
       * @param status - Optional status filter
       * @param limit - Optional limit (default 10)
       */
      listConversations: async (
        projectId: string,
        status?: ConversationStatus,
        limit = 10,
        signalOrOptions?: AbortSignal | ListConversationsOptions
      ) => {
        const { signal, silent = false } = normalizeListOptions(signalOrOptions);
        const state = get();
        const requestKey = conversationListRequestKey(projectId, status, limit);
        if (activeListConversationsRequest?.key === requestKey) {
          return;
        }
        if (silent && state.conversationsLoading) {
          return;
        }
        if (state.conversationsLoading && activeListConversationsRequest === null) {
          return;
        }

        const requestSequence = startListConversationsRequest(requestKey);
        if (!silent) {
          set({ conversationsLoading: true, conversationsError: null });
        }
        try {
          const response = signal
            ? await agentService.listConversations(
                projectId,
                status,
                limit,
                0,
                signal,
                groupedConversationListOptions
              )
            : await agentService.listConversations(
                projectId,
                status,
                limit,
                0,
                undefined,
                groupedConversationListOptions
              );
          if (!isActiveListConversationsRequest(requestSequence)) {
            return;
          }
          set({
            conversations: mergeUniqueConversations([], response.items),
            hasMoreConversations: response.has_more,
            conversationsTotal: response.total,
            conversationsNextOffset: responseNextOffset(response, 0),
            conversationListProjectId: projectId,
            ...(!silent ? { conversationsLoading: false } : {}),
          });
          finishListConversationsRequest(requestSequence);
        } catch (error: unknown) {
          if (!isActiveListConversationsRequest(requestSequence)) {
            return;
          }
          finishListConversationsRequest(requestSequence);
          // Defect #15: silently swallow aborted requests so a stale
          // project switch does not surface as a user-facing error.
          if (signal?.aborted || (error as { name?: string }).name === 'CanceledError') {
            if (!silent) {
              set({ conversationsLoading: false });
            }
            return;
          }
          const err = error as {
            response?: { data?: { detail?: string | undefined } | undefined } | undefined;
            message?: string | undefined;
          };
          if (!silent) {
            set({
              conversationsError: err.response?.data?.detail || 'Failed to list conversations',
              conversationsLoading: false,
            });
          }
          throw error;
        }
      },

      loadMoreConversations: async (projectId: string, status?: ConversationStatus) => {
        const state = get();
        if (state.conversationsLoadingMore || !state.hasMoreConversations) {
          return;
        }

        const requestSequence = listConversationsRequestSequence;
        set({ conversationsLoadingMore: true, conversationsError: null });
        try {
          const offset = state.conversationsNextOffset || state.conversations.length;
          const response = await agentService.listConversations(
            projectId,
            status,
            10,
            offset,
            undefined,
            groupedConversationListOptions
          );
          const latestState = get();
          if (
            requestSequence !== listConversationsRequestSequence ||
            (latestState.conversationListProjectId !== null &&
              latestState.conversationListProjectId !== projectId)
          ) {
            set({ conversationsLoadingMore: false });
            return;
          }
          set({
            conversations: appendUniqueConversations(latestState.conversations, response.items),
            hasMoreConversations: response.has_more,
            conversationsTotal: response.total,
            conversationsNextOffset: responseNextOffset(response, offset),
            conversationListProjectId: projectId,
            conversationsLoadingMore: false,
          });
        } catch (error: unknown) {
          if (requestSequence !== listConversationsRequestSequence) {
            set({ conversationsLoadingMore: false });
            return;
          }
          const err = error as {
            response?: { data?: { detail?: string | undefined } | undefined } | undefined;
            message?: string | undefined;
          };
          set({
            conversationsError: err.response?.data?.detail || 'Failed to load more conversations',
            conversationsLoadingMore: false,
          });
        }
      },

      /**
       * Create a new conversation
       *
       * @param projectId - The project ID
       * @param title - Optional title (default "New Chat")
       * @returns The created conversation
       */
      createConversation: async (projectId: string, title = 'New Chat') => {
        set({ conversationsLoading: true, conversationsError: null });
        try {
          const request: CreateConversationRequest = {
            project_id: projectId,
            title,
            agent_config: { selected_agent_id: DEFAULT_GENERAL_AGENT_ID },
          };
          const conversation = await agentService.createConversation(request);
          const { conversations } = get();
          set({
            conversations: [conversation, ...conversations],
            currentConversation: conversation,
            conversationsLoading: false,
            isNewConversationPending: true, // Mark as pending to prevent URL sync effect race condition
          });
          return conversation;
        } catch (error: unknown) {
          const err = error as {
            response?: { data?: { detail?: string | undefined } | undefined } | undefined;
            message?: string | undefined;
          };
          set({
            conversationsError: err.response?.data?.detail || 'Failed to create conversation',
            conversationsLoading: false,
          });
          throw error;
        }
      },

      /**
       * Get a specific conversation
       *
       * @param conversationId - The conversation ID
       * @param projectId - The project ID
       * @returns The conversation or null if not found
       */
      getConversation: async (conversationId: string, projectId: string) => {
        set({ conversationsLoading: true, conversationsError: null });
        try {
          const conversation = await agentService.getConversation(conversationId, projectId);
          set({ currentConversation: conversation, conversationsLoading: false });
          return conversation;
        } catch (error: unknown) {
          const err = error as {
            response?: { data?: { detail?: string | undefined } | undefined } | undefined;
            message?: string | undefined;
          };
          set({
            conversationsError: err.response?.data?.detail || 'Failed to get conversation',
            conversationsLoading: false,
          });
          return null;
        }
      },

      /**
       * Delete a conversation
       *
       * @param conversationId - The conversation ID
       * @param projectId - The project ID
       */
      deleteConversation: async (conversationId: string, projectId: string) => {
        set({ conversationsLoading: true, conversationsError: null });
        try {
          await agentService.deleteConversation(conversationId, projectId);
          const { conversations, currentConversation } = get();
          set({
            conversations: conversations.filter((c) => c.id !== conversationId),
            currentConversation:
              currentConversation?.id === conversationId ? null : currentConversation,
            conversationsLoading: false,
          });
          // Note: Conversation state cleanup is handled by the main agent store
        } catch (error: unknown) {
          const err = error as {
            response?: { data?: { detail?: string | undefined } | undefined } | undefined;
            message?: string | undefined;
          };
          set({
            conversationsError: err.response?.data?.detail || 'Failed to delete conversation',
            conversationsLoading: false,
          });
          throw error;
        }
      },

      renameConversation: async (conversationId: string, projectId: string, title: string) => {
        try {
          const updatedConversation = await agentService.updateConversationTitle(
            conversationId,
            projectId,
            title
          );
          set((state) => ({
            conversations: state.conversations.map((c) =>
              c.id === conversationId ? updatedConversation : c
            ),
            currentConversation:
              state.currentConversation?.id === conversationId
                ? updatedConversation
                : state.currentConversation,
          }));
        } catch (error: unknown) {
          const err = error as {
            response?: { data?: { detail?: string | undefined } | undefined } | undefined;
            message?: string | undefined;
          };
          set({
            conversationsError: err.response?.data?.detail || 'Failed to rename conversation',
          });
          throw error;
        }
      },

      /**
       * Set the current conversation
       *
       * This is a simplified version that just sets the conversation.
       * The complex state saving/restoration logic remains in the main agent store.
       *
       * @param conversation - The conversation to set as current
       */
      setCurrentConversation: (conversation: Conversation | null) => {
        set((state) => {
          // Clear pending flag when setting a conversation
          const updates = {
            currentConversation: conversation,
            isNewConversationPending: conversation ? false : state.isNewConversationPending,
          };
          return updates;
        });
      },

      /**
       * Generate a title for the current conversation
       *
       * Auto-generates a title based on the conversation content.
       */
      generateConversationTitle: async () => {
        const { currentConversation, conversations } = get();

        if (!currentConversation) {
          return;
        }

        try {
          const updatedConversation = await agentService.generateConversationTitle(
            currentConversation.id,
            currentConversation.project_id
          );

          // Update in conversations list
          const updatedList = conversations.map((conv) =>
            conv.id === updatedConversation.id ? updatedConversation : conv
          );

          set({
            currentConversation: updatedConversation,
            conversations: updatedList,
          });
        } catch (error) {
          // Log error but don't throw - title generation is best-effort
          console.error('[ConversationsStore] Failed to generate conversation title:', error);
        }
      },

      /**
       * Generate a summary for the current conversation
       *
       * Auto-generates a summary based on the conversation content.
       */
      generateConversationSummary: async () => {
        const { currentConversation, conversations } = get();

        if (!currentConversation) {
          return;
        }

        try {
          const updatedConversation = await agentService.generateConversationSummary(
            currentConversation.id,
            currentConversation.project_id
          );

          const updatedList = conversations.map((conv) =>
            conv.id === updatedConversation.id ? updatedConversation : conv
          );

          set({
            currentConversation: updatedConversation,
            conversations: updatedList,
          });
        } catch (error) {
          console.error('[ConversationsStore] Failed to generate conversation summary:', error);
        }
      },

      /**
       * Update the current conversation object
       *
       * Updates both currentConversation and the entry in conversations list.
       *
       * @param conversation - The updated conversation object
       */
      updateCurrentConversation: (conversation: Conversation) => {
        set((state) => {
          // Only update if IDs match
          if (state.currentConversation?.id !== conversation.id) {
            return {};
          }

          // Update in conversations list
          const updatedList = state.conversations.map((conv) =>
            conv.id === conversation.id ? conversation : conv
          );

          return {
            currentConversation: conversation,
            conversations: updatedList,
          };
        });
      },

      /**
       * Clear the new conversation pending flag
       *
       * This flag is used to prevent URL sync effect race conditions.
       */
      clearPendingFlag: () => {
        set({ isNewConversationPending: false });
      },

      /**
       * Reset store to initial state
       *
       * Completely resets all state in this store.
       */
      reset: () => {
        resetListConversationsRequestTracking();
        set(initialState);
      },
    }),
    {
      name: 'ConversationsStore',
      enabled: import.meta.env.DEV,
    }
  )
);

/**
 * Derived selector: Get conversations list
 */
export const useConversations = () => useConversationsStore((state) => state.conversations);

/**
 * Derived selector: Get current conversation
 */
export const useCurrentConversation = () =>
  useConversationsStore((state) => state.currentConversation);

/**
 * Derived selector: Get conversations loading state
 */
export const useConversationsLoading = () =>
  useConversationsStore((state) => state.conversationsLoading);

/**
 * Derived selector: Get conversations error
 */
export const useConversationsError = () =>
  useConversationsStore((state) => state.conversationsError);

/**
 * Derived selector: Get new conversation pending flag
 */
export const useIsNewConversationPending = () =>
  useConversationsStore((state) => state.isNewConversationPending);

/**
 * Derived selector: Has more conversations to load
 */
export const useHasMoreConversations = () =>
  useConversationsStore((state) => state.hasMoreConversations);

/**
 * Derived selector: Get conversations loading more state
 */
export const useConversationsLoadingMore = () =>
  useConversationsStore((state) => state.conversationsLoadingMore);

/**
 * Type export for store (used in tests)
 */
export type ConversationsStore = ReturnType<typeof useConversationsStore.getState>;
