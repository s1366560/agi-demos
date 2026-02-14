/**
 * memstack-agent-ui - SDK Type Definitions
 *
 * Re-exports core types for SDK consumers.
 *
 * @packageDocumentation
 */

export type {
  // Event types
  EventType,
  EventCategory,
} from '../core/src/types/events';

export type {
  // Agent state
  AgentState,
  ToolCall,
  ActiveToolCall,
  // Cost tracking
  CostTracking,
  // HITL/Doom loop
  DoomLoopDetected,
  DoomLoopIntervened,
  ErrorEventData,
  RetryEventData,
} from '../core/src/types/agent';

export type {
  // Conversation and timeline
  Message,
  TimelineEvent,
  TimelineEventBase,
  UserMessageEvent,
  AssistantMessageEvent,
  // HITL events
  PermissionAskedEventData,
  PermissionRepliedEventData,
  ClarificationAskedEventData,
  ClarificationAnsweredEventData,
  DecisionAskedEventData,
  DecisionAnsweredEventData,
  EnvVarRequestedEventData,
  EnvVarProvidedEventData,
  // Agent execution
  ThoughtEventData,
  ThoughtDeltaEventData,
  ActEventData,
  ActDeltaEventData,
  ObserveEventData,
  TextStartEventData,
  TextDeltaEventData,
  TextEndEventData,
  CompleteEventData,
  CostUpdateEventData,
  SuggestionsEventData,
  // Artifacts
  ArtifactCreatedEventData,
  ArtifactReadyEventData,
  ArtifactErrorEventData,
  TitleGeneratedEventData,
} from '../core/src/types/conversation';

export type {
  // Conversation state
  ConversationState,
  StreamStatus,
  HITLSummary,
} from '../core/src/types/conversation-state';

export type {
  AgentTask,
} from '../core/src/types/agent';
