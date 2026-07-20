use rusqlite::{params, Connection, OptionalExtension, Transaction};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use uuid::Uuid;

use agistack_core::agent::types::{DecisionContext, HitlKind};

use super::{session_store::required_string, LocalConversation};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum DesktopPlanStatus {
    Draft,
    Approved,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub(super) struct DesktopPlanVersion {
    pub id: String,
    pub conversation_id: String,
    pub version: i64,
    pub status: DesktopPlanStatus,
    pub tasks: Vec<Value>,
    pub created_at: String,
    pub approved_at: Option<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum DesktopArtifactStatus {
    Draft,
    Ready,
    Approved,
    Delivered,
    Superseded,
}

impl DesktopArtifactStatus {
    pub(super) fn can_review(self) -> bool {
        matches!(self, Self::Draft | Self::Ready | Self::Approved)
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub(super) struct DesktopArtifactVersion {
    pub id: String,
    pub artifact_id: String,
    pub source_artifact_id: String,
    pub conversation_id: String,
    pub run_id: Option<String>,
    pub version: i64,
    pub status: DesktopArtifactStatus,
    pub revision: u64,
    pub filename: String,
    pub mime_type: String,
    pub path: String,
    pub relative_path: String,
    pub bytes: u64,
    pub sources: Vec<Value>,
    pub checks: Vec<Value>,
    pub created_at: String,
    pub updated_at: String,
    pub approved_at: Option<String>,
    pub delivered_at: Option<String>,
    pub superseded_at: Option<String>,
    pub feedback: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub(super) struct DesktopArtifactDelivery {
    pub id: String,
    pub artifact_version_id: String,
    pub artifact_id: String,
    pub conversation_id: String,
    pub run_id: Option<String>,
    pub destination: String,
    pub receipt: Value,
    pub idempotency_key: String,
    pub created_at: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum DesktopRunStatus {
    Queued,
    Running,
    NeedsInput,
    NeedsApproval,
    Paused,
    ReadyReview,
    Completed,
    Failed,
    Disconnected,
    Interrupted,
    Cancelled,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum DesktopExecutionEnvironmentKind {
    Local,
    Worktree,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum DesktopPermissionProfile {
    #[default]
    ReadOnly,
    WorkspaceWrite,
    FullAccess,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct DesktopExecutionEnvironment {
    pub id: String,
    pub kind: DesktopExecutionEnvironmentKind,
    pub label: String,
    pub workspace_path: String,
    pub repository_root: Option<String>,
    pub branch: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub base_commit: Option<String>,
    pub source_run_id: Option<String>,
    pub created_at: String,
}

impl DesktopRunStatus {
    pub(super) fn is_terminal(self) -> bool {
        matches!(self, Self::Completed | Self::Failed | Self::Cancelled)
    }

    pub(super) fn can_transition_to(self, next: Self) -> bool {
        matches!(
            (self, next),
            (
                Self::Queued | Self::Paused | Self::Disconnected | Self::Interrupted,
                Self::Running,
            ) | (Self::Queued, Self::Failed | Self::Cancelled)
                | (
                    Self::Running,
                    Self::NeedsInput
                        | Self::NeedsApproval
                        | Self::Paused
                        | Self::ReadyReview
                        | Self::Failed
                        | Self::Disconnected
                        | Self::Cancelled
                )
                | (Self::NeedsInput | Self::NeedsApproval, Self::Running)
                | (
                    Self::Paused | Self::Disconnected | Self::Interrupted,
                    Self::Cancelled
                )
                | (Self::ReadyReview, Self::Running | Self::Completed)
        )
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub(super) struct DesktopRun {
    pub id: String,
    pub conversation_id: String,
    pub project_id: String,
    pub plan_version_id: String,
    pub idempotency_key: String,
    pub message_id: String,
    pub request_message: String,
    pub status: DesktopRunStatus,
    pub revision: u64,
    pub created_at: String,
    pub updated_at: String,
    pub started_at: Option<String>,
    pub completed_at: Option<String>,
    pub last_heartbeat_at: Option<String>,
    pub error: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub environment: Option<DesktopExecutionEnvironment>,
    #[serde(default)]
    pub permission_profile: DesktopPermissionProfile,
    pub authorization_snapshot: Value,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum DesktopHitlStatus {
    Pending,
    Responded,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct DesktopHitlRequest {
    pub id: String,
    pub conversation_id: String,
    pub run_id: Option<String>,
    pub round: u64,
    pub kind: HitlKind,
    pub prompt: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub decision: Option<DecisionContext>,
    pub status: DesktopHitlStatus,
    pub created_at: String,
    pub responded_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub response_data: Option<Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub response_actor: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub response_revision: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub idempotency_key: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct WorkspaceToolGrant {
    pub id: String,
    pub workspace_id: String,
    pub canonical_tool_name: String,
    pub source_hitl_request_id: String,
    pub revision: u64,
    pub created_by: String,
    pub created_at: String,
    pub revoked_by: Option<String>,
    pub revoked_at: Option<String>,
}

#[derive(Debug)]
pub(super) enum DesktopAuthorityError {
    ConversationNotFound,
    ProjectMismatch,
    PlanNotReady,
    PlanVersionMismatch,
    PlanVersionConflict { expected: i64, actual: i64 },
    IdempotencyConflict,
    Storage(String),
}

impl std::fmt::Display for DesktopAuthorityError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ConversationNotFound => formatter.write_str("conversation not found"),
            Self::ProjectMismatch => formatter.write_str("conversation project mismatch"),
            Self::PlanNotReady => formatter.write_str("no draft plan is ready for approval"),
            Self::PlanVersionMismatch => {
                formatter.write_str("approved plan does not match the reviewed plan version")
            }
            Self::PlanVersionConflict { expected, actual } => write!(
                formatter,
                "plan version conflict: expected {expected}, found {actual}"
            ),
            Self::IdempotencyConflict => {
                formatter.write_str("idempotency key is already bound to a different run request")
            }
            Self::Storage(error) => formatter.write_str(error),
        }
    }
}

#[derive(Clone, Debug)]
pub(super) struct ApprovePlanOutcome {
    pub conversation: LocalConversation,
    pub plan_version: DesktopPlanVersion,
    pub run: DesktopRun,
    pub created: bool,
}

pub(super) const QUEUED_RUN_RECOVERY_ERROR: &str =
    "approved run was queued when the local runtime stopped";

pub(super) fn is_recovered_unstarted_run(run: &DesktopRun) -> bool {
    run.status == DesktopRunStatus::Interrupted
        && run.started_at.is_none()
        && run.error.as_deref() == Some(QUEUED_RUN_RECOVERY_ERROR)
}

/// Reclassifies unfinished runs after an exclusive local-runtime store open.
pub(super) fn recover_interrupted_runs(connection: &Connection, now: &str) -> Result<(), String> {
    let transaction = connection
        .unchecked_transaction()
        .map_err(|error| error.to_string())?;
    let mut statement = transaction
        .prepare(
            "SELECT value_json FROM desktop_runs WHERE status IN ('queued', 'running')
             ORDER BY created_at ASC, id ASC",
        )
        .map_err(|error| error.to_string())?;
    let runs: Vec<DesktopRun> = typed_rows(statement.query_map([], |row| row.get::<_, String>(0)))?;
    drop(statement);
    for mut run in runs {
        let event_type = match run.status {
            DesktopRunStatus::Queued => {
                run.status = DesktopRunStatus::Interrupted;
                run.error = Some(QUEUED_RUN_RECOVERY_ERROR.to_string());
                "interrupted"
            }
            DesktopRunStatus::Running => {
                run.status = DesktopRunStatus::Disconnected;
                run.error = None;
                "disconnected"
            }
            _ => continue,
        };
        run.revision += 1;
        run.updated_at = now.to_string();
        update_run(&transaction, &run)?;
        insert_run_event(&transaction, &run, event_type, now).map_err(|error| error.to_string())?;
    }
    transaction.commit().map_err(|error| error.to_string())
}

pub(super) fn insert_plan_version(
    transaction: &Transaction<'_>,
    plan: &DesktopPlanVersion,
) -> Result<(), String> {
    transaction
        .execute(
            "INSERT INTO desktop_plan_versions(
               id, conversation_id, version, status, created_at, value_json
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params![
                plan.id,
                plan.conversation_id,
                plan.version,
                plan_status_name(plan.status),
                plan.created_at,
                serde_json::to_string(plan).map_err(|error| error.to_string())?,
            ],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

pub(super) fn update_plan_version(
    transaction: &Transaction<'_>,
    plan: &DesktopPlanVersion,
) -> Result<(), DesktopAuthorityError> {
    transaction
        .execute(
            "UPDATE desktop_plan_versions SET status = ?2, value_json = ?3 WHERE id = ?1",
            params![
                plan.id,
                plan_status_name(plan.status),
                serde_json::to_string(plan)
                    .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))?,
            ],
        )
        .map(|_| ())
        .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))
}

fn plan_status_name(status: DesktopPlanStatus) -> &'static str {
    match status {
        DesktopPlanStatus::Draft => "draft",
        DesktopPlanStatus::Approved => "approved",
    }
}

pub(super) fn artifact_status_name(status: DesktopArtifactStatus) -> &'static str {
    match status {
        DesktopArtifactStatus::Draft => "draft",
        DesktopArtifactStatus::Ready => "ready",
        DesktopArtifactStatus::Approved => "approved",
        DesktopArtifactStatus::Delivered => "delivered",
        DesktopArtifactStatus::Superseded => "superseded",
    }
}

pub(super) fn run_status_name(status: DesktopRunStatus) -> &'static str {
    match status {
        DesktopRunStatus::Queued => "queued",
        DesktopRunStatus::Running => "running",
        DesktopRunStatus::NeedsInput => "needs_input",
        DesktopRunStatus::NeedsApproval => "needs_approval",
        DesktopRunStatus::Paused => "paused",
        DesktopRunStatus::ReadyReview => "ready_review",
        DesktopRunStatus::Completed => "completed",
        DesktopRunStatus::Failed => "failed",
        DesktopRunStatus::Disconnected => "disconnected",
        DesktopRunStatus::Interrupted => "interrupted",
        DesktopRunStatus::Cancelled => "cancelled",
    }
}

pub(super) fn query_conversation(
    transaction: &Transaction<'_>,
    conversation_id: &str,
) -> Result<Option<LocalConversation>, DesktopAuthorityError> {
    let value = transaction
        .query_row(
            "SELECT value_json FROM desktop_conversations WHERE id = ?1",
            [conversation_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))?;
    value
        .map(|json| {
            serde_json::from_str(&json)
                .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))
        })
        .transpose()
}

pub(super) fn update_conversation_in_transaction(
    transaction: &Transaction<'_>,
    conversation: &LocalConversation,
) -> Result<(), DesktopAuthorityError> {
    transaction
        .execute(
            "UPDATE desktop_conversations
             SET project_id = ?2, workspace_id = ?3, updated_at = ?4, value_json = ?5
             WHERE id = ?1",
            params![
                conversation.id,
                conversation.project_id,
                conversation.workspace_id,
                conversation.updated_at,
                serde_json::to_string(conversation)
                    .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))?,
            ],
        )
        .map(|_| ())
        .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))
}

pub(super) fn query_latest_draft_plan(
    transaction: &Transaction<'_>,
    conversation_id: &str,
) -> Result<Option<DesktopPlanVersion>, DesktopAuthorityError> {
    let value = transaction
        .query_row(
            "SELECT value_json FROM desktop_plan_versions
             WHERE conversation_id = ?1 AND status = 'draft'
             ORDER BY version DESC LIMIT 1",
            [conversation_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))?;
    value
        .map(|json| {
            serde_json::from_str(&json)
                .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))
        })
        .transpose()
}

pub(super) fn query_plan_version(
    transaction: &Transaction<'_>,
    plan_version_id: &str,
) -> Result<Option<DesktopPlanVersion>, DesktopAuthorityError> {
    let value = transaction
        .query_row(
            "SELECT value_json FROM desktop_plan_versions WHERE id = ?1",
            [plan_version_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))?;
    value
        .map(|json| {
            serde_json::from_str(&json)
                .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))
        })
        .transpose()
}

pub(super) fn query_run_by_idempotency(
    transaction: &Transaction<'_>,
    idempotency_key: &str,
) -> Result<Option<DesktopRun>, DesktopAuthorityError> {
    let value = transaction
        .query_row(
            "SELECT value_json FROM desktop_runs WHERE idempotency_key = ?1",
            [idempotency_key],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))?;
    value
        .map(|json| {
            serde_json::from_str(&json)
                .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))
        })
        .transpose()
}

pub(super) fn insert_run(
    transaction: &Transaction<'_>,
    run: &DesktopRun,
) -> Result<(), DesktopAuthorityError> {
    transaction
        .execute(
            "INSERT INTO desktop_runs(
               id, conversation_id, project_id, plan_version_id, idempotency_key,
               status, revision, created_at, updated_at, value_json
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
            params![
                run.id,
                run.conversation_id,
                run.project_id,
                run.plan_version_id,
                run.idempotency_key,
                run_status_name(run.status),
                run.revision as i64,
                run.created_at,
                run.updated_at,
                serde_json::to_string(run)
                    .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))?,
            ],
        )
        .map(|_| ())
        .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))
}

pub(super) fn update_run(transaction: &Transaction<'_>, run: &DesktopRun) -> Result<(), String> {
    transaction
        .execute(
            "UPDATE desktop_runs
             SET status = ?2, revision = ?3, updated_at = ?4, value_json = ?5 WHERE id = ?1",
            params![
                run.id,
                run_status_name(run.status),
                run.revision as i64,
                run.updated_at,
                serde_json::to_string(run).map_err(|error| error.to_string())?,
            ],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

pub(super) fn query_run(
    connection: &Connection,
    run_id: &str,
) -> Result<Option<DesktopRun>, rusqlite::Error> {
    let value = connection
        .query_row(
            "SELECT value_json FROM desktop_runs WHERE id = ?1",
            [run_id],
            |row| row.get::<_, String>(0),
        )
        .optional()?;
    value
        .map(|json| {
            serde_json::from_str(&json).map_err(|error| {
                rusqlite::Error::FromSqlConversionFailure(
                    json.len(),
                    rusqlite::types::Type::Text,
                    Box::new(error),
                )
            })
        })
        .transpose()
}

pub(super) fn insert_run_event(
    transaction: &Transaction<'_>,
    run: &DesktopRun,
    event_type: &str,
    created_at: &str,
) -> Result<(), DesktopAuthorityError> {
    let event = run_event_value(run, event_type, created_at);
    transaction
        .execute(
            "INSERT INTO desktop_run_events(
               id, run_id, revision, event_type, created_at, value_json
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params![
                required_string(&event, "id").map_err(DesktopAuthorityError::Storage)?,
                run.id,
                run.revision as i64,
                event_type,
                created_at,
                serde_json::to_string(&event)
                    .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))?,
            ],
        )
        .map(|_| ())
        .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))
}

fn run_event_value(run: &DesktopRun, event_type: &str, created_at: &str) -> Value {
    json!({
        "id": format!("local-run-event-{}", Uuid::new_v4()),
        "run_id": run.id,
        "conversation_id": run.conversation_id,
        "revision": run.revision,
        "type": event_type,
        "status": run.status,
        "created_at": created_at,
        "timestamp": created_at,
        "source": "local_agent_runtime",
        "execution_id": run.id,
        "error": run.error,
    })
}

pub(super) fn typed_rows<T, R>(
    rows: Result<rusqlite::MappedRows<'_, T>, rusqlite::Error>,
) -> Result<Vec<R>, String>
where
    T: FnMut(&rusqlite::Row<'_>) -> rusqlite::Result<String>,
    R: serde::de::DeserializeOwned,
{
    rows.map_err(|error| error.to_string())?
        .map(|row| {
            let value = row.map_err(|error| error.to_string())?;
            serde_json::from_str(&value).map_err(|error| error.to_string())
        })
        .collect()
}
