//! Application orchestration for MemStack Workspace commands.
//!
//! HTTP adapters provide untrusted primitive input. This layer canonicalizes
//! the request, constructs validated service contracts, and invokes the atomic
//! store without exposing SQL or transaction steps to the adapter.

use std::collections::BTreeMap;

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use chrono::{SecondsFormat, Utc};
use memstack_workspace_service_api::{
    ActorId, BcsEnvironment, ContractVersion, ExpectedRevision, GroupId, IdempotencyKey,
    ParticipantActorId, ProjectId, RequestHash, TenantId, UserId, WorkspaceActor,
    WorkspaceCommandError, WorkspaceCreateOwner, WorkspaceCreateProfile, WorkspaceId,
    WorkspaceMemberId, WorkspaceMutationAction, WorkspaceMutationCommand, WorkspaceName,
    WorkspaceScope,
};
pub use memstack_workspace_service_api::{WorkspaceMemberRole, WorkspaceMutationAuthority};
use memstack_workspace_store::{
    WorkspaceCreationOwnerIdentity, WorkspaceCreationPlanError, WorkspaceCreationPlanner,
    WorkspaceCreationTimestamps, WorkspaceMutationStore, WorkspaceMutationStoreError,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use thiserror::Error;

mod plan_idempotency;
mod public_agents;
mod public_autonomy;
mod public_blackboard;
mod public_context;
mod public_creation;
mod public_diagnostics;
mod public_files;
mod public_genes;
mod public_members;
mod public_message_delivery;
mod public_messages;
mod public_mutations;
mod public_objectives;
mod public_plan_delivery;
mod public_plan_snapshot;
mod public_plans;
mod public_policy;
mod public_task_dispatch;
mod public_tasks;
mod public_topology;

pub use public_agents::{
    PublicBindWorkspaceAgentInput, PublicUnbindWorkspaceAgentInput,
    PublicUpdateWorkspaceAgentInput, PublicWorkspaceAgentMutationService,
};
pub use public_autonomy::{
    PublicWorkspaceAutonomyCandidate, PublicWorkspaceAutonomyContext, PublicWorkspaceAutonomyError,
    PublicWorkspaceAutonomyErrorKind, PublicWorkspaceAutonomyJudgeContractError,
    PublicWorkspaceAutonomyJudgePort, PublicWorkspaceAutonomyJudgePortError,
    PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgmentRequest,
    PublicWorkspaceAutonomyService, PublicWorkspaceAutonomyTickOutcome,
    PublicWorkspaceAutonomyTickResponse, PublicWorkspaceAutonomyVerdictKind,
};
pub use public_blackboard::{
    PublicCreateBlackboardPostInput, PublicCreateBlackboardReplyInput,
    PublicUpdateBlackboardPostFields, PublicUpdateBlackboardReplyInput,
    PublicWorkspaceBlackboardContext, PublicWorkspaceBlackboardDeleteOutcome,
    PublicWorkspaceBlackboardError, PublicWorkspaceBlackboardErrorKind,
    PublicWorkspaceBlackboardPost, PublicWorkspaceBlackboardPostOutcome,
    PublicWorkspaceBlackboardReply, PublicWorkspaceBlackboardReplyOutcome,
    PublicWorkspaceBlackboardService,
};
pub use public_context::{
    PublicSwitchWorkspaceContextInput, PublicWorkspaceContextAccess, PublicWorkspaceContextError,
    PublicWorkspaceContextErrorKind, PublicWorkspaceContextService, PublicWorkspaceContextSnapshot,
    PublicWorkspaceContextSwitchOutcome,
};
pub use public_creation::{
    PublicCreateWorkspaceInput, PublicWorkspaceCreationError, PublicWorkspaceCreationService,
    WorkspaceCollaborationMode, WorkspaceUseCase,
};
pub use public_diagnostics::{
    PublicWorkspaceExecutionDiagnostics, PublicWorkspaceExecutionDiagnosticsError,
    PublicWorkspaceExecutionDiagnosticsErrorKind, PublicWorkspaceExecutionDiagnosticsInput,
    PublicWorkspaceExecutionDiagnosticsService,
};
pub use public_files::{
    ObjectStageRequest, ObjectStoreError, ObjectStorePort, PublicWorkspaceFile,
    PublicWorkspaceFileContext, PublicWorkspaceFileDeleteOutcome, PublicWorkspaceFileDownload,
    PublicWorkspaceFileError, PublicWorkspaceFileErrorKind, PublicWorkspaceFileOutcome,
    PublicWorkspaceFileService, ReadyObjectReference, StagedObjectReference,
};
pub use public_genes::{
    PublicCreateWorkspaceGeneInput, PublicUpdateWorkspaceGeneFields, PublicWorkspaceGene,
    PublicWorkspaceGeneContext, PublicWorkspaceGeneDeleteOutcome, PublicWorkspaceGeneError,
    PublicWorkspaceGeneErrorKind, PublicWorkspaceGeneOutcome, PublicWorkspaceGeneService,
};
pub use public_members::{
    PublicAddWorkspaceMemberInput, PublicRemoveWorkspaceMemberInput,
    PublicUpdateWorkspaceMemberInput, PublicWorkspaceMemberMutationService,
};
pub use public_message_delivery::{
    PublicWorkspaceMessageDeliveryClaim, PublicWorkspaceMessageDeliveryFailureOutcome,
    PublicWorkspaceMessageDeliveryService,
};
pub use public_messages::{
    PublicSendWorkspaceMessageInput, PublicWorkspaceMessage, PublicWorkspaceMessageContext,
    PublicWorkspaceMessageDeliveryTarget, PublicWorkspaceMessageError,
    PublicWorkspaceMessageErrorKind, PublicWorkspaceMessageOutcome, PublicWorkspaceMessageService,
};
pub use public_mutations::{
    PublicDeleteWorkspaceInput, PublicUpdateWorkspaceInput, PublicWorkspaceMutationContext,
    PublicWorkspaceMutationError, PublicWorkspaceMutationErrorKind, PublicWorkspaceMutationOutcome,
    PublicWorkspaceMutationService,
};
pub use public_objectives::{
    PublicCreateWorkspaceObjectiveInput, PublicObjectiveTaskOutcome,
    PublicUpdateWorkspaceObjectiveFields, PublicWorkspaceObjective,
    PublicWorkspaceObjectiveContext, PublicWorkspaceObjectiveDeleteOutcome,
    PublicWorkspaceObjectiveError, PublicWorkspaceObjectiveErrorKind,
    PublicWorkspaceObjectiveOutcome, PublicWorkspaceObjectiveService,
};
pub use public_plan_delivery::{
    PublicWorkspacePlanDeliveryClaim, PublicWorkspacePlanDeliveryError,
    PublicWorkspacePlanDeliveryFailureOutcome, PublicWorkspacePlanDeliveryService,
};
pub use public_plan_snapshot::{
    PublicWorkspacePlan, PublicWorkspacePlanNode, PublicWorkspacePlanSnapshot,
};
pub use public_plans::{
    PublicWorkspacePlanAction, PublicWorkspacePlanActionInput, PublicWorkspacePlanActionResult,
    PublicWorkspacePlanContext, PublicWorkspacePlanError, PublicWorkspacePlanErrorKind,
    PublicWorkspacePlanService, PublicWorkspacePlanSnapshotInput,
};
pub use public_policy::{
    PublicPatchWorkspacePolicyInput, PublicPolicyRouteTarget, PublicPutWorkspacePolicyInput,
    PublicWorkspacePolicyContext, PublicWorkspacePolicyError, PublicWorkspacePolicyErrorKind,
    PublicWorkspacePolicyService,
};
pub use public_task_dispatch::{
    PublicWorkspaceTaskDispatchClaim, PublicWorkspaceTaskDispatchFailureOutcome,
    PublicWorkspaceTaskDispatchService,
};
pub use public_tasks::{
    PublicCreateWorkspaceTaskInput, PublicUpdateWorkspaceTaskFields, PublicWorkspaceTask,
    PublicWorkspaceTaskContext, PublicWorkspaceTaskError, PublicWorkspaceTaskErrorKind,
    PublicWorkspaceTaskOutcome, PublicWorkspaceTaskRecoveryAuthorityOutcome,
    PublicWorkspaceTaskRecoveryInput, PublicWorkspaceTaskRecoveryOutcome,
    PublicWorkspaceTaskService,
};
pub use public_topology::{
    PublicCreateTopologyEdgeInput, PublicCreateTopologyNodeInput, PublicUpdateTopologyEdgeFields,
    PublicUpdateTopologyNodeFields, PublicWorkspaceTopologyContext, PublicWorkspaceTopologyEdge,
    PublicWorkspaceTopologyError, PublicWorkspaceTopologyErrorKind, PublicWorkspaceTopologyNode,
    PublicWorkspaceTopologyOutcome, PublicWorkspaceTopologyService,
};

pub(crate) const CONTRACT_VERSION: &str = "2.0.0";
const BCS_ENVIRONMENT: &str = "memstack";

/// Tenant, Project, Workspace, and BCS Group identifiers for creation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CreateWorkspaceScopeInput {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub group_id: String,
}

/// Authenticated owner identifiers written to both ACL and BCS roster.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CreateWorkspaceOwnerInput {
    pub member_id: String,
    pub user_id: String,
    pub is_superuser: bool,
}

/// User-controlled Workspace profile fields.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CreateWorkspaceContentInput {
    pub name: String,
    pub description: Option<String>,
    pub metadata: Value,
}

/// Complete first-time Workspace command input.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CreateWorkspaceInput {
    pub scope: CreateWorkspaceScopeInput,
    pub owner: CreateWorkspaceOwnerInput,
    pub content: CreateWorkspaceContentInput,
    pub idempotency_key: String,
}

/// A committed or replayed Create Workspace result.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CreateWorkspaceOutcome {
    pub receipt_id: String,
    pub committed_revision: u64,
    pub response: Value,
    pub replayed: bool,
}

/// Stable error category consumed by transport adapters.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CreateWorkspaceErrorKind {
    Validation,
    Forbidden,
    Conflict,
    Unavailable,
}

/// Create Workspace validation, planning, or persistence failure.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum CreateWorkspaceServiceError {
    #[error(transparent)]
    Command(#[from] WorkspaceCommandError),

    #[error(transparent)]
    Plan(#[from] WorkspaceCreationPlanError),

    #[error(transparent)]
    Store(#[from] WorkspaceMutationStoreError),

    #[error("Workspace request canonicalization failed: {0}")]
    CanonicalJson(#[source] serde_json::Error),
}

impl CreateWorkspaceServiceError {
    /// Classify the error without leaking backend-specific details to adapters.
    #[must_use]
    pub const fn kind(&self) -> CreateWorkspaceErrorKind {
        match self {
            Self::Command(_) | Self::Plan(_) => CreateWorkspaceErrorKind::Validation,
            Self::Store(WorkspaceMutationStoreError::AccessDenied) => {
                CreateWorkspaceErrorKind::Forbidden
            }
            Self::Store(
                WorkspaceMutationStoreError::RevisionConflict
                | WorkspaceMutationStoreError::DomainConflict
                | WorkspaceMutationStoreError::WorkspaceAlreadyExists
                | WorkspaceMutationStoreError::IdempotencyConflict,
            ) => CreateWorkspaceErrorKind::Conflict,
            Self::Store(
                WorkspaceMutationStoreError::IncompleteReceipt
                | WorkspaceMutationStoreError::InvalidReceipt(_)
                | WorkspaceMutationStoreError::InvalidResponseJson(_)
                | WorkspaceMutationStoreError::Database(_),
            )
            | Self::CanonicalJson(_) => CreateWorkspaceErrorKind::Unavailable,
            Self::Store(_) => CreateWorkspaceErrorKind::Unavailable,
        }
    }
}

/// Application use case for first-time Workspace creation.
pub struct WorkspaceCreationService<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspaceCreationService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Atomically create BCS Group, Workspace Profile, owner ACL/roster,
    /// revision authority, mutation receipt, and durable outbox record.
    ///
    /// # Errors
    ///
    /// Returns structured validation, access, conflict, or infrastructure
    /// errors. A matching idempotent retry returns the committed receipt.
    pub async fn create(
        &self,
        input: &CreateWorkspaceInput,
    ) -> Result<CreateWorkspaceOutcome, CreateWorkspaceServiceError> {
        self.create_inner(input, None).await
    }

    /// Atomically create a public Workspace and its authenticated owner identity mirror.
    ///
    /// # Errors
    ///
    /// Returns the same structured errors as [`Self::create`].
    pub async fn create_with_owner_identity(
        &self,
        input: &CreateWorkspaceInput,
        owner_email: &str,
    ) -> Result<CreateWorkspaceOutcome, CreateWorkspaceServiceError> {
        self.create_inner(input, Some(owner_email)).await
    }

    async fn create_inner(
        &self,
        input: &CreateWorkspaceInput,
        owner_email: Option<&str>,
    ) -> Result<CreateWorkspaceOutcome, CreateWorkspaceServiceError> {
        let now = Utc::now();
        let persisted_at = now.to_rfc3339_opts(SecondsFormat::Micros, false);
        let response_at = now.to_rfc3339_opts(SecondsFormat::Micros, true);
        let timestamps =
            WorkspaceCreationTimestamps::new(persisted_at.clone(), persisted_at.clone())?;
        let request_hash = canonical_request_hash(input, owner_email)?;
        let workspace_id = WorkspaceId::parse(input.scope.workspace_id.clone())?;
        let actor_id = ActorId::parse(input.owner.user_id.clone())?;
        let command = WorkspaceMutationCommand::new(
            WorkspaceScope::new(
                TenantId::parse(input.scope.tenant_id.clone())?,
                ProjectId::parse(input.scope.project_id.clone())?,
                workspace_id,
            ),
            WorkspaceActor::new(actor_id, input.owner.is_superuser),
            ContractVersion::parse(CONTRACT_VERSION)?,
            WorkspaceMutationAction::CreateWorkspace,
            ExpectedRevision::new(0),
            IdempotencyKey::parse(input.idempotency_key.clone())?,
            request_hash,
        );
        let profile = WorkspaceCreateProfile::new(
            GroupId::parse(input.scope.group_id.clone())?,
            BcsEnvironment::parse(BCS_ENVIRONMENT)?,
            WorkspaceName::parse(input.content.name.clone())?,
            input.content.description.clone(),
            input.content.metadata.clone(),
        )?;
        let owner = WorkspaceCreateOwner::new(
            WorkspaceMemberId::parse(input.owner.member_id.clone())?,
            UserId::parse(input.owner.user_id.clone())?,
            ParticipantActorId::parse(input.owner.user_id.clone())?,
        );
        let response = creation_response(input, &response_at);
        let event_payload = owner_event_payload(input, &persisted_at);
        let planner = WorkspaceCreationPlanner::new(self.flavor);
        let plan = if let Some(owner_email) = owner_email {
            planner.plan_with_owner_identity(
                &command,
                profile,
                owner,
                response,
                event_payload,
                WorkspaceCreationOwnerIdentity::new(owner_email, &timestamps)?,
            )?
        } else {
            planner.plan_with_timestamps(
                &command,
                profile,
                owner,
                response,
                event_payload,
                &timestamps,
            )?
        };
        let outcome = WorkspaceMutationStore::new(self.db)
            .execute_creation(&command, plan)
            .await?;
        Ok(CreateWorkspaceOutcome {
            receipt_id: outcome.receipt_id,
            committed_revision: outcome.committed_revision,
            response: outcome.response,
            replayed: outcome.replayed,
        })
    }
}

fn canonical_request_hash(
    input: &CreateWorkspaceInput,
    owner_email: Option<&str>,
) -> Result<RequestHash, CreateWorkspaceServiceError> {
    let payload = json!({
        "scope": {
            "tenant_id": &input.scope.tenant_id,
            "project_id": &input.scope.project_id,
            "workspace_id": &input.scope.workspace_id,
            "group_id": &input.scope.group_id,
        },
        "owner": {
            "member_id": &input.owner.member_id,
            "user_id": &input.owner.user_id,
            "is_superuser": input.owner.is_superuser,
            "email": owner_email,
        },
        "content": {
            "name": &input.content.name,
            "description": &input.content.description,
            "metadata": &input.content.metadata,
        },
    });
    let canonical = canonical_json(&payload);
    let bytes =
        serde_json::to_vec(&canonical).map_err(CreateWorkspaceServiceError::CanonicalJson)?;
    Ok(RequestHash::parse(hex::encode(Sha256::digest(bytes)))?)
}

pub(crate) fn canonical_json(value: &Value) -> Value {
    match value {
        Value::Array(items) => Value::Array(items.iter().map(canonical_json).collect()),
        Value::Object(values) => {
            let ordered = values
                .iter()
                .map(|(key, value)| (key.clone(), canonical_json(value)))
                .collect::<BTreeMap<_, _>>();
            Value::Object(ordered.into_iter().collect())
        }
        scalar => scalar.clone(),
    }
}

fn creation_response(input: &CreateWorkspaceInput, timestamp: &str) -> Value {
    json!({
        "id": &input.scope.workspace_id,
        "tenant_id": &input.scope.tenant_id,
        "project_id": &input.scope.project_id,
        "name": &input.content.name,
        "created_by": &input.owner.user_id,
        "description": &input.content.description,
        "is_archived": false,
        "metadata": &input.content.metadata,
        "office_status": "inactive",
        "hex_layout_config": {},
        "created_at": timestamp,
        "updated_at": timestamp,
    })
}

fn owner_event_payload(input: &CreateWorkspaceInput, timestamp: &str) -> Value {
    json!({
        "workspace_id": &input.scope.workspace_id,
        "member_id": &input.owner.member_id,
        "user_id": &input.owner.user_id,
        "role": "owner",
        "invited_by": &input.owner.user_id,
        "member": {
            "id": &input.owner.member_id,
            "workspace_id": &input.scope.workspace_id,
            "user_id": &input.owner.user_id,
            "role": "owner",
            "invited_by": &input.owner.user_id,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
    })
}
