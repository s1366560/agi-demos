import { logger } from '../../utils/logger';

import type { ServerMessage } from './types';
import type {
  AgentEvent,
  AgentEventType,
  AgentStreamHandler,
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
  PermissionAskedEventData,
  PermissionRepliedEventData,
  CostUpdateEventData,
  SandboxEventData,
  CompleteEventData,
  TitleGeneratedEventData,
  ErrorEventData,
  RetryEventData,
  SkillMatchedEventData,
  SkillExecutionStartEventData,
  SkillToolStartEventData,
  SkillToolResultEventData,
  SkillExecutionCompleteEventData,
  SkillFallbackEventData,
  ContextCompressedEventData,
  ContextStatusEventData,
  PlanExecutionStartEvent,
  PlanExecutionCompleteEvent,
  ReflectionCompleteEvent,
  ArtifactCreatedEventData,
  ArtifactReadyEventData,
  ArtifactErrorEventData,
  ArtifactsBatchEventData,
  SuggestionsEventData,
  ArtifactOpenEventData,
  ArtifactUpdateEventData,
  ArtifactCloseEventData,
  SubAgentRoutedEventData,
  SubAgentStartedEventData,
  SubAgentCompletedEventData,
  SubAgentFailedEventData,
  SubAgentRunEventData,
  SubAgentAnnounceGiveupEventData,
  SubAgentAnnounceRetryEventData,
  SubAgentSessionMessageSentEventData,
  SubAgentSessionSpawnedEventData,
  SubAgentQueuedEventData,
  SubAgentKilledEventData,
  SubAgentSteeredEventData,
  SubAgentDepthLimitedEventData,
  SubAgentSessionUpdateEventData,
  ParallelStartedEventData,
  ParallelCompletedEventData,
  ChainStartedEventData,
  ChainStepStartedEventData,
  ChainStepCompletedEventData,
  ChainCompletedEventData,
  BackgroundLaunchedEventData,
  TaskListUpdatedEventData,
  TaskUpdatedEventData,
  TaskStartEventData,
  TaskCompleteEventData,
  CanvasUpdatedEventData,
  A2UIActionAskedEventData,
  MemoryRecalledEventData,
  MemoryCapturedEventData,
  ExecutionPathDecidedEventData,
  SelectionTraceEventData,
  PolicyFilteredEventData,
  ToolsetChangedEventData,
} from '../../types/agent';

export function routeSubagentLifecycleMessage(message: ServerMessage, getHandler: (conversationId: string) => AgentStreamHandler | undefined): void {

    const payload =
      message.data && typeof message.data === 'object'
        ? (message.data as Record<string, unknown>)
        : null;
    if (!payload) {
      return;
    }

    const lifecycleType = typeof payload.type === 'string' ? payload.type : '';
    const conversationId =
      typeof message.conversation_id === 'string' && message.conversation_id
        ? message.conversation_id
        : typeof payload.conversation_id === 'string'
          ? payload.conversation_id
          : '';
    if (!conversationId) {
      return;
    }

    const handler = getHandler(conversationId);
    if (!handler) {
      logger.debug(
        '[AgentWS] No handler found for subagent lifecycle conversation:',
        conversationId
      );
      return;
    }

    const runId = typeof payload.run_id === 'string' ? payload.run_id : '';
    const subagentName = typeof payload.subagent_name === 'string' ? payload.subagent_name : '';
    const status = typeof payload.status === 'string' ? payload.status : '';
    const summary = typeof payload.summary === 'string' ? payload.summary : '';
    const error = typeof payload.error === 'string' ? payload.error : '';

    if (lifecycleType === 'subagent_spawning') {
      routeToHandler(
        'subagent_started',
        {
          subagent_id: runId,
          subagent_name: subagentName,
          task: 'Spawning detached session',
        },
        handler
      );
      return;
    }

    if (lifecycleType === 'subagent_spawned') {
      routeToHandler(
        'subagent_session_spawned',
        {
          conversation_id: conversationId,
          run_id: runId,
          subagent_name: subagentName,
        },
        handler
      );
      return;
    }

    if (lifecycleType === 'subagent_ended') {
      const runEvent: SubAgentRunEventData = {
        run_id: runId,
        conversation_id: conversationId,
        subagent_name: subagentName,
        task: 'Detached session',
        status: status || 'unknown',
        summary: summary || undefined,
      };
      if (status === 'completed') {
        routeToHandler('subagent_run_completed', runEvent, handler);
        return;
      }
      routeToHandler(
        'subagent_run_failed',
        {
          ...runEvent,
          error: error || `Subagent ended with status: ${status || 'unknown'}`,
        },
        handler
      );
    }
  }

export function routeToHandler(eventType: AgentEventType, data: unknown, handler: AgentStreamHandler): void {

    logger.debug('[AgentWS] routeToHandler:', { eventType, hasData: !!data });
    const event = { type: eventType, data };

    switch (eventType) {
      case 'message':
        handler.onMessage?.(event as AgentEvent<MessageEventData>);
        break;
      case 'thought':
        handler.onThought?.(event as AgentEvent<ThoughtEventData>);
        break;
      case 'thought_delta':
        // Route thought_delta to onThoughtDelta handler for incremental thought updates
        handler.onThoughtDelta?.(event as AgentEvent<ThoughtDeltaEventData>);
        break;
      case 'work_plan':
        handler.onWorkPlan?.(event as AgentEvent<WorkPlanEventData>);
        break;
      case 'pattern_match':
        handler.onPatternMatch?.(event as AgentEvent<PatternMatchEventData>);
        break;
      case 'act':
        handler.onAct?.(event as AgentEvent<ActEventData>);
        break;
      case 'act_delta':
        handler.onActDelta?.(event as AgentEvent<ActDeltaEventData>);
        break;
      case 'observe':
        handler.onObserve?.(event as AgentEvent<ObserveEventData>);
        break;
      case 'text_start':
        handler.onTextStart?.();
        break;
      case 'text_delta':
        handler.onTextDelta?.(event as AgentEvent<TextDeltaEventData>);
        break;
      case 'text_end':
        handler.onTextEnd?.(event as AgentEvent<TextEndEventData>);
        break;
      case 'clarification_asked':
        handler.onClarificationAsked?.(event as AgentEvent<ClarificationAskedEventData>);
        break;
      case 'clarification_answered':
        handler.onClarificationAnswered?.(event as AgentEvent<ClarificationAnsweredEventData>);
        break;
      case 'decision_asked':
        handler.onDecisionAsked?.(event as AgentEvent<DecisionAskedEventData>);
        break;
      case 'decision_answered':
        handler.onDecisionAnswered?.(event as AgentEvent<DecisionAnsweredEventData>);
        break;
      // Environment variable events
      case 'env_var_requested':
        handler.onEnvVarRequested?.(event as AgentEvent<EnvVarRequestedEventData>);
        break;
      case 'env_var_provided':
        handler.onEnvVarProvided?.(event as AgentEvent<EnvVarProvidedEventData>);
        break;
      case 'complete':
        handler.onComplete?.(event as AgentEvent<CompleteEventData>);
        // Clean up handler after completion
        // Note: Don't remove immediately, some events might still come
        break;
      case 'title_generated':
        handler.onTitleGenerated?.(event as AgentEvent<TitleGeneratedEventData>);
        break;
      case 'error':
        handler.onError?.(event as AgentEvent<ErrorEventData>);
        break;
      case 'retry':
        handler.onRetry?.(event as AgentEvent<RetryEventData>);
        break;
      // Skill execution events (L2 layer)
      case 'skill_matched':
        handler.onSkillMatched?.(event as AgentEvent<SkillMatchedEventData>);
        break;
      case 'skill_execution_start':
        handler.onSkillExecutionStart?.(event as AgentEvent<SkillExecutionStartEventData>);
        break;
      case 'skill_tool_start':
        handler.onSkillToolStart?.(event as AgentEvent<SkillToolStartEventData>);
        break;
      case 'skill_tool_result':
        handler.onSkillToolResult?.(event as AgentEvent<SkillToolResultEventData>);
        break;
      case 'skill_execution_complete':
        handler.onSkillExecutionComplete?.(event as AgentEvent<SkillExecutionCompleteEventData>);
        break;
      case 'skill_fallback':
        handler.onSkillFallback?.(event as AgentEvent<SkillFallbackEventData>);
        break;
      // Artifact events
      case 'artifact_created':
        handler.onArtifactCreated?.(event as AgentEvent<ArtifactCreatedEventData>);
        break;
      case 'artifact_ready':
        handler.onArtifactReady?.(event as AgentEvent<ArtifactReadyEventData>);
        break;
      case 'artifact_error':
        handler.onArtifactError?.(event as AgentEvent<ArtifactErrorEventData>);
        break;
      case 'artifacts_batch':
        handler.onArtifactsBatch?.(event as AgentEvent<ArtifactsBatchEventData>);
        break;
      // Suggestion events
      case 'suggestions':
        handler.onSuggestions?.(event as AgentEvent<SuggestionsEventData>);
        break;
      // Artifact lifecycle events
      case 'artifact_open':
        handler.onArtifactOpen?.(event as AgentEvent<ArtifactOpenEventData>);
        break;
      case 'artifact_update':
        handler.onArtifactUpdate?.(event as AgentEvent<ArtifactUpdateEventData>);
        break;
      case 'artifact_close':
        handler.onArtifactClose?.(event as AgentEvent<ArtifactCloseEventData>);
        break;
      // Context management events
      case 'context_compressed':
        handler.onContextCompressed?.(event as AgentEvent<ContextCompressedEventData>);
        break;
      case 'context_status':
        handler.onContextStatus?.(event as AgentEvent<ContextStatusEventData>);
        break;
      // Plan Mode events (legacy no-ops)
      case 'plan_mode_enter':
      case 'plan_mode_exit':
      case 'plan_created':
      case 'plan_updated':
        break;
      // Plan Mode HITL events
      case 'plan_suggested':
        handler.onPlanSuggested?.(event as AgentEvent);
        break;
      case 'plan_exploration_started':
        handler.onPlanExplorationStarted?.(event as AgentEvent);
        break;
      case 'plan_exploration_completed':
        handler.onPlanExplorationCompleted?.(event as AgentEvent);
        break;
      case 'plan_draft_created':
        handler.onPlanDraftCreated?.(event as AgentEvent);
        break;
      case 'plan_approved':
        handler.onPlanApproved?.(event as AgentEvent);
        break;
      case 'plan_rejected':
        handler.onPlanRejected?.(event as AgentEvent);
        break;
      case 'plan_cancelled':
        handler.onPlanCancelled?.(event as AgentEvent);
        break;
      case 'workplan_created':
        handler.onWorkPlanCreated?.(event as AgentEvent);
        break;
      case 'workplan_step_started':
        handler.onWorkPlanStepStarted?.(event as AgentEvent);
        break;
      case 'workplan_step_completed':
        handler.onWorkPlanStepCompleted?.(event as AgentEvent);
        break;
      case 'workplan_step_failed':
        handler.onWorkPlanStepFailed?.(event as AgentEvent);
        break;
      case 'workplan_completed':
        handler.onWorkPlanCompleted?.(event as AgentEvent);
        break;
      case 'workplan_failed':
        handler.onWorkPlanFailed?.(event as AgentEvent);
        break;
      // Plan Mode execution events
      case 'plan_execution_start':
        handler.onPlanExecutionStart?.(event as AgentEvent<PlanExecutionStartEvent>);
        break;
      case 'plan_execution_complete':
        handler.onPlanExecutionComplete?.(event as AgentEvent<PlanExecutionCompleteEvent>);
        break;
      case 'plan_mode_changed':
        handler.onPlanModeChanged?.(event as AgentEvent);
        break;
      case 'reflection_complete':
        handler.onReflectionComplete?.(event as AgentEvent<ReflectionCompleteEvent>);
        break;
      // Extended Plan Mode events (no-op: plan mode system removed)
      case 'plan_status_changed':
      case 'plan_step_ready':
      case 'plan_step_complete':
      case 'plan_step_skipped':
      case 'plan_snapshot_created':
      case 'plan_rollback':
      case 'adjustment_applied':
        break;
      // Doom loop events
      case 'doom_loop_detected':
        handler.onDoomLoopDetected?.(event as AgentEvent<DoomLoopDetectedEventData>);
        break;
      case 'doom_loop_intervened':
        handler.onDoomLoopIntervened?.(event as AgentEvent<DoomLoopIntervenedEventData>);
        break;
      // Permission events
      case 'permission_asked':
        handler.onPermissionAsked?.(event as AgentEvent<PermissionAskedEventData>);
        break;
      case 'permission_replied':
        handler.onPermissionReplied?.(event as AgentEvent<PermissionRepliedEventData>);
        break;
      // Cost tracking events
      case 'cost_update':
        handler.onCostUpdate?.(event as AgentEvent<CostUpdateEventData>);
        break;
      // Sandbox events (unified WebSocket)
      case 'sandbox_created':
        handler.onSandboxCreated?.(event as AgentEvent<SandboxEventData>);
        break;
      case 'sandbox_terminated':
        handler.onSandboxTerminated?.(event as AgentEvent<SandboxEventData>);
        break;
      case 'sandbox_status':
        handler.onSandboxStatus?.(event as AgentEvent<SandboxEventData>);
        break;
      case 'desktop_started':
        handler.onDesktopStarted?.(event as AgentEvent<SandboxEventData>);
        break;
      case 'desktop_stopped':
        handler.onDesktopStopped?.(event as AgentEvent<SandboxEventData>);
        break;
      case 'terminal_started':
        handler.onTerminalStarted?.(event as AgentEvent<SandboxEventData>);
        break;
      case 'terminal_stopped':
        handler.onTerminalStopped?.(event as AgentEvent<SandboxEventData>);
        break;
      // SubAgent events (L3 layer)
      case 'subagent_routed':
        handler.onSubAgentRouted?.(event as AgentEvent<SubAgentRoutedEventData>);
        break;
      case 'subagent_started':
        handler.onSubAgentStarted?.(event as AgentEvent<SubAgentStartedEventData>);
        break;
      case 'subagent_completed':
        handler.onSubAgentCompleted?.(event as AgentEvent<SubAgentCompletedEventData>);
        break;
      case 'subagent_failed':
        handler.onSubAgentFailed?.(event as AgentEvent<SubAgentFailedEventData>);
        break;
      case 'subagent_run_started': {
        const data = event.data as SubAgentRunEventData;
        handler.onSubAgentStarted?.({
          ...event,
          type: 'subagent_started',
          data: {
            subagent_id: data.run_id,
            subagent_name: data.subagent_name,
            task: data.task,
          },
        } as AgentEvent<SubAgentStartedEventData>);
        break;
      }
      case 'subagent_run_completed': {
        const data = event.data as SubAgentRunEventData;
        handler.onSubAgentCompleted?.({
          ...event,
          type: 'subagent_completed',
          data: {
            subagent_id: data.run_id,
            subagent_name: data.subagent_name,
            summary: data.summary || '',
            tokens_used: data.tokens_used ?? undefined,
            execution_time_ms: data.execution_time_ms ?? undefined,
            success: true,
          },
        } as AgentEvent<SubAgentCompletedEventData>);
        break;
      }
      case 'subagent_run_failed': {
        const data = event.data as SubAgentRunEventData;
        handler.onSubAgentFailed?.({
          ...event,
          type: 'subagent_failed',
          data: {
            subagent_id: data.run_id,
            subagent_name: data.subagent_name,
            error: data.error || 'Unknown error',
          },
        } as AgentEvent<SubAgentFailedEventData>);
        break;
      }
      case 'subagent_killed':
        handler.onSubAgentKilled?.(event as AgentEvent<SubAgentKilledEventData>);
        break;
      case 'subagent_session_spawned': {
        const data = event.data as SubAgentSessionSpawnedEventData;
        handler.onSubAgentStarted?.({
          ...event,
          type: 'subagent_started',
          data: {
            subagent_id: data.run_id,
            subagent_name: data.subagent_name,
            task: 'Session spawned',
          },
        } as AgentEvent<SubAgentStartedEventData>);
        break;
      }
      case 'subagent_session_message_sent': {
        const data = event.data as SubAgentSessionMessageSentEventData;
        handler.onSubAgentStarted?.({
          ...event,
          type: 'subagent_started',
          data: {
            subagent_id: data.run_id,
            subagent_name: data.subagent_name,
            task: `Follow-up sent from ${data.parent_run_id}`,
          },
        } as AgentEvent<SubAgentStartedEventData>);
        break;
      }
      case 'subagent_announce_retry': {
        const data = event.data as SubAgentAnnounceRetryEventData;
        // Route to dedicated retry handler (no longer collapsed to started)
        handler.onSubAgentStarted?.({
          ...event,
          type: 'subagent_started',
          data: {
            subagent_id: data.run_id,
            subagent_name: data.subagent_name,
            task: `Retry ${data.attempt}: ${data.error}`,
          },
        } as AgentEvent<SubAgentStartedEventData>);
        break;
      }
      case 'subagent_announce_giveup': {
        const data = event.data as SubAgentAnnounceGiveupEventData;
        handler.onSubAgentFailed?.({
          ...event,
          type: 'subagent_failed',
          data: {
            subagent_id: data.run_id,
            subagent_name: data.subagent_name,
            error: `Give up after ${data.attempts} attempts: ${data.error}`,
          },
        } as AgentEvent<SubAgentFailedEventData>);
        break;
      }
      case 'subagent_steered':
        handler.onSubAgentSteered?.(event as AgentEvent<SubAgentSteeredEventData>);
        break;
      case 'subagent_queued':
        handler.onSubAgentQueued?.(event as AgentEvent<SubAgentQueuedEventData>);
        break;
      case 'subagent_depth_limited':
        handler.onSubAgentDepthLimited?.(event as AgentEvent<SubAgentDepthLimitedEventData>);
        break;
      case 'subagent_session_update':
        handler.onSubAgentSessionUpdate?.(event as AgentEvent<SubAgentSessionUpdateEventData>);
        break;
      case 'parallel_started':
        handler.onParallelStarted?.(event as AgentEvent<ParallelStartedEventData>);
        break;
      case 'parallel_completed':
        handler.onParallelCompleted?.(event as AgentEvent<ParallelCompletedEventData>);
        break;
      case 'chain_started':
        handler.onChainStarted?.(event as AgentEvent<ChainStartedEventData>);
        break;
      case 'chain_step_started':
        handler.onChainStepStarted?.(event as AgentEvent<ChainStepStartedEventData>);
        break;
      case 'chain_step_completed':
        handler.onChainStepCompleted?.(event as AgentEvent<ChainStepCompletedEventData>);
        break;
      case 'chain_completed':
        handler.onChainCompleted?.(event as AgentEvent<ChainCompletedEventData>);
        break;
      case 'background_launched':
        handler.onBackgroundLaunched?.(event as AgentEvent<BackgroundLaunchedEventData>);
        break;
      case 'execution_path_decided':
        handler.onExecutionPathDecided?.(event as AgentEvent<ExecutionPathDecidedEventData>);
        break;
      case 'selection_trace':
        handler.onSelectionTrace?.(event as AgentEvent<SelectionTraceEventData>);
        break;
      case 'policy_filtered':
        handler.onPolicyFiltered?.(event as AgentEvent<PolicyFilteredEventData>);
        break;
      case 'toolset_changed':
        handler.onToolsetChanged?.(event as AgentEvent<ToolsetChangedEventData>);
        break;
      // Task list events
      case 'task_list_updated':
        console.log(
          '[TaskSync] routeToHandler: task_list_updated, hasHandler:',
          !!handler.onTaskListUpdated
        );
        handler.onTaskListUpdated?.(event as AgentEvent<TaskListUpdatedEventData>);
        break;
      case 'task_updated':
        console.log(
          '[TaskSync] routeToHandler: task_updated, hasHandler:',
          !!handler.onTaskUpdated
        );
        handler.onTaskUpdated?.(event as AgentEvent<TaskUpdatedEventData>);
        break;
      // Task timeline events
      case 'task_start':
        handler.onTaskStart?.(event as AgentEvent<TaskStartEventData>);
        break;
      case 'task_complete':
        handler.onTaskComplete?.(event as AgentEvent<TaskCompleteEventData>);
        break;
      // MCP App events
      case 'mcp_app_result':
        handler.onMCPAppResult?.(event as AgentEvent);
        break;
      case 'mcp_app_registered':
        handler.onMCPAppRegistered?.(event as AgentEvent);
        break;
      // Memory events (auto-recall / auto-capture)
      case 'memory_recalled':
        handler.onMemoryRecalled?.(event as AgentEvent<MemoryRecalledEventData>);
        break;
      case 'memory_captured':
        handler.onMemoryCaptured?.(event as AgentEvent<MemoryCapturedEventData>);
        break;
      // Canvas events (A2UI deep integration)
      case 'canvas_updated':
        handler.onCanvasUpdated?.(event as AgentEvent<CanvasUpdatedEventData>);
        break;
      // A2UI interactive action events
      case 'a2ui_action_asked':
        handler.onA2UIActionAsked?.(event as AgentEvent<A2UIActionAskedEventData>);
        break;
    }
}
