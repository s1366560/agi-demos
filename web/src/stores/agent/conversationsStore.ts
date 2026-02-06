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
  conversationsError: string | null;
  isNewConversationPending: boolean;

  // Actions
  listConversations: (
    projectId: string,
    status?: ConversationStatus,
    limit?: number
  ) => Promise<void>;
  createConversation: (projectId: string, title?: string) => Promise<Conversation>;
  getConversation: (conversationId: string, projectId: string) => Promise<Conversation | null>;
  deleteConversation: (conversationId: string, projectId: string) => Promise<void>;
  renameConversation: (conversationId: string, projectId: string, title: string) => Promise<void>;
  setCurrentConversation: (conversation: Conversation | null) => void;
  generateConversationTitle: () => Promise<void>;
  updateCurrentConversation: (conversation: Conversation) => void;
  clearPendingFlag: () => void;
  reset: () => void;
}

/**
 * Initial state for Conversations store
 */
export const initialState = {
  conversations: [],
  currentConversation: null,
  conversationsLoading: false,
  conversationsError: null,
  isNewConversationPending: false,
};

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
       * @param limit - Optional limit (default 50)
       */
      listConversations: async (projectId: string, status?: ConversationStatus, limit = 50) => {
        // Skip if already loading for the same project
        const state = get();
        if (state.conversationsLoading) {
          console.log(
            '[conversationsStore] Already loading conversations, skipping duplicate call'
          );
          return;
        }

        set({ conversationsLoading: true, conversationsError: null });
        try {
          const conversations = await agentService.listConversations(projectId, status, limit);
          set({ conversations, conversationsLoading: false });
        } catch (error: unknown) {
          const err = error as { response?: { data?: { detail?: string } }; message?: string };
          set({
            conversationsError: err?.response?.data?.detail || 'Failed to list conversations',
            conversationsLoading: false,
          });
          throw error;
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
          const err = error as { response?: { data?: { detail?: string } }; message?: string };
          set({
            conversationsError: err?.response?.data?.detail || 'Failed to create conversation',
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
          const err = error as { response?: { data?: { detail?: string } }; message?: string };
          set({
            conversationsError: err?.response?.data?.detail || 'Failed to get conversation',
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
          const err = error as { response?: { data?: { detail?: string } }; message?: string };
          set({
            conversationsError: err?.response?.data?.detail || 'Failed to delete conversation',
            conversationsLoading: false,
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
        console.log('[ConversationsStore] setCurrentConversation called:', conversation?.id);

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
 * Type export for store (used in tests)
 */
export type ConversationsStore = ReturnType<typeof useConversationsStore.getState>;
