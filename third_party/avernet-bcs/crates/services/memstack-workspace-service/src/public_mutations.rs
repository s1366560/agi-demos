//! Legacy-compatible public Workspace update and delete orchestration.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use chrono::{SecondsFormat, Utc};
use memstack_workspace_service_api::{
    ActorId, ContractVersion, ExpectedRevision, IdempotencyKey, ProjectId, RequestHash, TenantId,
    WorkspaceActor, WorkspaceCommandError, WorkspaceId, WorkspaceMutationAction,
    WorkspaceMutationAuthority, WorkspaceMutationCommand, WorkspaceName, WorkspaceScope,
};
use memstack_workspace_store::{
    WorkspaceAgentStoreError, WorkspaceMemberStoreError, WorkspaceMutationPlanError,
    WorkspaceMutationPlanner, WorkspaceMutationStore, WorkspaceMutationStoreError,
    WorkspaceProfileSnapshot, WorkspaceProfileStore, WorkspaceProfileStoreError,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use thiserror::Error;
use uuid::Uuid;

use crate::{CONTRACT_VERSION, canonical_json};

/// Shared authenticated scope and transport guards for legacy mutations.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceMutationContext {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub user_id: String,
    pub expected_revision: Option<u64>,
    pub idempotency_key: Option<String>,
}

/// Legacy PATCH fields. `None` preserves the current persisted value.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicUpdateWorkspaceInput {
    pub context: PublicWorkspaceMutationContext,
    pub name: Option<String>,
    pub description: Option<String>,
    pub is_archived: Option<bool>,
    pub metadata: Option<Value>,
}

/// Legacy DELETE input.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicDeleteWorkspaceInput {
    pub context: PublicWorkspaceMutationContext,
}

/// A committed or replayed public Workspace mutation.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicWorkspaceMutationOutcome {
    pub receipt_id: String,
    pub committed_revision: u64,
    pub response: Value,
    pub replayed: bool,
}

/// Stable public mutation error category consumed by the HTTP adapter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PublicWorkspaceMutationErrorKind {
    Validation,
    NotFound,
    Forbidden,
    Conflict,
    Unavailable,
}

/// Public Workspace update/delete validation or persistence failure.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceMutationError {
    #[error(transparent)]
    Command(#[from] WorkspaceCommandError),

    #[error(transparent)]
    Profile(#[from] WorkspaceProfileStoreError),

    #[error(transparent)]
    Member(#[from] WorkspaceMemberStoreError),

    #[error(transparent)]
    Agent(#[from] WorkspaceAgentStoreError),

    #[error(transparent)]
    AgentRegistry(#[from] memstack_workspace_service_api::AgentRegistryPortError),

    #[error(transparent)]
    Plan(#[from] WorkspaceMutationPlanError),

    #[error(transparent)]
    Store(#[from] WorkspaceMutationStoreError),

    #[error("Workspace not found")]
    NotFound,

    #[error("Invalid workspace request")]
    InvalidRequest,

    #[error("Access denied")]
    Forbidden,

    #[error("Agent definition is not available for this workspace")]
    AgentUnavailable,

    #[error("Workspace authority is missing")]
    MissingAuthority,

    #[error("Workspace request canonicalization failed: {0}")]
    CanonicalJson(#[source] serde_json::Error),
}

impl PublicWorkspaceMutationError {
    #[must_use]
    pub const fn kind(&self) -> PublicWorkspaceMutationErrorKind {
        match self {
            Self::Command(_) | Self::Plan(_) | Self::InvalidRequest | Self::AgentUnavailable => {
                PublicWorkspaceMutationErrorKind::Validation
            }
            Self::NotFound => PublicWorkspaceMutationErrorKind::NotFound,
            Self::Forbidden => PublicWorkspaceMutationErrorKind::Forbidden,
            Self::Store(WorkspaceMutationStoreError::AccessDenied) => {
                PublicWorkspaceMutationErrorKind::Forbidden
            }
            Self::Store(
                WorkspaceMutationStoreError::RevisionConflict
                | WorkspaceMutationStoreError::DomainConflict
                | WorkspaceMutationStoreError::WorkspaceAlreadyExists
                | WorkspaceMutationStoreError::IdempotencyConflict,
            ) => PublicWorkspaceMutationErrorKind::Conflict,
            Self::Profile(_)
            | Self::Member(_)
            | Self::Agent(_)
            | Self::AgentRegistry(_)
            | Self::MissingAuthority
            | Self::CanonicalJson(_)
            | Self::Store(_) => PublicWorkspaceMutationErrorKind::Unavailable,
        }
    }
}

/// Public compatibility service over the shared mutation transaction contract.
pub struct PublicWorkspaceMutationService<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
    receipt_authority: Option<WorkspaceMutationAuthority>,
}

impl<'a> PublicWorkspaceMutationService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            db,
            flavor,
            receipt_authority: None,
        }
    }

    /// Persist the supplied collaboration receipt envelope in the same domain transaction.
    #[must_use]
    pub fn with_mutation_authority(mut self, authority: WorkspaceMutationAuthority) -> Self {
        self.receipt_authority = Some(authority);
        self
    }

    /// Apply a legacy Workspace patch using revision CAS and durable outbox.
    ///
    /// # Errors
    ///
    /// Returns a structured validation, access, conflict, or persistence error.
    pub async fn update(
        &self,
        input: &PublicUpdateWorkspaceInput,
    ) -> Result<PublicWorkspaceMutationOutcome, PublicWorkspaceMutationError> {
        if let Some(name) = &input.name {
            let _ = WorkspaceName::parse(name.clone())?;
        }
        if let Some(metadata) = &input.metadata
            && !metadata.is_object()
        {
            return Err(WorkspaceCommandError::MetadataNotObject.into());
        }

        let scope = parse_scope(&input.context)?;
        let profile_store = WorkspaceProfileStore::new(self.db, self.flavor);
        let mut profile = profile_store
            .read_profile(&scope)
            .await?
            .ok_or(PublicWorkspaceMutationError::NotFound)?;
        let revision =
            resolve_revision(&profile_store, &scope, input.context.expected_revision).await?;
        let command = attach_receipt_authority(
            mutation_command(
                &input.context,
                scope,
                WorkspaceMutationAction::UpdateWorkspace,
                revision,
                update_request_hash(input)?,
            )?,
            self.receipt_authority.as_ref(),
        );

        if let Some(name) = &input.name {
            profile.name.clone_from(name);
        }
        if let Some(description) = &input.description {
            profile.description = Some(description.clone());
        }
        if let Some(is_archived) = input.is_archived {
            profile.is_archived = is_archived;
        }
        if let Some(metadata) = &input.metadata {
            profile.metadata.clone_from(metadata);
        }

        let now = Utc::now();
        let persisted_at = now.to_rfc3339_opts(SecondsFormat::Micros, false);
        let response_at = now.to_rfc3339_opts(SecondsFormat::Micros, true);
        let response = workspace_response(&profile, Some(response_at.as_str()));
        let event_payload = json!({
            "workspace_id": &profile.workspace_id,
            "workspace": &response,
            "name": &profile.name,
            "is_archived": profile.is_archived,
            "updated_by": &input.context.user_id,
        });
        let plan = WorkspaceMutationPlanner::new(self.flavor).plan_existing(
            &command,
            vec![profile_store.update_mutation(&profile, &persisted_at)],
            response,
            event_payload,
        )?;
        execute(self.db, &command, plan, profile.is_deleted()).await
    }

    /// Tombstone a Workspace and close its BCS Group without deleting replay history.
    ///
    /// # Errors
    ///
    /// Returns a structured access, conflict, or persistence error.
    pub async fn delete(
        &self,
        input: &PublicDeleteWorkspaceInput,
    ) -> Result<PublicWorkspaceMutationOutcome, PublicWorkspaceMutationError> {
        let scope = parse_scope(&input.context)?;
        let profile_store = WorkspaceProfileStore::new(self.db, self.flavor);
        let profile = profile_store
            .read_profile(&scope)
            .await?
            .ok_or(PublicWorkspaceMutationError::NotFound)?;
        let revision =
            resolve_revision(&profile_store, &scope, input.context.expected_revision).await?;
        let command = attach_receipt_authority(
            mutation_command(
                &input.context,
                scope,
                WorkspaceMutationAction::DeleteWorkspace,
                revision,
                delete_request_hash(input)?,
            )?,
            self.receipt_authority.as_ref(),
        );
        let persisted_at = Utc::now().to_rfc3339_opts(SecondsFormat::Micros, false);
        let event_payload = json!({
            "workspace_id": &profile.workspace_id,
            "workspace": workspace_response(&profile, profile.updated_at.as_deref()),
            "deleted_by": &input.context.user_id,
        });
        let plan = WorkspaceMutationPlanner::new(self.flavor).plan_existing(
            &command,
            profile_store.delete_mutations(&profile, input.context.user_id.as_str(), &persisted_at),
            json!({"workspace_id": &profile.workspace_id}),
            event_payload,
        )?;
        execute(self.db, &command, plan, profile.is_deleted()).await
    }
}

pub(crate) async fn resolve_revision(
    store: &WorkspaceProfileStore<'_>,
    scope: &WorkspaceScope,
    supplied: Option<u64>,
) -> Result<u64, PublicWorkspaceMutationError> {
    if let Some(revision) = supplied {
        return Ok(revision);
    }
    store
        .read_revision(scope)
        .await?
        .ok_or(PublicWorkspaceMutationError::MissingAuthority)
}

pub(crate) fn mutation_command(
    context: &PublicWorkspaceMutationContext,
    scope: WorkspaceScope,
    action: WorkspaceMutationAction,
    revision: u64,
    request_hash: RequestHash,
) -> Result<WorkspaceMutationCommand, WorkspaceCommandError> {
    let idempotency_key = context
        .idempotency_key
        .clone()
        .unwrap_or_else(|| format!("legacy-{}:{}", action.as_str(), Uuid::new_v4()));
    Ok(WorkspaceMutationCommand::new(
        scope,
        // Legacy handlers require Workspace membership even for superusers.
        WorkspaceActor::new(ActorId::parse(context.user_id.clone())?, false),
        ContractVersion::parse(CONTRACT_VERSION)?,
        action,
        ExpectedRevision::new(revision),
        IdempotencyKey::parse(idempotency_key)?,
        request_hash,
    ))
}

pub(crate) fn attach_receipt_authority(
    command: WorkspaceMutationCommand,
    authority: Option<&WorkspaceMutationAuthority>,
) -> WorkspaceMutationCommand {
    match authority {
        Some(authority) => command.with_receipt_authority(authority.clone()),
        None => command,
    }
}

pub(crate) fn parse_scope(
    context: &PublicWorkspaceMutationContext,
) -> Result<WorkspaceScope, WorkspaceCommandError> {
    Ok(WorkspaceScope::new(
        TenantId::parse(context.tenant_id.clone())?,
        ProjectId::parse(context.project_id.clone())?,
        WorkspaceId::parse(context.workspace_id.clone())?,
    ))
}

fn update_request_hash(
    input: &PublicUpdateWorkspaceInput,
) -> Result<RequestHash, PublicWorkspaceMutationError> {
    canonical_hash(json!({
        "action": "update_workspace",
        "tenant_id": &input.context.tenant_id,
        "project_id": &input.context.project_id,
        "workspace_id": &input.context.workspace_id,
        "actor_id": &input.context.user_id,
        "name": &input.name,
        "description": &input.description,
        "is_archived": input.is_archived,
        "metadata": &input.metadata,
    }))
}

fn delete_request_hash(
    input: &PublicDeleteWorkspaceInput,
) -> Result<RequestHash, PublicWorkspaceMutationError> {
    canonical_hash(json!({
        "action": "delete_workspace",
        "tenant_id": &input.context.tenant_id,
        "project_id": &input.context.project_id,
        "workspace_id": &input.context.workspace_id,
        "actor_id": &input.context.user_id,
    }))
}

pub(crate) fn canonical_hash(payload: Value) -> Result<RequestHash, PublicWorkspaceMutationError> {
    let bytes = serde_json::to_vec(&canonical_json(&payload))
        .map_err(PublicWorkspaceMutationError::CanonicalJson)?;
    Ok(RequestHash::parse(hex::encode(Sha256::digest(bytes)))?)
}

fn workspace_response(profile: &WorkspaceProfileSnapshot, updated_at: Option<&str>) -> Value {
    json!({
        "id": &profile.workspace_id,
        "tenant_id": &profile.tenant_id,
        "project_id": &profile.project_id,
        "name": &profile.name,
        "created_by": &profile.created_by,
        "description": &profile.description,
        "is_archived": profile.is_archived,
        "metadata": &profile.metadata,
        "office_status": &profile.office_status,
        "hex_layout_config": &profile.hex_layout_config,
        "created_at": &profile.created_at,
        "updated_at": updated_at,
    })
}

async fn execute(
    db: &dyn DbPlugin,
    command: &WorkspaceMutationCommand,
    plan: memstack_workspace_store::WorkspaceMutationPlan,
    was_deleted: bool,
) -> Result<PublicWorkspaceMutationOutcome, PublicWorkspaceMutationError> {
    let outcome = WorkspaceMutationStore::new(db).execute(command, plan).await;
    let outcome = match outcome {
        Err(WorkspaceMutationStoreError::AccessDenied) if was_deleted => {
            return Err(PublicWorkspaceMutationError::NotFound);
        }
        result => result?,
    };
    Ok(PublicWorkspaceMutationOutcome {
        receipt_id: outcome.receipt_id,
        committed_revision: outcome.committed_revision,
        response: outcome.response,
        replayed: outcome.replayed,
    })
}
