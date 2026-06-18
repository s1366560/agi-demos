/**
 * Cross-tab synchronization for agent store state.
 *
 * Extracted from agentV3.ts to reduce file size and improve maintainability.
 * Subscribes to BroadcastChannel messages to keep state consistent across tabs.
 */

import { logger } from '../../utils/logger';
import { tabSync, type TabSyncMessage } from '../../utils/tabSync';

import { useConversationsStore } from './conversationsStore';

import type { AgentV3State } from './types';
import type { StoreApi, UseBoundStore } from 'zustand';

type AgentV3Store = UseBoundStore<StoreApi<AgentV3State>>;
let agentV3Store: AgentV3Store | null = null;

export function registerAgentV3Store(store: AgentV3Store): () => void {
  agentV3Store = store;

  return () => {
    if (agentV3Store === store) {
      agentV3Store = null;
    }
  };
}

/**
 * Initialize cross-tab synchronization.
 * This runs once when the module is loaded.
 */
export function initTabSync(): void {
  if (!tabSync.isSupported()) {
    logger.info('[AgentV3] Cross-tab sync not supported in this browser');
    return;
  }

  logger.info('[AgentV3] Initializing cross-tab sync');

  tabSync.subscribe((message: TabSyncMessage) => {
    const store = agentV3Store;
    if (!store) {
      logger.warn('[AgentV3] Ignoring tab sync message before store registration');
      return;
    }

    (() => {
      const state = store.getState();

      switch (message.type) {
        case 'STREAMING_STATE_CHANGED': {
          const msg = message as TabSyncMessage & {
            conversationId: string;
            isStreaming: boolean;
            streamStatus: string;
          };
          // Update conversation state if we have it
          const convState = state.conversationStates.get(msg.conversationId);
          if (convState) {
            state.updateConversationState(msg.conversationId, {
              isStreaming: msg.isStreaming,
              streamStatus: msg.streamStatus as 'idle' | 'connecting' | 'streaming' | 'error',
            });
            logger.debug(`[TabSync] Updated streaming state for ${msg.conversationId}`);
          }
          break;
        }

        case 'CONVERSATION_COMPLETED': {
          const msg = message as TabSyncMessage & {
            conversationId: string;
          };
          if (state.activeConversationId === msg.conversationId) {
            logger.info(
              `[TabSync] Conversation ${msg.conversationId} completed in another tab, reloading...`
            );
            const conv = useConversationsStore
              .getState()
              .conversations.find((c) => c.id === msg.conversationId);
            if (conv) {
              void state.loadMessages(msg.conversationId, conv.project_id, { force: true });
            }
          }
          break;
        }

        case 'HITL_STATE_CHANGED': {
          const msg = message as TabSyncMessage & {
            conversationId: string;
            hasPendingHITL: boolean;
            hitlType?: string | undefined;
          };
          // Update HITL state for this conversation
          const convState = state.conversationStates.get(msg.conversationId);
          if (convState) {
            // If HITL was resolved in another tab, clear our local pending state
            if (!msg.hasPendingHITL) {
              state.updateConversationState(msg.conversationId, {
                pendingClarification: null,
                pendingDecision: null,
                pendingEnvVarRequest: null,
              });
            }
            logger.debug(`[TabSync] Updated HITL state for ${msg.conversationId}`);
          }
          break;
        }

        case 'CONVERSATION_DELETED': {
          const msg = message as TabSyncMessage & {
            conversationId: string;
          };
          // Remove from conversations list
          useConversationsStore.setState((s) => ({
            conversations: s.conversations.filter((c) => c.id !== msg.conversationId),
          }));
          // Mirror to agentV3 during strangler-fig migration (will be removed in Wave 6e)
          store.setState((s) => ({
            conversations: s.conversations.filter((c) => c.id !== msg.conversationId),
          }));
          // Clean up conversation state
          const newStates = new Map(state.conversationStates);
          newStates.delete(msg.conversationId);
          store.setState({ conversationStates: newStates });
          // Clear active conversation if it was deleted
          if (state.activeConversationId === msg.conversationId) {
            store.setState({ activeConversationId: null });
          }
          logger.info(`[TabSync] Removed deleted conversation ${msg.conversationId}`);
          break;
        }

        case 'CONVERSATION_RENAMED': {
          const msg = message as TabSyncMessage & {
            conversationId: string;
            newTitle: string;
          };
          useConversationsStore.setState((s) => ({
            conversations: s.conversations.map((c) =>
              c.id === msg.conversationId ? { ...c, title: msg.newTitle } : c
            ),
          }));
          store.setState((s) => ({
            conversations: s.conversations.map((c) =>
              c.id === msg.conversationId ? { ...c, title: msg.newTitle } : c
            ),
          }));
          logger.debug(`[TabSync] Updated title for ${msg.conversationId}`);
          break;
        }
      }
    })();
  });
}
