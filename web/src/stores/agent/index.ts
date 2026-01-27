/**
 * Agent sub-stores barrel exports.
 *
 * This module exports all agent-related stores for cleaner imports.
 *
 * The agent store has been split into focused sub-stores:
 * - conversationsStore: Conversations state (list, current, CRUD operations)
 * - planModeStore: Plan Mode state (enter/exit plan mode, plan CRUD)
 * - streamingStore: Streaming state (connection status, typewriter effect)
 * - timelineStore: Timeline state (messages, events, pagination)
 * - executionStore: Execution state (work plan, steps, tool executions)
 * - conversationState: Per-conversation state types for concurrent switching
 *
 * Main agent store remains at ../agent.ts with backward-compatible exports.
 *
 * @module stores/agent/index
 */

// Conversations Store
export {
  useConversationsStore,
  useConversations,
  useCurrentConversation,
  useConversationsLoading,
  useConversationsError,
  useIsNewConversationPending,
  initialState as conversationsInitialState,
} from './conversationsStore';
export type { ConversationsStore } from './conversationsStore';

// Plan Mode Store
export {
  usePlanModeStore,
  useIsInPlanMode,
  initialState as planModeInitialState,
} from './planModeStore';

// Streaming Store
export {
  useStreamingStore,
  useIsActiveStreaming,
  useDraftContentLength,
  initialState as streamingInitialState,
} from './streamingStore';
export type { StreamStatus, StreamingStore } from './streamingStore';

// Timeline Store
export {
  useTimelineStore,
  useTimeline,
  useTimelineLoading,
  useTimelineError,
  useEarliestLoadedSequence,
  useLatestLoadedSequence,
  useTimelineWithChatFields,
  initialState as timelineInitialState,
} from './timelineStore';
export type { TimelineStore } from './timelineStore';

// Execution Store
export {
  useExecutionStore,
  useCurrentWorkPlan,
  useCurrentStepNumber,
  useCurrentStepStatus,
  useExecutionTimeline,
  useCurrentToolExecution,
  useToolExecutionHistory,
  useMatchedPattern,
  initialState as executionInitialState,
} from './executionStore';
export type {
  ExecutionStore,
  ExecutionState,
  StepStatus,
  MatchedPattern,
  CurrentToolExecution,
} from './executionStore';

// Conversation State Types (for concurrent conversation switching)
export {
  createEmptyConversationState,
  updateConversationState,
  isConversationLocked,
  setConversationLock,
} from './conversationState';
export type {
  ConversationState,
  ConversationLocks,
} from './conversationState';

// Re-export main types for convenience
export type { PlanDocument, PlanModeStatus } from '../../types/agent';

