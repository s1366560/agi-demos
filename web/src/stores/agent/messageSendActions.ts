/**
 * Message sending actions extracted from agentV3.ts.
 *
 * Contains sendMessage and abortStream which handle sending user messages,
 * creating conversations on-the-fly, and managing stream lifecycle.
 */

import { v4 as uuidv4 } from 'uuid';

import i18n from '../../i18n/config';
import { agentService } from '../../services/agentService';
import {
  type ConversationState,
  createDefaultConversationState,
  MAX_CONCURRENT_STREAMING_CONVERSATIONS,
} from '../../types/conversationState';

import { useConversationsStore } from './conversationsStore';
import {
  TOKEN_BATCH_INTERVAL_MS,
  THOUGHT_BATCH_INTERVAL_MS,
  getDeltaBuffer,
  clearDeltaBuffers,
  clearAllDeltaBuffers,
  clearAllTimelineBuffers,
  queueTimelineEvent as queueTimelineEventRaw,
  flushTimelineBufferSync as flushTimelineBufferSyncRaw,
  bindTimelineBufferDeps,
} from './deltaBuffers';
import { useExecutionStore } from './executionStore';
import { useAgentHITLStore } from './hitlStore';
import { createStreamEventHandlers } from './streamEventHandlers';
import { useStreamingStore } from './streamingStore';
import { useTimelineStore } from './timelineStore';
import { timelineToMessages } from './timelineUtils';

import type { StreamHandlerDeps } from './streamEventHandlers';
import type { AdditionalAgentHandlers, AgentV3State } from './types';
import type { AgentStreamHandler, Message, UserMessageEvent } from '../../types/agent';
import type { StoreApi } from 'zustand';

function getPreferredLanguage(): 'en-US' | 'zh-CN' {
  const language = i18n.resolvedLanguage || i18n.language;
  return language === 'zh-CN' || language === 'zh' ? 'zh-CN' : 'en-US';
}

async function syncConversationSelectedAgent(
  conversationId: string,
  projectId: string,
  selectedAgentId: string | undefined
): Promise<void> {
  if (!selectedAgentId) {
    return;
  }

  const conversationStore = useConversationsStore.getState();
  const currentConversation = conversationStore.currentConversation;
  const currentSelectedAgentId =
    currentConversation?.id === conversationId
      ? currentConversation.agent_config?.['selected_agent_id']
      : undefined;
  if (currentSelectedAgentId === selectedAgentId) {
    return;
  }

  const updatedConversation = await agentService.updateConversationConfig(conversationId, projectId, {
    selected_agent_id: selectedAgentId,
  });
  useConversationsStore.getState().updateCurrentConversation(updatedConversation);
}

export interface MessageSendActionDeps {
  get: () => {
    activeConversationId: string | null;
    conversationStates: Map<string, ConversationState>;
    getConversationState: (conversationId: string) => ConversationState;
    updateConversationState: (conversationId: string, updates: Partial<ConversationState>) => void;
    getStreamingConversationCount: () => number;
  };
  set: StoreApi<AgentV3State>['setState'];
  resetCanvasForConversationScope: () => void;
}

export function createMessageSendActions(deps: MessageSendActionDeps) {
  const { get, set, resetCanvasForConversationScope } = deps;

  return {
    sendMessage: async (
      content: string,
      projectId: string,
      additionalHandlers?: AdditionalAgentHandlers
    ): Promise<string | null> => {
      const { activeConversationId, getStreamingConversationCount } = get();
      const messages = useTimelineStore.getState().agentMessages;
      const timeline = useTimelineStore.getState().agentTimeline;

      // CRITICAL: Clear any stale delta buffers before starting new stream
      clearAllDeltaBuffers();
      clearAllTimelineBuffers();

      // Check concurrent streaming limit
      const streamingCount = getStreamingConversationCount();
      if (streamingCount >= MAX_CONCURRENT_STREAMING_CONVERSATIONS) {
        const concurrentErr = `Maximum ${String(MAX_CONCURRENT_STREAMING_CONVERSATIONS)} concurrent conversations reached. Please wait for one to complete.`;
        useStreamingStore.getState().setAgentError(concurrentErr);
        return null;
      }

      let conversationId = activeConversationId;
      let isNewConversation = false;

      if (!conversationId) {
        try {
          const newConv = await useConversationsStore
            .getState()
            .createConversation(projectId, content.slice(0, 30) + '...', additionalHandlers?.agentId);
          conversationId = newConv.id;
          isNewConversation = true;
          resetCanvasForConversationScope();

          const newConvState = createDefaultConversationState();
          const newConvId = conversationId;

          set((state) => {
            const newStates = new Map(state.conversationStates);
            newStates.set(newConvId, newConvState);
            return {
              activeConversationId: newConvId,
              conversations: useConversationsStore.getState().conversations,
              conversationStates: newStates,
            };
          });
        } catch (error) {
          const msg = error instanceof Error ? error.message : String(error);
          const createErr = `Failed to create conversation: ${msg}`;
          useStreamingStore.getState().setAgentError(createErr);
          return null;
        }
      }

      if (!isNewConversation) {
        try {
          await syncConversationSelectedAgent(
            conversationId,
            projectId,
            additionalHandlers?.agentId
          );
        } catch (error) {
          const msg = error instanceof Error ? error.message : String(error);
          useStreamingStore
            .getState()
            .setAgentError(`Failed to update conversation agent: ${msg}`);
          return null;
        }
      }

      const userMsgId = uuidv4();
      const userMsg: Message = {
        id: userMsgId,
        conversation_id: conversationId,
        role: 'user',
        content,
        message_type: 'text',
        created_at: new Date().toISOString(),
      };

      // Create user message TimelineEvent and append to timeline
      const userMessageMetadata: Record<string, unknown> = {};
      if (additionalHandlers?.forcedSkillName) {
        userMessageMetadata.forcedSkillName = additionalHandlers.forcedSkillName;
      }
      if (additionalHandlers?.fileMetadata && additionalHandlers.fileMetadata.length > 0) {
        userMessageMetadata.fileMetadata = additionalHandlers.fileMetadata;
      }
      const userMessageEvent: UserMessageEvent = {
        id: userMsgId,
        type: 'user_message',
        eventTimeUs: Date.now() * 1000,
        eventCounter: 0,
        timestamp: Date.now(),
        content,
        role: 'user',
        ...(Object.keys(userMessageMetadata).length > 0 && { metadata: userMessageMetadata }),
      };

      // Update both global state and conversation-specific state
      const newTimeline = [...timeline, userMessageEvent];
      set((state) => {
        const newStates = new Map(state.conversationStates);
        const convState = newStates.get(conversationId) || createDefaultConversationState();
        newStates.set(conversationId, {
          ...convState,
          timeline: newTimeline,
          isStreaming: true,
          streamStatus: 'connecting',
          streamingAssistantContent: '',
          error: null,
          currentThought: '',
          streamingThought: '',
          isThinkingStreaming: false,
          activeToolCalls: new Map(),
          pendingToolsStack: [],
          agentState: 'thinking',
          suggestions: [],
        });

        return { conversationStates: newStates };
      });

      // Bridge sendMessage reset to sub-stores
      useTimelineStore.getState().setAgentTimeline(newTimeline);
      useTimelineStore.getState().setAgentMessages([...messages, userMsg]);
      useStreamingStore.getState().resetAgentStreaming();
      useStreamingStore.getState().setAgentIsStreaming(true);
      useStreamingStore.getState().setAgentStreamStatus('connecting');
      useExecutionStore.getState().resetAgentExecution();
      useExecutionStore.getState().setAgentExecutionState('thinking');
      useAgentHITLStore.getState().setSuggestions([]);

      // Capture conversationId in closure for event handler isolation
      const handlerConversationId = conversationId;

      bindTimelineBufferDeps(handlerConversationId, {
        getConversationState: get().getConversationState,
        updateConversationState: get().updateConversationState,
      });

      const streamHandlerDeps: StreamHandlerDeps = {
        get,
        set: set as StreamHandlerDeps['set'],
        getDeltaBuffer,
        clearDeltaBuffers,
        clearAllDeltaBuffers,
        timelineToMessages,
        tokenBatchIntervalMs: TOKEN_BATCH_INTERVAL_MS,
        thoughtBatchIntervalMs: THOUGHT_BATCH_INTERVAL_MS,
        queueTimelineEvent: (event, stateUpdates) => {
          queueTimelineEventRaw(handlerConversationId, event, stateUpdates);
        },
        flushTimelineBufferSync: () => {
          flushTimelineBufferSyncRaw(handlerConversationId);
        },
      };

      const handler: AgentStreamHandler = createStreamEventHandlers(
        handlerConversationId,
        additionalHandlers,
        streamHandlerDeps
      );

      // For new conversations, wait until the WebSocket send is written before navigation.
      // The chat() promise resolves after send_message is queued, not after the assistant finishes.
      if (isNewConversation) {
        try {
          // Get app model context from conversation state (SEP-1865)
          const convState = get().conversationStates.get(conversationId);
          const appCtx = convState?.appModelContext || undefined;

          await agentService.chat(
            {
              conversation_id: conversationId,
              message: content,
              project_id: projectId,
              preferred_language: getPreferredLanguage(),
              file_metadata: additionalHandlers?.fileMetadata,
              forced_skill_name: additionalHandlers?.forcedSkillName,
              app_model_context: appCtx ?? undefined,
              image_attachments: additionalHandlers?.imageAttachments,
              agent_id: additionalHandlers?.agentId,
              mentions: additionalHandlers?.mentions,
            },
            handler
          );
          return conversationId;
        } catch {
          const { updateConversationState } = get();
          updateConversationState(handlerConversationId, {
            error: 'Failed to connect to chat stream',
            isStreaming: false,
            streamStatus: 'error',
          });
          return null;
        }
      }

      // For existing conversations, wait for stream to complete
      try {
        // Get app model context from conversation state (SEP-1865)
        const convState2 = get().conversationStates.get(conversationId);
        const appCtx2 = convState2?.appModelContext || undefined;

        await agentService.chat(
          {
            conversation_id: conversationId,
            message: content,
            project_id: projectId,
            preferred_language: getPreferredLanguage(),
            file_metadata: additionalHandlers?.fileMetadata,
            forced_skill_name: additionalHandlers?.forcedSkillName,
            app_model_context: appCtx2 ?? undefined,
            image_attachments: additionalHandlers?.imageAttachments,
            agent_id: additionalHandlers?.agentId,
            mentions: additionalHandlers?.mentions,
          },
          handler
        );
        return conversationId;
      } catch (_e) {
        const { updateConversationState } = get();
        updateConversationState(handlerConversationId, {
          error: 'Failed to connect to chat stream',
          isStreaming: false,
          streamStatus: 'error',
        });
        return null;
      }
    },

    abortStream: (conversationId?: string): void => {
      const targetConvId = conversationId || get().activeConversationId;
      if (targetConvId) {
        const stopSent = agentService.stopChat(targetConvId);

        if (!stopSent) {
          const { updateConversationState } = get();
          updateConversationState(targetConvId, {
            error: 'Failed to send stop request',
            isStreaming: false,
            streamStatus: 'error',
          });
          return;
        }

        // Clean up delta buffers to prevent stale timers from firing
        clearDeltaBuffers(targetConvId);

        const { updateConversationState } = get();
        updateConversationState(targetConvId, {
          isStreaming: false,
          streamStatus: 'idle',
          agentState: 'idle',
          streamingThought: '',
          isThinkingStreaming: false,
          streamingAssistantContent: '',
          pendingToolsStack: [],
        });
      }
    },
  };
}
