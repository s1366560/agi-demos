use serde::{Deserialize, Serialize};

/// Coarse grouping used for filtering/fan-out, mirroring Python `EventCategory`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum EventCategory {
    Agent,
    Hitl,
    Sandbox,
    System,
    Message,
}

impl EventCategory {
    /// The exact wire string (matches Python `EventCategory` values).
    pub fn as_str(&self) -> &'static str {
        match self {
            EventCategory::Agent => "agent",
            EventCategory::Hitl => "hitl",
            EventCategory::Sandbox => "sandbox",
            EventCategory::System => "system",
            EventCategory::Message => "message",
        }
    }
}

/// The unified agent event taxonomy — the single source of truth for event
/// `type` strings on the wire. Values match Python `AgentEventType` exactly so a
/// Rust producer and the existing frontend/`EventConverter` agree byte-for-byte.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum AgentEventType {
    #[serde(rename = "status")]
    Status,
    #[serde(rename = "start")]
    Start,
    #[serde(rename = "complete")]
    Complete,
    #[serde(rename = "error")]
    Error,
    #[serde(rename = "thought_start")]
    ThoughtStart,
    #[serde(rename = "thought")]
    Thought,
    #[serde(rename = "thought_delta")]
    ThoughtDelta,
    #[serde(rename = "act")]
    Act,
    #[serde(rename = "act_delta")]
    ActDelta,
    #[serde(rename = "observe")]
    Observe,
    #[serde(rename = "text_start")]
    TextStart,
    #[serde(rename = "text_delta")]
    TextDelta,
    #[serde(rename = "text_end")]
    TextEnd,
    #[serde(rename = "message")]
    Message,
    #[serde(rename = "user_message")]
    UserMessage,
    #[serde(rename = "assistant_message")]
    AssistantMessage,
    #[serde(rename = "permission_asked")]
    PermissionAsked,
    #[serde(rename = "permission_replied")]
    PermissionReplied,
    #[serde(rename = "doom_loop_detected")]
    DoomLoopDetected,
    #[serde(rename = "doom_loop_intervened")]
    DoomLoopIntervened,
    #[serde(rename = "clarification_asked")]
    ClarificationAsked,
    #[serde(rename = "clarification_answered")]
    ClarificationAnswered,
    #[serde(rename = "decision_asked")]
    DecisionAsked,
    #[serde(rename = "decision_answered")]
    DecisionAnswered,
    #[serde(rename = "env_var_requested")]
    EnvVarRequested,
    #[serde(rename = "env_var_provided")]
    EnvVarProvided,
    #[serde(rename = "cost_update")]
    CostUpdate,
    #[serde(rename = "retry")]
    Retry,
    #[serde(rename = "compact_needed")]
    CompactNeeded,
    #[serde(rename = "context_compressed")]
    ContextCompressed,
    #[serde(rename = "context_status")]
    ContextStatus,
    #[serde(rename = "context_summary_generated")]
    ContextSummaryGenerated,
    #[serde(rename = "memory_recalled")]
    MemoryRecalled,
    #[serde(rename = "memory_captured")]
    MemoryCaptured,
    #[serde(rename = "pattern_match")]
    PatternMatch,
    #[serde(rename = "skill_matched")]
    SkillMatched,
    #[serde(rename = "skill_execution_start")]
    SkillExecutionStart,
    #[serde(rename = "skill_execution_complete")]
    SkillExecutionComplete,
    #[serde(rename = "skill_fallback")]
    SkillFallback,
    #[serde(rename = "title_generated")]
    TitleGenerated,
    #[serde(rename = "sandbox_created")]
    SandboxCreated,
    #[serde(rename = "sandbox_terminated")]
    SandboxTerminated,
    #[serde(rename = "sandbox_status")]
    SandboxStatus,
    #[serde(rename = "desktop_started")]
    DesktopStarted,
    #[serde(rename = "desktop_stopped")]
    DesktopStopped,
    #[serde(rename = "desktop_status")]
    DesktopStatus,
    #[serde(rename = "terminal_started")]
    TerminalStarted,
    #[serde(rename = "terminal_stopped")]
    TerminalStopped,
    #[serde(rename = "terminal_status")]
    TerminalStatus,
    #[serde(rename = "http_service_started")]
    HttpServiceStarted,
    #[serde(rename = "http_service_updated")]
    HttpServiceUpdated,
    #[serde(rename = "http_service_stopped")]
    HttpServiceStopped,
    #[serde(rename = "http_service_error")]
    HttpServiceError,
    #[serde(rename = "suggestions")]
    Suggestions,
    #[serde(rename = "artifact_created")]
    ArtifactCreated,
    #[serde(rename = "artifact_ready")]
    ArtifactReady,
    #[serde(rename = "artifact_error")]
    ArtifactError,
    #[serde(rename = "artifacts_batch")]
    ArtifactsBatch,
    #[serde(rename = "artifact_open")]
    ArtifactOpen,
    #[serde(rename = "artifact_update")]
    ArtifactUpdate,
    #[serde(rename = "artifact_close")]
    ArtifactClose,
    #[serde(rename = "mcp_app_result")]
    McpAppResult,
    #[serde(rename = "mcp_app_registered")]
    McpAppRegistered,
    #[serde(rename = "subagent_routed")]
    SubagentRouted,
    #[serde(rename = "subagent_started")]
    SubagentStarted,
    #[serde(rename = "subagent_completed")]
    SubagentCompleted,
    #[serde(rename = "subagent_failed")]
    SubagentFailed,
    #[serde(rename = "subagent_spawning")]
    SubagentSpawning,
    #[serde(rename = "subagent_doom_loop")]
    SubagentDoomLoop,
    #[serde(rename = "subagent_retry")]
    SubagentRetry,
    #[serde(rename = "subagent_queued")]
    SubagentQueued,
    #[serde(rename = "subagent_killed")]
    SubagentKilled,
    #[serde(rename = "subagent_steered")]
    SubagentSteered,
    #[serde(rename = "subagent_depth_limited")]
    SubagentDepthLimited,
    #[serde(rename = "subagent_session_update")]
    SubagentSessionUpdate,
    #[serde(rename = "subagent_spawn_rejected")]
    SubagentSpawnRejected,
    #[serde(rename = "subagent_announce_retry")]
    SubagentAnnounceRetry,
    #[serde(rename = "subagent_orphan_detected")]
    SubagentOrphanDetected,
    #[serde(rename = "subagent_announce_sent")]
    SubagentAnnounceSent,
    #[serde(rename = "subagent_announce_received")]
    SubagentAnnounceReceived,
    #[serde(rename = "subagent_announce_expired")]
    SubagentAnnounceExpired,
    #[serde(rename = "tool_policy_denied")]
    ToolPolicyDenied,
    #[serde(rename = "cancelled")]
    Cancelled,
    #[serde(rename = "task_list_updated")]
    TaskListUpdated,
    #[serde(rename = "task_updated")]
    TaskUpdated,
    #[serde(rename = "task_start")]
    TaskStart,
    #[serde(rename = "task_complete")]
    TaskComplete,
    #[serde(rename = "tools_updated")]
    ToolsUpdated,
    #[serde(rename = "progress")]
    Progress,
    #[serde(rename = "elicitation_asked")]
    ElicitationAsked,
    #[serde(rename = "elicitation_answered")]
    ElicitationAnswered,
    #[serde(rename = "canvas_updated")]
    CanvasUpdated,
    #[serde(rename = "a2ui_action_asked")]
    A2uiActionAsked,
    #[serde(rename = "a2ui_action_answered")]
    A2uiActionAnswered,
    #[serde(rename = "plan_suggested")]
    PlanSuggested,
    #[serde(rename = "selection_trace")]
    SelectionTrace,
    #[serde(rename = "policy_filtered")]
    PolicyFiltered,
    #[serde(rename = "parallel_started")]
    ParallelStarted,
    #[serde(rename = "parallel_completed")]
    ParallelCompleted,
    #[serde(rename = "background_launched")]
    BackgroundLaunched,
    #[serde(rename = "agent_spawned")]
    AgentSpawned,
    #[serde(rename = "agent_completed")]
    AgentCompleted,
    #[serde(rename = "agent_message_sent")]
    AgentMessageSent,
    #[serde(rename = "agent_message_received")]
    AgentMessageReceived,
    #[serde(rename = "agent_stopped")]
    AgentStopped,
    #[serde(rename = "subagent_delegation")]
    SubagentDelegation,
    #[serde(rename = "context_compacted")]
    ContextCompacted,
    #[serde(rename = "session_forked")]
    SessionForked,
    #[serde(rename = "session_merged")]
    SessionMerged,
    #[serde(rename = "graph_run_started")]
    GraphRunStarted,
    #[serde(rename = "graph_run_completed")]
    GraphRunCompleted,
    #[serde(rename = "graph_run_failed")]
    GraphRunFailed,
    #[serde(rename = "graph_run_cancelled")]
    GraphRunCancelled,
    #[serde(rename = "graph_node_started")]
    GraphNodeStarted,
    #[serde(rename = "graph_node_completed")]
    GraphNodeCompleted,
    #[serde(rename = "graph_node_failed")]
    GraphNodeFailed,
    #[serde(rename = "graph_node_skipped")]
    GraphNodeSkipped,
    #[serde(rename = "graph_handoff")]
    GraphHandoff,
    #[serde(rename = "workspace_member_joined")]
    WorkspaceMemberJoined,
    #[serde(rename = "blackboard_post_created")]
    BlackboardPostCreated,
    #[serde(rename = "workspace_task_assigned")]
    WorkspaceTaskAssigned,
    #[serde(rename = "topology_updated")]
    TopologyUpdated,
    #[serde(rename = "workspace_task_created")]
    WorkspaceTaskCreated,
    #[serde(rename = "workspace_task_updated")]
    WorkspaceTaskUpdated,
    #[serde(rename = "workspace_task_deleted")]
    WorkspaceTaskDeleted,
    #[serde(rename = "workspace_task_status_changed")]
    WorkspaceTaskStatusChanged,
    #[serde(rename = "blackboard_post_updated")]
    BlackboardPostUpdated,
    #[serde(rename = "blackboard_post_deleted")]
    BlackboardPostDeleted,
    #[serde(rename = "blackboard_reply_created")]
    BlackboardReplyCreated,
    #[serde(rename = "blackboard_reply_updated")]
    BlackboardReplyUpdated,
    #[serde(rename = "blackboard_reply_deleted")]
    BlackboardReplyDeleted,
    #[serde(rename = "blackboard_file_created")]
    BlackboardFileCreated,
    #[serde(rename = "blackboard_file_updated")]
    BlackboardFileUpdated,
    #[serde(rename = "blackboard_file_deleted")]
    BlackboardFileDeleted,
    #[serde(rename = "blackboard_directory_deleted")]
    BlackboardDirectoryDeleted,
    #[serde(rename = "workspace_updated")]
    WorkspaceUpdated,
    #[serde(rename = "workspace_deleted")]
    WorkspaceDeleted,
    #[serde(rename = "workspace_member_updated")]
    WorkspaceMemberUpdated,
    #[serde(rename = "workspace_member_left")]
    WorkspaceMemberLeft,
    #[serde(rename = "workspace_agent_bound")]
    WorkspaceAgentBound,
    #[serde(rename = "workspace_agent_unbound")]
    WorkspaceAgentUnbound,
    #[serde(rename = "workspace_message_created")]
    WorkspaceMessageCreated,
    #[serde(rename = "conversation_participant_joined")]
    ConversationParticipantJoined,
    #[serde(rename = "conversation_participant_left")]
    ConversationParticipantLeft,
    #[serde(rename = "agent_task_assigned")]
    AgentTaskAssigned,
    #[serde(rename = "agent_task_refused")]
    AgentTaskRefused,
    #[serde(rename = "agent_human_input_requested")]
    AgentHumanInputRequested,
    #[serde(rename = "agent_escalated")]
    AgentEscalated,
    #[serde(rename = "agent_conflict_marked")]
    AgentConflictMarked,
    #[serde(rename = "agent_progress_declared")]
    AgentProgressDeclared,
    #[serde(rename = "agent_goal_completed")]
    AgentGoalCompleted,
    #[serde(rename = "agent_supervisor_verdict")]
    AgentSupervisorVerdict,
    #[serde(rename = "agent_decision_logged")]
    AgentDecisionLogged,
    #[serde(rename = "agent_conversation_finished")]
    AgentConversationFinished,
    #[serde(rename = "workspace_plan_updated")]
    WorkspacePlanUpdated,
    #[serde(rename = "workspace_goal_materialized")]
    WorkspaceGoalMaterialized,
    #[serde(rename = "workspace_decomposition_complete")]
    WorkspaceDecompositionComplete,
    #[serde(rename = "workspace_worker_dispatched")]
    WorkspaceWorkerDispatched,
    #[serde(rename = "workspace_worker_report_submitted")]
    WorkspaceWorkerReportSubmitted,
    #[serde(rename = "workspace_adjudication_complete")]
    WorkspaceAdjudicationComplete,
    #[serde(rename = "workspace_goal_completed")]
    WorkspaceGoalCompleted,
    #[serde(rename = "task_execution_session_updated")]
    TaskExecutionSessionUpdated,
    #[serde(rename = "task_execution_incident_opened")]
    TaskExecutionIncidentOpened,
    #[serde(rename = "task_recovery_action_started")]
    TaskRecoveryActionStarted,
    #[serde(rename = "task_recovery_action_completed")]
    TaskRecoveryActionCompleted,
}

impl AgentEventType {
    /// Category grouping. Mirrors Python `EVENT_CATEGORIES` with default `Agent`
    /// for the unmapped long-tail (Python `EVENT_CATEGORIES.get(t, AGENT)`).
    pub fn category(&self) -> EventCategory {
        match self {
            AgentEventType::Message => EventCategory::Message,
            AgentEventType::UserMessage => EventCategory::Message,
            AgentEventType::AssistantMessage => EventCategory::Message,
            AgentEventType::PermissionAsked => EventCategory::Hitl,
            AgentEventType::PermissionReplied => EventCategory::Hitl,
            AgentEventType::ClarificationAsked => EventCategory::Hitl,
            AgentEventType::ClarificationAnswered => EventCategory::Hitl,
            AgentEventType::DecisionAsked => EventCategory::Hitl,
            AgentEventType::DecisionAnswered => EventCategory::Hitl,
            AgentEventType::EnvVarRequested => EventCategory::Hitl,
            AgentEventType::EnvVarProvided => EventCategory::Hitl,
            AgentEventType::CostUpdate => EventCategory::System,
            AgentEventType::Retry => EventCategory::System,
            AgentEventType::CompactNeeded => EventCategory::System,
            AgentEventType::ContextCompressed => EventCategory::System,
            AgentEventType::ContextStatus => EventCategory::System,
            AgentEventType::ContextSummaryGenerated => EventCategory::System,
            AgentEventType::SandboxCreated => EventCategory::Sandbox,
            AgentEventType::SandboxTerminated => EventCategory::Sandbox,
            AgentEventType::SandboxStatus => EventCategory::Sandbox,
            AgentEventType::DesktopStarted => EventCategory::Sandbox,
            AgentEventType::DesktopStopped => EventCategory::Sandbox,
            AgentEventType::DesktopStatus => EventCategory::Sandbox,
            AgentEventType::TerminalStarted => EventCategory::Sandbox,
            AgentEventType::TerminalStopped => EventCategory::Sandbox,
            AgentEventType::TerminalStatus => EventCategory::Sandbox,
            AgentEventType::HttpServiceStarted => EventCategory::Sandbox,
            AgentEventType::HttpServiceUpdated => EventCategory::Sandbox,
            AgentEventType::HttpServiceStopped => EventCategory::Sandbox,
            AgentEventType::HttpServiceError => EventCategory::Sandbox,
            AgentEventType::ElicitationAsked => EventCategory::Hitl,
            AgentEventType::ElicitationAnswered => EventCategory::Hitl,
            AgentEventType::A2uiActionAsked => EventCategory::Hitl,
            AgentEventType::A2uiActionAnswered => EventCategory::Hitl,
            AgentEventType::ContextCompacted => EventCategory::System,
            _ => EventCategory::Agent,
        }
    }

    /// Streaming fragment not persisted to the event log (Python `DELTA_EVENT_TYPES`).
    pub fn is_delta(&self) -> bool {
        matches!(
            self,
            AgentEventType::ActDelta
                | AgentEventType::TextDelta
                | AgentEventType::TextEnd
                | AgentEventType::TextStart
                | AgentEventType::ThoughtDelta
                | AgentEventType::ThoughtStart
        )
    }

    /// Terminal event signalling stream completion (Python `TERMINAL_EVENT_TYPES`).
    pub fn is_terminal(&self) -> bool {
        matches!(
            self,
            AgentEventType::Cancelled | AgentEventType::Complete | AgentEventType::Error
        )
    }

    /// HITL event that blocks awaiting a human response (Python `HITL_EVENT_TYPES`).
    pub fn requires_human_response(&self) -> bool {
        matches!(
            self,
            AgentEventType::A2uiActionAsked
                | AgentEventType::ClarificationAsked
                | AgentEventType::DecisionAsked
                | AgentEventType::ElicitationAsked
                | AgentEventType::EnvVarRequested
                | AgentEventType::PermissionAsked
        )
    }

    /// Internal signal that must not be exposed to the frontend (Python
    /// `INTERNAL_EVENT_TYPES`).
    pub fn is_internal(&self) -> bool {
        matches!(self, AgentEventType::CompactNeeded | AgentEventType::Retry)
    }
}
