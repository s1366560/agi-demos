//! Structural Workspace execution diagnostics over durable Task and Plan projections.

use std::collections::BTreeMap;

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use chrono::{SecondsFormat, Utc};
use memstack_workspace_store::{
    WorkspacePlanOutboxRecord, WorkspacePlanScope, WorkspacePlanSnapshotQuery, WorkspacePlanStore,
    WorkspacePlanStoreError, WorkspaceTaskAttemptRecord, WorkspaceTaskRecord, WorkspaceTaskScope,
    WorkspaceTaskStore, WorkspaceTaskStoreError,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use thiserror::Error;

const TASK_LIMIT_MAX: i64 = 200;
const ATTEMPT_LIMIT: i64 = 3;
const OUTBOX_LIMIT: u64 = 50;

/// Authenticated scope and deterministic projection limits.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceExecutionDiagnosticsInput {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub user_id: String,
    pub task_limit: i64,
    pub tool_limit_per_conversation: i64,
}

/// Legacy-compatible execution diagnostics response.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PublicWorkspaceExecutionDiagnostics {
    pub workspace_id: String,
    pub generated_at: String,
    pub task_status_counts: BTreeMap<String, u64>,
    pub attempt_status_counts: BTreeMap<String, u64>,
    pub tool_status_counts: BTreeMap<String, u64>,
    pub tasks: Vec<Value>,
    pub blockers: Vec<Value>,
    pub pending_adjudications: Vec<Value>,
    pub evidence_gaps: Vec<Value>,
    pub recent_tool_failures: Vec<Value>,
    pub controller_state: Value,
    pub retry_queue: Vec<Value>,
    pub active_attempts: Vec<Value>,
    pub last_reconciliation: Value,
    pub completion_gate: Value,
    pub blocked_reason: Option<String>,
}

/// Stable diagnostics error category consumed by the HTTP adapter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PublicWorkspaceExecutionDiagnosticsErrorKind {
    InvalidRequest,
    NotFound,
    Forbidden,
    Unavailable,
}

/// Diagnostics validation, authorization, or durable projection failure.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceExecutionDiagnosticsError {
    #[error("invalid Workspace execution diagnostics request")]
    InvalidRequest,
    #[error("Workspace not found")]
    NotFound,
    #[error("Workspace access denied")]
    Forbidden,
    #[error(transparent)]
    Task(#[from] WorkspaceTaskStoreError),
    #[error(transparent)]
    Plan(#[from] WorkspacePlanStoreError),
}

impl PublicWorkspaceExecutionDiagnosticsError {
    #[must_use]
    pub const fn kind(&self) -> PublicWorkspaceExecutionDiagnosticsErrorKind {
        match self {
            Self::InvalidRequest => PublicWorkspaceExecutionDiagnosticsErrorKind::InvalidRequest,
            Self::NotFound | Self::Task(WorkspaceTaskStoreError::NotFound) => {
                PublicWorkspaceExecutionDiagnosticsErrorKind::NotFound
            }
            Self::Forbidden
            | Self::Task(
                WorkspaceTaskStoreError::AccessRequired
                | WorkspaceTaskStoreError::EditorAccessRequired,
            )
            | Self::Plan(
                WorkspacePlanStoreError::AccessDenied
                | WorkspacePlanStoreError::EditorAccessRequired,
            ) => PublicWorkspaceExecutionDiagnosticsErrorKind::Forbidden,
            Self::Task(_) | Self::Plan(_) => {
                PublicWorkspaceExecutionDiagnosticsErrorKind::Unavailable
            }
        }
    }
}

/// Read-only diagnostics service. It never advances execution or derives semantic verdicts.
pub struct PublicWorkspaceExecutionDiagnosticsService<'a> {
    task_store: WorkspaceTaskStore<'a>,
    plan_store: WorkspacePlanStore<'a>,
}

impl<'a> PublicWorkspaceExecutionDiagnosticsService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            task_store: WorkspaceTaskStore::new(db, flavor),
            plan_store: WorkspacePlanStore::new(db, flavor),
        }
    }

    /// Build structural counts and explicit persisted blockers from Task and Plan authority.
    ///
    /// Tool execution detail remains owned by Agent Runtime, so this projection deliberately
    /// returns empty tool rows instead of reconstructing them from unrelated text fields.
    ///
    /// # Errors
    ///
    /// Returns stable validation, authorization, or persistence errors.
    pub async fn read(
        &self,
        input: &PublicWorkspaceExecutionDiagnosticsInput,
    ) -> Result<PublicWorkspaceExecutionDiagnostics, PublicWorkspaceExecutionDiagnosticsError> {
        validate_input(input)?;
        let task_scope = WorkspaceTaskScope {
            tenant_id: input.tenant_id.clone(),
            project_id: input.project_id.clone(),
            workspace_id: input.workspace_id.clone(),
        };
        self.task_store
            .require_access(&task_scope, input.user_id.as_str(), false)
            .await?;
        let tasks = self
            .task_store
            .list(&task_scope, None, input.task_limit, 0)
            .await?;
        let plan = self
            .plan_store
            .snapshot(&WorkspacePlanSnapshotQuery {
                scope: WorkspacePlanScope {
                    tenant_id: input.tenant_id.clone(),
                    project_id: input.project_id.clone(),
                    workspace_id: input.workspace_id.clone(),
                    actor_id: input.user_id.clone(),
                    actor_is_superuser: false,
                },
                plan_id: None,
                include_details: true,
                outbox_limit: OUTBOX_LIMIT,
                event_limit: 1,
            })
            .await?;

        let mut task_status_counts = BTreeMap::new();
        let mut attempt_status_counts = BTreeMap::new();
        let mut task_rows = Vec::with_capacity(tasks.len());
        let mut blockers = Vec::new();
        let mut pending_adjudications = Vec::new();
        let mut evidence_gaps = Vec::new();
        let mut active_attempts = Vec::new();

        for task in &tasks {
            increment(&mut task_status_counts, task.status.as_str());
            let attempts = self
                .task_store
                .attempts(&task_scope, task.task_id.as_str(), ATTEMPT_LIMIT)
                .await?;
            for attempt in &attempts {
                increment(&mut attempt_status_counts, attempt.status.as_str());
            }
            let execution = self
                .task_store
                .execution(&task_scope, task.task_id.as_str())
                .await?;
            let latest = attempts.first();
            task_rows.push(task_row(task, latest));
            append_task_blockers(&mut blockers, task, latest);
            append_pending_adjudication(&mut pending_adjudications, task, latest);
            append_evidence_gaps(&mut evidence_gaps, task, latest);
            if let Some(attempt) = latest
                && is_active_attempt(attempt.status.as_str())
            {
                active_attempts.push(json!({
                    "task_id": &task.task_id,
                    "attempt_id": &attempt.attempt_id,
                    "status": &attempt.status,
                    "conversation_id": &attempt.conversation_id,
                    "worker_agent_id": &attempt.worker_agent_id,
                    "updated_at": &attempt.updated_at,
                }));
            }
            if execution
                .as_ref()
                .is_some_and(|value| value.status == "failed")
            {
                blockers.push(json!({
                    "type": "execution_failed",
                    "task_id": &task.task_id,
                    "correlation_id": execution.as_ref().map(|value| &value.correlation_id),
                    "reason": Value::Null,
                }));
            }
        }

        for node in &plan.nodes {
            if node.status == "blocked" {
                blockers.push(json!({
                    "type": "plan_node_blocked",
                    "node_id": &node.node_id,
                    "task_id": &node.workspace_task_id,
                    "title": &node.title,
                    "reason": node.metadata.get("blocked_reason").cloned(),
                }));
            }
        }
        let retry_queue = retry_queue(&plan.outbox);
        append_outbox_blockers(&mut blockers, &plan.outbox);

        let all_tasks_terminal =
            !tasks.is_empty() && tasks.iter().all(|task| task.status == "done");
        let completion_gate = json!({
            "all_tasks_terminal": all_tasks_terminal,
            "pending_outbox_count": retry_queue.len(),
            "active_attempt_count": active_attempts.len(),
            "evidence_gap_count": evidence_gaps.len(),
            "ready": all_tasks_terminal
                && retry_queue.is_empty()
                && active_attempts.is_empty()
                && evidence_gaps.is_empty(),
        });
        let blocked_reason = blockers.iter().find_map(explicit_blocked_reason);
        let generated_at = Utc::now().to_rfc3339_opts(SecondsFormat::Micros, true);
        let selected_plan = plan.selected.as_ref();
        let controller_state = json!({
            "workspace_id": &input.workspace_id,
            "plan_id": selected_plan.map(|value| &value.plan_id),
            "plan_status": selected_plan.map(|value| &value.status),
            "plan_revision": selected_plan.map(|value| value.revision),
            "task_count": tasks.len(),
            "agent_runtime_detail_authority": "external",
        });

        Ok(PublicWorkspaceExecutionDiagnostics {
            workspace_id: input.workspace_id.clone(),
            generated_at: generated_at.clone(),
            task_status_counts,
            attempt_status_counts,
            tool_status_counts: BTreeMap::new(),
            tasks: task_rows,
            blockers,
            pending_adjudications,
            evidence_gaps,
            recent_tool_failures: Vec::new(),
            controller_state,
            retry_queue,
            active_attempts,
            last_reconciliation: json!({
                "workspace_id": &input.workspace_id,
                "generated_at": &generated_at,
                "source": "avernet_durable_projection",
            }),
            completion_gate,
            blocked_reason,
        })
    }
}

fn validate_input(
    input: &PublicWorkspaceExecutionDiagnosticsInput,
) -> Result<(), PublicWorkspaceExecutionDiagnosticsError> {
    if input.tenant_id.trim().is_empty()
        || input.project_id.trim().is_empty()
        || input.workspace_id.trim().is_empty()
        || input.user_id.trim().is_empty()
        || !(1..=TASK_LIMIT_MAX).contains(&input.task_limit)
        || !(1..=500).contains(&input.tool_limit_per_conversation)
    {
        return Err(PublicWorkspaceExecutionDiagnosticsError::InvalidRequest);
    }
    Ok(())
}

fn increment(counts: &mut BTreeMap<String, u64>, status: &str) {
    let count = counts.entry(status.to_string()).or_default();
    *count = count.saturating_add(1);
}

fn task_row(task: &WorkspaceTaskRecord, latest: Option<&WorkspaceTaskAttemptRecord>) -> Value {
    let current_attempt_id = task
        .metadata
        .get("current_attempt_id")
        .and_then(Value::as_str);
    json!({
        "task_id": &task.task_id,
        "title": &task.title,
        "status": &task.status,
        "priority": priority_name(task.priority),
        "blocker_reason": &task.blocker_reason,
        "current_attempt_id": current_attempt_id,
        "latest_attempt_id": latest.map(|value| &value.attempt_id),
        "latest_attempt_status": latest.map(|value| &value.status),
        "latest_attempt_conversation_id": latest.and_then(|value| value.conversation_id.as_ref()),
        "pending_leader_adjudication": latest
            .is_some_and(|value| value.status == "awaiting_leader_adjudication"),
        "last_worker_report_summary": latest.and_then(|value| value.candidate_summary.as_ref()),
        "verification_count": latest.map_or(0, |value| json_array_len(&value.candidate_verifications)),
        "tool_execution_count": 0,
        "failed_tool_count": 0,
        "latest_tool": Value::Null,
        "updated_at": &task.updated_at,
    })
}

fn priority_name(priority: i64) -> Option<String> {
    (1..=4).contains(&priority).then(|| format!("P{priority}"))
}

fn append_task_blockers(
    rows: &mut Vec<Value>,
    task: &WorkspaceTaskRecord,
    latest: Option<&WorkspaceTaskAttemptRecord>,
) {
    if task.status == "blocked" {
        rows.push(json!({
            "type": "task_blocked",
            "task_id": &task.task_id,
            "title": &task.title,
            "reason": &task.blocker_reason,
        }));
    }
    if let Some(attempt) = latest
        && matches!(
            attempt.status.as_str(),
            "blocked" | "rejected" | "cancelled"
        )
    {
        rows.push(json!({
            "type": "attempt_blocked",
            "task_id": &task.task_id,
            "title": &task.title,
            "attempt_id": &attempt.attempt_id,
            "attempt_status": &attempt.status,
            "reason": attempt.leader_feedback.as_ref().or(attempt.adjudication_reason.as_ref()),
        }));
    }
}

fn append_pending_adjudication(
    rows: &mut Vec<Value>,
    task: &WorkspaceTaskRecord,
    latest: Option<&WorkspaceTaskAttemptRecord>,
) {
    if task.status == "adjudicating"
        || latest.is_some_and(|attempt| attempt.status == "awaiting_leader_adjudication")
    {
        rows.push(json!({
            "task_id": &task.task_id,
            "title": &task.title,
            "attempt_id": latest.map(|value| &value.attempt_id),
            "status": latest.map(|value| &value.status),
        }));
    }
}

fn append_evidence_gaps(
    rows: &mut Vec<Value>,
    task: &WorkspaceTaskRecord,
    latest: Option<&WorkspaceTaskAttemptRecord>,
) {
    if !matches!(task.status.as_str(), "reported" | "adjudicating" | "done") {
        return;
    }
    let Some(attempt) = latest else {
        rows.push(json!({
            "type": "missing_structured_attempt",
            "task_id": &task.task_id,
            "title": &task.title,
        }));
        return;
    };
    let artifacts_missing = json_array_len(&attempt.candidate_artifacts) == 0;
    let verifications_missing = json_array_len(&attempt.candidate_verifications) == 0;
    if artifacts_missing || verifications_missing {
        rows.push(json!({
            "type": "missing_structured_evidence",
            "task_id": &task.task_id,
            "attempt_id": &attempt.attempt_id,
            "artifacts_missing": artifacts_missing,
            "verifications_missing": verifications_missing,
        }));
    }
}

fn retry_queue(outbox: &[WorkspacePlanOutboxRecord]) -> Vec<Value> {
    outbox
        .iter()
        .filter(|item| item.status != "dispatched")
        .map(|item| {
            json!({
                "outbox_id": &item.outbox_id,
                "event_type": &item.event_type,
                "status": &item.status,
                "attempt_count": item.attempt_count,
                "max_attempts": item.max_attempts,
                "next_attempt_at": &item.next_attempt_at,
                "last_error": &item.last_error,
            })
        })
        .collect()
}

fn append_outbox_blockers(rows: &mut Vec<Value>, outbox: &[WorkspacePlanOutboxRecord]) {
    for item in outbox.iter().filter(|item| item.status == "dead_letter") {
        rows.push(json!({
            "type": "outbox_dead_letter",
            "outbox_id": &item.outbox_id,
            "event_type": &item.event_type,
            "reason": &item.last_error,
        }));
    }
}

fn explicit_blocked_reason(row: &Value) -> Option<String> {
    row.get("reason")
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .map(str::to_string)
}

fn json_array_len(value: &Value) -> usize {
    value.as_array().map_or(0, Vec::len)
}

fn is_active_attempt(status: &str) -> bool {
    matches!(
        status,
        "pending" | "running" | "awaiting_leader_adjudication"
    )
}
