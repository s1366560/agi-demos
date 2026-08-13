//! Atomic Task mutation preparation shared by public Task use cases.

use memstack_workspace_store::{
    WorkspaceTaskAuxiliaryWrite, WorkspaceTaskDispatchWrite, WorkspaceTaskDomainWrite,
    WorkspaceTaskMutation, WorkspaceTaskMutationOutcome, WorkspaceTaskOutboxEvent,
    WorkspaceTaskRecord, WorkspaceTaskScope,
};
use serde_json::{Value, json};
use uuid::Uuid;

use super::{
    PUBLIC_TASK_NAMESPACE, PublicWorkspaceTask, PublicWorkspaceTaskContext,
    PublicWorkspaceTaskError, PublicWorkspaceTaskOutcome, PublicWorkspaceTaskService, hash_payload,
    request_hash, task_scope, validate_idempotency_key,
};

impl<'a> PublicWorkspaceTaskService<'a> {
    #[allow(clippy::too_many_arguments)]
    pub(super) async fn commit_task(
        &self,
        context: &PublicWorkspaceTaskContext,
        action: &str,
        task_id: &str,
        domain_write: WorkspaceTaskDomainWrite,
        auxiliary_writes: Vec<WorkspaceTaskAuxiliaryWrite>,
        response: PublicWorkspaceTask,
        event_type: &str,
    ) -> Result<PublicWorkspaceTaskOutcome, PublicWorkspaceTaskError> {
        let response_value =
            serde_json::to_value(&response).map_err(PublicWorkspaceTaskError::Json)?;
        let outcome = self
            .commit_value(
                context,
                action,
                task_id,
                domain_write,
                auxiliary_writes,
                response_value.clone(),
                event_type,
                json!({"workspace_id": &context.workspace_id, "task": response_value}),
            )
            .await?;
        Ok(PublicWorkspaceTaskOutcome {
            task: serde_json::from_value(outcome.response)
                .map_err(PublicWorkspaceTaskError::Json)?,
            committed_revision: outcome.committed_revision,
            outbox_id: outcome.outbox_id,
            replayed: outcome.replayed,
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) async fn commit_value(
        &self,
        context: &PublicWorkspaceTaskContext,
        action: &str,
        task_id: &str,
        domain_write: WorkspaceTaskDomainWrite,
        auxiliary_writes: Vec<WorkspaceTaskAuxiliaryWrite>,
        response: Value,
        event_type: &str,
        event_payload: Value,
    ) -> Result<WorkspaceTaskMutationOutcome, PublicWorkspaceTaskError> {
        self.commit_value_with_events(
            context,
            action,
            task_id,
            domain_write,
            auxiliary_writes,
            response,
            event_type,
            event_payload,
            Vec::new(),
            None,
        )
        .await
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) async fn commit_value_with_events(
        &self,
        context: &PublicWorkspaceTaskContext,
        action: &str,
        task_id: &str,
        domain_write: WorkspaceTaskDomainWrite,
        mut auxiliary_writes: Vec<WorkspaceTaskAuxiliaryWrite>,
        response: Value,
        event_type: &str,
        event_payload: Value,
        additional_events: Vec<WorkspaceTaskOutboxEvent>,
        request_payload: Option<Value>,
    ) -> Result<WorkspaceTaskMutationOutcome, PublicWorkspaceTaskError> {
        let scope = task_scope(context);
        let expected_revision = match context.expected_revision {
            Some(revision) => revision,
            None => self.store.revision(&scope).await?,
        };
        let idempotency_key = context
            .idempotency_key
            .clone()
            .unwrap_or_else(|| format!("legacy-{action}:{}", Uuid::new_v4()));
        validate_idempotency_key(idempotency_key.as_str())?;
        if let Some(dispatch) = task_dispatch_write(
            &scope,
            action,
            idempotency_key.as_str(),
            &domain_write,
            &event_payload,
        ) {
            auxiliary_writes.push(WorkspaceTaskAuxiliaryWrite::QueueDispatch(dispatch));
        }
        let scope_payload = json!({
            "tenant_id": &context.tenant_id,
            "project_id": &context.project_id,
            "workspace_id": &context.workspace_id,
        });
        let hash_input = request_payload.map_or_else(
            || {
                json!({
                    "action": action,
                    "scope": scope_payload,
                    "actor_id": &context.user_id,
                    "task_id": task_id,
                    "response": hash_payload(&response),
                    "event_payload": hash_payload(&event_payload),
                })
            },
            |request| {
                json!({
                    "action": action,
                    "scope": scope_payload,
                    "actor_id": &context.user_id,
                    "task_id": task_id,
                    "request": request,
                })
            },
        );
        let domain_hash = request_hash(hash_input)?;
        let payload_hash = self
            .receipt_authority
            .as_ref()
            .map_or(domain_hash, |authority| {
                authority.request_hash().as_str().to_string()
            });
        self.store
            .mutate(&WorkspaceTaskMutation {
                scope,
                actor_id: context.user_id.clone(),
                action: action.to_string(),
                idempotency_key,
                payload_hash,
                expected_revision,
                task_id: task_id.to_string(),
                domain_write,
                auxiliary_writes,
                response,
                event_type: event_type.to_string(),
                event_payload,
                additional_events,
                receipt_authority: self.receipt_authority.clone(),
            })
            .await
            .map_err(Into::into)
    }
}

fn task_dispatch_write(
    scope: &WorkspaceTaskScope,
    action: &str,
    idempotency_key: &str,
    domain_write: &WorkspaceTaskDomainWrite,
    event_payload: &Value,
) -> Option<WorkspaceTaskDispatchWrite> {
    if !is_dispatch_action(action, event_payload) {
        return None;
    }
    let record = match domain_write {
        WorkspaceTaskDomainWrite::Create(record) | WorkspaceTaskDomainWrite::Update(record) => {
            record
        }
        WorkspaceTaskDomainWrite::Delete { .. } => return None,
    };
    let metadata = record.metadata.as_object()?;
    if metadata.get("task_role").and_then(Value::as_str) != Some("execution_task") {
        return None;
    }
    let agent_id = record.assignee_agent_id.as_deref()?.trim();
    let binding_id = metadata
        .get("workspace_agent_binding_id")
        .and_then(Value::as_str)?
        .trim();
    if agent_id.is_empty() || binding_id.is_empty() {
        return None;
    }
    let delivery_seed = format!(
        "workspace-task-dispatch:{}:{}:{idempotency_key}",
        scope.workspace_id, record.task_id
    );
    let delivery_request_id = deterministic_dispatch_uuid(delivery_seed.as_str());
    Some(WorkspaceTaskDispatchWrite {
        dispatch_id: format!(
            "task-dispatch-{}",
            deterministic_dispatch_uuid(format!("row:{delivery_seed}").as_str())
        ),
        scope: scope.clone(),
        task_id: record.task_id.clone(),
        attempt_id: metadata_string(record, "current_attempt_id"),
        plan_id: metadata_string(record, "plan_id"),
        plan_node_id: metadata_string(record, "plan_node_id"),
        user_id: record.created_by.clone(),
        agent_id: agent_id.to_string(),
        workspace_agent_binding_id: binding_id.to_string(),
        conversation_id: deterministic_dispatch_uuid(
            format!(
                "workspace-task:{}:{}:agent:{agent_id}",
                scope.workspace_id, record.task_id
            )
            .as_str(),
        ),
        delivery_request_id,
        created_at_ms: chrono::Utc::now().timestamp_millis(),
    })
}

fn is_dispatch_action(action: &str, event_payload: &Value) -> bool {
    if action == "assign_agent" {
        return true;
    }
    action == "recovery_action"
        && matches!(
            event_payload.get("action").and_then(Value::as_str),
            Some("retry_launch" | "new_attempt" | "reassign")
        )
}

fn metadata_string(record: &WorkspaceTaskRecord, field: &str) -> Option<String> {
    record
        .metadata
        .get(field)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn deterministic_dispatch_uuid(seed: &str) -> String {
    Uuid::new_v5(&PUBLIC_TASK_NAMESPACE, seed.as_bytes()).to_string()
}
