/**
 * Per-conversation state types for concurrent agent conversation switching.
 *
 * This module defines types for storing conversation-specific state that
 * persists even when switching away from a conversation.
 */

import type { WorkPlan, ToolExecution, SkillExecutionState, TimelineEvent, ThoughtLevel } from '../../types/agent';

/**
 * Streaming state for a single conversation
 */
export interface ConversationStreamingState {
  isStreaming: boolean;
  streamStatus: 'idle' | 'connecting' | 'streaming' | 'error';
  startedAt?: number;
}

/**
 * Execution state for a single conversation
 */
export interface ConversationExecutionState {
  currentThought: string | null;
  currentThoughtLevel: ThoughtLevel | null;
  currentToolCall: {
    name: string;
    input: Record<string, unknown>;
    stepNumber?: number;
  } | null;
  currentObservation: string | null;
  currentToolExecution: {
    id: string;
    toolName: string;
    input: Record<string, unknown>;
    stepNumber?: number;
    startTime: string;
  } | null;
  toolExecutionHistory: ToolExecution[];
  executionTimeline: Array<{
    stepNumber: number;
    description: string;
    status: 'pending' | 'running' | 'completed' | 'failed';
    thoughts: string[];
    toolExecutions: ToolExecution[];
    startTime?: string;
    endTime?: string;
    duration?: number;
  }>;
  currentSkillExecution: SkillExecutionState | null;
}

/**
 * Complete state for a single conversation
 */
export interface ConversationState {
  id: string;

  // Streaming state
  streaming: ConversationStreamingState;

  // Execution state
  execution: ConversationExecutionState;

  // Work plan state
  workPlan: WorkPlan | null;
  currentStepNumber: number | null;
  currentStepStatus: 'pending' | 'running' | 'completed' | 'failed' | null;

  // Timeline state
  timeline: TimelineEvent[];
  earliestLoadedSequence: number | null;
  latestLoadedSequence: number | null;
  hasEarlierMessages: boolean;

  // Draft content for typewriter effect
  assistantDraftContent: string;
  isTextStreaming: boolean;

  // Metadata
  lastAccessedAt: number;
}

/**
 * Create an empty conversation state for a new conversation
 */
export function createEmptyConversationState(conversationId: string): ConversationState {
  return {
    id: conversationId,
    streaming: {
      isStreaming: false,
      streamStatus: 'idle',
    },
    execution: {
      currentThought: null,
      currentThoughtLevel: null,
      currentToolCall: null,
      currentObservation: null,
      currentToolExecution: null,
      toolExecutionHistory: [],
      executionTimeline: [],
      currentSkillExecution: null,
    },
    workPlan: null,
    currentStepNumber: null,
    currentStepStatus: null,
    timeline: [],
    earliestLoadedSequence: null,
    latestLoadedSequence: null,
    hasEarlierMessages: false,
    assistantDraftContent: '',
    isTextStreaming: false,
    lastAccessedAt: Date.now(),
  };
}

/**
 * Merge partial updates into a conversation state
 */
export function updateConversationState(
  state: ConversationState,
  updates: Partial<Omit<ConversationState, 'id' | 'lastAccessedAt'>>
): ConversationState {
  return {
    ...state,
    ...updates,
    lastAccessedAt: Date.now(),
  };
}

/**
 * Per-conversation message lock state
 */
export type ConversationLocks = Map<string, boolean>;

/**
 * Check if a conversation has an active message lock
 */
export function isConversationLocked(locks: ConversationLocks, conversationId: string): boolean {
  return locks.get(conversationId) ?? false;
}

/**
 * Set the lock state for a conversation
 */
export function setConversationLock(
  locks: ConversationLocks,
  conversationId: string,
  locked: boolean
): ConversationLocks {
  const newLocks = new Map(locks);
  if (locked) {
    newLocks.set(conversationId, true);
  } else {
    newLocks.delete(conversationId);
  }
  return newLocks;
}
