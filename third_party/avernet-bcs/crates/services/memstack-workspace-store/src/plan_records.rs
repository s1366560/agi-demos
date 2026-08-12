//! Workspace Plan row decoding and transition result classification.

use bcs_db_api::{DbError, DbRow, DbTransactionStepResult};
use serde_json::Value;
use thiserror::Error;

use crate::{
    WorkspacePipelineRunRecord, WorkspacePlanBlackboardRecord, WorkspacePlanEventRecord,
    WorkspacePlanNodeRecord, WorkspacePlanOutboxRecord, WorkspacePlanRecord,
    WorkspacePlanTransitionOutcome,
};

/// Invalid authority, snapshot, or persistence state.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspacePlanStoreError {
    #[error(transparent)]
    Database(#[from] DbError),
    #[error("Workspace not found")]
    WorkspaceNotFound,
    #[error("Workspace access required")]
    AccessDenied,
    #[error("Workspace editor access required")]
    EditorAccessRequired,
    #[error("Workspace Plan not found")]
    PlanNotFound,
    #[error("Workspace Plan node not found")]
    NodeNotFound,
    #[error("Workspace Plan outbox item not found")]
    OutboxNotFound,
    #[error("Workspace Plan revision conflict")]
    RevisionConflict,
    #[error("Workspace Plan transition conflicts with current state")]
    InvalidTransition,
    #[error("Workspace Plan idempotency key conflicts with another request")]
    IdempotencyConflict,
    #[error("Workspace Plan persistence field is invalid: {0}")]
    InvalidField(&'static str),
    #[error("Workspace Plan JSON is invalid: {0}")]
    InvalidJson(#[source] serde_json::Error),
    #[error("Workspace Plan transaction result is invalid")]
    InvalidTransactionResult,
}

pub(crate) fn rows_at(
    results: &[DbTransactionStepResult],
    index: usize,
) -> Result<&[DbRow], WorkspacePlanStoreError> {
    match results.get(index) {
        Some(DbTransactionStepResult::Rows(rows)) => Ok(rows),
        _ => Err(WorkspacePlanStoreError::InvalidTransactionResult),
    }
}

fn required_string(row: &DbRow, field: &'static str) -> Result<String, WorkspacePlanStoreError> {
    row.get_string(field)?
        .ok_or(WorkspacePlanStoreError::InvalidField(field))
}

fn optional_string(
    row: &DbRow,
    field: &'static str,
) -> Result<Option<String>, WorkspacePlanStoreError> {
    Ok(row.get_string(field)?)
}

fn required_u64(row: &DbRow, field: &'static str) -> Result<u64, WorkspacePlanStoreError> {
    let value = row
        .get_i64(field)?
        .ok_or(WorkspacePlanStoreError::InvalidField(field))?;
    u64::try_from(value).map_err(|_| WorkspacePlanStoreError::InvalidField(field))
}

fn json_field(row: &DbRow, field: &'static str) -> Result<Value, WorkspacePlanStoreError> {
    serde_json::from_str(&required_string(row, field)?)
        .map_err(WorkspacePlanStoreError::InvalidJson)
}

fn optional_json_field(
    row: &DbRow,
    field: &'static str,
) -> Result<Option<Value>, WorkspacePlanStoreError> {
    optional_string(row, field)?
        .map(|value| serde_json::from_str(&value).map_err(WorkspacePlanStoreError::InvalidJson))
        .transpose()
}

pub(crate) fn plan_from_row(row: &DbRow) -> Result<WorkspacePlanRecord, WorkspacePlanStoreError> {
    Ok(WorkspacePlanRecord {
        plan_id: required_string(row, "plan_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        source_task_id: optional_string(row, "source_task_id")?,
        goal: required_string(row, "goal")?,
        goal_json: json_field(row, "goal_json")?,
        status: required_string(row, "status")?,
        revision: required_u64(row, "revision")?,
        metadata: json_field(row, "metadata_json")?,
        created_at: required_string(row, "created_at")?,
        updated_at: required_string(row, "updated_at")?,
        completed_at: optional_string(row, "completed_at")?,
    })
}

pub(crate) fn node_from_row(
    row: &DbRow,
) -> Result<WorkspacePlanNodeRecord, WorkspacePlanStoreError> {
    Ok(WorkspacePlanNodeRecord {
        node_id: required_string(row, "node_id")?,
        plan_id: required_string(row, "plan_id")?,
        workspace_task_id: optional_string(row, "workspace_task_id")?,
        parent_id: optional_string(row, "parent_id")?,
        kind: required_string(row, "kind")?,
        title: required_string(row, "title")?,
        description: optional_string(row, "description")?,
        intent: optional_string(row, "intent")?,
        status: required_string(row, "status")?,
        sequence_number: row
            .get_i64("sequence_number")?
            .ok_or(WorkspacePlanStoreError::InvalidField("sequence_number"))?,
        dependencies: json_field(row, "dependencies_json")?,
        acceptance_criteria: json_field(row, "acceptance_criteria_json")?,
        feature_checkpoint: optional_json_field(row, "feature_checkpoint_json")?,
        handoff_package: optional_json_field(row, "handoff_package_json")?,
        recommended_capabilities: json_field(row, "recommended_capabilities_json")?,
        priority: row
            .get_i64("priority")?
            .ok_or(WorkspacePlanStoreError::InvalidField("priority"))?,
        progress: json_field(row, "progress_json")?,
        assignee_agent_id: optional_string(row, "assignee_agent_id")?,
        current_attempt_id: optional_string(row, "current_attempt_id")?,
        timeout_deadline_at: optional_string(row, "timeout_deadline_at")?,
        metadata: json_field(row, "metadata_json")?,
        created_at: required_string(row, "created_at")?,
        updated_at: required_string(row, "updated_at")?,
        completed_at: optional_string(row, "completed_at")?,
    })
}

pub(crate) fn blackboard_from_row(
    row: &DbRow,
) -> Result<WorkspacePlanBlackboardRecord, WorkspacePlanStoreError> {
    Ok(WorkspacePlanBlackboardRecord {
        plan_id: required_string(row, "plan_id")?,
        key: required_string(row, "key")?,
        value: json_field(row, "value_json")?,
        published_by: optional_string(row, "created_by_actor_id")?,
        version: required_u64(row, "version")?,
        schema_ref: optional_string(row, "schema_ref")?,
        metadata: json_field(row, "metadata_json")?,
    })
}

pub(crate) fn outbox_from_row(
    row: &DbRow,
) -> Result<WorkspacePlanOutboxRecord, WorkspacePlanStoreError> {
    Ok(WorkspacePlanOutboxRecord {
        outbox_id: required_string(row, "outbox_id")?,
        aggregate_id: required_string(row, "aggregate_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        event_type: required_string(row, "event_type")?,
        payload: json_field(row, "payload_json")?,
        status: required_string(row, "status")?,
        attempt_count: required_u64(row, "attempt_count")?,
        max_attempts: required_u64(row, "max_attempts")?,
        lease_owner: optional_string(row, "lease_owner")?,
        lease_expires_at: optional_string(row, "lease_expires_at")?,
        last_error: optional_string(row, "last_error")?,
        next_attempt_at: optional_string(row, "next_attempt_at")?,
        dispatched_at: optional_string(row, "dispatched_at")?,
        metadata: json_field(row, "metadata_json")?,
        created_at: required_string(row, "created_at")?,
        updated_at: required_string(row, "updated_at")?,
    })
}

pub(crate) fn event_from_row(
    row: &DbRow,
) -> Result<WorkspacePlanEventRecord, WorkspacePlanStoreError> {
    Ok(WorkspacePlanEventRecord {
        event_id: required_string(row, "event_id")?,
        plan_id: required_string(row, "plan_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        node_id: optional_string(row, "node_id")?,
        attempt_id: optional_string(row, "attempt_id")?,
        event_type: required_string(row, "event_type")?,
        source: required_string(row, "source")?,
        actor_id: optional_string(row, "actor_id")?,
        payload: json_field(row, "payload_json")?,
        created_at: required_string(row, "created_at")?,
    })
}

pub(crate) fn pipeline_run_from_row(
    row: &DbRow,
) -> Result<WorkspacePipelineRunRecord, WorkspacePlanStoreError> {
    Ok(WorkspacePipelineRunRecord {
        run_id: required_string(row, "run_id")?,
        provider: required_string(row, "provider")?,
        status: required_string(row, "status")?,
        reason: optional_string(row, "reason")?,
        node_id: optional_string(row, "node_id")?,
        attempt_id: optional_string(row, "attempt_id")?,
        commit_ref: optional_string(row, "commit_ref")?,
        metadata: json_field(row, "metadata_json")?,
        started_at: optional_string(row, "started_at")?,
        completed_at: optional_string(row, "completed_at")?,
        created_at: required_string(row, "created_at")?,
    })
}

pub(crate) fn required_json(
    value: &Option<Value>,
    field: &'static str,
) -> Result<String, WorkspacePlanStoreError> {
    value
        .as_ref()
        .map(Value::to_string)
        .ok_or(WorkspacePlanStoreError::InvalidField(field))
}

pub(crate) fn revision_i64(revision: u64) -> i64 {
    i64::try_from(revision).unwrap_or(i64::MAX)
}

pub(crate) fn replay_from_rows(
    rows: &[DbRow],
    replayed: bool,
    expected_event_type: &str,
    expected_request_hash: &str,
) -> Result<WorkspacePlanTransitionOutcome, WorkspacePlanStoreError> {
    let Some(row) = rows.first() else {
        return Err(WorkspacePlanStoreError::InvalidTransactionResult);
    };
    let metadata = json_field(row, "metadata_json")?;
    let event_type = required_string(row, "event_type")?;
    let request_hash = metadata.get("request_hash").and_then(Value::as_str);
    if event_type != expected_event_type || request_hash != Some(expected_request_hash) {
        return Err(WorkspacePlanStoreError::IdempotencyConflict);
    }
    let response = metadata
        .get("public_response")
        .cloned()
        .ok_or(WorkspacePlanStoreError::InvalidField("public_response"))?;
    Ok(WorkspacePlanTransitionOutcome { response, replayed })
}

pub(crate) fn classify_transition_error(
    error: DbError,
    access_step: usize,
    revision_step: usize,
    domain_start: usize,
    domain_end: usize,
    plan_cas_step: usize,
) -> WorkspacePlanStoreError {
    if let DbError::TransactionExpectation { step_index, .. } = &error {
        if *step_index == access_step {
            return WorkspacePlanStoreError::EditorAccessRequired;
        }
        if *step_index == revision_step || *step_index == plan_cas_step {
            return WorkspacePlanStoreError::RevisionConflict;
        }
        if (domain_start..domain_end).contains(step_index) {
            return WorkspacePlanStoreError::InvalidTransition;
        }
    }
    WorkspacePlanStoreError::Database(error)
}
