//! Agent event model — the runtime-agnostic taxonomy + wire envelope shared by
//! the SessionProcessor (emits), the `EventStream` port (F5, transports opaque
//! JSON), and the WS event bridge (F7, delivers). This is the Rust port of the
//! Python single-source-of-truth `src/domain/events/{types,envelope}.py`.
//!
//! Pure data + pure functions: no I/O, no `uuid`/`rand`/clock — the `event_id`
//! and `timestamp` are **injected** by the caller (server uses uuid + a real
//! clock; device/tests inject deterministic values), mirroring the hexagonal
//! id/time discipline in [`crate::util`] and ADR-0001. Compiles to `wasm32`.

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::util::fnv1a;

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
    /// The exact wire `type` string (e.g. `"thought"`, `"act"`, `"task_complete"`).
    pub fn as_str(&self) -> &'static str {
        match self {
            AgentEventType::Status => "status",
            AgentEventType::Start => "start",
            AgentEventType::Complete => "complete",
            AgentEventType::Error => "error",
            AgentEventType::ThoughtStart => "thought_start",
            AgentEventType::Thought => "thought",
            AgentEventType::ThoughtDelta => "thought_delta",
            AgentEventType::Act => "act",
            AgentEventType::ActDelta => "act_delta",
            AgentEventType::Observe => "observe",
            AgentEventType::TextStart => "text_start",
            AgentEventType::TextDelta => "text_delta",
            AgentEventType::TextEnd => "text_end",
            AgentEventType::Message => "message",
            AgentEventType::UserMessage => "user_message",
            AgentEventType::AssistantMessage => "assistant_message",
            AgentEventType::PermissionAsked => "permission_asked",
            AgentEventType::PermissionReplied => "permission_replied",
            AgentEventType::DoomLoopDetected => "doom_loop_detected",
            AgentEventType::DoomLoopIntervened => "doom_loop_intervened",
            AgentEventType::ClarificationAsked => "clarification_asked",
            AgentEventType::ClarificationAnswered => "clarification_answered",
            AgentEventType::DecisionAsked => "decision_asked",
            AgentEventType::DecisionAnswered => "decision_answered",
            AgentEventType::EnvVarRequested => "env_var_requested",
            AgentEventType::EnvVarProvided => "env_var_provided",
            AgentEventType::CostUpdate => "cost_update",
            AgentEventType::Retry => "retry",
            AgentEventType::CompactNeeded => "compact_needed",
            AgentEventType::ContextCompressed => "context_compressed",
            AgentEventType::ContextStatus => "context_status",
            AgentEventType::ContextSummaryGenerated => "context_summary_generated",
            AgentEventType::MemoryRecalled => "memory_recalled",
            AgentEventType::MemoryCaptured => "memory_captured",
            AgentEventType::PatternMatch => "pattern_match",
            AgentEventType::SkillMatched => "skill_matched",
            AgentEventType::SkillExecutionStart => "skill_execution_start",
            AgentEventType::SkillExecutionComplete => "skill_execution_complete",
            AgentEventType::SkillFallback => "skill_fallback",
            AgentEventType::TitleGenerated => "title_generated",
            AgentEventType::SandboxCreated => "sandbox_created",
            AgentEventType::SandboxTerminated => "sandbox_terminated",
            AgentEventType::SandboxStatus => "sandbox_status",
            AgentEventType::DesktopStarted => "desktop_started",
            AgentEventType::DesktopStopped => "desktop_stopped",
            AgentEventType::DesktopStatus => "desktop_status",
            AgentEventType::TerminalStarted => "terminal_started",
            AgentEventType::TerminalStopped => "terminal_stopped",
            AgentEventType::TerminalStatus => "terminal_status",
            AgentEventType::HttpServiceStarted => "http_service_started",
            AgentEventType::HttpServiceUpdated => "http_service_updated",
            AgentEventType::HttpServiceStopped => "http_service_stopped",
            AgentEventType::HttpServiceError => "http_service_error",
            AgentEventType::Suggestions => "suggestions",
            AgentEventType::ArtifactCreated => "artifact_created",
            AgentEventType::ArtifactReady => "artifact_ready",
            AgentEventType::ArtifactError => "artifact_error",
            AgentEventType::ArtifactsBatch => "artifacts_batch",
            AgentEventType::ArtifactOpen => "artifact_open",
            AgentEventType::ArtifactUpdate => "artifact_update",
            AgentEventType::ArtifactClose => "artifact_close",
            AgentEventType::McpAppResult => "mcp_app_result",
            AgentEventType::McpAppRegistered => "mcp_app_registered",
            AgentEventType::SubagentRouted => "subagent_routed",
            AgentEventType::SubagentStarted => "subagent_started",
            AgentEventType::SubagentCompleted => "subagent_completed",
            AgentEventType::SubagentFailed => "subagent_failed",
            AgentEventType::SubagentSpawning => "subagent_spawning",
            AgentEventType::SubagentDoomLoop => "subagent_doom_loop",
            AgentEventType::SubagentRetry => "subagent_retry",
            AgentEventType::SubagentQueued => "subagent_queued",
            AgentEventType::SubagentKilled => "subagent_killed",
            AgentEventType::SubagentSteered => "subagent_steered",
            AgentEventType::SubagentDepthLimited => "subagent_depth_limited",
            AgentEventType::SubagentSessionUpdate => "subagent_session_update",
            AgentEventType::SubagentSpawnRejected => "subagent_spawn_rejected",
            AgentEventType::SubagentAnnounceRetry => "subagent_announce_retry",
            AgentEventType::SubagentOrphanDetected => "subagent_orphan_detected",
            AgentEventType::SubagentAnnounceSent => "subagent_announce_sent",
            AgentEventType::SubagentAnnounceReceived => "subagent_announce_received",
            AgentEventType::SubagentAnnounceExpired => "subagent_announce_expired",
            AgentEventType::ToolPolicyDenied => "tool_policy_denied",
            AgentEventType::Cancelled => "cancelled",
            AgentEventType::TaskListUpdated => "task_list_updated",
            AgentEventType::TaskUpdated => "task_updated",
            AgentEventType::TaskStart => "task_start",
            AgentEventType::TaskComplete => "task_complete",
            AgentEventType::ToolsUpdated => "tools_updated",
            AgentEventType::Progress => "progress",
            AgentEventType::ElicitationAsked => "elicitation_asked",
            AgentEventType::ElicitationAnswered => "elicitation_answered",
            AgentEventType::CanvasUpdated => "canvas_updated",
            AgentEventType::A2uiActionAsked => "a2ui_action_asked",
            AgentEventType::A2uiActionAnswered => "a2ui_action_answered",
            AgentEventType::PlanSuggested => "plan_suggested",
            AgentEventType::SelectionTrace => "selection_trace",
            AgentEventType::PolicyFiltered => "policy_filtered",
            AgentEventType::ParallelStarted => "parallel_started",
            AgentEventType::ParallelCompleted => "parallel_completed",
            AgentEventType::BackgroundLaunched => "background_launched",
            AgentEventType::AgentSpawned => "agent_spawned",
            AgentEventType::AgentCompleted => "agent_completed",
            AgentEventType::AgentMessageSent => "agent_message_sent",
            AgentEventType::AgentMessageReceived => "agent_message_received",
            AgentEventType::AgentStopped => "agent_stopped",
            AgentEventType::SubagentDelegation => "subagent_delegation",
            AgentEventType::ContextCompacted => "context_compacted",
            AgentEventType::SessionForked => "session_forked",
            AgentEventType::SessionMerged => "session_merged",
            AgentEventType::GraphRunStarted => "graph_run_started",
            AgentEventType::GraphRunCompleted => "graph_run_completed",
            AgentEventType::GraphRunFailed => "graph_run_failed",
            AgentEventType::GraphRunCancelled => "graph_run_cancelled",
            AgentEventType::GraphNodeStarted => "graph_node_started",
            AgentEventType::GraphNodeCompleted => "graph_node_completed",
            AgentEventType::GraphNodeFailed => "graph_node_failed",
            AgentEventType::GraphNodeSkipped => "graph_node_skipped",
            AgentEventType::GraphHandoff => "graph_handoff",
            AgentEventType::WorkspaceMemberJoined => "workspace_member_joined",
            AgentEventType::BlackboardPostCreated => "blackboard_post_created",
            AgentEventType::WorkspaceTaskAssigned => "workspace_task_assigned",
            AgentEventType::TopologyUpdated => "topology_updated",
            AgentEventType::WorkspaceTaskCreated => "workspace_task_created",
            AgentEventType::WorkspaceTaskUpdated => "workspace_task_updated",
            AgentEventType::WorkspaceTaskDeleted => "workspace_task_deleted",
            AgentEventType::WorkspaceTaskStatusChanged => "workspace_task_status_changed",
            AgentEventType::BlackboardPostUpdated => "blackboard_post_updated",
            AgentEventType::BlackboardPostDeleted => "blackboard_post_deleted",
            AgentEventType::BlackboardReplyCreated => "blackboard_reply_created",
            AgentEventType::BlackboardReplyUpdated => "blackboard_reply_updated",
            AgentEventType::BlackboardReplyDeleted => "blackboard_reply_deleted",
            AgentEventType::BlackboardFileCreated => "blackboard_file_created",
            AgentEventType::BlackboardFileUpdated => "blackboard_file_updated",
            AgentEventType::BlackboardFileDeleted => "blackboard_file_deleted",
            AgentEventType::BlackboardDirectoryDeleted => "blackboard_directory_deleted",
            AgentEventType::WorkspaceUpdated => "workspace_updated",
            AgentEventType::WorkspaceDeleted => "workspace_deleted",
            AgentEventType::WorkspaceMemberUpdated => "workspace_member_updated",
            AgentEventType::WorkspaceMemberLeft => "workspace_member_left",
            AgentEventType::WorkspaceAgentBound => "workspace_agent_bound",
            AgentEventType::WorkspaceAgentUnbound => "workspace_agent_unbound",
            AgentEventType::WorkspaceMessageCreated => "workspace_message_created",
            AgentEventType::ConversationParticipantJoined => "conversation_participant_joined",
            AgentEventType::ConversationParticipantLeft => "conversation_participant_left",
            AgentEventType::AgentTaskAssigned => "agent_task_assigned",
            AgentEventType::AgentTaskRefused => "agent_task_refused",
            AgentEventType::AgentHumanInputRequested => "agent_human_input_requested",
            AgentEventType::AgentEscalated => "agent_escalated",
            AgentEventType::AgentConflictMarked => "agent_conflict_marked",
            AgentEventType::AgentProgressDeclared => "agent_progress_declared",
            AgentEventType::AgentGoalCompleted => "agent_goal_completed",
            AgentEventType::AgentSupervisorVerdict => "agent_supervisor_verdict",
            AgentEventType::AgentDecisionLogged => "agent_decision_logged",
            AgentEventType::AgentConversationFinished => "agent_conversation_finished",
            AgentEventType::WorkspacePlanUpdated => "workspace_plan_updated",
            AgentEventType::WorkspaceGoalMaterialized => "workspace_goal_materialized",
            AgentEventType::WorkspaceDecompositionComplete => "workspace_decomposition_complete",
            AgentEventType::WorkspaceWorkerDispatched => "workspace_worker_dispatched",
            AgentEventType::WorkspaceWorkerReportSubmitted => "workspace_worker_report_submitted",
            AgentEventType::WorkspaceAdjudicationComplete => "workspace_adjudication_complete",
            AgentEventType::WorkspaceGoalCompleted => "workspace_goal_completed",
            AgentEventType::TaskExecutionSessionUpdated => "task_execution_session_updated",
            AgentEventType::TaskExecutionIncidentOpened => "task_execution_incident_opened",
            AgentEventType::TaskRecoveryActionStarted => "task_recovery_action_started",
            AgentEventType::TaskRecoveryActionCompleted => "task_recovery_action_completed",
        }
    }

    /// Parse a wire `type` string back into a typed variant.
    pub fn from_wire(s: &str) -> Option<Self> {
        match s {
            "status" => Some(AgentEventType::Status),
            "start" => Some(AgentEventType::Start),
            "complete" => Some(AgentEventType::Complete),
            "error" => Some(AgentEventType::Error),
            "thought_start" => Some(AgentEventType::ThoughtStart),
            "thought" => Some(AgentEventType::Thought),
            "thought_delta" => Some(AgentEventType::ThoughtDelta),
            "act" => Some(AgentEventType::Act),
            "act_delta" => Some(AgentEventType::ActDelta),
            "observe" => Some(AgentEventType::Observe),
            "text_start" => Some(AgentEventType::TextStart),
            "text_delta" => Some(AgentEventType::TextDelta),
            "text_end" => Some(AgentEventType::TextEnd),
            "message" => Some(AgentEventType::Message),
            "user_message" => Some(AgentEventType::UserMessage),
            "assistant_message" => Some(AgentEventType::AssistantMessage),
            "permission_asked" => Some(AgentEventType::PermissionAsked),
            "permission_replied" => Some(AgentEventType::PermissionReplied),
            "doom_loop_detected" => Some(AgentEventType::DoomLoopDetected),
            "doom_loop_intervened" => Some(AgentEventType::DoomLoopIntervened),
            "clarification_asked" => Some(AgentEventType::ClarificationAsked),
            "clarification_answered" => Some(AgentEventType::ClarificationAnswered),
            "decision_asked" => Some(AgentEventType::DecisionAsked),
            "decision_answered" => Some(AgentEventType::DecisionAnswered),
            "env_var_requested" => Some(AgentEventType::EnvVarRequested),
            "env_var_provided" => Some(AgentEventType::EnvVarProvided),
            "cost_update" => Some(AgentEventType::CostUpdate),
            "retry" => Some(AgentEventType::Retry),
            "compact_needed" => Some(AgentEventType::CompactNeeded),
            "context_compressed" => Some(AgentEventType::ContextCompressed),
            "context_status" => Some(AgentEventType::ContextStatus),
            "context_summary_generated" => Some(AgentEventType::ContextSummaryGenerated),
            "memory_recalled" => Some(AgentEventType::MemoryRecalled),
            "memory_captured" => Some(AgentEventType::MemoryCaptured),
            "pattern_match" => Some(AgentEventType::PatternMatch),
            "skill_matched" => Some(AgentEventType::SkillMatched),
            "skill_execution_start" => Some(AgentEventType::SkillExecutionStart),
            "skill_execution_complete" => Some(AgentEventType::SkillExecutionComplete),
            "skill_fallback" => Some(AgentEventType::SkillFallback),
            "title_generated" => Some(AgentEventType::TitleGenerated),
            "sandbox_created" => Some(AgentEventType::SandboxCreated),
            "sandbox_terminated" => Some(AgentEventType::SandboxTerminated),
            "sandbox_status" => Some(AgentEventType::SandboxStatus),
            "desktop_started" => Some(AgentEventType::DesktopStarted),
            "desktop_stopped" => Some(AgentEventType::DesktopStopped),
            "desktop_status" => Some(AgentEventType::DesktopStatus),
            "terminal_started" => Some(AgentEventType::TerminalStarted),
            "terminal_stopped" => Some(AgentEventType::TerminalStopped),
            "terminal_status" => Some(AgentEventType::TerminalStatus),
            "http_service_started" => Some(AgentEventType::HttpServiceStarted),
            "http_service_updated" => Some(AgentEventType::HttpServiceUpdated),
            "http_service_stopped" => Some(AgentEventType::HttpServiceStopped),
            "http_service_error" => Some(AgentEventType::HttpServiceError),
            "suggestions" => Some(AgentEventType::Suggestions),
            "artifact_created" => Some(AgentEventType::ArtifactCreated),
            "artifact_ready" => Some(AgentEventType::ArtifactReady),
            "artifact_error" => Some(AgentEventType::ArtifactError),
            "artifacts_batch" => Some(AgentEventType::ArtifactsBatch),
            "artifact_open" => Some(AgentEventType::ArtifactOpen),
            "artifact_update" => Some(AgentEventType::ArtifactUpdate),
            "artifact_close" => Some(AgentEventType::ArtifactClose),
            "mcp_app_result" => Some(AgentEventType::McpAppResult),
            "mcp_app_registered" => Some(AgentEventType::McpAppRegistered),
            "subagent_routed" => Some(AgentEventType::SubagentRouted),
            "subagent_started" => Some(AgentEventType::SubagentStarted),
            "subagent_completed" => Some(AgentEventType::SubagentCompleted),
            "subagent_failed" => Some(AgentEventType::SubagentFailed),
            "subagent_spawning" => Some(AgentEventType::SubagentSpawning),
            "subagent_doom_loop" => Some(AgentEventType::SubagentDoomLoop),
            "subagent_retry" => Some(AgentEventType::SubagentRetry),
            "subagent_queued" => Some(AgentEventType::SubagentQueued),
            "subagent_killed" => Some(AgentEventType::SubagentKilled),
            "subagent_steered" => Some(AgentEventType::SubagentSteered),
            "subagent_depth_limited" => Some(AgentEventType::SubagentDepthLimited),
            "subagent_session_update" => Some(AgentEventType::SubagentSessionUpdate),
            "subagent_spawn_rejected" => Some(AgentEventType::SubagentSpawnRejected),
            "subagent_announce_retry" => Some(AgentEventType::SubagentAnnounceRetry),
            "subagent_orphan_detected" => Some(AgentEventType::SubagentOrphanDetected),
            "subagent_announce_sent" => Some(AgentEventType::SubagentAnnounceSent),
            "subagent_announce_received" => Some(AgentEventType::SubagentAnnounceReceived),
            "subagent_announce_expired" => Some(AgentEventType::SubagentAnnounceExpired),
            "tool_policy_denied" => Some(AgentEventType::ToolPolicyDenied),
            "cancelled" => Some(AgentEventType::Cancelled),
            "task_list_updated" => Some(AgentEventType::TaskListUpdated),
            "task_updated" => Some(AgentEventType::TaskUpdated),
            "task_start" => Some(AgentEventType::TaskStart),
            "task_complete" => Some(AgentEventType::TaskComplete),
            "tools_updated" => Some(AgentEventType::ToolsUpdated),
            "progress" => Some(AgentEventType::Progress),
            "elicitation_asked" => Some(AgentEventType::ElicitationAsked),
            "elicitation_answered" => Some(AgentEventType::ElicitationAnswered),
            "canvas_updated" => Some(AgentEventType::CanvasUpdated),
            "a2ui_action_asked" => Some(AgentEventType::A2uiActionAsked),
            "a2ui_action_answered" => Some(AgentEventType::A2uiActionAnswered),
            "plan_suggested" => Some(AgentEventType::PlanSuggested),
            "selection_trace" => Some(AgentEventType::SelectionTrace),
            "policy_filtered" => Some(AgentEventType::PolicyFiltered),
            "parallel_started" => Some(AgentEventType::ParallelStarted),
            "parallel_completed" => Some(AgentEventType::ParallelCompleted),
            "background_launched" => Some(AgentEventType::BackgroundLaunched),
            "agent_spawned" => Some(AgentEventType::AgentSpawned),
            "agent_completed" => Some(AgentEventType::AgentCompleted),
            "agent_message_sent" => Some(AgentEventType::AgentMessageSent),
            "agent_message_received" => Some(AgentEventType::AgentMessageReceived),
            "agent_stopped" => Some(AgentEventType::AgentStopped),
            "subagent_delegation" => Some(AgentEventType::SubagentDelegation),
            "context_compacted" => Some(AgentEventType::ContextCompacted),
            "session_forked" => Some(AgentEventType::SessionForked),
            "session_merged" => Some(AgentEventType::SessionMerged),
            "graph_run_started" => Some(AgentEventType::GraphRunStarted),
            "graph_run_completed" => Some(AgentEventType::GraphRunCompleted),
            "graph_run_failed" => Some(AgentEventType::GraphRunFailed),
            "graph_run_cancelled" => Some(AgentEventType::GraphRunCancelled),
            "graph_node_started" => Some(AgentEventType::GraphNodeStarted),
            "graph_node_completed" => Some(AgentEventType::GraphNodeCompleted),
            "graph_node_failed" => Some(AgentEventType::GraphNodeFailed),
            "graph_node_skipped" => Some(AgentEventType::GraphNodeSkipped),
            "graph_handoff" => Some(AgentEventType::GraphHandoff),
            "workspace_member_joined" => Some(AgentEventType::WorkspaceMemberJoined),
            "blackboard_post_created" => Some(AgentEventType::BlackboardPostCreated),
            "workspace_task_assigned" => Some(AgentEventType::WorkspaceTaskAssigned),
            "topology_updated" => Some(AgentEventType::TopologyUpdated),
            "workspace_task_created" => Some(AgentEventType::WorkspaceTaskCreated),
            "workspace_task_updated" => Some(AgentEventType::WorkspaceTaskUpdated),
            "workspace_task_deleted" => Some(AgentEventType::WorkspaceTaskDeleted),
            "workspace_task_status_changed" => Some(AgentEventType::WorkspaceTaskStatusChanged),
            "blackboard_post_updated" => Some(AgentEventType::BlackboardPostUpdated),
            "blackboard_post_deleted" => Some(AgentEventType::BlackboardPostDeleted),
            "blackboard_reply_created" => Some(AgentEventType::BlackboardReplyCreated),
            "blackboard_reply_updated" => Some(AgentEventType::BlackboardReplyUpdated),
            "blackboard_reply_deleted" => Some(AgentEventType::BlackboardReplyDeleted),
            "blackboard_file_created" => Some(AgentEventType::BlackboardFileCreated),
            "blackboard_file_updated" => Some(AgentEventType::BlackboardFileUpdated),
            "blackboard_file_deleted" => Some(AgentEventType::BlackboardFileDeleted),
            "blackboard_directory_deleted" => Some(AgentEventType::BlackboardDirectoryDeleted),
            "workspace_updated" => Some(AgentEventType::WorkspaceUpdated),
            "workspace_deleted" => Some(AgentEventType::WorkspaceDeleted),
            "workspace_member_updated" => Some(AgentEventType::WorkspaceMemberUpdated),
            "workspace_member_left" => Some(AgentEventType::WorkspaceMemberLeft),
            "workspace_agent_bound" => Some(AgentEventType::WorkspaceAgentBound),
            "workspace_agent_unbound" => Some(AgentEventType::WorkspaceAgentUnbound),
            "workspace_message_created" => Some(AgentEventType::WorkspaceMessageCreated),
            "conversation_participant_joined" => {
                Some(AgentEventType::ConversationParticipantJoined)
            }
            "conversation_participant_left" => Some(AgentEventType::ConversationParticipantLeft),
            "agent_task_assigned" => Some(AgentEventType::AgentTaskAssigned),
            "agent_task_refused" => Some(AgentEventType::AgentTaskRefused),
            "agent_human_input_requested" => Some(AgentEventType::AgentHumanInputRequested),
            "agent_escalated" => Some(AgentEventType::AgentEscalated),
            "agent_conflict_marked" => Some(AgentEventType::AgentConflictMarked),
            "agent_progress_declared" => Some(AgentEventType::AgentProgressDeclared),
            "agent_goal_completed" => Some(AgentEventType::AgentGoalCompleted),
            "agent_supervisor_verdict" => Some(AgentEventType::AgentSupervisorVerdict),
            "agent_decision_logged" => Some(AgentEventType::AgentDecisionLogged),
            "agent_conversation_finished" => Some(AgentEventType::AgentConversationFinished),
            "workspace_plan_updated" => Some(AgentEventType::WorkspacePlanUpdated),
            "workspace_goal_materialized" => Some(AgentEventType::WorkspaceGoalMaterialized),
            "workspace_decomposition_complete" => {
                Some(AgentEventType::WorkspaceDecompositionComplete)
            }
            "workspace_worker_dispatched" => Some(AgentEventType::WorkspaceWorkerDispatched),
            "workspace_worker_report_submitted" => {
                Some(AgentEventType::WorkspaceWorkerReportSubmitted)
            }
            "workspace_adjudication_complete" => {
                Some(AgentEventType::WorkspaceAdjudicationComplete)
            }
            "workspace_goal_completed" => Some(AgentEventType::WorkspaceGoalCompleted),
            "task_execution_session_updated" => Some(AgentEventType::TaskExecutionSessionUpdated),
            "task_execution_incident_opened" => Some(AgentEventType::TaskExecutionIncidentOpened),
            "task_recovery_action_started" => Some(AgentEventType::TaskRecoveryActionStarted),
            "task_recovery_action_completed" => Some(AgentEventType::TaskRecoveryActionCompleted),
            _ => None,
        }
    }

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

/// Standard wire envelope wrapping every domain event — the Rust port of Python
/// `EventEnvelope`. Field set, defaults, and `to_value` key order match
/// `envelope.py::to_dict`, so a Rust producer and the Python/frontend consumer
/// serialize identically. `correlation_id`/`causation_id` serialize as JSON
/// `null` when absent (no `skip_serializing_if`) to preserve shape parity.
///
/// `event_id`/`timestamp` are injected (see module docs) rather than generated
/// ambiently, keeping the type pure and `wasm32`-clean.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EventEnvelope {
    pub schema_version: String,
    pub event_id: String,
    pub event_type: String,
    pub timestamp: String,
    pub source: String,
    pub correlation_id: Option<String>,
    pub causation_id: Option<String>,
    pub payload: Value,
    pub metadata: Value,
}

impl EventEnvelope {
    /// Default schema version (Python `EventEnvelope.schema_version`).
    pub const SCHEMA_VERSION: &'static str = "1.0";
    /// Default source system (Python `EventEnvelope.source`).
    pub const SOURCE: &'static str = "memstack";

    /// Primary factory: wrap a typed domain event into an envelope. Mirrors
    /// Python `EventEnvelope.wrap`, except `event_id`/`timestamp` are injected.
    pub fn wrap(
        event_type: AgentEventType,
        payload: Value,
        event_id: impl Into<String>,
        timestamp: impl Into<String>,
    ) -> Self {
        Self {
            schema_version: Self::SCHEMA_VERSION.to_string(),
            event_id: event_id.into(),
            event_type: event_type.as_str().to_string(),
            timestamp: timestamp.into(),
            source: Self::SOURCE.to_string(),
            correlation_id: None,
            causation_id: None,
            payload,
            metadata: Value::Object(Map::new()),
        }
    }

    /// The typed event kind, if `event_type` is a known wire string.
    pub fn typed(&self) -> Option<AgentEventType> {
        AgentEventType::from_wire(&self.event_type)
    }

    /// Category grouping via the typed event kind (defaults to `Agent` for any
    /// known-but-unmapped type; `None` only for an unrecognized wire string).
    pub fn category(&self) -> Option<EventCategory> {
        self.typed().map(|t| t.category())
    }

    /// Set correlation (and optional causation) ids, mirroring Python
    /// `with_correlation`.
    pub fn with_correlation(
        mut self,
        correlation_id: impl Into<String>,
        causation_id: Option<String>,
    ) -> Self {
        self.correlation_id = Some(correlation_id.into());
        if causation_id.is_some() {
            self.causation_id = causation_id;
        }
        self
    }

    /// Insert a single metadata key, mirroring Python `with_metadata`.
    pub fn with_metadata(mut self, key: impl Into<String>, value: Value) -> Self {
        if !self.metadata.is_object() {
            self.metadata = Value::Object(Map::new());
        }
        if let Some(obj) = self.metadata.as_object_mut() {
            obj.insert(key.into(), value);
        }
        self
    }

    /// Derive a child envelope: the child inherits this envelope's
    /// `correlation_id`, takes this envelope's `event_id` as its `causation_id`,
    /// and merges parent metadata under child overrides. Mirrors Python
    /// `create_child_envelope`.
    pub fn child(
        &self,
        event_type: AgentEventType,
        payload: Value,
        event_id: impl Into<String>,
        timestamp: impl Into<String>,
    ) -> Self {
        let mut metadata = self.metadata.clone();
        if !metadata.is_object() {
            metadata = Value::Object(Map::new());
        }
        Self {
            schema_version: Self::SCHEMA_VERSION.to_string(),
            event_id: event_id.into(),
            event_type: event_type.as_str().to_string(),
            timestamp: timestamp.into(),
            source: Self::SOURCE.to_string(),
            correlation_id: self.correlation_id.clone(),
            causation_id: Some(self.event_id.clone()),
            payload,
            metadata,
        }
    }

    /// Serialize to a `serde_json::Value` (the normalized wire form the F5
    /// `EventStream` transports as opaque JSON and the F7 bridge delivers).
    pub fn to_value(&self) -> Value {
        serde_json::to_value(self).unwrap_or(Value::Null)
    }

    /// Serialize to a JSON string (Python `to_json`).
    pub fn to_json(&self) -> String {
        serde_json::to_string(self).unwrap_or_else(|_| "{}".to_string())
    }

    /// Parse an envelope from a JSON string (Python `from_json`).
    pub fn from_json(s: &str) -> Result<Self, serde_json::Error> {
        serde_json::from_str(s)
    }
}

/// Deterministic, `wasm32`-clean `evt_`-prefixed event id derived from a seed via
/// FNV-1a — matches the Python `evt_` + 12-hex shape without pulling `uuid`.
/// Callers needing globally-unique random ids inject them instead (server: uuid
/// v4), consistent with the injected-id discipline in [`crate::util`].
pub fn derive_event_id(seed: &str) -> String {
    format!("evt_{:012x}", fnv1a(seed) & 0x0000_ffff_ffff_ffff)
}

impl AgentEventType {
    /// Every variant, for exhaustive iteration (e.g. wire round-trip checks).
    pub const ALL: &'static [AgentEventType] = &[
        AgentEventType::Status,
        AgentEventType::Start,
        AgentEventType::Complete,
        AgentEventType::Error,
        AgentEventType::ThoughtStart,
        AgentEventType::Thought,
        AgentEventType::ThoughtDelta,
        AgentEventType::Act,
        AgentEventType::ActDelta,
        AgentEventType::Observe,
        AgentEventType::TextStart,
        AgentEventType::TextDelta,
        AgentEventType::TextEnd,
        AgentEventType::Message,
        AgentEventType::UserMessage,
        AgentEventType::AssistantMessage,
        AgentEventType::PermissionAsked,
        AgentEventType::PermissionReplied,
        AgentEventType::DoomLoopDetected,
        AgentEventType::DoomLoopIntervened,
        AgentEventType::ClarificationAsked,
        AgentEventType::ClarificationAnswered,
        AgentEventType::DecisionAsked,
        AgentEventType::DecisionAnswered,
        AgentEventType::EnvVarRequested,
        AgentEventType::EnvVarProvided,
        AgentEventType::CostUpdate,
        AgentEventType::Retry,
        AgentEventType::CompactNeeded,
        AgentEventType::ContextCompressed,
        AgentEventType::ContextStatus,
        AgentEventType::ContextSummaryGenerated,
        AgentEventType::MemoryRecalled,
        AgentEventType::MemoryCaptured,
        AgentEventType::PatternMatch,
        AgentEventType::SkillMatched,
        AgentEventType::SkillExecutionStart,
        AgentEventType::SkillExecutionComplete,
        AgentEventType::SkillFallback,
        AgentEventType::TitleGenerated,
        AgentEventType::SandboxCreated,
        AgentEventType::SandboxTerminated,
        AgentEventType::SandboxStatus,
        AgentEventType::DesktopStarted,
        AgentEventType::DesktopStopped,
        AgentEventType::DesktopStatus,
        AgentEventType::TerminalStarted,
        AgentEventType::TerminalStopped,
        AgentEventType::TerminalStatus,
        AgentEventType::HttpServiceStarted,
        AgentEventType::HttpServiceUpdated,
        AgentEventType::HttpServiceStopped,
        AgentEventType::HttpServiceError,
        AgentEventType::Suggestions,
        AgentEventType::ArtifactCreated,
        AgentEventType::ArtifactReady,
        AgentEventType::ArtifactError,
        AgentEventType::ArtifactsBatch,
        AgentEventType::ArtifactOpen,
        AgentEventType::ArtifactUpdate,
        AgentEventType::ArtifactClose,
        AgentEventType::McpAppResult,
        AgentEventType::McpAppRegistered,
        AgentEventType::SubagentRouted,
        AgentEventType::SubagentStarted,
        AgentEventType::SubagentCompleted,
        AgentEventType::SubagentFailed,
        AgentEventType::SubagentSpawning,
        AgentEventType::SubagentDoomLoop,
        AgentEventType::SubagentRetry,
        AgentEventType::SubagentQueued,
        AgentEventType::SubagentKilled,
        AgentEventType::SubagentSteered,
        AgentEventType::SubagentDepthLimited,
        AgentEventType::SubagentSessionUpdate,
        AgentEventType::SubagentSpawnRejected,
        AgentEventType::SubagentAnnounceRetry,
        AgentEventType::SubagentOrphanDetected,
        AgentEventType::SubagentAnnounceSent,
        AgentEventType::SubagentAnnounceReceived,
        AgentEventType::SubagentAnnounceExpired,
        AgentEventType::ToolPolicyDenied,
        AgentEventType::Cancelled,
        AgentEventType::TaskListUpdated,
        AgentEventType::TaskUpdated,
        AgentEventType::TaskStart,
        AgentEventType::TaskComplete,
        AgentEventType::ToolsUpdated,
        AgentEventType::Progress,
        AgentEventType::ElicitationAsked,
        AgentEventType::ElicitationAnswered,
        AgentEventType::CanvasUpdated,
        AgentEventType::A2uiActionAsked,
        AgentEventType::A2uiActionAnswered,
        AgentEventType::PlanSuggested,
        AgentEventType::SelectionTrace,
        AgentEventType::PolicyFiltered,
        AgentEventType::ParallelStarted,
        AgentEventType::ParallelCompleted,
        AgentEventType::BackgroundLaunched,
        AgentEventType::AgentSpawned,
        AgentEventType::AgentCompleted,
        AgentEventType::AgentMessageSent,
        AgentEventType::AgentMessageReceived,
        AgentEventType::AgentStopped,
        AgentEventType::SubagentDelegation,
        AgentEventType::ContextCompacted,
        AgentEventType::SessionForked,
        AgentEventType::SessionMerged,
        AgentEventType::GraphRunStarted,
        AgentEventType::GraphRunCompleted,
        AgentEventType::GraphRunFailed,
        AgentEventType::GraphRunCancelled,
        AgentEventType::GraphNodeStarted,
        AgentEventType::GraphNodeCompleted,
        AgentEventType::GraphNodeFailed,
        AgentEventType::GraphNodeSkipped,
        AgentEventType::GraphHandoff,
        AgentEventType::WorkspaceMemberJoined,
        AgentEventType::BlackboardPostCreated,
        AgentEventType::WorkspaceTaskAssigned,
        AgentEventType::TopologyUpdated,
        AgentEventType::WorkspaceTaskCreated,
        AgentEventType::WorkspaceTaskUpdated,
        AgentEventType::WorkspaceTaskDeleted,
        AgentEventType::WorkspaceTaskStatusChanged,
        AgentEventType::BlackboardPostUpdated,
        AgentEventType::BlackboardPostDeleted,
        AgentEventType::BlackboardReplyCreated,
        AgentEventType::BlackboardReplyUpdated,
        AgentEventType::BlackboardReplyDeleted,
        AgentEventType::BlackboardFileCreated,
        AgentEventType::BlackboardFileUpdated,
        AgentEventType::BlackboardFileDeleted,
        AgentEventType::BlackboardDirectoryDeleted,
        AgentEventType::WorkspaceUpdated,
        AgentEventType::WorkspaceDeleted,
        AgentEventType::WorkspaceMemberUpdated,
        AgentEventType::WorkspaceMemberLeft,
        AgentEventType::WorkspaceAgentBound,
        AgentEventType::WorkspaceAgentUnbound,
        AgentEventType::WorkspaceMessageCreated,
        AgentEventType::ConversationParticipantJoined,
        AgentEventType::ConversationParticipantLeft,
        AgentEventType::AgentTaskAssigned,
        AgentEventType::AgentTaskRefused,
        AgentEventType::AgentHumanInputRequested,
        AgentEventType::AgentEscalated,
        AgentEventType::AgentConflictMarked,
        AgentEventType::AgentProgressDeclared,
        AgentEventType::AgentGoalCompleted,
        AgentEventType::AgentSupervisorVerdict,
        AgentEventType::AgentDecisionLogged,
        AgentEventType::AgentConversationFinished,
        AgentEventType::WorkspacePlanUpdated,
        AgentEventType::WorkspaceGoalMaterialized,
        AgentEventType::WorkspaceDecompositionComplete,
        AgentEventType::WorkspaceWorkerDispatched,
        AgentEventType::WorkspaceWorkerReportSubmitted,
        AgentEventType::WorkspaceAdjudicationComplete,
        AgentEventType::WorkspaceGoalCompleted,
        AgentEventType::TaskExecutionSessionUpdated,
        AgentEventType::TaskExecutionIncidentOpened,
        AgentEventType::TaskRecoveryActionStarted,
        AgentEventType::TaskRecoveryActionCompleted,
    ];
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn wire_values_round_trip_for_every_variant() {
        // Guards against a rename typo across all 165 variants: the serde wire
        // string must parse back to the same variant, and serde must agree.
        for &t in AgentEventType::ALL {
            assert_eq!(
                AgentEventType::from_wire(t.as_str()),
                Some(t),
                "from_wire({})",
                t.as_str()
            );
            let ser = serde_json::to_string(&t).unwrap();
            assert_eq!(
                ser,
                format!("\"{}\"", t.as_str()),
                "serde rename for {:?}",
                t
            );
            let de: AgentEventType = serde_json::from_str(&ser).unwrap();
            assert_eq!(de, t);
        }
        assert_eq!(AgentEventType::ALL.len(), 165);
        assert_eq!(AgentEventType::from_wire("not_a_real_event"), None);
    }

    #[test]
    fn category_matches_python_mapping() {
        // Explicit non-Agent arms.
        assert_eq!(
            AgentEventType::ClarificationAsked.category(),
            EventCategory::Hitl
        );
        assert_eq!(
            AgentEventType::EnvVarRequested.category(),
            EventCategory::Hitl
        );
        assert_eq!(
            AgentEventType::SandboxCreated.category(),
            EventCategory::Sandbox
        );
        assert_eq!(
            AgentEventType::TerminalStarted.category(),
            EventCategory::Sandbox
        );
        assert_eq!(
            AgentEventType::HttpServiceError.category(),
            EventCategory::Sandbox
        );
        assert_eq!(
            AgentEventType::UserMessage.category(),
            EventCategory::Message
        );
        assert_eq!(AgentEventType::CostUpdate.category(), EventCategory::System);
        assert_eq!(
            AgentEventType::ContextCompacted.category(),
            EventCategory::System
        );
        assert_eq!(AgentEventType::Retry.category(), EventCategory::System);
        // Default-Agent long-tail (unmapped in Python EVENT_CATEGORIES).
        assert_eq!(
            AgentEventType::MemoryRecalled.category(),
            EventCategory::Agent
        );
        assert_eq!(
            AgentEventType::ArtifactCreated.category(),
            EventCategory::Agent
        );
        assert_eq!(AgentEventType::Thought.category(), EventCategory::Agent);
        assert_eq!(EventCategory::Hitl.as_str(), "hitl");
    }

    #[test]
    fn classification_predicates_match_python_sets() {
        assert!(AgentEventType::ThoughtDelta.is_delta());
        assert!(AgentEventType::TextEnd.is_delta());
        assert!(!AgentEventType::Thought.is_delta());

        assert!(AgentEventType::Complete.is_terminal());
        assert!(AgentEventType::Error.is_terminal());
        assert!(AgentEventType::Cancelled.is_terminal());
        assert!(!AgentEventType::Status.is_terminal());

        assert!(AgentEventType::PermissionAsked.requires_human_response());
        assert!(AgentEventType::A2uiActionAsked.requires_human_response());
        assert!(!AgentEventType::DecisionAnswered.requires_human_response());

        assert!(AgentEventType::CompactNeeded.is_internal());
        assert!(AgentEventType::Retry.is_internal());
        assert!(!AgentEventType::Status.is_internal());
    }

    #[test]
    fn envelope_wrap_shape_matches_python_to_dict() {
        let env = EventEnvelope::wrap(
            AgentEventType::Thought,
            json!({"text": "hello"}),
            "evt_test01",
            "2024-01-01T00:00:00Z",
        );
        let v = env.to_value();
        assert_eq!(v["schema_version"], json!("1.0"));
        assert_eq!(v["event_id"], json!("evt_test01"));
        assert_eq!(v["event_type"], json!("thought"));
        assert_eq!(v["timestamp"], json!("2024-01-01T00:00:00Z"));
        assert_eq!(v["source"], json!("memstack"));
        // Absent correlation/causation serialize as explicit null (shape parity).
        assert_eq!(v["correlation_id"], Value::Null);
        assert_eq!(v["causation_id"], Value::Null);
        assert_eq!(v["payload"], json!({"text": "hello"}));
        assert_eq!(v["metadata"], json!({}));
        assert_eq!(env.typed(), Some(AgentEventType::Thought));
        assert_eq!(env.category(), Some(EventCategory::Agent));
    }

    #[test]
    fn child_inherits_correlation_and_sets_causation() {
        let parent = EventEnvelope::wrap(AgentEventType::Start, json!({}), "evt_parent", "t0")
            .with_correlation("corr_1", None)
            .with_metadata("tenant_id", json!("acme"));

        let child = parent.child(AgentEventType::Thought, json!({"i": 1}), "evt_child", "t1");
        assert_eq!(child.correlation_id.as_deref(), Some("corr_1"));
        assert_eq!(child.causation_id.as_deref(), Some("evt_parent"));
        // Parent metadata is merged into the child.
        assert_eq!(child.metadata["tenant_id"], json!("acme"));
        assert_eq!(child.event_type, "thought");
    }

    #[test]
    fn json_round_trip_is_lossless() {
        let env = EventEnvelope::wrap(
            AgentEventType::TaskComplete,
            json!({"task_id": "t7"}),
            "evt_x",
            "t0",
        )
        .with_correlation("c9", Some("evt_cause".to_string()));
        let s = env.to_json();
        let back = EventEnvelope::from_json(&s).unwrap();
        assert_eq!(back, env);
        assert_eq!(back.causation_id.as_deref(), Some("evt_cause"));
    }

    #[test]
    fn derive_event_id_is_deterministic_and_shaped() {
        let a = derive_event_id("round:3|type:thought");
        let b = derive_event_id("round:3|type:thought");
        assert_eq!(a, b);
        assert!(a.starts_with("evt_"));
        assert_eq!(a.len(), 4 + 12); // "evt_" + 12 hex chars
        assert!(a[4..].chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(a, derive_event_id("round:4|type:thought"));
    }
}
