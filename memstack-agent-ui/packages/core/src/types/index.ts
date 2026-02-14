/**
 * memstack-agent-ui - Core Type Definitions
 *
 * Central export point for all core types.
 *
 * @packageDocumentation
 */

// Event types and utilities
export type {
  EventCategory,
  EventType,
} from './events';
export {
  EVENT_CATEGORIES,
  isDeltaEvent,
  isTerminalEvent,
  isHITLEvent,
  SAVE_TRIGGER_EVENTS,
  COST_UPDATE_EVENTS,
} from './events';

// Agent state and execution types
export type {
  AgentState,
  ToolCallStatus,
  ToolCall,
  ActiveToolCall,
  AgentTask,
  CostTracking,
  DoomLoopDetected,
  DoomLoopIntervened,
  ErrorEventData,
  RetryEventData,
} from './agent';

// Conversation and timeline types
export type {
  MessageRole,
  MessageType,
  Message,
  TimelineEventBase,
  UserMessageEvent,
  AssistantMessageEvent,
  ThoughtEventData,
  ThoughtDeltaEventData,
  WorkPlanEventData,
  ActEventData,
  ActDeltaEventData,
  ObserveEventData,
  TextStartEventData,
  TextDeltaEventData,
  TextEndEventData,
  PermissionAskedEventData,
  PermissionRepliedEventData,
  ClarificationAskedEventData,
  ClarificationAnsweredEventData,
  DecisionAskedEventData,
  DecisionAnsweredEventData,
  EnvVarRequestedEventData,
  EnvVarProvidedEventData,
  CompleteEventData,
  ErrorEventDataType,
  RetryEventDataType,
  DoomLoopDetectedDataType,
  DoomLoopIntervenedDataType,
  CostUpdateEventData,
  SuggestionsEventData,
  ArtifactCreatedEventData,
  ArtifactReadyEventData,
  ArtifactErrorEventData,
  TitleGeneratedEventData,
  TimelineEvent,
} from './conversation';

// Re-export ErrorEventData as ErrorEventData for convenience
export { ErrorEventData } from './agent';

// Conversation state types
export type {
  StreamStatus,
  HITLSummary,
  ConversationState,
  AgentTask,
} from './conversation-state';
export {
  createDefaultConversationState,
  getHITLSummaryFromState,
  MAX_CONCURRENT_STREAMING_CONVERSATIONS,
} from './conversation-state';
