//! Task validation, response projection, and structural read-model helpers.

use chrono::{SecondsFormat, Utc};
use memstack_workspace_store::{
    WorkspaceTaskAttemptRecord, WorkspaceTaskRecord, WorkspaceTaskScope,
};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::canonical_json;

use super::{
    MAX_IDEMPOTENCY_KEY_CHARS, MAX_TITLE_CHARS, PUBLIC_TASK_NAMESPACE, PublicWorkspaceTask,
    PublicWorkspaceTaskContext, PublicWorkspaceTaskError, RECOVERY_ACTION_LIMIT,
};

pub(super) fn task_scope(context: &PublicWorkspaceTaskContext) -> WorkspaceTaskScope {
    WorkspaceTaskScope {
        tenant_id: context.tenant_id.clone(),
        project_id: context.project_id.clone(),
        workspace_id: context.workspace_id.clone(),
    }
}

pub(super) fn prepared_context(
    context: &PublicWorkspaceTaskContext,
    action: &str,
) -> PublicWorkspaceTaskContext {
    let mut context = context.clone();
    if context.idempotency_key.is_none() {
        context.idempotency_key = Some(format!("legacy-{action}:{}", Uuid::new_v4()));
    }
    context
}

pub(super) fn deterministic_task_id(context: &PublicWorkspaceTaskContext) -> String {
    let identity = format!(
        "{}\0{}\0{}\0{}\0{}",
        context.tenant_id,
        context.project_id,
        context.workspace_id,
        context.user_id,
        context.idempotency_key.as_deref().unwrap_or_default(),
    );
    Uuid::new_v5(&PUBLIC_TASK_NAMESPACE, identity.as_bytes()).to_string()
}

pub(super) fn deterministic_attempt_id(
    context: &PublicWorkspaceTaskContext,
    task_id: &str,
) -> String {
    let Some(idempotency_key) = context.idempotency_key.as_deref() else {
        return Uuid::new_v4().to_string();
    };
    let identity = format!(
        "attempt\0{}\0{}\0{}",
        context.workspace_id, task_id, idempotency_key,
    );
    Uuid::new_v5(&PUBLIC_TASK_NAMESPACE, identity.as_bytes()).to_string()
}

pub(super) fn hash_payload(value: &Value) -> Value {
    match value {
        Value::Object(fields) => Value::Object(
            fields
                .iter()
                .filter(|(key, _)| {
                    !matches!(
                        key.as_str(),
                        "created_at" | "updated_at" | "completed_at" | "archived_at" | "at"
                    )
                })
                .map(|(key, value)| (key.clone(), hash_payload(value)))
                .collect(),
        ),
        Value::Array(values) => Value::Array(values.iter().map(hash_payload).collect()),
        _ => value.clone(),
    }
}

pub(super) fn public_task(
    record: &WorkspaceTaskRecord,
) -> Result<PublicWorkspaceTask, PublicWorkspaceTaskError> {
    let metadata = record
        .metadata
        .as_object()
        .ok_or(PublicWorkspaceTaskError::InvalidRequest)?;
    Ok(PublicWorkspaceTask {
        id: record.task_id.clone(),
        workspace_id: record.workspace_id.clone(),
        title: record.title.clone(),
        description: record.description.clone(),
        created_by: record.created_by.clone(),
        assignee_user_id: record.assignee_user_id.clone(),
        assignee_agent_id: record.assignee_agent_id.clone(),
        workspace_agent_id: workspace_agent_id(metadata),
        current_attempt_id: string_field(metadata, "current_attempt_id"),
        current_attempt_number: i64_field(metadata, "current_attempt_number"),
        current_attempt_conversation_id: string_field(metadata, "current_attempt_conversation_id"),
        current_attempt_worker_binding_id: string_field(
            metadata,
            "current_attempt_worker_binding_id",
        ),
        current_attempt_worker_agent_id: string_field(metadata, "current_attempt_worker_agent_id"),
        last_attempt_status: string_field(metadata, "last_attempt_status"),
        pending_leader_adjudication: metadata
            .get("pending_leader_adjudication")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        last_worker_report_type: string_field(metadata, "last_worker_report_type"),
        last_worker_report_summary: string_field(metadata, "last_worker_report_summary"),
        last_worker_report_artifacts: string_array(metadata, "last_worker_report_artifacts", 3),
        last_worker_report_verifications: string_array(
            metadata,
            "last_worker_report_verifications",
            3,
        ),
        status: record.status.clone(),
        metadata: record.metadata.clone(),
        created_at: record.created_at.clone(),
        updated_at: record.updated_at.clone(),
        priority: priority_name(record.priority),
        estimated_effort: record.estimated_effort.clone(),
        blocker_reason: record.blocker_reason.clone(),
        completed_at: record.completed_at.clone(),
        archived_at: record.archived_at.clone(),
    })
}

pub(super) fn validate_title(title: &str) -> Result<(), PublicWorkspaceTaskError> {
    let chars = title.chars().count();
    if title.trim().is_empty() || chars > MAX_TITLE_CHARS {
        return Err(PublicWorkspaceTaskError::InvalidRequest);
    }
    Ok(())
}

pub(super) fn validate_status(status: &str) -> Result<(), PublicWorkspaceTaskError> {
    if matches!(
        status,
        "todo"
            | "in_progress"
            | "blocked"
            | "done"
            | "dispatched"
            | "executing"
            | "reported"
            | "adjudicating"
    ) {
        Ok(())
    } else {
        Err(PublicWorkspaceTaskError::InvalidRequest)
    }
}

pub(super) fn parse_priority(priority: Option<&str>) -> Result<i64, PublicWorkspaceTaskError> {
    match priority.unwrap_or("") {
        "" => Ok(0),
        "P1" => Ok(1),
        "P2" => Ok(2),
        "P3" => Ok(3),
        "P4" => Ok(4),
        _ => Err(PublicWorkspaceTaskError::InvalidRequest),
    }
}

pub(super) fn priority_name(priority: i64) -> Option<String> {
    match priority {
        1..=4 => Some(format!("P{priority}")),
        _ => None,
    }
}

pub(super) fn apply_transition(
    record: &mut WorkspaceTaskRecord,
    target: &str,
) -> Result<(), PublicWorkspaceTaskError> {
    validate_status(target)?;
    let allowed = matches!(
        (record.status.as_str(), target),
        ("todo", "in_progress" | "blocked")
            | ("in_progress", "blocked" | "done")
            | ("blocked", "in_progress" | "done")
    );
    if !allowed {
        return Err(PublicWorkspaceTaskError::InvalidTransition {
            from: record.status.clone(),
            to: target.to_string(),
        });
    }
    let now = now_string();
    record.status = target.to_string();
    record.updated_at = Some(now.clone());
    record.completed_at = (target == "done").then_some(now);
    if target != "blocked" {
        record.blocker_reason = None;
    }
    Ok(())
}

pub(super) fn require_public_authority(
    record: &WorkspaceTaskRecord,
) -> Result<(), PublicWorkspaceTaskError> {
    if record
        .metadata
        .get("task_role")
        .and_then(Value::as_str)
        .is_some_and(|role| matches!(role, "goal_root" | "execution_task"))
    {
        return Err(PublicWorkspaceTaskError::StructuredAuthorityRequired);
    }
    Ok(())
}

pub(super) fn require_agent_assignment_authority(
    record: &WorkspaceTaskRecord,
) -> Result<(), PublicWorkspaceTaskError> {
    if record.metadata.get("task_role").and_then(Value::as_str) == Some("goal_root") {
        return Err(PublicWorkspaceTaskError::StructuredAuthorityRequired);
    }
    Ok(())
}

pub(super) fn object_or_empty(
    value: Option<Value>,
) -> Result<Map<String, Value>, PublicWorkspaceTaskError> {
    match value {
        None => Ok(Map::new()),
        Some(Value::Object(value)) => Ok(value),
        Some(_) => Err(PublicWorkspaceTaskError::InvalidRequest),
    }
}

pub(super) fn merge_metadata(
    target: &mut Value,
    patch: &Value,
) -> Result<(), PublicWorkspaceTaskError> {
    let target = target
        .as_object_mut()
        .ok_or(PublicWorkspaceTaskError::InvalidRequest)?;
    let patch = patch
        .as_object()
        .ok_or(PublicWorkspaceTaskError::InvalidRequest)?;
    target.extend(patch.clone());
    Ok(())
}

pub(super) fn touch_actor(
    record: &mut WorkspaceTaskRecord,
    action: &str,
    context: &PublicWorkspaceTaskContext,
    agent_id: Option<&str>,
    binding_id: Option<&str>,
) {
    record.updated_at = Some(now_string());
    if let Some(metadata) = record.metadata.as_object_mut() {
        record_actor(metadata, action, context, agent_id, binding_id);
    }
}

pub(super) fn record_actor(
    metadata: &mut Map<String, Value>,
    action: &str,
    context: &PublicWorkspaceTaskContext,
    agent_id: Option<&str>,
    binding_id: Option<&str>,
) {
    metadata.insert(
        "last_mutation_actor".to_string(),
        json!({
            "action": action,
            "actor_type": "human",
            "actor_user_id": &context.user_id,
            "actor_agent_id": agent_id,
            "workspace_agent_binding_id": binding_id,
            "reason": format!("workspace_task.{action}"),
            "at": now_string(),
        }),
    );
}

pub(super) fn clear_binding(metadata: &mut Value) {
    if let Some(metadata) = metadata.as_object_mut() {
        metadata.remove("workspace_agent_binding_id");
    }
}

pub(super) fn workspace_agent_id(metadata: &Map<String, Value>) -> Option<String> {
    string_field(metadata, "workspace_agent_binding_id").or_else(|| {
        metadata
            .get("last_mutation_actor")
            .and_then(Value::as_object)
            .and_then(|actor| string_field(actor, "workspace_agent_binding_id"))
    })
}

pub(super) fn string_field(metadata: &Map<String, Value>, field: &str) -> Option<String> {
    metadata
        .get(field)
        .and_then(Value::as_str)
        .and_then(|value| nonblank(Some(value)))
}

pub(super) fn i64_field(metadata: &Map<String, Value>, field: &str) -> Option<i64> {
    metadata.get(field).and_then(Value::as_i64)
}

pub(super) fn string_array(
    metadata: &Map<String, Value>,
    field: &str,
    limit: usize,
) -> Vec<String> {
    metadata
        .get(field)
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .filter_map(|value| nonblank(Some(value)))
        .take(limit)
        .collect()
}

pub(super) fn nonblank(value: Option<&str>) -> Option<String> {
    value
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

pub(super) fn append_recovery_ledger(metadata: &mut Value, action: &str, reason: &str) {
    let Some(metadata) = metadata.as_object_mut() else {
        return;
    };
    let ledger = metadata
        .entry("recovery_actions")
        .or_insert_with(|| Value::Array(Vec::new()));
    let Some(ledger) = ledger.as_array_mut() else {
        return;
    };
    ledger.push(json!({"action": action, "reason": reason, "at": now_string()}));
    if ledger.len() > RECOVERY_ACTION_LIMIT {
        ledger.drain(0..ledger.len() - RECOVERY_ACTION_LIMIT);
    }
}

pub(super) fn experience_value(
    record: &WorkspaceTaskRecord,
    attempts: &[WorkspaceTaskAttemptRecord],
) -> Value {
    let metadata = record.metadata.as_object();
    let values = |field: &str| {
        metadata
            .map(|value| string_array(value, field, 20))
            .unwrap_or_default()
    };
    let attempt_values = attempts.iter().map(attempt_value).collect::<Vec<_>>();
    json!({
        "task_id": &record.task_id,
        "workspace_id": &record.workspace_id,
        "readiness": {
            "goal_contract": {
                "task_role": metadata.and_then(|value| string_field(value, "task_role")),
                "root_goal_task_id": metadata.and_then(|value| string_field(value, "root_goal_task_id")),
                "description_present": record.description.is_some(),
            },
            "missing_evidence": [],
            "blocked_requirements": [],
            "transition_gates": {"judgment": "agent_judgment_required"},
        },
        "execution": {
            "assignee_user_id": &record.assignee_user_id,
            "assignee_agent_id": &record.assignee_agent_id,
            "workspace_agent_id": metadata.and_then(workspace_agent_id),
            "current_attempt_id": metadata.and_then(|value| string_field(value, "current_attempt_id")),
            "current_attempt_number": metadata.and_then(|value| i64_field(value, "current_attempt_number")),
            "active_attempt": attempt_values.first(),
            "attempts": attempt_values,
        },
        "evidence": {
            "evidence_refs": values("evidence_refs"),
            "artifacts": values("last_worker_report_artifacts"),
            "verification_summaries": values("last_worker_report_verifications"),
            "worker_report": {
                "type": metadata.and_then(|value| string_field(value, "last_worker_report_type")),
                "summary": metadata.and_then(|value| string_field(value, "last_worker_report_summary")),
            },
        },
        "diagnostics": {
            "blocker_reason": &record.blocker_reason,
            "pending_leader_adjudication": metadata
                .and_then(|value| value.get("pending_leader_adjudication"))
                .and_then(Value::as_bool)
                .unwrap_or(false),
            "transition_gates": {"judgment": "agent_judgment_required"},
        },
        "activity": [{"type": "task_created", "at": &record.created_at, "summary": "Task created"}],
    })
}

pub(super) fn attempt_value(attempt: &WorkspaceTaskAttemptRecord) -> Value {
    json!({
        "id": &attempt.attempt_id,
        "attempt_number": attempt.attempt_number,
        "status": &attempt.status,
        "conversation_id": &attempt.conversation_id,
        "worker_agent_id": &attempt.worker_agent_id,
        "leader_agent_id": &attempt.leader_agent_id,
        "summary": &attempt.candidate_summary,
        "artifacts": &attempt.candidate_artifacts,
        "verifications": &attempt.candidate_verifications,
        "leader_feedback": &attempt.leader_feedback,
        "adjudication_reason": &attempt.adjudication_reason,
        "created_at": &attempt.created_at,
        "updated_at": &attempt.updated_at,
        "completed_at": &attempt.completed_at,
    })
}

pub(super) fn execution_session_value(
    record: &WorkspaceTaskRecord,
    attempt: Option<&WorkspaceTaskAttemptRecord>,
    execution: Option<memstack_workspace_store::WorkspaceTaskExecutionRecord>,
) -> Value {
    let has_execution = execution.is_some();
    let (conversation_id, execution_status, last_event_at, session_status) = execution
        .map(|value| {
            (
                Some(value.conversation_id),
                value.execution_status,
                Some(value.updated_at),
                value.status,
            )
        })
        .unwrap_or((None, None, None, "not_started".to_string()));
    json!({
        "workspace_id": &record.workspace_id,
        "task_id": &record.task_id,
        "task_status": &record.status,
        "health": if has_execution { "recorded" } else { "idle" },
        "session_status": session_status,
        "conversation_id": conversation_id,
        "attempt_id": attempt.map(|value| value.attempt_id.as_str()),
        "attempt_status": attempt.map(|value| value.status.as_str()),
        "execution_status": execution_status,
        "last_event_at": last_event_at,
        "last_assistant_event_at": Value::Null,
        "last_error": Value::Null,
        "has_user_input": false,
        "has_assistant_output": false,
        "incidents": [],
        "recommended_recovery_action": Value::Null,
        "available_interventions": ["retry_launch", "new_attempt", "reassign", "mark_human_blocked", "terminate_stale_conversation"],
        "recent_events": [],
        "recovery_actions": record.metadata.get("recovery_actions").cloned().unwrap_or_else(|| json!([])),
    })
}

pub(super) fn validate_recovery_action(action: &str) -> Result<(), PublicWorkspaceTaskError> {
    if matches!(
        action,
        "retry_launch"
            | "new_attempt"
            | "reassign"
            | "mark_human_blocked"
            | "terminate_stale_conversation"
    ) {
        Ok(())
    } else {
        Err(PublicWorkspaceTaskError::InvalidRequest)
    }
}

pub(super) fn validate_idempotency_key(value: &str) -> Result<(), PublicWorkspaceTaskError> {
    if value.trim().is_empty() || value.chars().count() > MAX_IDEMPOTENCY_KEY_CHARS {
        return Err(PublicWorkspaceTaskError::InvalidRequest);
    }
    Ok(())
}

pub(super) fn request_hash(payload: Value) -> Result<String, PublicWorkspaceTaskError> {
    let bytes =
        serde_json::to_vec(&canonical_json(&payload)).map_err(PublicWorkspaceTaskError::Json)?;
    Ok(hex::encode(Sha256::digest(bytes)))
}

pub(super) fn now_string() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Micros, true)
}
