//! Atomic Workspace-owned half of the platform task-session saga.

use chrono::{SecondsFormat, Utc};
use memstack_workspace_service_api::{
    ActorId, ModelId, ProjectId, ProviderId, ProviderRegistryLookup, ProviderRegistryPort,
    ProviderRegistryPortError, TenantId, WorkspaceCommandError, WorkspaceId, WorkspaceName,
    WorkspaceScope,
};
use memstack_workspace_store::{
    TaskSessionPolicyWrite, TaskSessionStore, TaskSessionStoreError, TaskSessionWorkspaceCreate,
    TaskSessionWrite, WorkspacePolicyStore, WorkspacePolicyStoreError, WorkspaceProfileStore,
    WorkspaceProfileStoreError,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use thiserror::Error;
use uuid::Uuid;

use crate::canonical_json;

const TASK_SESSION_NAMESPACE: Uuid = Uuid::from_u128(0x8596_61df_6102_4da9_94da_cfb7_3027_2c2a);
const CAPABILITY_VERSION: &str = "avernet-task-session-v1";
const MAX_MESSAGE_CHARS: usize = 100_000;
const MAX_EMAIL_CHARS: usize = 320;
const MAX_POLICY_REVISION: u64 = i64::MAX as u64;

/// Stable gateway-provided identifiers and caller identity.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TaskSessionContext {
    pub tenant_id: String,
    pub project_id: String,
    pub actor_id: String,
    pub actor_email: String,
    pub actor_is_superuser: bool,
    pub idempotency_key: String,
    pub conversation_id: String,
}

/// New or existing Workspace selected by the platform gateway.
#[derive(Debug, Clone, PartialEq)]
pub enum TaskSessionWorkspaceInput {
    Create {
        workspace_id: String,
        name: String,
        description: Option<String>,
        metadata: Value,
    },
    Existing {
        workspace_id: String,
    },
}

/// Stable initial human message supplied by the platform gateway.
#[derive(Debug, Clone, PartialEq)]
pub struct TaskSessionMessageInput {
    pub message_id: String,
    pub content: String,
    pub context_items: Value,
}

/// Optional Workspace Agent Policy selection committed by Core.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TaskSessionPolicyInput {
    pub expected_revision: u64,
    pub provider_id: String,
    pub model_id: String,
    pub reasoning_effort: String,
    pub permission_mode: String,
}

/// Complete command at the Core-owned saga boundary.
#[derive(Debug, Clone, PartialEq)]
pub struct CreateTaskSessionInput {
    pub context: TaskSessionContext,
    pub workspace: TaskSessionWorkspaceInput,
    pub initial_message: TaskSessionMessageInput,
    pub policy: Option<TaskSessionPolicyInput>,
    pub capability_mode: String,
}

/// Committed or replayed Core result returned to the platform gateway.
#[derive(Debug, Clone, PartialEq)]
pub struct CreateTaskSessionOutcome {
    pub receipt_id: String,
    pub response: Value,
    pub replayed: bool,
}

/// Stable transport-facing task-session error category.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CreateTaskSessionErrorKind {
    Validation,
    NotFound,
    Forbidden,
    Conflict,
    IdempotencyConflict,
    Unavailable,
}

/// Validation, authority, registry, or transactional persistence failure.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum CreateTaskSessionError {
    #[error(transparent)]
    Command(#[from] WorkspaceCommandError),

    #[error("invalid task-session request: {0}")]
    InvalidRequest(&'static str),

    #[error("Workspace not found")]
    WorkspaceNotFound,

    #[error("Workspace Agent Policy revision conflict")]
    PolicyRevisionConflict,

    #[error("invalid Provider route")]
    InvalidProviderRoute,

    #[error(transparent)]
    Provider(#[from] ProviderRegistryPortError),

    #[error(transparent)]
    Profile(#[from] WorkspaceProfileStoreError),

    #[error(transparent)]
    Policy(#[from] WorkspacePolicyStoreError),

    #[error(transparent)]
    Store(#[from] TaskSessionStoreError),

    #[error("task-session serialization failed: {0}")]
    Json(#[source] serde_json::Error),
}

impl CreateTaskSessionError {
    #[must_use]
    pub const fn kind(&self) -> CreateTaskSessionErrorKind {
        match self {
            Self::Command(_) | Self::InvalidRequest(_) | Self::InvalidProviderRoute => {
                CreateTaskSessionErrorKind::Validation
            }
            Self::Store(TaskSessionStoreError::AccessDenied) => {
                CreateTaskSessionErrorKind::Forbidden
            }
            Self::Store(TaskSessionStoreError::IdempotencyConflict) => {
                CreateTaskSessionErrorKind::IdempotencyConflict
            }
            Self::PolicyRevisionConflict
            | Self::Store(TaskSessionStoreError::AuthorityConflict) => {
                CreateTaskSessionErrorKind::Conflict
            }
            Self::WorkspaceNotFound => CreateTaskSessionErrorKind::NotFound,
            Self::Provider(_)
            | Self::Profile(_)
            | Self::Policy(_)
            | Self::Store(_)
            | Self::Json(_) => CreateTaskSessionErrorKind::Unavailable,
        }
    }
}

/// Application service that validates and commits Core-owned task-session state.
pub struct CreateTaskSessionService<'a> {
    db: &'a dyn bcs_db_api::DbPlugin,
    flavor: bcs_db_api::DbSqlFlavor,
    provider_registry: &'a dyn ProviderRegistryPort,
}

impl<'a> CreateTaskSessionService<'a> {
    #[must_use]
    pub const fn new(
        db: &'a dyn bcs_db_api::DbPlugin,
        flavor: bcs_db_api::DbSqlFlavor,
        provider_registry: &'a dyn ProviderRegistryPort,
    ) -> Self {
        Self {
            db,
            flavor,
            provider_registry,
        }
    }

    /// Commit Workspace/Profile/Policy/Message/receipt/outbox state in one transaction.
    ///
    /// # Errors
    ///
    /// Returns structured validation, ACL, idempotency, registry, or persistence errors.
    pub async fn create(
        &self,
        input: &CreateTaskSessionInput,
    ) -> Result<CreateTaskSessionOutcome, CreateTaskSessionError> {
        validate_input(input)?;
        let scope = scope(input)?;
        let profile_store = WorkspaceProfileStore::new(self.db, self.flavor);
        let policy_store = WorkspacePolicyStore::new(self.db, self.flavor);
        let (workspace_create, workspace, expected_authority_revision) = match &input.workspace {
            TaskSessionWorkspaceInput::Create {
                workspace_id,
                name,
                description,
                metadata,
            } => {
                let group_id = deterministic_id("group", input);
                let owner_member_id = deterministic_id("owner", input);
                let timestamp = Utc::now().to_rfc3339_opts(SecondsFormat::Micros, true);
                let workspace = json!({
                    "id": workspace_id,
                    "tenant_id": input.context.tenant_id,
                    "project_id": input.context.project_id,
                    "name": name,
                    "description": description,
                    "status": "open",
                    "is_archived": false,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "metadata": metadata,
                });
                (
                    Some(TaskSessionWorkspaceCreate {
                        group_id,
                        owner_member_id,
                        name: name.clone(),
                        description: description.clone(),
                        metadata: metadata.clone(),
                    }),
                    workspace,
                    0,
                )
            }
            TaskSessionWorkspaceInput::Existing { .. } => {
                let profile = profile_store
                    .read_profile(&scope)
                    .await?
                    .filter(|profile| !profile.is_deleted())
                    .ok_or(CreateTaskSessionError::WorkspaceNotFound)?;
                let revision = profile_store
                    .read_revision(&scope)
                    .await?
                    .ok_or(CreateTaskSessionError::WorkspaceNotFound)?;
                let workspace = json!({
                    "id": profile.workspace_id,
                    "tenant_id": profile.tenant_id,
                    "project_id": profile.project_id,
                    "name": profile.name,
                    "description": profile.description,
                    "status": "open",
                    "is_archived": profile.is_archived,
                    "created_at": profile.created_at,
                    "updated_at": profile.updated_at,
                    "metadata": profile.metadata,
                });
                (None, workspace, revision)
            }
        };
        let policy = self.prepare_policy(input, &scope, &policy_store).await?;
        let committed_authority_revision = expected_authority_revision + 1;
        let now = Utc::now();
        let created_at = now.to_rfc3339_opts(SecondsFormat::Millis, true);
        let message = json!({
            "id": input.initial_message.message_id,
            "workspace_id": scope.workspace_id().as_str(),
            "sender_id": input.context.actor_id,
            "sender_type": "human",
            "content": input.initial_message.content,
            "mentions": [],
            "parent_message_id": null,
            "metadata": {
                "source": "task_session",
                "conversation_id": input.context.conversation_id,
                "runtime": "workspace_core",
                "context_items": input.initial_message.context_items,
            },
            "created_at": created_at,
        });
        let policy_response = policy.as_ref().map(|policy| {
            json!({
                "tenant_id": input.context.tenant_id,
                "project_id": input.context.project_id,
                "workspace_id": scope.workspace_id().as_str(),
                "revision": policy.committed_revision,
                "roles": policy.roles,
                "fallbacks": [],
                "reasoning_effort": policy.reasoning_effort,
                "permission_mode": policy.permission_mode,
                "capability_version": "workspace-agent-policy-v1",
                "updated_at": policy.updated_at,
            })
        });
        let response = json!({
            "workspace": workspace,
            "initial_message": message,
            "policy": policy_response,
            "capability_version": CAPABILITY_VERSION,
        });
        let payload_hash = canonical_hash(input)?;
        let receipt_id = deterministic_id("receipt", input);
        let write = TaskSessionWrite {
            tenant_id: input.context.tenant_id.clone(),
            project_id: input.context.project_id.clone(),
            workspace_id: scope.workspace_id().as_str().to_string(),
            actor_id: input.context.actor_id.clone(),
            actor_email: input.context.actor_email.clone(),
            actor_is_superuser: input.context.actor_is_superuser,
            idempotency_key: input.context.idempotency_key.clone(),
            payload_hash,
            receipt_id,
            conversation_id: input.context.conversation_id.clone(),
            message_id: input.initial_message.message_id.clone(),
            message_content_json: serde_json::to_string(&input.initial_message.content)
                .map_err(CreateTaskSessionError::Json)?,
            message_metadata_json: response["initial_message"]["metadata"].to_string(),
            message_created_at_ms: now.timestamp_millis(),
            expected_authority_revision,
            committed_authority_revision,
            response,
            workspace_create,
            policy,
        };
        let outcome = TaskSessionStore::new(self.db, self.flavor)
            .execute(&write)
            .await?;
        Ok(CreateTaskSessionOutcome {
            receipt_id: outcome.receipt_id,
            response: outcome.response,
            replayed: outcome.replayed,
        })
    }

    async fn prepare_policy(
        &self,
        input: &CreateTaskSessionInput,
        scope: &WorkspaceScope,
        store: &WorkspacePolicyStore<'_>,
    ) -> Result<Option<TaskSessionPolicyWrite>, CreateTaskSessionError> {
        let Some(selection) = &input.policy else {
            return Ok(None);
        };
        if selection.expected_revision >= MAX_POLICY_REVISION {
            return Err(CreateTaskSessionError::InvalidRequest(
                "policy revision is outside the supported range",
            ));
        }
        let lookup = ProviderRegistryLookup::new(
            TenantId::parse(input.context.tenant_id.clone())?,
            ProviderId::parse(selection.provider_id.clone())?,
            ModelId::parse(selection.model_id.clone())?,
        );
        if self.provider_registry.resolve(&lookup).await?.is_none() {
            return Err(CreateTaskSessionError::InvalidProviderRoute);
        }
        let current = if matches!(input.workspace, TaskSessionWorkspaceInput::Existing { .. }) {
            store.read_policy(scope).await?
        } else {
            None
        };
        let actual_revision = current.as_ref().map_or(0, |policy| policy.revision);
        if actual_revision != selection.expected_revision {
            return Err(CreateTaskSessionError::PolicyRevisionConflict);
        }
        let route = json!({
            "provider_id": selection.provider_id,
            "model_id": selection.model_id,
        });
        let mut roles = current.map_or_else(
            || json!({"default": null, "fast": null, "coding": null, "vision": null}),
            |policy| policy.roles,
        );
        if roles["default"].is_null() {
            roles["default"] = route.clone();
        }
        roles[if input.capability_mode == "work" {
            "default"
        } else {
            "coding"
        }] = route;
        Ok(Some(TaskSessionPolicyWrite {
            expected_revision: selection.expected_revision,
            committed_revision: selection.expected_revision + 1,
            roles,
            reasoning_effort: selection.reasoning_effort.clone(),
            permission_mode: selection.permission_mode.clone(),
            updated_at: Utc::now().to_rfc3339_opts(SecondsFormat::Micros, true),
        }))
    }
}

fn validate_input(input: &CreateTaskSessionInput) -> Result<(), CreateTaskSessionError> {
    let _ = TenantId::parse(input.context.tenant_id.clone())?;
    let _ = ProjectId::parse(input.context.project_id.clone())?;
    let _ = ActorId::parse(input.context.actor_id.clone())?;
    if input.context.actor_email.trim().is_empty()
        || input.context.actor_email.chars().count() > MAX_EMAIL_CHARS
    {
        return Err(CreateTaskSessionError::InvalidRequest(
            "invalid actor email",
        ));
    }
    if input.context.conversation_id.trim().is_empty()
        || input.initial_message.message_id.trim().is_empty()
    {
        return Err(CreateTaskSessionError::InvalidRequest(
            "stable conversation and message IDs are required",
        ));
    }
    if input.initial_message.content.trim().is_empty()
        || input.initial_message.content.chars().count() > MAX_MESSAGE_CHARS
    {
        return Err(CreateTaskSessionError::InvalidRequest(
            "initial message is blank or too long",
        ));
    }
    if !input.initial_message.context_items.is_array() {
        return Err(CreateTaskSessionError::InvalidRequest(
            "context_items must be an array",
        ));
    }
    if !matches!(input.capability_mode.as_str(), "work" | "code") {
        return Err(CreateTaskSessionError::InvalidRequest(
            "capability_mode must be work or code",
        ));
    }
    match &input.workspace {
        TaskSessionWorkspaceInput::Create {
            workspace_id,
            name,
            metadata,
            ..
        } => {
            let _ = WorkspaceId::parse(workspace_id.clone())?;
            let _ = WorkspaceName::parse(name.clone())?;
            if !metadata.is_object() {
                return Err(CreateTaskSessionError::InvalidRequest(
                    "workspace metadata must be an object",
                ));
            }
        }
        TaskSessionWorkspaceInput::Existing { workspace_id } => {
            let _ = WorkspaceId::parse(workspace_id.clone())?;
        }
    }
    Ok(())
}

fn scope(input: &CreateTaskSessionInput) -> Result<WorkspaceScope, WorkspaceCommandError> {
    let workspace_id = match &input.workspace {
        TaskSessionWorkspaceInput::Create { workspace_id, .. }
        | TaskSessionWorkspaceInput::Existing { workspace_id } => workspace_id,
    };
    Ok(WorkspaceScope::new(
        TenantId::parse(input.context.tenant_id.clone())?,
        ProjectId::parse(input.context.project_id.clone())?,
        WorkspaceId::parse(workspace_id.clone())?,
    ))
}

fn canonical_hash(input: &CreateTaskSessionInput) -> Result<String, CreateTaskSessionError> {
    let workspace = match &input.workspace {
        TaskSessionWorkspaceInput::Create {
            workspace_id,
            name,
            description,
            metadata,
        } => json!({
            "kind": "create",
            "workspace_id": workspace_id,
            "name": name,
            "description": description,
            "metadata": metadata,
        }),
        TaskSessionWorkspaceInput::Existing { workspace_id } => {
            json!({"kind": "existing", "workspace_id": workspace_id})
        }
    };
    let policy = input.policy.as_ref().map(|policy| {
        json!({
            "expected_revision": policy.expected_revision,
            "provider_id": policy.provider_id,
            "model_id": policy.model_id,
            "reasoning_effort": policy.reasoning_effort,
            "permission_mode": policy.permission_mode,
        })
    });
    let value = canonical_json(&json!({
        "tenant_id": input.context.tenant_id,
        "project_id": input.context.project_id,
        "actor_id": input.context.actor_id,
        "actor_email": input.context.actor_email,
        "conversation_id": input.context.conversation_id,
        "workspace": workspace,
        "initial_message": {
            "message_id": input.initial_message.message_id,
            "content": input.initial_message.content,
            "context_items": input.initial_message.context_items,
        },
        "policy": policy,
        "capability_mode": input.capability_mode,
    }));
    let bytes = serde_json::to_vec(&value).map_err(CreateTaskSessionError::Json)?;
    Ok(hex::encode(Sha256::digest(bytes)))
}

fn deterministic_id(label: &str, input: &CreateTaskSessionInput) -> String {
    let material = format!(
        "{label}:{}:{}:{}:{}",
        input.context.tenant_id,
        input.context.project_id,
        input.context.actor_id,
        input.context.idempotency_key
    );
    Uuid::new_v5(&TASK_SESSION_NAMESPACE, material.as_bytes()).to_string()
}
