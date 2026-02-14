/**
 * memstack-agent-ui - Core Store Interface
 *
 * Defines the base store interface for agent state management.
 * Based on MemStack's Zustand + IndexedDB pattern.
 *
 * @packageDocumentation
 */

import type { ConversationState } from '../types/conversation-state';
import type { Message, TimelineEvent } from '../types';

/**
 * Base store interface for agent state management
 *
 * Defines the contract that all agent store implementations must follow.
 * Supports multi-conversation isolation with Map-based state storage.
 */
export interface AgentStore {
  // ========================================================================
  // Conversation Management
  // ========================================================================

  /** All conversations keyed by ID */
  conversations: Map<string, ConversationState>;

  /** Currently active conversation ID */
  activeConversationId: string | null;

  // ========================================================================
  // Actions
  // ========================================================================

  /**
   * Get state for a specific conversation
   *
   * @param conversationId - Conversation ID to get state for
   * @returns Conversation state or undefined if not found
   */
  getConversation: (conversationId: string) => ConversationState | undefined;

  /**
   * Update state for a specific conversation
   *
   * Merges partial updates into existing conversation state.
   * Creates default state if conversation doesn't exist.
   *
   * @param conversationId - Conversation ID to update
   * @param updates - Partial state updates to merge
   */
  updateConversation: (
     conversationId: string,
     updates: Partial<ConversationState>
   ) => void;

  /**
   * Create a new conversation
   *
   * @param id - Optional conversation ID (generates UUID if not provided)
   * @returns New conversation ID
   */
  createConversation: (id?: string) => string;

  /**
   * Delete a conversation and all its state
   *
   * @param conversationId - Conversation ID to delete
   */
  deleteConversation: (conversationId: string) => void;

  /**
   * Set the active conversation
   *
   * Switches to the specified conversation, loading its state.
   * Clears active state if null is passed.
   *
   * @param conversationId - Conversation ID to activate, or null to clear
   */
  setActiveConversation: (conversationId: string | null) => void;

  // ========================================================================
  // Timeline & Messages
  // ========================================================================

  /**
   * Append an event to a conversation's timeline
   *
   * @param conversationId - Conversation ID
   * @param event - Event to append
   */
  appendTimelineEvent: (
     conversationId: string,
     event: TimelineEvent
   ) => void;

  /**
   * Prepend events to a conversation's timeline
   *
   * Used for pagination when loading earlier messages.
   *
   * @param conversationId - Conversation ID
   * @param events - Events to prepend
   */
  prependTimelineEvents: (
     conversationId: string,
     events: TimelineEvent[]
   ) => void;

  /**
   * Get messages for a conversation
   *
   * Messages are derived from timeline events.
   *
   * @param conversationId - Conversation ID
   * @returns Array of messages
   */
  getMessages: (conversationId: string) => Message[];

  /**
   * Get timeline for a conversation
   *
   * @param conversationId - Conversation ID
   * @returns Timeline events array
   */
  getTimeline: (conversationId: string) => TimelineEvent[];

  // ========================================================================
  // Streaming State
  // ========================================================================

  /**
   * Set streaming state for a conversation
   *
   * @param conversationId - Conversation ID
   * @param isStreaming - Whether conversation is streaming
   * @param status - Optional stream status override
   */
  setStreamingState: (
     conversationId: string,
     isStreaming: boolean,
     status?: 'idle' | 'connecting' | 'streaming' | 'error'
   ) => void;

  /**
   * Update streaming assistant content
   *
   * Accumulates delta content during text streaming.
   *
   * @param conversationId - Conversation ID
   * @param content - Content to append (or set to replace)
   * @param replace - Whether to replace instead of append
   */
  updateStreamingContent: (
     conversationId: string,
     content: string,
     replace?: boolean
   ) => void;

  // ========================================================================
  // Agent Execution State
  // ========================================================================

  /**
   * Set agent state for a conversation
   *
   * @param conversationId - Conversation ID
   * @param agentState - New agent state
   */
  setAgentState: (
     conversationId: string,
     agentState: ConversationState['agentState']
   ) => void;

  /**
   * Update thought content for a conversation
   *
   * @param conversationId - Conversation ID
   * @param thought - Thought content to set
   * @param streaming - Whether this is streaming content
   */
  updateThought: (
     conversationId: string,
     thought: string,
     streaming?: boolean
   ) => void;

  /**
   * Add or update an active tool call
   *
   * @param conversationId - Conversation ID
   * @param toolCall - Tool call to add/update
   */
  upsertToolCall: (
     conversationId: string,
     toolCall: Omit<ConversationState['activeToolCalls'], 'clear'>[string]
   ) => void;

  /**
   * Remove a tool call from active calls
   *
   * @param conversationId - Conversation ID
   * @param toolCallId - Tool call ID to remove
   */
  removeToolCall: (
     conversationId: string,
     toolCallId: string
   ) => void;

  /**
   * Push tool to pending stack
   *
   * @param conversationId - Conversation ID
   * @param toolName - Tool name to push
   */
  pushPendingTool: (
     conversationId: string,
     toolName: string
   ) => void;

  /**
   * Pop tool from pending stack
   *
   * @param conversationId - Conversation ID
   * @returns Popped tool name or undefined
   */
  popPendingTool: (conversationId: string) => string | undefined;

  // ========================================================================
  // HITL State
  // ========================================================================

  /**
   * Set pending clarification request
   *
   * @param conversationId - Conversation ID
   * @param clarification - Clarification request data
   */
  setPendingClarification: (
     conversationId: string,
     clarification: ConversationState['pendingClarification']
   ) => void;

  /**
   * Set pending decision request
   *
   * @param conversationId - Conversation ID
   * @param decision - Decision request data
   */
  setPendingDecision: (
     conversationId: string,
     decision: ConversationState['pendingDecision']
   ) => void;

  /**
   * Set pending environment variable request
   *
   * @param conversationId - Conversation ID
   * @param envVarRequest - Env var request data
   */
  setPendingEnvVarRequest: (
     conversationId: string,
     envVarRequest: ConversationState['pendingEnvVarRequest']
   ) => void;

  /**
   * Set pending permission request
   *
   * @param conversationId - Conversation ID
   * @param permission - Permission request data
   */
  setPendingPermission: (
     conversationId: string,
     permission: ConversationState['pendingPermission']
   ) => void;

  /**
   * Clear all HITL requests for a conversation
   *
   * @param conversationId - Conversation ID
   */
  clearHITLRequests: (conversationId: string) => void;

  /**
   * Get HITL summary for a conversation
   *
   * @param conversationId - Conversation ID
   * @returns HITL summary or null
   */
  getHITLSummary: (conversationId: string) => ConversationState['pendingHITLSummary'] | null;

  /**
   * Get all conversations with pending HITL requests
   *
   * @returns Array of conversation IDs and their HITL summaries
   */
  getConversationsWithPendingHITL: () => Array<{
     conversationId: string;
     summary: ConversationState['pendingHITLSummary'];
   }>;

  // ========================================================================
  // Error Handling
  // ========================================================================

  /**
   * Set error for a conversation
   *
   * @param conversationId - Conversation ID
   * @param error - Error message or null to clear
   */
  setError: (
     conversationId: string,
     error: string | null
   ) => void;

  /**
   * Clear error for a conversation
   *
   * @param conversationId - Conversation ID
   */
  clearError: (conversationId: string) => void;
}
