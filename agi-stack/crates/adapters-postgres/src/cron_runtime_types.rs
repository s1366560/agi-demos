//! Closed runtime contracts shared by cron dispatch and terminal projection.

use std::fmt;

use chrono::{DateTime, Utc};

const TERMINAL_STATUSES: &[&str] = &["success", "failed", "timeout", "cancelled", "skipped"];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum AutomationRunStatus {
    Queued,
    Running,
    WaitingHuman,
    Success,
    Failed,
    Timeout,
    Cancelled,
    Skipped,
}

impl AutomationRunStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Running => "running",
            Self::WaitingHuman => "waiting_human",
            Self::Success => "success",
            Self::Failed => "failed",
            Self::Timeout => "timeout",
            Self::Cancelled => "cancelled",
            Self::Skipped => "skipped",
        }
    }

    pub fn is_terminal(self) -> bool {
        TERMINAL_STATUSES.contains(&self.as_str())
    }
}

impl TryFrom<&str> for AutomationRunStatus {
    type Error = AutomationRuntimeRepositoryError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        match value {
            "queued" => Ok(Self::Queued),
            "running" => Ok(Self::Running),
            "waiting_human" => Ok(Self::WaitingHuman),
            "success" => Ok(Self::Success),
            "failed" => Ok(Self::Failed),
            "timeout" => Ok(Self::Timeout),
            "cancelled" => Ok(Self::Cancelled),
            "skipped" => Ok(Self::Skipped),
            _ => Err(AutomationRuntimeRepositoryError::InvalidRunState),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AutomationPayload {
    AgentTurn { message: String },
    SystemEvent { content: String },
}

impl AutomationPayload {
    pub fn goal(&self) -> String {
        match self {
            Self::AgentTurn { message } => message.clone(),
            Self::SystemEvent { content } => format!("[System Event] {content}"),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AutomationRunContext {
    pub tenant_id: String,
    pub project_id: String,
    pub job_id: String,
    pub run_id: String,
    pub runtime_execution_id: String,
    pub conversation_id: String,
    pub actor_user_id: String,
    pub actor_api_key_id: Option<String>,
    pub payload: AutomationPayload,
    pub timeout_seconds: i64,
    pub status: AutomationRunStatus,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AutomationRunLease {
    pub context: AutomationRunContext,
    pub runtime_revision: i64,
    pub lease_owner: String,
    pub lease_token: String,
    pub lease_expires_at: DateTime<Utc>,
    pub deadline_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AutomationTerminalOutcome {
    Success,
    Failed,
    Timeout,
    Cancelled,
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct AutomationTerminalObservation<'a> {
    pub outcome: AutomationTerminalOutcome,
    pub error_code: Option<&'a str>,
    pub event_count: u64,
    pub execution_time_ms: u64,
    pub observed_at: DateTime<Utc>,
}

impl AutomationTerminalOutcome {
    pub(crate) fn status(self) -> AutomationRunStatus {
        match self {
            Self::Success => AutomationRunStatus::Success,
            Self::Failed => AutomationRunStatus::Failed,
            Self::Timeout => AutomationRunStatus::Timeout,
            Self::Cancelled => AutomationRunStatus::Cancelled,
        }
    }

    pub(crate) fn counts_as_failure(self) -> bool {
        matches!(self, Self::Failed | Self::Timeout)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AutomationTerminalProjection {
    pub matched: bool,
    pub duplicate: bool,
    pub run_status: Option<AutomationRunStatus>,
    pub operation_status: Option<String>,
    pub delivery_ack_pending: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AutomationRuntimeRepositoryError {
    NotFound,
    LeaseLost,
    StaleRevision,
    MissingActor,
    InvalidPayload,
    InvalidConversation,
    InvalidRunState,
    TerminalConflict,
    Storage(String),
}

impl fmt::Display for AutomationRuntimeRepositoryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::NotFound => "automation runtime target not found",
            Self::LeaseLost => "automation runtime lease lost",
            Self::StaleRevision => "automation job revision is stale",
            Self::MissingActor => "automation runtime actor is missing",
            Self::InvalidPayload => "automation payload is invalid",
            Self::InvalidConversation => "automation conversation is invalid",
            Self::InvalidRunState => "automation run state is invalid",
            Self::TerminalConflict => "automation run already has a different terminal state",
            Self::Storage(_) => "automation runtime storage failed",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for AutomationRuntimeRepositoryError {}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AutomationRuntimeScope {
    pub tenant_id: String,
    pub project_id: String,
}
