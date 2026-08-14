//! Internal structured Workspace Task authority for Agent Runtime.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use chrono::{SecondsFormat, Utc};
use memstack_workspace_store::{
    WorkspaceTaskAuxiliaryWrite, WorkspaceTaskDispatchWrite, WorkspaceTaskDomainWrite,
    WorkspaceTaskMutation, WorkspaceTaskMutationOutcome, WorkspaceTaskRecord, WorkspaceTaskScope,
    WorkspaceTaskStore, WorkspaceTaskStoreError,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use thiserror::Error;
use uuid::Uuid;

use crate::canonical_json;

const STRUCTURED_TASK_NAMESPACE: Uuid = Uuid::from_u128(0x91b8_47bb_6389_4c3e_a287_6eef_414e_8b47);

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct StructuredTaskActor {
    pub user_id: String,
    pub leader_agent_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct StructuredTaskContext {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub actor: StructuredTaskActor,
    pub expected_revision: Option<u64>,
    pub idempotency_key: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Deserialize)]
pub struct StructuredTaskMutationFields {
    pub title: Option<String>,
    pub description: Option<String>,
    pub status: Option<String>,
    pub priority: Option<String>,
    pub metadata: Option<Value>,
    pub workspace_agent_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StructuredWorkspaceTask {
    pub id: String,
    pub workspace_id: String,
    pub title: String,
    pub description: Option<String>,
    pub created_by: String,
    pub assignee_user_id: Option<String>,
    pub assignee_agent_id: Option<String>,
    pub workspace_agent_id: Option<String>,
    pub status: String,
    pub priority: String,
    pub estimated_effort: Option<String>,
    pub blocker_reason: Option<String>,
    pub metadata: Value,
    pub created_at: String,
    pub updated_at: Option<String>,
    pub completed_at: Option<String>,
    pub archived_at: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StructuredTaskMutationOutcome {
    pub task: StructuredWorkspaceTask,
    pub committed_revision: u64,
    pub outbox_id: String,
    pub replayed: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StructuredTaskDeleteOutcome {
    pub task_id: String,
    pub workspace_id: String,
    pub committed_revision: u64,
    pub outbox_id: String,
    pub replayed: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StructuredTaskErrorKind {
    InvalidRequest,
    NotFound,
    Forbidden,
    Conflict,
    Unavailable,
}

#[derive(Debug, Error)]
#[non_exhaustive]
pub enum StructuredTaskError {
    #[error("invalid structured Workspace Task request")]
    InvalidRequest,
    #[error("structured Workspace Task was not found")]
    NotFound,
    #[error(transparent)]
    Store(#[from] WorkspaceTaskStoreError),
    #[error("structured Workspace Task JSON serialization failed: {0}")]
    Json(#[from] serde_json::Error),
}

impl StructuredTaskError {
    #[must_use]
    pub const fn kind(&self) -> StructuredTaskErrorKind {
        match self {
            Self::InvalidRequest => StructuredTaskErrorKind::InvalidRequest,
            Self::NotFound | Self::Store(WorkspaceTaskStoreError::TaskNotFound) => {
                StructuredTaskErrorKind::NotFound
            }
            Self::Store(
                WorkspaceTaskStoreError::AccessRequired
                | WorkspaceTaskStoreError::EditorAccessRequired,
            ) => StructuredTaskErrorKind::Forbidden,
            Self::Store(
                WorkspaceTaskStoreError::Conflict
                | WorkspaceTaskStoreError::IdempotencyConflict
                | WorkspaceTaskStoreError::IncompleteReceipt,
            ) => StructuredTaskErrorKind::Conflict,
            Self::Store(WorkspaceTaskStoreError::NotFound) => StructuredTaskErrorKind::NotFound,
            Self::Store(_) | Self::Json(_) => StructuredTaskErrorKind::Unavailable,
        }
    }
}

pub struct StructuredTaskService<'a> {
    store: WorkspaceTaskStore<'a>,
}

impl<'a> StructuredTaskService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            store: WorkspaceTaskStore::new(db, flavor),
        }
    }

    /// Derive the stable execution Task identifier before attempting its idempotent create.
    pub fn execution_task_id(
        context: &StructuredTaskContext,
    ) -> Result<String, StructuredTaskError> {
        validate_context(context)?;
        if context
            .idempotency_key
            .as_deref()
            .is_some_and(|key| key.trim().is_empty() || key.chars().count() > 256)
        {
            return Err(StructuredTaskError::InvalidRequest);
        }
        Ok(deterministic_task_id(context))
    }

    pub async fn get(
        &self,
        context: &StructuredTaskContext,
        task_id: &str,
    ) -> Result<StructuredWorkspaceTask, StructuredTaskError> {
        let scope = validate_context(context)?;
        self.store
            .require_access(&scope, context.actor.user_id.as_str(), false)
            .await?;
        let record = self
            .store
            .get(&scope, task_id)
            .await?
            .ok_or(StructuredTaskError::NotFound)?;
        project_task(&record)
    }

    pub async fn list_root_children(
        &self,
        context: &StructuredTaskContext,
        root_goal_task_id: &str,
    ) -> Result<Vec<StructuredWorkspaceTask>, StructuredTaskError> {
        let scope = validate_context(context)?;
        if root_goal_task_id.trim().is_empty() {
            return Err(StructuredTaskError::InvalidRequest);
        }
        self.store
            .require_access(&scope, context.actor.user_id.as_str(), false)
            .await?;
        self.store
            .list(&scope, None, 500, 0)
            .await?
            .iter()
            .filter(|task| {
                task.archived_at.is_none()
                    && task
                        .metadata
                        .get("root_goal_task_id")
                        .and_then(Value::as_str)
                        == Some(root_goal_task_id)
            })
            .map(project_task)
            .collect()
    }

    pub async fn create_execution_task(
        &self,
        context: &StructuredTaskContext,
        fields: &StructuredTaskMutationFields,
        root_goal_task_id: &str,
    ) -> Result<StructuredTaskMutationOutcome, StructuredTaskError> {
        let scope = validate_context(context)?;
        let title = fields
            .title
            .as_deref()
            .filter(|value| !value.trim().is_empty() && value.chars().count() <= 255)
            .ok_or(StructuredTaskError::InvalidRequest)?;
        if root_goal_task_id.trim().is_empty() {
            return Err(StructuredTaskError::InvalidRequest);
        }
        let task_id = Self::execution_task_id(context)?;
        let now = now_string();
        let mut metadata = metadata_object(fields.metadata.clone())?;
        metadata.insert("autonomy_schema_version".to_string(), Value::from(1));
        metadata.insert(
            "task_role".to_string(),
            Value::String("execution_task".to_string()),
        );
        metadata.insert(
            "root_goal_task_id".to_string(),
            Value::String(root_goal_task_id.to_string()),
        );
        record_actor(
            &mut metadata,
            "create",
            context,
            fields.workspace_agent_id.as_deref(),
        );
        let mut record = WorkspaceTaskRecord {
            task_id: task_id.clone(),
            tenant_id: scope.tenant_id.clone(),
            project_id: scope.project_id.clone(),
            workspace_id: scope.workspace_id.clone(),
            title: title.to_string(),
            description: fields.description.clone(),
            created_by: context.actor.user_id.clone(),
            assignee_user_id: None,
            assignee_agent_id: None,
            status: "todo".to_string(),
            priority: priority_rank(fields.priority.as_deref())?,
            estimated_effort: None,
            blocker_reason: None,
            metadata: Value::Object(metadata),
            created_at: now.clone(),
            updated_at: Some(now),
            completed_at: None,
            archived_at: None,
        };
        if let Some(binding_id) = fields.workspace_agent_id.as_deref() {
            assign_binding(&self.store, &scope, &mut record, binding_id).await?;
        }
        self.commit(
            context,
            "create_execution_task",
            WorkspaceTaskDomainWrite::Create(record.clone()),
            record,
            "workspace_task_created",
        )
        .await
    }

    pub async fn update(
        &self,
        context: &StructuredTaskContext,
        task_id: &str,
        fields: &StructuredTaskMutationFields,
    ) -> Result<StructuredTaskMutationOutcome, StructuredTaskError> {
        let scope = validate_context(context)?;
        let mut record = self
            .store
            .get(&scope, task_id)
            .await?
            .ok_or(StructuredTaskError::NotFound)?;
        require_structured_role(&record)?;
        if let Some(title) = fields.title.as_deref() {
            if title.trim().is_empty() || title.chars().count() > 255 {
                return Err(StructuredTaskError::InvalidRequest);
            }
            record.title = title.to_string();
        }
        if let Some(description) = &fields.description {
            record.description = Some(description.clone());
        }
        if let Some(priority) = fields.priority.as_deref() {
            record.priority = priority_rank(Some(priority))?;
        }
        if let Some(metadata) = fields.metadata.clone() {
            let patch = metadata_object(Some(metadata))?;
            let current = record
                .metadata
                .as_object_mut()
                .ok_or(StructuredTaskError::InvalidRequest)?;
            for protected in ["task_role", "root_goal_task_id"] {
                if patch
                    .get(protected)
                    .is_some_and(|value| current.get(protected) != Some(value))
                {
                    return Err(StructuredTaskError::InvalidRequest);
                }
            }
            current.extend(patch);
        }
        if let Some(status) = fields.status.as_deref()
            && status != record.status
        {
            apply_transition(&mut record, status)?;
        }
        if let Some(binding_id) = fields.workspace_agent_id.as_deref() {
            assign_binding(&self.store, &scope, &mut record, binding_id).await?;
        }
        let metadata = record
            .metadata
            .as_object_mut()
            .ok_or(StructuredTaskError::InvalidRequest)?;
        record_actor(
            metadata,
            "update",
            context,
            fields.workspace_agent_id.as_deref(),
        );
        record.updated_at = Some(now_string());
        self.commit(
            context,
            "update_structured_task",
            WorkspaceTaskDomainWrite::Update(record.clone()),
            record,
            "workspace_task_updated",
        )
        .await
    }

    pub async fn assign_and_start(
        &self,
        context: &StructuredTaskContext,
        task_id: &str,
        workspace_agent_id: &str,
    ) -> Result<StructuredTaskMutationOutcome, StructuredTaskError> {
        let scope = validate_context(context)?;
        let mut record = self
            .store
            .get(&scope, task_id)
            .await?
            .ok_or(StructuredTaskError::NotFound)?;
        if record.metadata.get("task_role").and_then(Value::as_str) != Some("execution_task") {
            return Err(StructuredTaskError::InvalidRequest);
        }
        if !matches!(record.status.as_str(), "todo" | "in_progress") {
            return Err(StructuredTaskError::InvalidRequest);
        }
        assign_binding(&self.store, &scope, &mut record, workspace_agent_id).await?;
        if record.status == "todo" {
            apply_transition(&mut record, "in_progress")?;
        }
        let metadata = record
            .metadata
            .as_object_mut()
            .ok_or(StructuredTaskError::InvalidRequest)?;
        record_actor(
            metadata,
            "assign_and_start",
            context,
            Some(workspace_agent_id),
        );
        record.updated_at = Some(now_string());
        let task = project_task(&record)?;
        let response = serde_json::to_value(&task)?;
        let idempotency_key = context
            .idempotency_key
            .clone()
            .unwrap_or_else(|| format!("structured-assign-and-start:{}", Uuid::new_v4()));
        let dispatch = task_dispatch_write(
            &scope,
            &record,
            workspace_agent_id,
            idempotency_key.as_str(),
        )?;
        let outcome = self
            .mutate_with_auxiliary(
                context,
                "assign_and_start_execution_task",
                task_id,
                WorkspaceTaskDomainWrite::Update(record),
                response,
                "workspace_task_assigned",
                vec![WorkspaceTaskAuxiliaryWrite::QueueDispatch(dispatch)],
            )
            .await?;
        Ok(StructuredTaskMutationOutcome {
            task: serde_json::from_value(outcome.response)?,
            committed_revision: outcome.committed_revision,
            outbox_id: outcome.outbox_id,
            replayed: outcome.replayed,
        })
    }

    pub async fn delete(
        &self,
        context: &StructuredTaskContext,
        task_id: &str,
    ) -> Result<StructuredTaskDeleteOutcome, StructuredTaskError> {
        let scope = validate_context(context)?;
        let record = self
            .store
            .get(&scope, task_id)
            .await?
            .ok_or(StructuredTaskError::NotFound)?;
        require_structured_role(&record)?;
        if record.metadata.get("task_role").and_then(Value::as_str) == Some("goal_root") {
            return Err(StructuredTaskError::InvalidRequest);
        }
        let response = json!({"task_id": task_id, "workspace_id": &context.workspace_id});
        let outcome = self
            .mutate(
                context,
                "delete_structured_task",
                task_id,
                WorkspaceTaskDomainWrite::Delete {
                    task_id: task_id.to_string(),
                },
                response,
                "workspace_task_deleted",
            )
            .await?;
        Ok(StructuredTaskDeleteOutcome {
            task_id: task_id.to_string(),
            workspace_id: context.workspace_id.clone(),
            committed_revision: outcome.committed_revision,
            outbox_id: outcome.outbox_id,
            replayed: outcome.replayed,
        })
    }

    async fn commit(
        &self,
        context: &StructuredTaskContext,
        action: &str,
        write: WorkspaceTaskDomainWrite,
        record: WorkspaceTaskRecord,
        event_type: &str,
    ) -> Result<StructuredTaskMutationOutcome, StructuredTaskError> {
        let task = project_task(&record)?;
        let response = serde_json::to_value(&task)?;
        let outcome = self
            .mutate(
                context,
                action,
                record.task_id.as_str(),
                write,
                response,
                event_type,
            )
            .await?;
        Ok(StructuredTaskMutationOutcome {
            task: serde_json::from_value(outcome.response)?,
            committed_revision: outcome.committed_revision,
            outbox_id: outcome.outbox_id,
            replayed: outcome.replayed,
        })
    }

    async fn mutate(
        &self,
        context: &StructuredTaskContext,
        action: &str,
        task_id: &str,
        write: WorkspaceTaskDomainWrite,
        response: Value,
        event_type: &str,
    ) -> Result<WorkspaceTaskMutationOutcome, StructuredTaskError> {
        self.mutate_with_auxiliary(
            context,
            action,
            task_id,
            write,
            response,
            event_type,
            Vec::new(),
        )
        .await
    }

    #[allow(clippy::too_many_arguments)]
    async fn mutate_with_auxiliary(
        &self,
        context: &StructuredTaskContext,
        action: &str,
        task_id: &str,
        write: WorkspaceTaskDomainWrite,
        response: Value,
        event_type: &str,
        auxiliary_writes: Vec<WorkspaceTaskAuxiliaryWrite>,
    ) -> Result<WorkspaceTaskMutationOutcome, StructuredTaskError> {
        let scope = validate_context(context)?;
        let expected_revision = match context.expected_revision {
            Some(revision) => revision,
            None => self.store.revision(&scope).await?,
        };
        let idempotency_key = context
            .idempotency_key
            .clone()
            .unwrap_or_else(|| format!("structured-{action}:{}", Uuid::new_v4()));
        if idempotency_key.trim().is_empty() || idempotency_key.chars().count() > 256 {
            return Err(StructuredTaskError::InvalidRequest);
        }
        let request = json!({
            "action": action,
            "scope": {
                "tenant_id": &context.tenant_id,
                "project_id": &context.project_id,
                "workspace_id": &context.workspace_id,
            },
            "actor": {
                "user_id": &context.actor.user_id,
                "leader_agent_id": &context.actor.leader_agent_id,
            },
            "task_id": task_id,
            "response": &response,
        });
        let bytes = serde_json::to_vec(&canonical_json(&request))?;
        let payload_hash = hex::encode(Sha256::digest(bytes));
        self.store
            .mutate(&WorkspaceTaskMutation {
                scope,
                actor_id: context.actor.user_id.clone(),
                action: action.to_string(),
                idempotency_key,
                payload_hash,
                expected_revision,
                task_id: task_id.to_string(),
                domain_write: write,
                auxiliary_writes,
                response: response.clone(),
                event_type: event_type.to_string(),
                event_payload: json!({"workspace_id": &context.workspace_id, "task": response}),
                additional_events: Vec::new(),
                receipt_authority: None,
            })
            .await
            .map_err(Into::into)
    }
}

fn task_dispatch_write(
    scope: &WorkspaceTaskScope,
    record: &WorkspaceTaskRecord,
    binding_id: &str,
    idempotency_key: &str,
) -> Result<WorkspaceTaskDispatchWrite, StructuredTaskError> {
    let agent_id = record
        .assignee_agent_id
        .as_deref()
        .filter(|value| !value.trim().is_empty())
        .ok_or(StructuredTaskError::InvalidRequest)?;
    let seed = format!(
        "workspace-task-dispatch:{}:{}:{idempotency_key}",
        scope.workspace_id, record.task_id
    );
    Ok(WorkspaceTaskDispatchWrite {
        dispatch_id: format!(
            "task-dispatch-{}",
            Uuid::new_v5(&STRUCTURED_TASK_NAMESPACE, format!("row:{seed}").as_bytes())
        ),
        scope: scope.clone(),
        task_id: record.task_id.clone(),
        attempt_id: record
            .metadata
            .get("current_attempt_id")
            .and_then(Value::as_str)
            .map(str::to_string),
        plan_id: record
            .metadata
            .get("plan_id")
            .and_then(Value::as_str)
            .map(str::to_string),
        plan_node_id: record
            .metadata
            .get("plan_node_id")
            .and_then(Value::as_str)
            .map(str::to_string),
        user_id: record.created_by.clone(),
        agent_id: agent_id.to_string(),
        workspace_agent_binding_id: binding_id.to_string(),
        conversation_id: Uuid::new_v5(
            &STRUCTURED_TASK_NAMESPACE,
            format!(
                "workspace-task:{}:{}:agent:{agent_id}",
                scope.workspace_id, record.task_id
            )
            .as_bytes(),
        )
        .to_string(),
        delivery_request_id: Uuid::new_v5(&STRUCTURED_TASK_NAMESPACE, seed.as_bytes()).to_string(),
        created_at_ms: Utc::now().timestamp_millis(),
    })
}

fn validate_context(
    context: &StructuredTaskContext,
) -> Result<WorkspaceTaskScope, StructuredTaskError> {
    if [
        context.tenant_id.as_str(),
        context.project_id.as_str(),
        context.workspace_id.as_str(),
        context.actor.user_id.as_str(),
        context.actor.leader_agent_id.as_str(),
    ]
    .iter()
    .any(|value| value.trim().is_empty())
    {
        return Err(StructuredTaskError::InvalidRequest);
    }
    Ok(WorkspaceTaskScope {
        tenant_id: context.tenant_id.clone(),
        project_id: context.project_id.clone(),
        workspace_id: context.workspace_id.clone(),
    })
}

fn require_structured_role(record: &WorkspaceTaskRecord) -> Result<(), StructuredTaskError> {
    if record
        .metadata
        .get("task_role")
        .and_then(Value::as_str)
        .is_some_and(|role| matches!(role, "goal_root" | "execution_task"))
    {
        Ok(())
    } else {
        Err(StructuredTaskError::InvalidRequest)
    }
}

async fn assign_binding(
    store: &WorkspaceTaskStore<'_>,
    scope: &WorkspaceTaskScope,
    record: &mut WorkspaceTaskRecord,
    binding_id: &str,
) -> Result<(), StructuredTaskError> {
    let Some((tenant_id, project_id, workspace_id, agent_id, is_active)) =
        store.agent_binding(binding_id).await?
    else {
        return Err(StructuredTaskError::InvalidRequest);
    };
    if (tenant_id, project_id, workspace_id)
        != (
            scope.tenant_id.clone(),
            scope.project_id.clone(),
            scope.workspace_id.clone(),
        )
        || !is_active
    {
        return Err(StructuredTaskError::InvalidRequest);
    }
    record.assignee_user_id = None;
    record.assignee_agent_id = Some(agent_id);
    let metadata = record
        .metadata
        .as_object_mut()
        .ok_or(StructuredTaskError::InvalidRequest)?;
    metadata.insert(
        "workspace_agent_binding_id".to_string(),
        Value::String(binding_id.to_string()),
    );
    Ok(())
}

fn apply_transition(
    record: &mut WorkspaceTaskRecord,
    target: &str,
) -> Result<(), StructuredTaskError> {
    if !matches!(target, "todo" | "in_progress" | "blocked" | "done") {
        return Err(StructuredTaskError::InvalidRequest);
    }
    let allowed = matches!(
        (record.status.as_str(), target),
        ("todo", "in_progress" | "blocked")
            | ("in_progress", "blocked" | "done")
            | ("blocked", "in_progress" | "done")
    );
    if !allowed {
        return Err(StructuredTaskError::InvalidRequest);
    }
    let now = now_string();
    record.status = target.to_string();
    record.updated_at = Some(now.clone());
    record.completed_at = (target == "done").then_some(now);
    Ok(())
}

fn metadata_object(
    value: Option<Value>,
) -> Result<serde_json::Map<String, Value>, StructuredTaskError> {
    match value {
        None => Ok(serde_json::Map::new()),
        Some(Value::Object(value)) => Ok(value),
        Some(_) => Err(StructuredTaskError::InvalidRequest),
    }
}

fn priority_rank(priority: Option<&str>) -> Result<i64, StructuredTaskError> {
    match priority.unwrap_or("") {
        "" => Ok(0),
        "P1" => Ok(1),
        "P2" => Ok(2),
        "P3" => Ok(3),
        "P4" => Ok(4),
        _ => Err(StructuredTaskError::InvalidRequest),
    }
}

fn project_task(
    record: &WorkspaceTaskRecord,
) -> Result<StructuredWorkspaceTask, StructuredTaskError> {
    let workspace_agent_id = record
        .metadata
        .get("workspace_agent_binding_id")
        .and_then(Value::as_str)
        .map(str::to_string);
    Ok(StructuredWorkspaceTask {
        id: record.task_id.clone(),
        workspace_id: record.workspace_id.clone(),
        title: record.title.clone(),
        description: record.description.clone(),
        created_by: record.created_by.clone(),
        assignee_user_id: record.assignee_user_id.clone(),
        assignee_agent_id: record.assignee_agent_id.clone(),
        workspace_agent_id,
        status: record.status.clone(),
        priority: match record.priority {
            1..=4 => format!("P{}", record.priority),
            _ => String::new(),
        },
        estimated_effort: record.estimated_effort.clone(),
        blocker_reason: record.blocker_reason.clone(),
        metadata: record.metadata.clone(),
        created_at: record.created_at.clone(),
        updated_at: record.updated_at.clone(),
        completed_at: record.completed_at.clone(),
        archived_at: record.archived_at.clone(),
    })
}

fn record_actor(
    metadata: &mut serde_json::Map<String, Value>,
    action: &str,
    context: &StructuredTaskContext,
    binding_id: Option<&str>,
) {
    metadata.insert(
        "last_mutation_actor".to_string(),
        json!({
            "action": action,
            "actor_type": "agent",
            "actor_user_id": &context.actor.user_id,
            "actor_agent_id": &context.actor.leader_agent_id,
            "workspace_agent_binding_id": binding_id,
            "reason": format!("workspace_task.structured.{action}"),
            "at": now_string(),
        }),
    );
}

fn deterministic_task_id(context: &StructuredTaskContext) -> String {
    let seed = format!(
        "{}\0{}\0{}\0{}\0{}",
        context.tenant_id,
        context.project_id,
        context.workspace_id,
        context.actor.user_id,
        context.idempotency_key.as_deref().unwrap_or_default(),
    );
    Uuid::new_v5(&STRUCTURED_TASK_NAMESPACE, seed.as_bytes()).to_string()
}

fn now_string() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Micros, true)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn execution_task_id_is_stable_across_revision_retries() -> Result<(), StructuredTaskError> {
        let mut context = StructuredTaskContext {
            tenant_id: "tenant-1".to_string(),
            project_id: "project-1".to_string(),
            workspace_id: "workspace-1".to_string(),
            actor: StructuredTaskActor {
                user_id: "user-1".to_string(),
                leader_agent_id: "judge-1".to_string(),
            },
            expected_revision: Some(3),
            idempotency_key: Some("autonomy-progression:progression-1:create".to_string()),
        };
        let first = StructuredTaskService::execution_task_id(&context)?;
        context.expected_revision = Some(4);
        assert_eq!(first, StructuredTaskService::execution_task_id(&context)?);
        Ok(())
    }
}
