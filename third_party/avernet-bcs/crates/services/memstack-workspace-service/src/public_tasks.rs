//! Legacy-compatible Workspace Task use cases over the Avernet authority.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use memstack_workspace_service_api::WorkspaceMutationAuthority;
use memstack_workspace_store::{
    WorkspaceTaskAttemptRecord, WorkspaceTaskAuxiliaryWrite, WorkspaceTaskDomainWrite,
    WorkspaceTaskMutationOutcome, WorkspaceTaskRecord, WorkspaceTaskStore, WorkspaceTaskStoreError,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use thiserror::Error;
use uuid::Uuid;

#[path = "public_tasks_commit.rs"]
mod commit;
#[path = "public_tasks_projection.rs"]
mod projection;

use projection::*;

const MAX_TITLE_CHARS: usize = 255;
const MAX_IDEMPOTENCY_KEY_CHARS: usize = 256;
const RECOVERY_ACTION_LIMIT: usize = 20;
const PUBLIC_TASK_NAMESPACE: Uuid = Uuid::from_u128(0x92ae_36c7_03ef_49f4_b7e7_8091_0ad2_5dcb);

/// Authenticated Task request scope supplied by the Gateway.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceTaskContext {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub user_id: String,
    pub expected_revision: Option<u64>,
    pub idempotency_key: Option<String>,
}

/// Legacy Task create fields.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicCreateWorkspaceTaskInput {
    pub context: PublicWorkspaceTaskContext,
    pub title: String,
    pub description: Option<String>,
    pub assignee_user_id: Option<String>,
    pub metadata: Option<Value>,
    pub preferred_language: Option<String>,
    pub priority: Option<String>,
    pub estimated_effort: Option<String>,
    pub blocker_reason: Option<String>,
}

/// Legacy PATCH fields. `None` preserves the persisted field.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct PublicUpdateWorkspaceTaskFields {
    pub title: Option<String>,
    pub description: Option<String>,
    pub assignee_user_id: Option<String>,
    pub status: Option<String>,
    pub metadata: Option<Value>,
    pub priority: Option<String>,
    pub estimated_effort: Option<String>,
    pub blocker_reason: Option<String>,
}

/// One explicit recovery intervention selected by the authenticated caller.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceTaskRecoveryInput {
    pub action: String,
    pub reason: Option<String>,
    pub workspace_agent_id: Option<String>,
}

/// Exact legacy Task response projection.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PublicWorkspaceTask {
    pub id: String,
    pub workspace_id: String,
    pub title: String,
    pub description: Option<String>,
    pub created_by: String,
    pub assignee_user_id: Option<String>,
    pub assignee_agent_id: Option<String>,
    pub workspace_agent_id: Option<String>,
    pub current_attempt_id: Option<String>,
    pub current_attempt_number: Option<i64>,
    pub current_attempt_conversation_id: Option<String>,
    pub current_attempt_worker_binding_id: Option<String>,
    pub current_attempt_worker_agent_id: Option<String>,
    pub last_attempt_status: Option<String>,
    pub pending_leader_adjudication: bool,
    pub last_worker_report_type: Option<String>,
    pub last_worker_report_summary: Option<String>,
    pub last_worker_report_artifacts: Vec<String>,
    pub last_worker_report_verifications: Vec<String>,
    pub status: String,
    pub metadata: Value,
    pub created_at: String,
    pub updated_at: Option<String>,
    pub priority: Option<String>,
    pub estimated_effort: Option<String>,
    pub blocker_reason: Option<String>,
    pub completed_at: Option<String>,
    pub archived_at: Option<String>,
}

/// Committed or replayed Task response plus durable authority facts.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceTaskOutcome {
    pub task: PublicWorkspaceTask,
    pub committed_revision: u64,
    pub outbox_id: String,
    pub replayed: bool,
}

/// Explicit recovery action response.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PublicWorkspaceTaskRecoveryOutcome {
    pub workspace_id: String,
    pub task_id: String,
    pub action: String,
    pub status: String,
    pub message: String,
    pub conversation_id: Option<String>,
    pub attempt_id: Option<String>,
    pub outbox_id: Option<String>,
    pub session: Option<Value>,
}

/// Recovery response plus the durable Workspace authority facts omitted from
/// the legacy response projection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceTaskRecoveryAuthorityOutcome {
    pub response: PublicWorkspaceTaskRecoveryOutcome,
    pub committed_revision: u64,
    pub replayed: bool,
}

/// Stable public Task error category consumed by HTTP adapters.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PublicWorkspaceTaskErrorKind {
    InvalidRequest,
    NotFound,
    Forbidden,
    Conflict,
    Unavailable,
}

/// Public Task validation, authorization, or persistence failure.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceTaskError {
    #[error("Invalid workspace task request")]
    InvalidRequest,

    #[error("Workspace task not found")]
    NotFound,

    #[error("Access denied")]
    Forbidden,

    #[error("Cannot transition task status from {from} to {to}")]
    InvalidTransition { from: String, to: String },

    #[error("Workspace agent binding does not belong to workspace")]
    BindingWorkspaceMismatch,

    #[error("Workspace agent binding must be active for assignment")]
    InactiveBinding,

    #[error("Autonomy task mutation requires structured leader or worker authority")]
    StructuredAuthorityRequired,

    #[error("Workspace task serialization failed: {0}")]
    Json(#[source] serde_json::Error),

    #[error(transparent)]
    Store(#[from] WorkspaceTaskStoreError),
}

impl PublicWorkspaceTaskError {
    #[must_use]
    pub const fn kind(&self) -> PublicWorkspaceTaskErrorKind {
        match self {
            Self::InvalidRequest
            | Self::InvalidTransition { .. }
            | Self::BindingWorkspaceMismatch
            | Self::InactiveBinding => PublicWorkspaceTaskErrorKind::InvalidRequest,
            Self::NotFound | Self::Store(WorkspaceTaskStoreError::TaskNotFound) => {
                PublicWorkspaceTaskErrorKind::NotFound
            }
            Self::Forbidden
            | Self::StructuredAuthorityRequired
            | Self::Store(
                WorkspaceTaskStoreError::AccessRequired
                | WorkspaceTaskStoreError::EditorAccessRequired,
            ) => PublicWorkspaceTaskErrorKind::Forbidden,
            Self::Store(
                WorkspaceTaskStoreError::Conflict | WorkspaceTaskStoreError::IdempotencyConflict,
            ) => PublicWorkspaceTaskErrorKind::Conflict,
            Self::Store(WorkspaceTaskStoreError::NotFound) => {
                PublicWorkspaceTaskErrorKind::NotFound
            }
            Self::Json(_) | Self::Store(_) => PublicWorkspaceTaskErrorKind::Unavailable,
        }
    }
}

/// Public Task application service over the atomic Task store.
pub struct PublicWorkspaceTaskService<'a> {
    store: WorkspaceTaskStore<'a>,
    receipt_authority: Option<WorkspaceMutationAuthority>,
}

impl<'a> PublicWorkspaceTaskService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            store: WorkspaceTaskStore::new(db, flavor),
            receipt_authority: None,
        }
    }

    /// Persist a collaboration receipt envelope with the Task domain write.
    #[must_use]
    pub fn with_mutation_authority(mut self, authority: WorkspaceMutationAuthority) -> Self {
        self.receipt_authority = Some(authority);
        self
    }

    /// Create one Task and its durable legacy outbox event atomically.
    ///
    /// # Errors
    ///
    /// Returns stable validation, authorization, conflict, or persistence errors.
    pub async fn create(
        &self,
        input: &PublicCreateWorkspaceTaskInput,
    ) -> Result<PublicWorkspaceTaskOutcome, PublicWorkspaceTaskError> {
        self.create_with_auxiliary(input, Vec::new()).await
    }

    /// Create one Task with checked domain relations in the same authority transaction.
    pub(crate) async fn create_with_auxiliary(
        &self,
        input: &PublicCreateWorkspaceTaskInput,
        auxiliary_writes: Vec<WorkspaceTaskAuxiliaryWrite>,
    ) -> Result<PublicWorkspaceTaskOutcome, PublicWorkspaceTaskError> {
        let context = prepared_context(&input.context, "create_task");
        validate_title(input.title.as_str())?;
        let priority = parse_priority(input.priority.as_deref())?;
        let mut metadata = object_or_empty(input.metadata.clone())?;
        if let Some(language) = nonblank(input.preferred_language.as_deref()) {
            metadata.insert("preferred_language".to_string(), Value::String(language));
        }
        let now = now_string();
        record_actor(&mut metadata, "create", &context, None, None);
        let scope = task_scope(&context);
        let record = WorkspaceTaskRecord {
            task_id: deterministic_task_id(&context),
            tenant_id: scope.tenant_id.clone(),
            project_id: scope.project_id.clone(),
            workspace_id: scope.workspace_id.clone(),
            title: input.title.clone(),
            description: input.description.clone(),
            created_by: context.user_id.clone(),
            assignee_user_id: input.assignee_user_id.clone(),
            assignee_agent_id: None,
            status: "todo".to_string(),
            priority,
            estimated_effort: input.estimated_effort.clone(),
            blocker_reason: input.blocker_reason.clone(),
            metadata: Value::Object(metadata),
            created_at: now.clone(),
            updated_at: Some(now),
            completed_at: None,
            archived_at: None,
        };
        self.commit_task(
            &context,
            "create_task",
            record.task_id.as_str(),
            WorkspaceTaskDomainWrite::Create(record.clone()),
            auxiliary_writes,
            public_task(&record)?,
            "workspace_task_created",
        )
        .await
    }

    /// List Tasks newest-first through the exact legacy pagination contract.
    ///
    /// # Errors
    ///
    /// Returns stable validation, authorization, or persistence errors.
    pub async fn list(
        &self,
        context: &PublicWorkspaceTaskContext,
        status: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<PublicWorkspaceTask>, PublicWorkspaceTaskError> {
        if !(1..=500).contains(&limit) || offset < 0 {
            return Err(PublicWorkspaceTaskError::InvalidRequest);
        }
        if let Some(status) = status {
            validate_status(status)?;
        }
        let scope = task_scope(context);
        self.store
            .require_access(&scope, context.user_id.as_str(), false)
            .await?;
        self.store
            .list(&scope, status, limit, offset)
            .await?
            .iter()
            .map(public_task)
            .collect()
    }

    /// Read one scoped Task.
    ///
    /// # Errors
    ///
    /// Returns stable authorization, not-found, or persistence errors.
    pub async fn get(
        &self,
        context: &PublicWorkspaceTaskContext,
        task_id: &str,
    ) -> Result<PublicWorkspaceTask, PublicWorkspaceTaskError> {
        public_task(&self.require_task(context, task_id, false).await?)
    }

    /// Apply a legacy Task patch under the Task authority transaction.
    ///
    /// # Errors
    ///
    /// Returns stable validation, authorization, conflict, or persistence errors.
    pub async fn update(
        &self,
        context: &PublicWorkspaceTaskContext,
        task_id: &str,
        fields: &PublicUpdateWorkspaceTaskFields,
    ) -> Result<PublicWorkspaceTaskOutcome, PublicWorkspaceTaskError> {
        let mut record = self.require_task(context, task_id, true).await?;
        require_public_authority(&record)?;
        if let Some(title) = &fields.title {
            validate_title(title)?;
            record.title.clone_from(title);
        }
        if let Some(description) = &fields.description {
            record.description = Some(description.clone());
        }
        if let Some(assignee_user_id) = &fields.assignee_user_id {
            record.assignee_user_id = Some(assignee_user_id.clone());
            record.assignee_agent_id = None;
            clear_binding(&mut record.metadata);
        }
        if let Some(metadata) = &fields.metadata {
            merge_metadata(&mut record.metadata, metadata)?;
        }
        if let Some(priority) = &fields.priority {
            record.priority = parse_priority(Some(priority.as_str()))?;
        }
        if let Some(effort) = &fields.estimated_effort {
            record.estimated_effort = Some(effort.clone());
        }
        if let Some(reason) = &fields.blocker_reason {
            record.blocker_reason = Some(reason.clone());
        }
        if let Some(status) = &fields.status
            && status != &record.status
        {
            apply_transition(&mut record, status)?;
        }
        touch_actor(&mut record, "update", context, None, None);
        self.commit_task(
            context,
            "update_task",
            task_id,
            WorkspaceTaskDomainWrite::Update(record.clone()),
            Vec::new(),
            public_task(&record)?,
            "workspace_task_updated",
        )
        .await
    }

    /// Delete one Task under revision CAS and durable replay protection.
    ///
    /// # Errors
    ///
    /// Returns stable authorization, not-found, conflict, or persistence errors.
    pub async fn delete(
        &self,
        context: &PublicWorkspaceTaskContext,
        task_id: &str,
    ) -> Result<WorkspaceTaskMutationOutcome, PublicWorkspaceTaskError> {
        let record = self.require_task(context, task_id, true).await?;
        require_public_authority(&record)?;
        let response = json!({"task_id": task_id, "workspace_id": &context.workspace_id});
        self.commit_value(
            context,
            "delete_task",
            task_id,
            WorkspaceTaskDomainWrite::Delete {
                task_id: task_id.to_string(),
            },
            Vec::new(),
            response.clone(),
            "workspace_task_deleted",
            response,
        )
        .await
    }

    /// Assign one active Workspace Agent binding to a Task.
    ///
    /// # Errors
    ///
    /// Returns stable binding, authorization, conflict, or persistence errors.
    pub async fn assign_agent(
        &self,
        context: &PublicWorkspaceTaskContext,
        task_id: &str,
        workspace_agent_id: &str,
        preferred_language: Option<&str>,
    ) -> Result<PublicWorkspaceTaskOutcome, PublicWorkspaceTaskError> {
        let mut record = self.require_task(context, task_id, true).await?;
        require_agent_assignment_authority(&record)?;
        let Some((tenant_id, project_id, workspace_id, agent_id, is_active)) =
            self.store.agent_binding(workspace_agent_id).await?
        else {
            return Err(PublicWorkspaceTaskError::BindingWorkspaceMismatch);
        };
        if (tenant_id, project_id, workspace_id)
            != (
                context.tenant_id.clone(),
                context.project_id.clone(),
                context.workspace_id.clone(),
            )
        {
            return Err(PublicWorkspaceTaskError::BindingWorkspaceMismatch);
        }
        if !is_active {
            return Err(PublicWorkspaceTaskError::InactiveBinding);
        }
        record.assignee_user_id = None;
        record.assignee_agent_id = Some(agent_id.clone());
        let metadata = record
            .metadata
            .as_object_mut()
            .ok_or(PublicWorkspaceTaskError::InvalidRequest)?;
        metadata.insert(
            "workspace_agent_binding_id".to_string(),
            Value::String(workspace_agent_id.to_string()),
        );
        if let Some(language) = nonblank(preferred_language) {
            metadata.insert("preferred_language".to_string(), Value::String(language));
        }
        touch_actor(
            &mut record,
            "assign_agent",
            context,
            Some(agent_id.as_str()),
            Some(workspace_agent_id),
        );
        self.commit_task(
            context,
            "assign_agent",
            task_id,
            WorkspaceTaskDomainWrite::Update(record.clone()),
            Vec::new(),
            public_task(&record)?,
            "workspace_task_assigned",
        )
        .await
    }

    /// Remove the Agent assignment while retaining any human assignee.
    ///
    /// # Errors
    ///
    /// Returns stable authorization, conflict, or persistence errors.
    pub async fn unassign_agent(
        &self,
        context: &PublicWorkspaceTaskContext,
        task_id: &str,
    ) -> Result<PublicWorkspaceTaskOutcome, PublicWorkspaceTaskError> {
        let mut record = self.require_task(context, task_id, true).await?;
        require_public_authority(&record)?;
        record.assignee_agent_id = None;
        clear_binding(&mut record.metadata);
        touch_actor(&mut record, "unassign_agent", context, None, None);
        self.commit_task(
            context,
            "unassign_agent",
            task_id,
            WorkspaceTaskDomainWrite::Update(record.clone()),
            Vec::new(),
            public_task(&record)?,
            "workspace_task_updated",
        )
        .await
    }

    /// Claim a non-completed Task for the authenticated human caller.
    ///
    /// # Errors
    ///
    /// Returns stable validation, authorization, conflict, or persistence errors.
    pub async fn claim(
        &self,
        context: &PublicWorkspaceTaskContext,
        task_id: &str,
    ) -> Result<PublicWorkspaceTaskOutcome, PublicWorkspaceTaskError> {
        let mut record = self.require_task(context, task_id, true).await?;
        require_public_authority(&record)?;
        if record.status == "done"
            || record
                .assignee_user_id
                .as_deref()
                .is_some_and(|assignee| assignee != context.user_id)
        {
            return Err(PublicWorkspaceTaskError::InvalidRequest);
        }
        record.assignee_user_id = Some(context.user_id.clone());
        record.assignee_agent_id = None;
        clear_binding(&mut record.metadata);
        touch_actor(&mut record, "claim", context, None, None);
        self.commit_task(
            context,
            "claim_task",
            task_id,
            WorkspaceTaskDomainWrite::Update(record.clone()),
            Vec::new(),
            public_task(&record)?,
            "workspace_task_updated",
        )
        .await
    }

    /// Apply one deterministic lifecycle transition.
    ///
    /// # Errors
    ///
    /// Returns stable transition, authorization, conflict, or persistence errors.
    pub async fn transition(
        &self,
        context: &PublicWorkspaceTaskContext,
        task_id: &str,
        target: &str,
    ) -> Result<PublicWorkspaceTaskOutcome, PublicWorkspaceTaskError> {
        let mut record = self.require_task(context, task_id, true).await?;
        require_public_authority(&record)?;
        apply_transition(&mut record, target)?;
        let action = match target {
            "in_progress" => "start_task",
            "blocked" => "block_task",
            "done" => "complete_task",
            _ => return Err(PublicWorkspaceTaskError::InvalidRequest),
        };
        touch_actor(&mut record, action, context, None, None);
        self.commit_task(
            context,
            action,
            task_id,
            WorkspaceTaskDomainWrite::Update(record.clone()),
            Vec::new(),
            public_task(&record)?,
            "workspace_task_updated",
        )
        .await
    }

    /// Build the legacy experience envelope from Task and attempt facts only.
    ///
    /// Subjective evidence quality remains explicitly unjudged until a structured
    /// Agent/JudgePort verdict has been persisted.
    ///
    /// # Errors
    ///
    /// Returns stable authorization, not-found, or persistence errors.
    pub async fn experience(
        &self,
        context: &PublicWorkspaceTaskContext,
        task_id: &str,
    ) -> Result<Value, PublicWorkspaceTaskError> {
        let record = self.require_task(context, task_id, false).await?;
        let attempts = self
            .store
            .attempts(&task_scope(context), task_id, 5)
            .await?;
        Ok(experience_value(&record, attempts.as_slice()))
    }

    /// Build the execution-session envelope from durable structural facts.
    ///
    /// # Errors
    ///
    /// Returns stable authorization, not-found, or persistence errors.
    pub async fn execution_session(
        &self,
        context: &PublicWorkspaceTaskContext,
        task_id: &str,
    ) -> Result<Value, PublicWorkspaceTaskError> {
        let record = self.require_task(context, task_id, false).await?;
        let scope = task_scope(context);
        let attempts = self.store.attempts(&scope, task_id, 5).await?;
        let execution = self.store.execution(&scope, task_id).await?;
        Ok(execution_session_value(
            &record,
            attempts.first(),
            execution,
        ))
    }

    /// Persist one caller-selected recovery intervention and its durable event.
    ///
    /// # Errors
    ///
    /// Returns stable validation, authorization, conflict, or persistence errors.
    pub async fn recovery_action(
        &self,
        context: &PublicWorkspaceTaskContext,
        task_id: &str,
        input: &PublicWorkspaceTaskRecoveryInput,
    ) -> Result<PublicWorkspaceTaskRecoveryOutcome, PublicWorkspaceTaskError> {
        self.recovery_action_with_authority(context, task_id, input)
            .await
            .map(|outcome| outcome.response)
    }

    /// Persist a recovery intervention and retain its revision/replay facts.
    ///
    /// # Errors
    ///
    /// Returns stable validation, authorization, conflict, or persistence errors.
    pub async fn recovery_action_with_authority(
        &self,
        context: &PublicWorkspaceTaskContext,
        task_id: &str,
        input: &PublicWorkspaceTaskRecoveryInput,
    ) -> Result<PublicWorkspaceTaskRecoveryAuthorityOutcome, PublicWorkspaceTaskError> {
        validate_recovery_action(input.action.as_str())?;
        let mut record = self.require_task(context, task_id, true).await?;
        let scope = task_scope(context);
        let attempts = self.store.attempts(&scope, task_id, 5).await?;
        let execution = self.store.execution(&scope, task_id).await?;
        let mut auxiliary = Vec::new();
        let mut attempt_id = attempts.first().map(|attempt| attempt.attempt_id.clone());
        let reason = nonblank(input.reason.as_deref())
            .unwrap_or_else(|| format!("Explicit recovery action: {}", input.action));

        match input.action.as_str() {
            "mark_human_blocked" => {
                record.status = "blocked".to_string();
                record.blocker_reason = Some(reason.clone());
            }
            "reassign" => {
                let binding_id = input
                    .workspace_agent_id
                    .as_deref()
                    .ok_or(PublicWorkspaceTaskError::InvalidRequest)?;
                let Some((tenant_id, project_id, workspace_id, agent_id, is_active)) =
                    self.store.agent_binding(binding_id).await?
                else {
                    return Err(PublicWorkspaceTaskError::BindingWorkspaceMismatch);
                };
                if (tenant_id, project_id, workspace_id)
                    != (
                        context.tenant_id.clone(),
                        context.project_id.clone(),
                        context.workspace_id.clone(),
                    )
                {
                    return Err(PublicWorkspaceTaskError::BindingWorkspaceMismatch);
                }
                if !is_active {
                    return Err(PublicWorkspaceTaskError::InactiveBinding);
                }
                record.assignee_user_id = None;
                record.assignee_agent_id = Some(agent_id);
                record.metadata["workspace_agent_binding_id"] =
                    Value::String(binding_id.to_string());
            }
            "new_attempt" => {
                let attempt_number = attempts
                    .first()
                    .map_or(1, |attempt| attempt.attempt_number.saturating_add(1));
                let created_at = now_string();
                let new_attempt_id = deterministic_attempt_id(context, task_id);
                let root_goal_task_id = record
                    .metadata
                    .get("root_goal_task_id")
                    .and_then(Value::as_str)
                    .unwrap_or(task_id)
                    .to_string();
                auxiliary.push(WorkspaceTaskAuxiliaryWrite::CreateAttempt(
                    WorkspaceTaskAttemptRecord {
                        attempt_id: new_attempt_id.clone(),
                        task_id: task_id.to_string(),
                        root_goal_task_id,
                        attempt_number,
                        status: "pending".to_string(),
                        conversation_id: None,
                        worker_agent_id: record.assignee_agent_id.clone(),
                        leader_agent_id: None,
                        candidate_summary: None,
                        candidate_artifacts: json!([]),
                        candidate_verifications: json!([]),
                        leader_feedback: None,
                        adjudication_reason: None,
                        created_at: created_at.clone(),
                        updated_at: Some(created_at),
                        completed_at: None,
                    },
                ));
                record.metadata["current_attempt_id"] = Value::String(new_attempt_id.clone());
                record.metadata["current_attempt_number"] = Value::from(attempt_number);
                attempt_id = Some(new_attempt_id);
            }
            "retry_launch" | "terminate_stale_conversation" => {}
            _ => return Err(PublicWorkspaceTaskError::InvalidRequest),
        }
        append_recovery_ledger(&mut record.metadata, &input.action, &reason);
        touch_actor(
            &mut record,
            "recovery_action",
            context,
            None,
            input.workspace_agent_id.as_deref(),
        );
        let response = PublicWorkspaceTaskRecoveryOutcome {
            workspace_id: context.workspace_id.clone(),
            task_id: task_id.to_string(),
            action: input.action.clone(),
            status: if input.action == "mark_human_blocked" {
                "completed".to_string()
            } else {
                "queued".to_string()
            },
            message: "Recovery action persisted for durable execution.".to_string(),
            conversation_id: execution.map(|value| value.conversation_id),
            attempt_id,
            outbox_id: None,
            session: None,
        };
        let response_value =
            serde_json::to_value(&response).map_err(PublicWorkspaceTaskError::Json)?;
        let outcome = self
            .commit_value(
                context,
                "recovery_action",
                task_id,
                WorkspaceTaskDomainWrite::Update(record),
                auxiliary,
                response_value.clone(),
                "task_recovery_action_started",
                response_value,
            )
            .await?;
        let mut response: PublicWorkspaceTaskRecoveryOutcome =
            serde_json::from_value(outcome.response).map_err(PublicWorkspaceTaskError::Json)?;
        response.outbox_id = Some(outcome.outbox_id);
        Ok(PublicWorkspaceTaskRecoveryAuthorityOutcome {
            response,
            committed_revision: outcome.committed_revision,
            replayed: outcome.replayed,
        })
    }

    async fn require_task(
        &self,
        context: &PublicWorkspaceTaskContext,
        task_id: &str,
        require_editor: bool,
    ) -> Result<WorkspaceTaskRecord, PublicWorkspaceTaskError> {
        let scope = task_scope(context);
        self.store
            .require_access(&scope, context.user_id.as_str(), require_editor)
            .await?;
        self.store
            .get(&scope, task_id)
            .await?
            .ok_or(PublicWorkspaceTaskError::NotFound)
    }
}
