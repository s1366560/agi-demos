/**
 * memstack-agent-ui - SDK Package
 *
 * Complete SDK for memstack-agent-ui framework.
 *
 * @packageDocumentation
 */

// Core types
export type {
  // Event types
  EventType,
  EventCategory,

  // Agent state
  AgentState,
  ToolCallStatus,
  ToolCall,
  ActiveToolCall,

  // HITL types
  HITLRequestType,
  HITLRequestStatus,

  // Task and cost tracking
  AgentTask,
  CostTracking,
  DoomLoopDetected,
  DoomLoopIntervened,
} from './core/src/types';

export type {
  isDeltaEvent,
  isTerminalEvent,
  isHITLEvent,
} from './core/src/types';

export type {
  EVENT_CATEGORIES,
  SAVE_TRIGGER_EVENTS,
  COST_UPDATE_EVENTS,
} from './core/src/types';

// Conversation types
export type {
  MessageRole,
  MessageType,
  Message,

  // Timeline events
  TimelineEvent,
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

  // HITL events
  PermissionAskedEventData,
  PermissionRepliedEventData,
  ClarificationAskedEventData,
  ClarificationAnsweredEventData,
  DecisionAskedEventData,
  DecisionAnsweredEventData,
  EnvVarRequestedEventData,
  EnvVarProvidedEventData,

  // Other events
  CompleteEventData,
  CostUpdateEventData,
  SuggestionsEventData,
  ArtifactCreatedEventData,
  ArtifactReadyEventData,
  ArtifactErrorEventData,
  TitleGeneratedEventData,
} from './core/src/types';

export type {
  StreamStatus,
  HITLSummary,
  ConversationState,
  createDefaultConversationState,
  getHITLSummaryFromState,
  MAX_CONCURRENT_STREAMING_CONVERSATIONS,
} from './core/src/types';

export type {
  AgentStore,
} from './core/src/state';

// WebSocket client
export type {
  WebSocketClientOptions,
  WebSocketStatus,
  WebSocketClient,
} from './client';

export type {
  EventRouter,
} from './client';

export type {
  EventHandler,
  AgentEvent,
} from './client';

// Store
export type {
  ConversationManager,
  ConversationManagerOptions,
  LRUCacheOptions,
  LRUCache,
} from './store';
