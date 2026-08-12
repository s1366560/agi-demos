//! Legacy-compatible Workspace Objective use cases over the Avernet authority.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use chrono::{SecondsFormat, Utc};
use memstack_workspace_service_api::WorkspaceMutationAuthority;
use memstack_workspace_store::{
    WorkspaceObjectiveDomainWrite, WorkspaceObjectiveMutation, WorkspaceObjectiveRecord,
    WorkspaceObjectiveScope, WorkspaceObjectiveStore, WorkspaceObjectiveStoreError,
    WorkspaceObjectiveTaskProjectionWrite, WorkspaceTaskAuxiliaryWrite,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use thiserror::Error;
use uuid::Uuid;

use crate::{
    PublicCreateWorkspaceTaskInput, PublicWorkspaceTask, PublicWorkspaceTaskContext,
    PublicWorkspaceTaskError, PublicWorkspaceTaskService, canonical_json,
};

const OBJECTIVE_NAMESPACE: Uuid = Uuid::from_u128(0x81d4_2b79_b42b_43d4_93be_b9b8_4c21_1008);
const OBJECTIVE_TYPES: &[&str] = &["objective", "key_result"];
const MAX_TITLE_CHARS: usize = 255;
const MAX_IDEMPOTENCY_KEY_CHARS: usize = 256;

/// Authenticated public Objective request scope.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceObjectiveContext {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub user_id: String,
    pub is_superuser: bool,
    pub expected_revision: Option<u64>,
    pub idempotency_key: Option<String>,
}

/// Exact legacy Objective response projection.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PublicWorkspaceObjective {
    pub id: String,
    pub workspace_id: String,
    pub title: String,
    pub description: Option<String>,
    pub obj_type: String,
    pub parent_id: Option<String>,
    pub progress: f64,
    pub created_by: String,
    pub created_at: String,
    pub updated_at: Option<String>,
}

/// Create-Objective input after HTTP decoding.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicCreateWorkspaceObjectiveInput {
    pub context: PublicWorkspaceObjectiveContext,
    pub title: String,
    pub description: Option<String>,
    pub objective_type: String,
    pub parent_objective_id: Option<String>,
    pub progress: f64,
}

/// PATCH fields where `None` preserves the persisted value.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct PublicUpdateWorkspaceObjectiveFields {
    pub title: Option<String>,
    pub description: Option<String>,
    pub objective_type: Option<String>,
    pub parent_objective_id: Option<String>,
    pub progress: Option<f64>,
}

/// Successful Objective mutation with authority metadata.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicWorkspaceObjectiveOutcome {
    pub objective: PublicWorkspaceObjective,
    pub committed_revision: u64,
    pub outbox_id: String,
    pub replayed: bool,
}

/// Objective-to-Task materialization result.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicObjectiveTaskOutcome {
    pub task: PublicWorkspaceTask,
    pub existing: bool,
    pub committed_revision: u64,
    pub outbox_id: String,
    pub replayed: bool,
}

/// Successful Objective deletion authority facts.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicWorkspaceObjectiveDeleteOutcome {
    pub committed_revision: u64,
    pub outbox_id: String,
    pub replayed: bool,
}

/// Stable Objective application failure categories.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PublicWorkspaceObjectiveErrorKind {
    InvalidRequest,
    NotFound,
    Forbidden,
    Conflict,
    Unavailable,
}

/// Stable Objective application failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceObjectiveError {
    #[error("invalid Workspace Objective request")]
    InvalidRequest,
    #[error("Objective not found")]
    ObjectiveNotFound,
    #[error("Workspace Objective access denied")]
    Forbidden,
    #[error("Workspace Objective authority conflict")]
    Conflict,
    #[error("Workspace Objective JSON serialization failed: {0}")]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Task(#[from] PublicWorkspaceTaskError),
    #[error(transparent)]
    Store(#[from] WorkspaceObjectiveStoreError),
}

impl PublicWorkspaceObjectiveError {
    #[must_use]
    pub const fn kind(&self) -> PublicWorkspaceObjectiveErrorKind {
        match self {
            Self::InvalidRequest => PublicWorkspaceObjectiveErrorKind::InvalidRequest,
            Self::ObjectiveNotFound => PublicWorkspaceObjectiveErrorKind::NotFound,
            Self::Forbidden => PublicWorkspaceObjectiveErrorKind::Forbidden,
            Self::Conflict => PublicWorkspaceObjectiveErrorKind::Conflict,
            Self::Json(_) => PublicWorkspaceObjectiveErrorKind::Unavailable,
            Self::Task(error) => match error.kind() {
                crate::PublicWorkspaceTaskErrorKind::InvalidRequest => {
                    PublicWorkspaceObjectiveErrorKind::InvalidRequest
                }
                crate::PublicWorkspaceTaskErrorKind::NotFound => {
                    PublicWorkspaceObjectiveErrorKind::NotFound
                }
                crate::PublicWorkspaceTaskErrorKind::Forbidden => {
                    PublicWorkspaceObjectiveErrorKind::Forbidden
                }
                crate::PublicWorkspaceTaskErrorKind::Conflict => {
                    PublicWorkspaceObjectiveErrorKind::Conflict
                }
                crate::PublicWorkspaceTaskErrorKind::Unavailable => {
                    PublicWorkspaceObjectiveErrorKind::Unavailable
                }
            },
            Self::Store(error) => match error {
                WorkspaceObjectiveStoreError::NotFound
                | WorkspaceObjectiveStoreError::ObjectiveNotFound => {
                    PublicWorkspaceObjectiveErrorKind::NotFound
                }
                WorkspaceObjectiveStoreError::AccessRequired
                | WorkspaceObjectiveStoreError::EditorAccessRequired => {
                    PublicWorkspaceObjectiveErrorKind::Forbidden
                }
                WorkspaceObjectiveStoreError::Conflict
                | WorkspaceObjectiveStoreError::IdempotencyConflict
                | WorkspaceObjectiveStoreError::IncompleteReceipt => {
                    PublicWorkspaceObjectiveErrorKind::Conflict
                }
                WorkspaceObjectiveStoreError::InvalidRecord(_)
                | WorkspaceObjectiveStoreError::Database(_) => {
                    PublicWorkspaceObjectiveErrorKind::Unavailable
                }
                _ => PublicWorkspaceObjectiveErrorKind::Unavailable,
            },
        }
    }
}

/// Objective CRUD and formal Task materialization service.
pub struct PublicWorkspaceObjectiveService<'a> {
    store: WorkspaceObjectiveStore<'a>,
    tasks: PublicWorkspaceTaskService<'a>,
    receipt_authority: Option<WorkspaceMutationAuthority>,
}

impl<'a> PublicWorkspaceObjectiveService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            store: WorkspaceObjectiveStore::new(db, flavor),
            tasks: PublicWorkspaceTaskService::new(db, flavor),
            receipt_authority: None,
        }
    }

    /// Persist a collaboration receipt envelope with the Objective or projected Task write.
    #[must_use]
    pub fn with_mutation_authority(mut self, authority: WorkspaceMutationAuthority) -> Self {
        self.tasks = self.tasks.with_mutation_authority(authority.clone());
        self.receipt_authority = Some(authority);
        self
    }

    /// Create one Objective with ACL, CAS, receipt, and outbox atomically.
    pub async fn create(
        &self,
        input: &PublicCreateWorkspaceObjectiveInput,
    ) -> Result<PublicWorkspaceObjectiveOutcome, PublicWorkspaceObjectiveError> {
        validate_title(input.title.as_str())?;
        validate_objective_fields(
            input.objective_type.as_str(),
            input.parent_objective_id.as_deref(),
            input.progress,
        )?;
        let context = prepared_context(&input.context, "create_objective");
        let scope = objective_scope(&context);
        require_parent(&self.store, &scope, input.parent_objective_id.as_deref()).await?;
        let now = now_string();
        let record = WorkspaceObjectiveRecord {
            objective_id: deterministic_objective_id(&context),
            tenant_id: context.tenant_id.clone(),
            project_id: context.project_id.clone(),
            workspace_id: context.workspace_id.clone(),
            title: input.title.clone(),
            description: input.description.clone(),
            objective_type: input.objective_type.clone(),
            parent_objective_id: input.parent_objective_id.clone(),
            progress: input.progress,
            created_by_actor_id: context.user_id.clone(),
            created_at: now.clone(),
            updated_at: Some(now),
        };
        self.commit(
            &context,
            "create_objective",
            WorkspaceObjectiveDomainWrite::Create(record.clone()),
            public_objective(&record),
            "workspace_objective_created",
        )
        .await
    }

    /// List scoped Objectives.
    pub async fn list(
        &self,
        context: &PublicWorkspaceObjectiveContext,
        objective_type: Option<&str>,
        parent_objective_id: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<PublicWorkspaceObjective>, PublicWorkspaceObjectiveError> {
        if !(1..=500).contains(&limit) || offset < 0 {
            return Err(PublicWorkspaceObjectiveError::InvalidRequest);
        }
        if let Some(objective_type) = objective_type {
            validate_objective_type(objective_type)?;
        }
        let scope = objective_scope(context);
        self.store
            .require_access(
                &scope,
                context.user_id.as_str(),
                false,
                context.is_superuser,
            )
            .await?;
        Ok(self
            .store
            .list(&scope, objective_type, parent_objective_id, limit, offset)
            .await?
            .iter()
            .map(public_objective)
            .collect())
    }

    /// Read one scoped Objective.
    pub async fn get(
        &self,
        context: &PublicWorkspaceObjectiveContext,
        objective_id: &str,
    ) -> Result<PublicWorkspaceObjective, PublicWorkspaceObjectiveError> {
        let scope = objective_scope(context);
        self.store
            .require_access(
                &scope,
                context.user_id.as_str(),
                false,
                context.is_superuser,
            )
            .await?;
        self.store
            .get(&scope, objective_id)
            .await?
            .as_ref()
            .map(public_objective)
            .ok_or(PublicWorkspaceObjectiveError::ObjectiveNotFound)
    }

    /// Patch one Objective atomically.
    pub async fn update(
        &self,
        context: &PublicWorkspaceObjectiveContext,
        objective_id: &str,
        fields: &PublicUpdateWorkspaceObjectiveFields,
    ) -> Result<PublicWorkspaceObjectiveOutcome, PublicWorkspaceObjectiveError> {
        let scope = objective_scope(context);
        self.store
            .require_access(&scope, context.user_id.as_str(), true, context.is_superuser)
            .await?;
        let mut record = self
            .store
            .get(&scope, objective_id)
            .await?
            .ok_or(PublicWorkspaceObjectiveError::ObjectiveNotFound)?;
        if let Some(title) = &fields.title {
            validate_title(title)?;
            record.title.clone_from(title);
        }
        if let Some(description) = &fields.description {
            record.description = Some(description.clone());
        }
        if let Some(objective_type) = &fields.objective_type {
            record.objective_type.clone_from(objective_type);
        }
        if let Some(parent_objective_id) = &fields.parent_objective_id {
            if parent_objective_id == objective_id {
                return Err(PublicWorkspaceObjectiveError::InvalidRequest);
            }
            record.parent_objective_id = Some(parent_objective_id.clone());
        }
        if let Some(progress) = fields.progress {
            record.progress = progress;
        }
        validate_objective_fields(
            record.objective_type.as_str(),
            record.parent_objective_id.as_deref(),
            record.progress,
        )?;
        require_parent(&self.store, &scope, record.parent_objective_id.as_deref()).await?;
        record.updated_at = Some(now_string());
        self.commit(
            context,
            "update_objective",
            WorkspaceObjectiveDomainWrite::Update(record.clone()),
            public_objective(&record),
            "workspace_objective_updated",
        )
        .await
    }

    /// Delete one Objective atomically.
    pub async fn delete(
        &self,
        context: &PublicWorkspaceObjectiveContext,
        objective_id: &str,
    ) -> Result<PublicWorkspaceObjectiveDeleteOutcome, PublicWorkspaceObjectiveError> {
        let scope = objective_scope(context);
        self.store
            .require_access(&scope, context.user_id.as_str(), true, context.is_superuser)
            .await?;
        if self.store.get(&scope, objective_id).await?.is_none() {
            return Err(PublicWorkspaceObjectiveError::ObjectiveNotFound);
        }
        let response = json!({"success": true});
        let outcome = self
            .commit_value(
                context,
                "delete_objective",
                objective_id,
                WorkspaceObjectiveDomainWrite::Delete {
                    objective_id: objective_id.to_string(),
                },
                response,
                "workspace_objective_deleted",
            )
            .await?;
        Ok(PublicWorkspaceObjectiveDeleteOutcome {
            committed_revision: outcome.committed_revision,
            outbox_id: outcome.outbox_id,
            replayed: outcome.replayed,
        })
    }

    /// Materialize an Objective as a formal root Task and relation in one Task transaction.
    pub async fn project_to_task(
        &self,
        context: &PublicWorkspaceObjectiveContext,
        objective_id: &str,
        preferred_language: Option<&str>,
    ) -> Result<PublicObjectiveTaskOutcome, PublicWorkspaceObjectiveError> {
        if preferred_language.is_some_and(|value| !matches!(value, "en-US" | "zh-CN")) {
            return Err(PublicWorkspaceObjectiveError::InvalidRequest);
        }
        let scope = objective_scope(context);
        self.store
            .require_access(&scope, context.user_id.as_str(), true, context.is_superuser)
            .await?;
        let objective = self
            .store
            .get(&scope, objective_id)
            .await?
            .ok_or(PublicWorkspaceObjectiveError::ObjectiveNotFound)?;
        let task_context = projected_task_context(context, objective_id);
        if let Some(projection) = self.store.projected_task(&scope, objective_id).await? {
            return Ok(PublicObjectiveTaskOutcome {
                task: self
                    .tasks
                    .get(&task_context, projection.task_id.as_str())
                    .await?,
                existing: true,
                committed_revision: projection.committed_revision,
                outbox_id: projection.outbox_id,
                replayed: true,
            });
        }
        let projection_id = Uuid::new_v5(
            &OBJECTIVE_NAMESPACE,
            format!("projection\0{}\0{objective_id}", context.workspace_id).as_bytes(),
        )
        .to_string();
        let metadata = projected_root_metadata(&objective, preferred_language);
        let outcome = self
            .tasks
            .create_with_auxiliary(
                &PublicCreateWorkspaceTaskInput {
                    context: task_context,
                    title: objective.title,
                    description: objective.description,
                    assignee_user_id: None,
                    metadata: Some(metadata),
                    preferred_language: preferred_language.map(str::to_string),
                    priority: None,
                    estimated_effort: None,
                    blocker_reason: None,
                },
                vec![WorkspaceTaskAuxiliaryWrite::CreateObjectiveProjection(
                    WorkspaceObjectiveTaskProjectionWrite {
                        projection_id,
                        objective_id: objective_id.to_string(),
                        task_id: projected_task_id(context, objective_id),
                        actor_id: context.user_id.clone(),
                        created_at: now_string(),
                    },
                )],
            )
            .await?;
        Ok(PublicObjectiveTaskOutcome {
            task: outcome.task,
            existing: false,
            committed_revision: outcome.committed_revision,
            outbox_id: outcome.outbox_id,
            replayed: outcome.replayed,
        })
    }

    async fn commit(
        &self,
        context: &PublicWorkspaceObjectiveContext,
        action: &str,
        domain_write: WorkspaceObjectiveDomainWrite,
        response: PublicWorkspaceObjective,
        event_type: &str,
    ) -> Result<PublicWorkspaceObjectiveOutcome, PublicWorkspaceObjectiveError> {
        let objective_id = response.id.clone();
        let response_value = serde_json::to_value(&response)?;
        let outcome = self
            .commit_value(
                context,
                action,
                objective_id.as_str(),
                domain_write,
                response_value,
                event_type,
            )
            .await?;
        Ok(PublicWorkspaceObjectiveOutcome {
            objective: serde_json::from_value(outcome.response)?,
            committed_revision: outcome.committed_revision,
            outbox_id: outcome.outbox_id,
            replayed: outcome.replayed,
        })
    }

    #[allow(clippy::too_many_arguments)]
    async fn commit_value(
        &self,
        context: &PublicWorkspaceObjectiveContext,
        action: &str,
        objective_id: &str,
        domain_write: WorkspaceObjectiveDomainWrite,
        response: Value,
        event_type: &str,
    ) -> Result<
        memstack_workspace_store::WorkspaceObjectiveMutationOutcome,
        PublicWorkspaceObjectiveError,
    > {
        let context = prepared_context(context, action);
        let scope = objective_scope(&context);
        let expected_revision = match context.expected_revision {
            Some(revision) => revision,
            None => self.store.revision(&scope).await?,
        };
        let idempotency_key = context
            .idempotency_key
            .clone()
            .ok_or(PublicWorkspaceObjectiveError::InvalidRequest)?;
        validate_idempotency_key(idempotency_key.as_str())?;
        let intent = objective_intent(&domain_write);
        let domain_hash = hash_value(json!({
            "action": action,
            "scope": {
                "tenant_id": &context.tenant_id,
                "project_id": &context.project_id,
                "workspace_id": &context.workspace_id,
            },
            "actor_id": &context.user_id,
            "objective_id": objective_id,
            "intent": intent,
        }))?;
        let request_hash = self
            .receipt_authority
            .as_ref()
            .map_or(domain_hash, |authority| {
                authority.request_hash().as_str().to_string()
            });
        self.store
            .mutate(&WorkspaceObjectiveMutation {
                scope,
                actor_id: context.user_id,
                actor_is_superuser: context.is_superuser,
                action: action.to_string(),
                idempotency_key,
                request_hash,
                expected_revision,
                objective_id: objective_id.to_string(),
                domain_write,
                response,
                event_type: event_type.to_string(),
                receipt_authority: self.receipt_authority.clone(),
            })
            .await
            .map_err(Into::into)
    }
}

fn objective_intent(domain_write: &WorkspaceObjectiveDomainWrite) -> Value {
    match domain_write {
        WorkspaceObjectiveDomainWrite::Create(record)
        | WorkspaceObjectiveDomainWrite::Update(record) => json!({
            "title": &record.title,
            "description": &record.description,
            "objective_type": &record.objective_type,
            "parent_objective_id": &record.parent_objective_id,
            "progress": record.progress,
        }),
        WorkspaceObjectiveDomainWrite::Delete { objective_id } => {
            json!({"objective_id": objective_id})
        }
    }
}

async fn require_parent(
    store: &WorkspaceObjectiveStore<'_>,
    scope: &WorkspaceObjectiveScope,
    parent_id: Option<&str>,
) -> Result<(), PublicWorkspaceObjectiveError> {
    if let Some(parent_id) = parent_id
        && store.get(scope, parent_id).await?.is_none()
    {
        return Err(PublicWorkspaceObjectiveError::InvalidRequest);
    }
    Ok(())
}

fn objective_scope(context: &PublicWorkspaceObjectiveContext) -> WorkspaceObjectiveScope {
    WorkspaceObjectiveScope {
        tenant_id: context.tenant_id.clone(),
        project_id: context.project_id.clone(),
        workspace_id: context.workspace_id.clone(),
    }
}

fn prepared_context(
    context: &PublicWorkspaceObjectiveContext,
    action: &str,
) -> PublicWorkspaceObjectiveContext {
    let mut context = context.clone();
    if context.idempotency_key.is_none() {
        context.idempotency_key = Some(format!("legacy-{action}:{}", Uuid::new_v4()));
    }
    context
}

fn projected_task_context(
    context: &PublicWorkspaceObjectiveContext,
    objective_id: &str,
) -> PublicWorkspaceTaskContext {
    let source_key = context
        .idempotency_key
        .as_deref()
        .unwrap_or("legacy-objective-projection");
    let mut digest = Sha256::new();
    digest.update(source_key.as_bytes());
    digest.update(objective_id.as_bytes());
    PublicWorkspaceTaskContext {
        tenant_id: context.tenant_id.clone(),
        project_id: context.project_id.clone(),
        workspace_id: context.workspace_id.clone(),
        user_id: context.user_id.clone(),
        expected_revision: context.expected_revision,
        idempotency_key: Some(format!(
            "project-objective:{}",
            hex::encode(digest.finalize())
        )),
    }
}

fn projected_task_id(context: &PublicWorkspaceObjectiveContext, objective_id: &str) -> String {
    let task_context = projected_task_context(context, objective_id);
    let identity = format!(
        "{}\0{}\0{}\0{}\0{}",
        task_context.tenant_id,
        task_context.project_id,
        task_context.workspace_id,
        task_context.user_id,
        task_context.idempotency_key.as_deref().unwrap_or_default(),
    );
    let task_namespace = Uuid::from_u128(0x92ae_36c7_03ef_49f4_b7e7_8091_0ad2_5dcb);
    Uuid::new_v5(&task_namespace, identity.as_bytes()).to_string()
}

fn deterministic_objective_id(context: &PublicWorkspaceObjectiveContext) -> String {
    let identity = format!(
        "{}\0{}\0{}\0{}\0{}",
        context.tenant_id,
        context.project_id,
        context.workspace_id,
        context.user_id,
        context.idempotency_key.as_deref().unwrap_or_default(),
    );
    Uuid::new_v5(&OBJECTIVE_NAMESPACE, identity.as_bytes()).to_string()
}

fn projected_root_metadata(
    objective: &WorkspaceObjectiveRecord,
    preferred_language: Option<&str>,
) -> Value {
    let mut metadata = json!({
        "autonomy_schema_version": 1,
        "task_role": "goal_root",
        "goal_origin": "existing_objective",
        "goal_source_refs": [format!("objective:{}", objective.objective_id)],
        "objective_id": &objective.objective_id,
        "goal_formalization_reason": "selected workspace objective projected into execution root",
        "root_goal_policy": {
            "mutable_by_agent": false,
            "completion_requires_external_proof": true,
        },
        "goal_health": "healthy",
        "replan_attempt_count": 0,
        "workspace_harness": {
            "schema_version": 1,
            "harness_id": format!("harness:objective:{}", objective.objective_id),
            "goal_task_id": null,
            "mode": "long_running_agent",
            "feature_ledger": [],
            "required_preflight_checks": [],
            "acceptance_policy": {
                "require_preflight_evidence": true,
                "require_clean_git": false,
                "require_commit_ref": false,
                "require_test_evidence": false,
                "require_browser_e2e": false,
                "minimum_verification_grade": null,
            },
            "progress_notes": [],
        },
    });
    if let Some(language) = preferred_language {
        metadata["preferred_language"] = Value::String(language.to_string());
    }
    metadata
}

fn public_objective(record: &WorkspaceObjectiveRecord) -> PublicWorkspaceObjective {
    PublicWorkspaceObjective {
        id: record.objective_id.clone(),
        workspace_id: record.workspace_id.clone(),
        title: record.title.clone(),
        description: record.description.clone(),
        obj_type: record.objective_type.clone(),
        parent_id: record.parent_objective_id.clone(),
        progress: record.progress,
        created_by: record.created_by_actor_id.clone(),
        created_at: record.created_at.clone(),
        updated_at: record.updated_at.clone(),
    }
}

fn validate_title(title: &str) -> Result<(), PublicWorkspaceObjectiveError> {
    let length = title.chars().count();
    if title.trim().is_empty() || length > MAX_TITLE_CHARS {
        return Err(PublicWorkspaceObjectiveError::InvalidRequest);
    }
    Ok(())
}

fn validate_objective_fields(
    objective_type: &str,
    parent_objective_id: Option<&str>,
    progress: f64,
) -> Result<(), PublicWorkspaceObjectiveError> {
    validate_objective_type(objective_type)?;
    if !progress.is_finite() || !(0.0..=1.0).contains(&progress) {
        return Err(PublicWorkspaceObjectiveError::InvalidRequest);
    }
    if objective_type == "key_result"
        && parent_objective_id.is_none_or(|parent_id| parent_id.trim().is_empty())
    {
        return Err(PublicWorkspaceObjectiveError::InvalidRequest);
    }
    Ok(())
}

fn validate_objective_type(value: &str) -> Result<(), PublicWorkspaceObjectiveError> {
    if !OBJECTIVE_TYPES.contains(&value) {
        return Err(PublicWorkspaceObjectiveError::InvalidRequest);
    }
    Ok(())
}

fn validate_idempotency_key(value: &str) -> Result<(), PublicWorkspaceObjectiveError> {
    if value.trim().is_empty() || value.chars().count() > MAX_IDEMPOTENCY_KEY_CHARS {
        return Err(PublicWorkspaceObjectiveError::InvalidRequest);
    }
    Ok(())
}

fn hash_value(value: Value) -> Result<String, serde_json::Error> {
    let bytes = serde_json::to_vec(&canonical_json(&value))?;
    Ok(hex::encode(Sha256::digest(bytes)))
}

fn now_string() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Micros, false)
}
