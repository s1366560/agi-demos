import type {
  AgentEvent,
  MessageEventData,
  ThoughtEventData,
  ThoughtDeltaEventData,
  WorkPlanEventData,
  PatternMatchEventData,
  ActEventData,
  ActDeltaEventData,
  ObserveEventData,
  TextDeltaEventData,
  TextEndEventData,
  ClarificationAskedEventData,
  ClarificationAnsweredEventData,
  DecisionAskedEventData,
  DecisionAnsweredEventData,
  DoomLoopDetectedEventData,
  DoomLoopIntervenedEventData,
  EnvVarRequestedEventData,
  EnvVarProvidedEventData,
  SkillMatchedEventData,
  SkillExecutionStartEventData,
  SkillToolStartEventData,
  SkillToolResultEventData,
  SkillExecutionCompleteEventData,
  SkillFallbackEventData,
  ArtifactCreatedEventData,
  ArtifactReadyEventData,
  ArtifactErrorEventData,
  ArtifactsBatchEventData,
  SuggestionsEventData,
  ArtifactOpenEventData,
  ArtifactUpdateEventData,
  ArtifactCloseEventData,
  ContextCompressedEventData,
  ContextStatusEventData,
  TitleGeneratedEventData,
  PlanExecutionStartEvent,
  PlanExecutionCompleteEvent,
  ReflectionCompleteEvent,
  PermissionAskedEventData,
  PermissionRepliedEventData,
  CostUpdateEventData,
  SandboxEventData,
  SubAgentRoutedEventData,
  SubAgentStartedEventData,
  SubAgentCompletedEventData,
  SubAgentFailedEventData,
  SubAgentQueuedEventData,
  SubAgentKilledEventData,
  SubAgentSteeredEventData,
  ToolPolicyDeniedEventData,
  SubAgentDepthLimitedEventData,
  SubAgentSessionUpdateEventData,
  ParallelStartedEventData,
  ParallelCompletedEventData,
  ChainStartedEventData,
  ChainStepStartedEventData,
  ChainStepCompletedEventData,
  ChainCompletedEventData,
  BackgroundLaunchedEventData,
  ExecutionPathDecidedEventData,
  SelectionTraceEventData,
  PolicyFilteredEventData,
  ToolsetChangedEventData,
  TaskListUpdatedEventData,
  TaskUpdatedEventData,
  TaskStartEventData,
  TaskCompleteEventData,
  ModelSwitchRequestedEventData,
  ModelOverrideRejectedEventData,
  MemoryRecalledEventData,
  MemoryCapturedEventData,
  CanvasUpdatedEventData,
  A2UIActionAskedEventData,
  AgentSpawnedEventData,
  AgentCompletedEventData,
  AgentStoppedEventData,
  GraphRunStartedEventData,
  GraphRunCompletedEventData,
  GraphRunFailedEventData,
  GraphRunCancelledEventData,
  GraphNodeStartedEventData,
  GraphNodeCompletedEventData,
  GraphNodeFailedEventData,
  GraphNodeSkippedEventData,
  GraphHandoffEventData,
  CompleteEventData,
  ErrorEventData,
  RetryEventData,
} from './events';
/**
 * Agent SSE stream handler (extended for multi-level thinking and typewriter effect)
 */
export interface AgentStreamHandler {
  onMessage?: ((event: AgentEvent<MessageEventData>) => void) | undefined;
  onThought?: ((event: AgentEvent<ThoughtEventData>) => void) | undefined;
  onThoughtDelta?: ((event: AgentEvent<ThoughtDeltaEventData>) => void) | undefined; // Streaming thought
  onWorkPlan?: ((event: AgentEvent<WorkPlanEventData>) => void) | undefined;
  onPatternMatch?: ((event: AgentEvent<PatternMatchEventData>) => void) | undefined; // T079
  onAct?: ((event: AgentEvent<ActEventData>) => void) | undefined;
  onActDelta?: ((event: AgentEvent<ActDeltaEventData>) => void) | undefined;
  onObserve?: ((event: AgentEvent<ObserveEventData>) => void) | undefined;
  onTextStart?: (() => void) | undefined; // Typewriter effect
  onTextDelta?: ((event: AgentEvent<TextDeltaEventData>) => void) | undefined; // Typewriter effect
  onTextEnd?: ((event: AgentEvent<TextEndEventData>) => void) | undefined; // Typewriter effect
  onClarificationAsked?: ((event: AgentEvent<ClarificationAskedEventData>) => void) | undefined;
  onClarificationAnswered?:
    | ((event: AgentEvent<ClarificationAnsweredEventData>) => void)
    | undefined;
  onDecisionAsked?: ((event: AgentEvent<DecisionAskedEventData>) => void) | undefined;
  onDecisionAnswered?: ((event: AgentEvent<DecisionAnsweredEventData>) => void) | undefined;
  onDoomLoopDetected?: ((event: AgentEvent<DoomLoopDetectedEventData>) => void) | undefined;
  onDoomLoopIntervened?: ((event: AgentEvent<DoomLoopIntervenedEventData>) => void) | undefined;
  // Environment variable handlers
  onEnvVarRequested?: ((event: AgentEvent<EnvVarRequestedEventData>) => void) | undefined;
  onEnvVarProvided?: ((event: AgentEvent<EnvVarProvidedEventData>) => void) | undefined;
  // Skill execution handlers (L2 layer)
  onSkillMatched?: ((event: AgentEvent<SkillMatchedEventData>) => void) | undefined;
  onSkillExecutionStart?: ((event: AgentEvent<SkillExecutionStartEventData>) => void) | undefined;
  onSkillToolStart?: ((event: AgentEvent<SkillToolStartEventData>) => void) | undefined;
  onSkillToolResult?: ((event: AgentEvent<SkillToolResultEventData>) => void) | undefined;
  onSkillExecutionComplete?:
    | ((event: AgentEvent<SkillExecutionCompleteEventData>) => void)
    | undefined;
  onSkillFallback?: ((event: AgentEvent<SkillFallbackEventData>) => void) | undefined;
  // Artifact handlers
  onArtifactCreated?: ((event: AgentEvent<ArtifactCreatedEventData>) => void) | undefined;
  onArtifactReady?: ((event: AgentEvent<ArtifactReadyEventData>) => void) | undefined;
  onArtifactError?: ((event: AgentEvent<ArtifactErrorEventData>) => void) | undefined;
  onArtifactsBatch?: ((event: AgentEvent<ArtifactsBatchEventData>) => void) | undefined;
  // Suggestion handlers
  onSuggestions?: ((event: AgentEvent<SuggestionsEventData>) => void) | undefined;
  // Artifact lifecycle handlers
  onArtifactOpen?: ((event: AgentEvent<ArtifactOpenEventData>) => void) | undefined;
  onArtifactUpdate?: ((event: AgentEvent<ArtifactUpdateEventData>) => void) | undefined;
  onArtifactClose?: ((event: AgentEvent<ArtifactCloseEventData>) => void) | undefined;
  // Context management handlers
  onContextCompressed?: ((event: AgentEvent<ContextCompressedEventData>) => void) | undefined;
  onContextStatus?: ((event: AgentEvent<ContextStatusEventData>) => void) | undefined;
  // Title generation handlers
  onTitleGenerated?: ((event: AgentEvent<TitleGeneratedEventData>) => void) | undefined;
  // Plan Mode execution handlers (deprecated - kept for backward compatibility)
  onPlanExecutionStart?: ((event: AgentEvent<PlanExecutionStartEvent>) => void) | undefined;
  onPlanExecutionComplete?: ((event: AgentEvent<PlanExecutionCompleteEvent>) => void) | undefined;
  onReflectionComplete?: ((event: AgentEvent<ReflectionCompleteEvent>) => void) | undefined;
  // Plan Mode change handler
  onPlanModeChanged?: ((event: AgentEvent) => void) | undefined;
  // Plan Mode HITL handlers (legacy, kept for backward compatibility)
  onPlanSuggested?: ((event: AgentEvent) => void) | undefined;
  onPlanExplorationStarted?: ((event: AgentEvent) => void) | undefined;
  onPlanExplorationCompleted?: ((event: AgentEvent) => void) | undefined;
  onPlanDraftCreated?: ((event: AgentEvent) => void) | undefined;
  onPlanApproved?: ((event: AgentEvent) => void) | undefined;
  onPlanRejected?: ((event: AgentEvent) => void) | undefined;
  onPlanCancelled?: ((event: AgentEvent) => void) | undefined;
  onWorkPlanCreated?: ((event: AgentEvent) => void) | undefined;
  onWorkPlanStepStarted?: ((event: AgentEvent) => void) | undefined;
  onWorkPlanStepCompleted?: ((event: AgentEvent) => void) | undefined;
  onWorkPlanStepFailed?: ((event: AgentEvent) => void) | undefined;
  onWorkPlanCompleted?: ((event: AgentEvent) => void) | undefined;
  onWorkPlanFailed?: ((event: AgentEvent) => void) | undefined;
  // Permission handlers
  onPermissionAsked?: ((event: AgentEvent<PermissionAskedEventData>) => void) | undefined;
  onPermissionReplied?: ((event: AgentEvent<PermissionRepliedEventData>) => void) | undefined;
  // Cost tracking handlers
  onCostUpdate?: ((event: AgentEvent<CostUpdateEventData>) => void) | undefined;
  // Sandbox handlers (unified WebSocket)
  onSandboxCreated?: ((event: AgentEvent<SandboxEventData>) => void) | undefined;
  onSandboxTerminated?: ((event: AgentEvent<SandboxEventData>) => void) | undefined;
  onSandboxStatus?: ((event: AgentEvent<SandboxEventData>) => void) | undefined;
  onDesktopStarted?: ((event: AgentEvent<SandboxEventData>) => void) | undefined;
  onDesktopStopped?: ((event: AgentEvent<SandboxEventData>) => void) | undefined;
  onTerminalStarted?: ((event: AgentEvent<SandboxEventData>) => void) | undefined;
  onTerminalStopped?: ((event: AgentEvent<SandboxEventData>) => void) | undefined;
  // SubAgent handlers (L3 layer)
  onSubAgentRouted?: ((event: AgentEvent<SubAgentRoutedEventData>) => void) | undefined;
  onSubAgentStarted?: ((event: AgentEvent<SubAgentStartedEventData>) => void) | undefined;
  onSubAgentCompleted?: ((event: AgentEvent<SubAgentCompletedEventData>) => void) | undefined;
  onSubAgentFailed?: ((event: AgentEvent<SubAgentFailedEventData>) => void) | undefined;
  onSubAgentQueued?: ((event: AgentEvent<SubAgentQueuedEventData>) => void) | undefined;
  onSubAgentKilled?: ((event: AgentEvent<SubAgentKilledEventData>) => void) | undefined;
  onSubAgentSteered?: ((event: AgentEvent<SubAgentSteeredEventData>) => void) | undefined;
  onToolPolicyDenied?: ((event: AgentEvent<ToolPolicyDeniedEventData>) => void) | undefined;
  onSubAgentDepthLimited?: ((event: AgentEvent<SubAgentDepthLimitedEventData>) => void) | undefined;
  onSubAgentSessionUpdate?:
    | ((event: AgentEvent<SubAgentSessionUpdateEventData>) => void)
    | undefined;
  onParallelStarted?: ((event: AgentEvent<ParallelStartedEventData>) => void) | undefined;
  onParallelCompleted?: ((event: AgentEvent<ParallelCompletedEventData>) => void) | undefined;
  onChainStarted?: ((event: AgentEvent<ChainStartedEventData>) => void) | undefined;
  onChainStepStarted?: ((event: AgentEvent<ChainStepStartedEventData>) => void) | undefined;
  onChainStepCompleted?: ((event: AgentEvent<ChainStepCompletedEventData>) => void) | undefined;
  onChainCompleted?: ((event: AgentEvent<ChainCompletedEventData>) => void) | undefined;
  onBackgroundLaunched?: ((event: AgentEvent<BackgroundLaunchedEventData>) => void) | undefined;
  // Multi-agent lifecycle handlers (L4 layer)
  onAgentSpawned?: ((event: AgentEvent<AgentSpawnedEventData>) => void) | undefined;
  onAgentCompleted?: ((event: AgentEvent<AgentCompletedEventData>) => void) | undefined;
  onAgentStopped?: ((event: AgentEvent<AgentStoppedEventData>) => void) | undefined;
  // Graph orchestration handlers (multi-agent DAG)
  onGraphRunStarted?: ((event: AgentEvent<GraphRunStartedEventData>) => void) | undefined;
  onGraphRunCompleted?: ((event: AgentEvent<GraphRunCompletedEventData>) => void) | undefined;
  onGraphRunFailed?: ((event: AgentEvent<GraphRunFailedEventData>) => void) | undefined;
  onGraphRunCancelled?: ((event: AgentEvent<GraphRunCancelledEventData>) => void) | undefined;
  onGraphNodeStarted?: ((event: AgentEvent<GraphNodeStartedEventData>) => void) | undefined;
  onGraphNodeCompleted?: ((event: AgentEvent<GraphNodeCompletedEventData>) => void) | undefined;
  onGraphNodeFailed?: ((event: AgentEvent<GraphNodeFailedEventData>) => void) | undefined;
  onGraphNodeSkipped?: ((event: AgentEvent<GraphNodeSkippedEventData>) => void) | undefined;
  onGraphHandoff?: ((event: AgentEvent<GraphHandoffEventData>) => void) | undefined;
  onExecutionPathDecided?: ((event: AgentEvent<ExecutionPathDecidedEventData>) => void) | undefined;
  onSelectionTrace?: ((event: AgentEvent<SelectionTraceEventData>) => void) | undefined;
  onPolicyFiltered?: ((event: AgentEvent<PolicyFilteredEventData>) => void) | undefined;
  onToolsetChanged?: ((event: AgentEvent<ToolsetChangedEventData>) => void) | undefined;
  // Task list handlers
  onTaskListUpdated?: ((event: AgentEvent<TaskListUpdatedEventData>) => void) | undefined;
  onTaskUpdated?: ((event: AgentEvent<TaskUpdatedEventData>) => void) | undefined;
  // Task timeline handlers
  onTaskStart?: ((event: AgentEvent<TaskStartEventData>) => void) | undefined;
  onTaskComplete?: ((event: AgentEvent<TaskCompleteEventData>) => void) | undefined;
  onModelSwitchRequested?: ((event: AgentEvent<ModelSwitchRequestedEventData>) => void) | undefined;
  onModelOverrideRejected?:
    | ((event: AgentEvent<ModelOverrideRejectedEventData>) => void)
    | undefined;
  // MCP App handlers
  onMCPAppResult?: ((event: AgentEvent) => void) | undefined;
  onMCPAppRegistered?: ((event: AgentEvent) => void) | undefined;
  // Canvas handlers (A2UI deep integration)
  onCanvasUpdated?: ((event: AgentEvent<CanvasUpdatedEventData>) => void) | undefined;
  // A2UI interactive action handlers
  onA2UIActionAsked?: ((event: AgentEvent<A2UIActionAskedEventData>) => void) | undefined;
  // Memory handlers (auto-recall / auto-capture)
  onMemoryRecalled?: ((event: AgentEvent<MemoryRecalledEventData>) => void) | undefined;
  onMemoryCaptured?: ((event: AgentEvent<MemoryCapturedEventData>) => void) | undefined;
  // Agent definition management handlers (self-creation tool)
  onAgentDefinitionCreated?: ((event: AgentEvent) => void) | undefined;
  onAgentDefinitionUpdated?: ((event: AgentEvent) => void) | undefined;
  onAgentDefinitionDeleted?: ((event: AgentEvent) => void) | undefined;
  // Terminal handlers
  onComplete?: ((event: AgentEvent<CompleteEventData>) => void) | undefined;
  onError?: ((event: AgentEvent<ErrorEventData>) => void) | undefined;
  /** Called when LLM is retrying after a transient error (e.g., rate limit) */
  onRetry?: ((event: AgentEvent<RetryEventData>) => void) | undefined;
  onClose?: (() => void) | undefined;
}
