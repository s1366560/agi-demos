/**
 * Type definitions for the agent store.
 *
 * Extracted from agentV3.ts to reduce file size and improve maintainability.
 */

import type { FileMetadata } from '../../services/sandboxUploadService';
import type {
  ActEventData,
  AgentEvent,
  ClarificationAskedEventData,
  Conversation,
  DecisionAskedEventData,
  DoomLoopDetectedEventData,
  EnvVarRequestedEventData,
  Message,
  ObserveEventData,
  PermissionAskedEventData,
  TimelineEvent,
  ToolCall,
} from '../../types/agent';
import type {
  ConversationState,
  CostTrackingState,
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

  // Timeline State (for active conversation - backward compatibility)
  timeline: TimelineEvent[];

  // Messages State (Derived from timeline for backward compatibility)
  messages: Message[];
  isLoadingHistory: boolean; // For initial message load (shows loading in sidebar)
  isLoadingEarlier: boolean; // For pagination (does NOT show loading in sidebar)
  hasEarlier: boolean; // Whether there are earlier messages to load
  earliestTimeUs: number | null; // For pagination
  earliestCounter: number | null; // For pagination

  // Stream State (for active conversation - backward compatibility)
  isStreaming: boolean;
  streamStatus: 'idle' | 'connecting' | 'streaming' | 'error';
  error: string | null;
  streamingAssistantContent: string; // Streaming content (used for real-time display)

  // Agent Execution State (for active conversation - backward compatibility)
  agentState:
    | 'idle'
    | 'thinking'
    | 'preparing'
    | 'acting'
    | 'observing'
    | 'awaiting_input'
    | 'retrying';
  currentThought: string;
  streamingThought: string; // For streaming thought_delta content
  isThinkingStreaming: boolean; // Whether thought is currently streaming
  activeToolCalls: Map<
    string,
    ToolCall & {
      status: 'preparing' | 'running' | 'success' | 'failed';
      startTime: number;
      partialArguments?: string | undefined;
    }
  >;
  pendingToolsStack: string[]; // Track order of tool executions

  // Plan Mode State
  isPlanMode: boolean;

  // UI State
  showPlanPanel: boolean;
  showHistorySidebar: boolean;
  leftSidebarWidth: number;
  rightPanelWidth: number;

  // Interactivity (for active conversation - backward compatibility)
  pendingClarification: ClarificationAskedEventData | null; // Pending clarification request from agent
  pendingDecision: DecisionAskedEventData | null; // Pending decision request from agent
  pendingEnvVarRequest: EnvVarRequestedEventData | null; // Pending environment variable request from agent
  pendingPermission: PermissionAskedEventData | null; // Pending permission request
  doomLoopDetected: DoomLoopDetectedEventData | null;
  costTracking: CostTrackingState | null; // Cost tracking state
  suggestions: string[]; // Follow-up suggestions from agent
  pinnedEventIds: Set<string>; // Pinned message event IDs (per-conversation, local only)

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
  togglePlanPanel: () => void;
  toggleHistorySidebar: () => void;
  setLeftSidebarWidth: (width: number) => void;
  setRightPanelWidth: (width: number) => void;
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
