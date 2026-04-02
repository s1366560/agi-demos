/**
 * Type definitions for the agent store.
 *
 * Extracted from agentV3.ts to reduce file size and improve maintainability.
 */

import type { FileMetadata } from '../../services/sandboxUploadService';
import type {
  ActEventData,
  AgentEvent,
  Conversation,
  ObserveEventData,
} from '../../types/agent';
import type {
  ConversationState,
  HITLSummary,
} from '../../types/conversationState';
import type { LLMConfigOverrides } from '../../types/memory';

/**
 * Additional handlers that can be injected into sendMessage
 * for external integrations (e.g., sandbox tool detection)
 */
export interface AdditionalAgentHandlers {
  onAct?: ((event: AgentEvent<ActEventData>) => void) | undefined;
  onObserve?: ((event: AgentEvent<ObserveEventData>) => void) | undefined;
  /** File metadata for files uploaded to sandbox */
  fileMetadata?: FileMetadata[] | undefined;
  /** Force execution of a specific skill by name */
  forcedSkillName?: string | undefined;
  /** Base64 data URL image attachments from video frame capture */
  imageAttachments?: string[] | undefined;
  /** Target agent ID for multi-agent routing */
  agentId?: string | undefined;
}

export interface AgentV3State {
  // Conversation State
  conversations: Conversation[];
  activeConversationId: string | null;
  hasMoreConversations: boolean;
  conversationsTotal: number;

  // Per-conversation state (isolated for multi-conversation support)
  conversationStates: Map<string, ConversationState>;

  // Multi-conversation state helpers
  getConversationState: (conversationId: string) => ConversationState;
  updateConversationState: (conversationId: string, updates: Partial<ConversationState>) => void;
  getStreamingConversationCount: () => number;
  getConversationsWithPendingHITL: () => Array<{
    conversationId: string;
    summary: HITLSummary;
  }>;
  syncActiveConversationState: () => void;

  // Actions
  setActiveConversation: (id: string | null) => void;
  loadConversations: (projectId: string) => Promise<void>;
  loadMoreConversations: (projectId: string) => Promise<void>;
  loadMessages: (conversationId: string, projectId: string) => Promise<void>;
  loadEarlierMessages: (conversationId: string, projectId: string) => Promise<boolean>;
  createNewConversation: (projectId: string) => Promise<string | null>;
  sendMessage: (
    content: string,
    projectId: string,
    additionalHandlers?: AdditionalAgentHandlers
  ) => Promise<string | null>;
  deleteConversation: (conversationId: string, projectId: string) => Promise<void>;
  renameConversation: (conversationId: string, projectId: string, title: string) => Promise<void>;
  abortStream: (conversationId?: string) => void;
  respondToClarification: (requestId: string, answer: string) => Promise<void>;
  respondToDecision: (requestId: string, decision: string | string[]) => Promise<void>;
  respondToEnvVar: (requestId: string, values: Record<string, string>) => Promise<void>;
  respondToPermission: (requestId: string, granted: boolean) => Promise<void>;
  loadPendingHITL: (conversationId: string) => Promise<void>;
  clearError: () => void;
  togglePinEvent: (eventId: string) => void;
  setLlmOverrides: (conversationId: string, overrides: LLMConfigOverrides | null) => void;
  setLlmModelOverride: (conversationId: string, modelName: string | null) => void;
}
