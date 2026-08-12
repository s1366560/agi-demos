//! Legacy-compatible Workspace Agent Policy application service.

use std::collections::BTreeMap;

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use chrono::{SecondsFormat, Utc};
use memstack_workspace_service_api::{
    ActorId, ContractVersion, ExpectedRevision, IdempotencyKey, ModelId, ProjectId, ProviderId,
    ProviderRegistryLookup, ProviderRegistryPort, ProviderRegistryPortError, RequestHash, TenantId,
    WorkspaceActor, WorkspaceCommandError, WorkspaceId, WorkspaceMutationAction,
    WorkspaceMutationCommand, WorkspaceScope,
};
use memstack_workspace_store::{
    WorkspaceMutationPlanner, WorkspaceMutationStore, WorkspaceMutationStoreError,
    WorkspacePolicyScopeSnapshot, WorkspacePolicySnapshot, WorkspacePolicyStore,
    WorkspacePolicyStoreError, WorkspaceProfileStore, WorkspaceProfileStoreError,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use thiserror::Error;

use crate::{CONTRACT_VERSION, canonical_json};

const CAPABILITY_VERSION: &str = "workspace-agent-policy-v1";
const MAX_POLICY_REVISION: u64 = i64::MAX as u64;
const AUTHORITY_RETRY_LIMIT: usize = 3;

/// Provider/model route exposed by the legacy policy contract.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PublicPolicyRouteTarget {
    pub provider_id: String,
    pub model_id: String,
}

/// Shared trusted caller and Workspace scope for policy operations.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspacePolicyContext {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub actor_id: String,
}

/// Workspace-scoped partial policy mutation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicPatchWorkspacePolicyInput {
    pub context: PublicWorkspacePolicyContext,
    pub expected_revision: u64,
    pub capability_mode: String,
    pub route: PublicPolicyRouteTarget,
    pub reasoning_effort: String,
    pub permission_mode: String,
}

/// Legacy complete routing-policy replacement.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicPutWorkspacePolicyInput {
    pub project_id: String,
    pub workspace_id: String,
    pub actor_id: String,
    pub expected_revision: u64,
    pub roles: BTreeMap<String, Option<PublicPolicyRouteTarget>>,
    pub fallbacks: Vec<PublicPolicyRouteTarget>,
}

/// Stable error category consumed by the HTTP adapter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PublicWorkspacePolicyErrorKind {
    Validation,
    NotFound,
    Forbidden,
    Conflict,
    Unavailable,
}

/// Workspace Agent Policy validation, authority, or persistence failure.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspacePolicyError {
    #[error(transparent)]
    Command(#[from] WorkspaceCommandError),

    #[error("Default model route is required")]
    DefaultRouteRequired,

    #[error("Invalid provider route")]
    InvalidProviderRoute,

    #[error("Workspace not found")]
    WorkspaceNotFound,

    #[error("Access denied")]
    AccessDenied,

    #[error("Workspace policy revision conflict")]
    PolicyRevisionConflict,

    #[error("Workspace policy revision is exhausted")]
    RevisionExhausted,

    #[error(transparent)]
    Provider(#[from] ProviderRegistryPortError),

    #[error(transparent)]
    PolicyStore(#[from] WorkspacePolicyStoreError),

    #[error(transparent)]
    ProfileStore(#[from] WorkspaceProfileStoreError),

    #[error(transparent)]
    Plan(#[from] memstack_workspace_store::WorkspaceMutationPlanError),

    #[error(transparent)]
    Mutation(#[from] WorkspaceMutationStoreError),

    #[error("Workspace policy JSON serialization failed: {0}")]
    Json(#[source] serde_json::Error),

    #[error("Workspace authority changed too frequently to commit policy")]
    AuthorityBusy,
}

impl PublicWorkspacePolicyError {
    #[must_use]
    pub const fn kind(&self) -> PublicWorkspacePolicyErrorKind {
        match self {
            Self::Command(_) | Self::DefaultRouteRequired | Self::InvalidProviderRoute => {
                PublicWorkspacePolicyErrorKind::Validation
            }
            Self::WorkspaceNotFound => PublicWorkspacePolicyErrorKind::NotFound,
            Self::AccessDenied | Self::Mutation(WorkspaceMutationStoreError::AccessDenied) => {
                PublicWorkspacePolicyErrorKind::Forbidden
            }
            Self::PolicyRevisionConflict
            | Self::RevisionExhausted
            | Self::Mutation(
                WorkspaceMutationStoreError::DomainConflict
                | WorkspaceMutationStoreError::IdempotencyConflict,
            ) => PublicWorkspacePolicyErrorKind::Conflict,
            Self::Provider(_)
            | Self::PolicyStore(_)
            | Self::ProfileStore(_)
            | Self::Plan(_)
            | Self::Json(_)
            | Self::AuthorityBusy
            | Self::Mutation(_) => PublicWorkspacePolicyErrorKind::Unavailable,
        }
    }
}

/// Application use cases for the four public Agent Policy routes.
pub struct PublicWorkspacePolicyService<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
    provider_registry: &'a dyn ProviderRegistryPort,
}

impl<'a> PublicWorkspacePolicyService<'a> {
    #[must_use]
    pub const fn new(
        db: &'a dyn DbPlugin,
        flavor: DbSqlFlavor,
        provider_registry: &'a dyn ProviderRegistryPort,
    ) -> Self {
        Self {
            db,
            flavor,
            provider_registry,
        }
    }

    /// Read one Workspace-scoped policy or its tenant-registry default.
    ///
    /// # Errors
    ///
    /// Returns structured not-found, access, registry, or persistence errors.
    pub async fn get(
        &self,
        context: &PublicWorkspacePolicyContext,
    ) -> Result<Value, PublicWorkspacePolicyError> {
        let scope = parse_scope(context)?;
        let store = WorkspacePolicyStore::new(self.db, self.flavor);
        let profile = store
            .read_scope(&scope)
            .await?
            .ok_or(PublicWorkspacePolicyError::WorkspaceNotFound)?;
        self.require_access(&store, &scope, &context.actor_id, false)
            .await?;
        self.response(&scope, &profile, store.read_policy(&scope).await?)
            .await
    }

    /// Read the legacy query-param policy route.
    ///
    /// # Errors
    ///
    /// Returns structured not-found, access, registry, or persistence errors.
    pub async fn get_legacy(
        &self,
        project_id: &str,
        workspace_id: &str,
        actor_id: &str,
    ) -> Result<Value, PublicWorkspacePolicyError> {
        let store = WorkspacePolicyStore::new(self.db, self.flavor);
        let profile = store
            .read_scope_by_project(project_id, workspace_id)
            .await?
            .ok_or(PublicWorkspacePolicyError::WorkspaceNotFound)?;
        let scope = scope_from_profile(&profile)?;
        self.require_access(&store, &scope, actor_id, false).await?;
        self.response(&scope, &profile, store.read_policy(&scope).await?)
            .await
    }

    /// Patch the Work or Code route with policy-revision CAS.
    ///
    /// # Errors
    ///
    /// Returns validation, access, conflict, registry, or persistence errors.
    pub async fn patch(
        &self,
        input: &PublicPatchWorkspacePolicyInput,
    ) -> Result<Value, PublicWorkspacePolicyError> {
        let scope = parse_scope(&input.context)?;
        self.validate_route(&scope, &input.route).await?;
        let store = WorkspacePolicyStore::new(self.db, self.flavor);
        let _profile = store
            .read_scope(&scope)
            .await?
            .ok_or(PublicWorkspacePolicyError::WorkspaceNotFound)?;
        self.require_access(&store, &scope, &input.context.actor_id, true)
            .await?;
        let current = store.read_policy(&scope).await?;
        let mut roles = current
            .as_ref()
            .map(|policy| policy.roles.clone())
            .unwrap_or_else(default_roles);
        let route = serde_json::to_value(&input.route).map_err(PublicWorkspacePolicyError::Json)?;
        if roles.get("default").is_none_or(Value::is_null) {
            roles["default"] = route.clone();
        }
        roles[if input.capability_mode == "work" {
            "default"
        } else {
            "coding"
        }] = route;
        let fallbacks = current
            .as_ref()
            .map(|policy| policy.fallbacks.clone())
            .unwrap_or_else(|| json!([]));
        self.commit(
            &scope,
            &input.context.actor_id,
            input.expected_revision,
            roles,
            fallbacks,
            input.reasoning_effort.clone(),
            input.permission_mode.clone(),
        )
        .await
    }

    /// Replace the complete legacy routing policy with policy-revision CAS.
    ///
    /// # Errors
    ///
    /// Returns validation, access, conflict, registry, or persistence errors.
    pub async fn put_legacy(
        &self,
        input: &PublicPutWorkspacePolicyInput,
    ) -> Result<Value, PublicWorkspacePolicyError> {
        if input
            .roles
            .get("default")
            .and_then(Option::as_ref)
            .is_none()
        {
            return Err(PublicWorkspacePolicyError::DefaultRouteRequired);
        }
        let store = WorkspacePolicyStore::new(self.db, self.flavor);
        let profile = store
            .read_scope_by_project(&input.project_id, &input.workspace_id)
            .await?
            .ok_or(PublicWorkspacePolicyError::WorkspaceNotFound)?;
        let scope = scope_from_profile(&profile)?;
        self.require_access(&store, &scope, &input.actor_id, true)
            .await?;
        for route in input
            .roles
            .values()
            .filter_map(Option::as_ref)
            .chain(input.fallbacks.iter())
        {
            self.validate_route(&scope, route).await?;
        }
        let roles = serde_json::to_value(&input.roles).map_err(PublicWorkspacePolicyError::Json)?;
        let fallbacks =
            serde_json::to_value(&input.fallbacks).map_err(PublicWorkspacePolicyError::Json)?;
        self.commit(
            &scope,
            &input.actor_id,
            input.expected_revision,
            roles,
            fallbacks,
            "medium".to_string(),
            "ask".to_string(),
        )
        .await
    }

    async fn require_access(
        &self,
        store: &WorkspacePolicyStore<'_>,
        scope: &WorkspaceScope,
        actor_id: &str,
        require_manager: bool,
    ) -> Result<(), PublicWorkspacePolicyError> {
        if store.has_access(scope, actor_id, require_manager).await? {
            Ok(())
        } else {
            Err(PublicWorkspacePolicyError::AccessDenied)
        }
    }

    async fn response(
        &self,
        scope: &WorkspaceScope,
        profile: &WorkspacePolicyScopeSnapshot,
        policy: Option<WorkspacePolicySnapshot>,
    ) -> Result<Value, PublicWorkspacePolicyError> {
        if let Some(policy) = policy {
            return Ok(policy_response(&policy));
        }
        let default = self
            .provider_registry
            .tenant_default(scope.tenant_id())
            .await?
            .map(|route| {
                json!({
                    "provider_id": route.provider_id().as_str(),
                    "model_id": route.model_id().as_str(),
                })
            })
            .unwrap_or(Value::Null);
        let mut roles = default_roles();
        roles["default"] = default.clone();
        roles["coding"] = default;
        Ok(json!({
            "tenant_id": profile.tenant_id,
            "project_id": profile.project_id,
            "workspace_id": profile.workspace_id,
            "revision": 0,
            "roles": roles,
            "fallbacks": [],
            "reasoning_effort": "medium",
            "permission_mode": "ask",
            "capability_version": CAPABILITY_VERSION,
            "updated_at": profile.updated_at.as_deref().unwrap_or(&profile.created_at),
        }))
    }

    async fn validate_route(
        &self,
        scope: &WorkspaceScope,
        route: &PublicPolicyRouteTarget,
    ) -> Result<(), PublicWorkspacePolicyError> {
        let lookup = ProviderRegistryLookup::new(
            TenantId::parse(scope.tenant_id().as_str())?,
            ProviderId::parse(route.provider_id.clone())?,
            ModelId::parse(route.model_id.clone())?,
        );
        if self.provider_registry.resolve(&lookup).await?.is_none() {
            return Err(PublicWorkspacePolicyError::InvalidProviderRoute);
        }
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    async fn commit(
        &self,
        scope: &WorkspaceScope,
        actor_id: &str,
        expected_policy_revision: u64,
        roles: Value,
        fallbacks: Value,
        reasoning_effort: String,
        permission_mode: String,
    ) -> Result<Value, PublicWorkspacePolicyError> {
        if expected_policy_revision >= MAX_POLICY_REVISION {
            return Err(PublicWorkspacePolicyError::RevisionExhausted);
        }
        let committed_policy_revision = expected_policy_revision + 1;
        let updated_at = Utc::now().to_rfc3339_opts(SecondsFormat::Micros, true);
        let response = json!({
            "tenant_id": scope.tenant_id().as_str(),
            "project_id": scope.project_id().as_str(),
            "workspace_id": scope.workspace_id().as_str(),
            "revision": committed_policy_revision,
            "roles": roles,
            "fallbacks": fallbacks,
            "reasoning_effort": reasoning_effort,
            "permission_mode": permission_mode,
            "capability_version": CAPABILITY_VERSION,
            "updated_at": updated_at,
        });
        let request_hash = request_hash(&response, expected_policy_revision, actor_id)?;
        let idempotency_key =
            IdempotencyKey::parse(format!("workspace-agent-policy:{}", request_hash.as_str()))?;
        let policy = WorkspacePolicySnapshot {
            tenant_id: scope.tenant_id().as_str().to_string(),
            project_id: scope.project_id().as_str().to_string(),
            workspace_id: scope.workspace_id().as_str().to_string(),
            revision: committed_policy_revision,
            roles: response["roles"].clone(),
            fallbacks: response["fallbacks"].clone(),
            reasoning_effort: response["reasoning_effort"]
                .as_str()
                .unwrap_or("medium")
                .to_string(),
            permission_mode: response["permission_mode"]
                .as_str()
                .unwrap_or("ask")
                .to_string(),
            updated_at,
        };
        let profile_store = WorkspaceProfileStore::new(self.db, self.flavor);
        for _attempt in 0..AUTHORITY_RETRY_LIMIT {
            let authority_revision = profile_store
                .read_revision(scope)
                .await?
                .ok_or(PublicWorkspacePolicyError::WorkspaceNotFound)?;
            let command = WorkspaceMutationCommand::new(
                scope.clone(),
                WorkspaceActor::new(ActorId::parse(actor_id.to_string())?, false),
                ContractVersion::parse(CONTRACT_VERSION)?,
                WorkspaceMutationAction::UpdateAgentPolicy,
                ExpectedRevision::new(authority_revision),
                idempotency_key.clone(),
                request_hash.clone(),
            );
            let mutation = WorkspacePolicyStore::new(self.db, self.flavor).upsert_mutation(
                &policy,
                expected_policy_revision,
                actor_id,
            );
            let plan = WorkspaceMutationPlanner::new(self.flavor).plan_existing(
                &command,
                vec![mutation],
                response.clone(),
                json!({
                    "workspace_id": scope.workspace_id().as_str(),
                    "revision": committed_policy_revision,
                    "updated_by": actor_id,
                }),
            )?;
            match WorkspaceMutationStore::new(self.db)
                .execute(&command, plan)
                .await
            {
                Ok(outcome) => return Ok(outcome.response),
                Err(WorkspaceMutationStoreError::RevisionConflict) => continue,
                Err(error) => return Err(error.into()),
            }
        }
        Err(PublicWorkspacePolicyError::AuthorityBusy)
    }
}

fn parse_scope(
    context: &PublicWorkspacePolicyContext,
) -> Result<WorkspaceScope, WorkspaceCommandError> {
    Ok(WorkspaceScope::new(
        TenantId::parse(context.tenant_id.clone())?,
        ProjectId::parse(context.project_id.clone())?,
        WorkspaceId::parse(context.workspace_id.clone())?,
    ))
}

fn scope_from_profile(
    profile: &WorkspacePolicyScopeSnapshot,
) -> Result<WorkspaceScope, WorkspaceCommandError> {
    Ok(WorkspaceScope::new(
        TenantId::parse(profile.tenant_id.clone())?,
        ProjectId::parse(profile.project_id.clone())?,
        WorkspaceId::parse(profile.workspace_id.clone())?,
    ))
}

fn default_roles() -> Value {
    json!({"default": null, "fast": null, "coding": null, "vision": null})
}

fn policy_response(policy: &WorkspacePolicySnapshot) -> Value {
    json!({
        "tenant_id": policy.tenant_id,
        "project_id": policy.project_id,
        "workspace_id": policy.workspace_id,
        "revision": policy.revision,
        "roles": policy.roles,
        "fallbacks": policy.fallbacks,
        "reasoning_effort": policy.reasoning_effort,
        "permission_mode": policy.permission_mode,
        "capability_version": CAPABILITY_VERSION,
        "updated_at": policy.updated_at,
    })
}

fn request_hash(
    response: &Value,
    expected_policy_revision: u64,
    actor_id: &str,
) -> Result<RequestHash, PublicWorkspacePolicyError> {
    let mut response = response.clone();
    if let Some(fields) = response.as_object_mut() {
        fields.remove("updated_at");
    }
    let payload = canonical_json(&json!({
        "actor_id": actor_id,
        "expected_policy_revision": expected_policy_revision,
        "response": response,
    }));
    let bytes = serde_json::to_vec(&payload).map_err(PublicWorkspacePolicyError::Json)?;
    Ok(RequestHash::parse(hex::encode(Sha256::digest(bytes)))?)
}
