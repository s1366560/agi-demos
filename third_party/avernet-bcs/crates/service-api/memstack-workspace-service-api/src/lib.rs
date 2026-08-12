//! Route-facing application contracts for the MemStack Workspace extension.
//!
//! HTTP adapters parse untrusted strings into these validated types before
//! invoking an application service. Persistence details and SQL stay below
//! this crate.

use serde_json::Value;
use thiserror::Error;

mod agent_registry;
mod context_judge;
mod plan_dispatch;
mod plan_judge;
mod provider_registry;

pub use agent_registry::{
    AgentRegistryAgent, AgentRegistryLookup, AgentRegistryPort, AgentRegistryPortError,
};
pub use context_judge::{
    WorkspaceContextCandidate, WorkspaceContextCurrent, WorkspaceContextJudgeContractError,
    WorkspaceContextJudgePort, WorkspaceContextJudgePortError, WorkspaceContextJudgment,
    WorkspaceContextJudgmentRequest,
};
pub use plan_dispatch::{
    WORKSPACE_PLAN_RUNTIME_EVENT_TYPES, WorkspacePlanDispatchAction,
    WorkspacePlanDispatchContractError, WorkspacePlanDispatchPort, WorkspacePlanDispatchPortError,
    WorkspacePlanDispatchReceipt, WorkspacePlanDispatchRequest,
};
pub use plan_judge::{
    WorkspacePlanJudgeContractError, WorkspacePlanJudgePort, WorkspacePlanJudgePortError,
    WorkspacePlanJudgment, WorkspacePlanJudgmentKind, WorkspacePlanJudgmentRequest,
};
pub use provider_registry::{
    ProviderRegistryLookup, ProviderRegistryPort, ProviderRegistryPortError, ProviderRegistryRoute,
};

const SCOPE_ID_MAX_CHARS: usize = 128;
const ACTOR_ID_MAX_CHARS: usize = 256;
const BCS_GROUP_ID_MAX_CHARS: usize = 64;
const BCS_ENVIRONMENT_MAX_CHARS: usize = 64;
const WORKSPACE_NAME_MAX_CHARS: usize = 255;
const MODEL_ID_MAX_CHARS: usize = 512;
const MEMBERSHIP_ROLE_MAX_CHARS: usize = 64;
const CONTRACT_VERSION_MAX_CHARS: usize = 20;
const MUTATION_SURFACE_MAX_CHARS: usize = 32;
const MUTATION_ACTION_MAX_CHARS: usize = 64;
const IDEMPOTENCY_KEY_MAX_CHARS: usize = 256;
const SHA256_HEX_CHARS: usize = 64;

/// Invalid structured Workspace mutation input.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
#[non_exhaustive]
pub enum WorkspaceCommandError {
    #[error("{field} must not be blank")]
    Blank { field: &'static str },

    #[error("{field} exceeds {max_chars} characters")]
    TooLong {
        field: &'static str,
        max_chars: usize,
        actual_chars: usize,
    },

    #[error("request_hash must be 64 lowercase hexadecimal characters")]
    InvalidRequestHash,

    #[error("metadata must be a JSON object")]
    MetadataNotObject,

    #[error("config must be a JSON object")]
    ConfigNotObject,

    #[error("hex_q and hex_r must be provided together")]
    InvalidHexPair,

    #[error("hex target must stay within Workspace radius 24")]
    HexOutOfBounds,

    #[error("center hex is reserved for the blackboard")]
    ReservedHex,

    #[error("role must be owner, editor, or viewer")]
    InvalidMemberRole,
}

macro_rules! validated_text {
    ($name:ident, $field:literal, $max_chars:expr) => {
        #[derive(Debug, Clone, PartialEq, Eq, Hash)]
        pub struct $name(String);

        impl $name {
            /// Parse a non-blank, bounded string.
            ///
            /// # Errors
            ///
            /// Returns [`WorkspaceCommandError`] when the value is blank or
            /// exceeds the persisted field width.
            pub fn parse(value: impl Into<String>) -> Result<Self, WorkspaceCommandError> {
                let value = value.into();
                if value.trim().is_empty() {
                    return Err(WorkspaceCommandError::Blank { field: $field });
                }
                let actual_chars = value.chars().count();
                if actual_chars > $max_chars {
                    return Err(WorkspaceCommandError::TooLong {
                        field: $field,
                        max_chars: $max_chars,
                        actual_chars,
                    });
                }
                Ok(Self(value))
            }

            #[must_use]
            pub fn as_str(&self) -> &str {
                &self.0
            }
        }
    };
}

validated_text!(TenantId, "tenant_id", SCOPE_ID_MAX_CHARS);
validated_text!(ProjectId, "project_id", SCOPE_ID_MAX_CHARS);
validated_text!(WorkspaceId, "workspace_id", SCOPE_ID_MAX_CHARS);
validated_text!(ActorId, "actor_id", ACTOR_ID_MAX_CHARS);
validated_text!(GroupId, "group_id", BCS_GROUP_ID_MAX_CHARS);
validated_text!(BcsEnvironment, "bcs_environment", BCS_ENVIRONMENT_MAX_CHARS);
validated_text!(WorkspaceMemberId, "member_id", SCOPE_ID_MAX_CHARS);
validated_text!(UserId, "user_id", SCOPE_ID_MAX_CHARS);
validated_text!(AgentId, "agent_id", SCOPE_ID_MAX_CHARS);
validated_text!(ProviderId, "provider_id", SCOPE_ID_MAX_CHARS);
validated_text!(ModelId, "model_id", MODEL_ID_MAX_CHARS);
validated_text!(
    WorkspaceAgentBindingId,
    "workspace_agent_id",
    SCOPE_ID_MAX_CHARS
);
validated_text!(
    ParticipantActorId,
    "participant_actor_id",
    ACTOR_ID_MAX_CHARS
);
validated_text!(WorkspaceName, "name", WORKSPACE_NAME_MAX_CHARS);
validated_text!(
    ContractVersion,
    "contract_version",
    CONTRACT_VERSION_MAX_CHARS
);
validated_text!(IdempotencyKey, "idempotency_key", IDEMPOTENCY_KEY_MAX_CHARS);
validated_text!(MembershipRole, "membership_role", MEMBERSHIP_ROLE_MAX_CHARS);
validated_text!(MutationSurface, "surface", MUTATION_SURFACE_MAX_CHARS);
validated_text!(MutationAction, "action", MUTATION_ACTION_MAX_CHARS);

/// BCS Group and Workspace Profile fields for first-time creation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceCreateProfile {
    group_id: GroupId,
    bcs_environment: BcsEnvironment,
    name: WorkspaceName,
    description: Option<String>,
    metadata: Value,
}

impl WorkspaceCreateProfile {
    /// Construct a validated first-time Workspace profile.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspaceCommandError::MetadataNotObject`] when metadata is
    /// not a JSON object.
    pub fn new(
        group_id: GroupId,
        bcs_environment: BcsEnvironment,
        name: WorkspaceName,
        description: Option<String>,
        metadata: Value,
    ) -> Result<Self, WorkspaceCommandError> {
        if !metadata.is_object() {
            return Err(WorkspaceCommandError::MetadataNotObject);
        }
        Ok(Self {
            group_id,
            bcs_environment,
            name,
            description,
            metadata,
        })
    }

    #[must_use]
    pub const fn group_id(&self) -> &GroupId {
        &self.group_id
    }

    #[must_use]
    pub const fn bcs_environment(&self) -> &BcsEnvironment {
        &self.bcs_environment
    }

    #[must_use]
    pub const fn name(&self) -> &WorkspaceName {
        &self.name
    }

    #[must_use]
    pub fn description(&self) -> Option<&str> {
        self.description.as_deref()
    }

    #[must_use]
    pub const fn metadata(&self) -> &Value {
        &self.metadata
    }
}

/// Human owner identifiers written to both Workspace ACL and BCS roster.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceCreateOwner {
    member_id: WorkspaceMemberId,
    user_id: UserId,
    participant_actor_id: ParticipantActorId,
}

impl WorkspaceCreateOwner {
    #[must_use]
    pub const fn new(
        member_id: WorkspaceMemberId,
        user_id: UserId,
        participant_actor_id: ParticipantActorId,
    ) -> Self {
        Self {
            member_id,
            user_id,
            participant_actor_id,
        }
    }

    #[must_use]
    pub const fn member_id(&self) -> &WorkspaceMemberId {
        &self.member_id
    }

    #[must_use]
    pub const fn user_id(&self) -> &UserId {
        &self.user_id
    }

    #[must_use]
    pub const fn participant_actor_id(&self) -> &ParticipantActorId {
        &self.participant_actor_id
    }
}

/// Canonical SHA-256 of the structured mutation request.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct RequestHash(String);

impl RequestHash {
    /// Parse a lowercase SHA-256 hexadecimal digest.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspaceCommandError::InvalidRequestHash`] for any other
    /// representation.
    pub fn parse(value: impl Into<String>) -> Result<Self, WorkspaceCommandError> {
        let value = value.into();
        let valid = value.len() == SHA256_HEX_CHARS
            && value
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte));
        if !valid {
            return Err(WorkspaceCommandError::InvalidRequestHash);
        }
        Ok(Self(value))
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Canonical receipt metadata supplied by a versioned collaboration façade.
///
/// The domain action remains independently typed so event generation cannot be
/// redirected by transport input. This value only replaces the receipt
/// contract, surface, action, and request hash written by the atomic mutation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceMutationAuthority {
    contract_version: ContractVersion,
    surface: MutationSurface,
    action: MutationAction,
    request_hash: RequestHash,
}

impl WorkspaceMutationAuthority {
    /// Parse bounded receipt metadata at the compatibility boundary.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspaceCommandError`] when a field is blank, oversized, or
    /// the request hash is not a lowercase SHA-256 digest.
    pub fn parse(
        contract_version: impl Into<String>,
        surface: impl Into<String>,
        action: impl Into<String>,
        request_hash: impl Into<String>,
    ) -> Result<Self, WorkspaceCommandError> {
        Ok(Self {
            contract_version: ContractVersion::parse(contract_version)?,
            surface: MutationSurface::parse(surface)?,
            action: MutationAction::parse(action)?,
            request_hash: RequestHash::parse(request_hash)?,
        })
    }

    #[must_use]
    pub const fn contract_version(&self) -> &ContractVersion {
        &self.contract_version
    }

    #[must_use]
    pub const fn surface(&self) -> &MutationSurface {
        &self.surface
    }

    #[must_use]
    pub const fn action(&self) -> &MutationAction {
        &self.action
    }

    #[must_use]
    pub const fn request_hash(&self) -> &RequestHash {
        &self.request_hash
    }
}

/// Optimistic authority revision supplied by the caller.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ExpectedRevision(u64);

impl ExpectedRevision {
    #[must_use]
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    #[must_use]
    pub const fn get(self) -> u64 {
        self.0
    }
}

/// Tenant/project/workspace isolation scope.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceScope {
    tenant_id: TenantId,
    project_id: ProjectId,
    workspace_id: WorkspaceId,
}

/// Authenticated principal supplied by the trusted HTTP adapter.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceActor {
    actor_id: ActorId,
    is_superuser: bool,
}

impl WorkspaceActor {
    #[must_use]
    pub const fn new(actor_id: ActorId, is_superuser: bool) -> Self {
        Self {
            actor_id,
            is_superuser,
        }
    }

    #[must_use]
    pub const fn actor_id(&self) -> &ActorId {
        &self.actor_id
    }

    #[must_use]
    pub const fn is_superuser(&self) -> bool {
        self.is_superuser
    }
}

impl WorkspaceScope {
    #[must_use]
    pub const fn new(
        tenant_id: TenantId,
        project_id: ProjectId,
        workspace_id: WorkspaceId,
    ) -> Self {
        Self {
            tenant_id,
            project_id,
            workspace_id,
        }
    }

    #[must_use]
    pub const fn tenant_id(&self) -> &TenantId {
        &self.tenant_id
    }

    #[must_use]
    pub const fn project_id(&self) -> &ProjectId {
        &self.project_id
    }

    #[must_use]
    pub const fn workspace_id(&self) -> &WorkspaceId {
        &self.workspace_id
    }
}

/// Canonical collaboration surface affected by a Workspace command.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum WorkspaceMutationSurface {
    Settings,
    Members,
    Collaboration,
}

/// Closed Workspace ACL role set shared by HTTP, application, and store layers.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum WorkspaceMemberRole {
    Owner,
    Editor,
    Viewer,
}

impl WorkspaceMemberRole {
    /// Parse the public snake-case role value.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspaceCommandError::InvalidMemberRole`] for any other value.
    pub fn parse(value: &str) -> Result<Self, WorkspaceCommandError> {
        match value {
            "owner" => Ok(Self::Owner),
            "editor" => Ok(Self::Editor),
            "viewer" => Ok(Self::Viewer),
            _ => Err(WorkspaceCommandError::InvalidMemberRole),
        }
    }

    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Owner => "owner",
            Self::Editor => "editor",
            Self::Viewer => "viewer",
        }
    }
}

impl WorkspaceMutationSurface {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Settings => "settings",
            Self::Members => "members",
            Self::Collaboration => "collaboration",
        }
    }
}

/// Closed set of Wave A Workspace roster commands.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum WorkspaceMutationAction {
    CreateWorkspace,
    UpdateWorkspace,
    DeleteWorkspace,
    AddMember,
    UpdateMemberRole,
    RemoveMember,
    BindAgent,
    UpdateAgentBinding,
    UnbindAgent,
    UpdateAgentPolicy,
}

impl WorkspaceMutationAction {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::CreateWorkspace => "create_workspace",
            Self::UpdateWorkspace => "update_workspace",
            Self::DeleteWorkspace => "delete_workspace",
            Self::AddMember => "add_member",
            Self::UpdateMemberRole => "update_member_role",
            Self::RemoveMember => "remove_member",
            Self::BindAgent => "bind_agent",
            Self::UpdateAgentBinding => "update_agent_binding",
            Self::UnbindAgent => "unbind_agent",
            Self::UpdateAgentPolicy => "update_agent_policy",
        }
    }

    #[must_use]
    pub const fn surface(self) -> WorkspaceMutationSurface {
        match self {
            Self::CreateWorkspace | Self::UpdateWorkspace | Self::DeleteWorkspace => {
                WorkspaceMutationSurface::Settings
            }
            Self::AddMember | Self::UpdateMemberRole | Self::RemoveMember => {
                WorkspaceMutationSurface::Members
            }
            Self::BindAgent | Self::UpdateAgentBinding | Self::UnbindAgent => {
                WorkspaceMutationSurface::Collaboration
            }
            Self::UpdateAgentPolicy => WorkspaceMutationSurface::Collaboration,
        }
    }
}

/// Validated command envelope shared by all Wave A write use cases.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceMutationCommand {
    scope: WorkspaceScope,
    actor: WorkspaceActor,
    contract_version: ContractVersion,
    action: WorkspaceMutationAction,
    expected_revision: ExpectedRevision,
    idempotency_key: IdempotencyKey,
    request_hash: RequestHash,
    receipt_authority: Option<WorkspaceMutationAuthority>,
}

impl WorkspaceMutationCommand {
    #[must_use]
    pub const fn new(
        scope: WorkspaceScope,
        actor: WorkspaceActor,
        contract_version: ContractVersion,
        action: WorkspaceMutationAction,
        expected_revision: ExpectedRevision,
        idempotency_key: IdempotencyKey,
        request_hash: RequestHash,
    ) -> Self {
        Self {
            scope,
            actor,
            contract_version,
            action,
            expected_revision,
            idempotency_key,
            request_hash,
            receipt_authority: None,
        }
    }

    /// Override only the durable receipt envelope for a compatibility façade.
    #[must_use]
    pub fn with_receipt_authority(mut self, authority: WorkspaceMutationAuthority) -> Self {
        self.receipt_authority = Some(authority);
        self
    }

    #[must_use]
    pub const fn scope(&self) -> &WorkspaceScope {
        &self.scope
    }

    #[must_use]
    pub const fn actor(&self) -> &WorkspaceActor {
        &self.actor
    }

    #[must_use]
    pub fn contract_version(&self) -> &ContractVersion {
        self.receipt_authority.as_ref().map_or(
            &self.contract_version,
            WorkspaceMutationAuthority::contract_version,
        )
    }

    #[must_use]
    pub const fn action(&self) -> WorkspaceMutationAction {
        self.action
    }

    #[must_use]
    pub const fn expected_revision(&self) -> ExpectedRevision {
        self.expected_revision
    }

    #[must_use]
    pub const fn idempotency_key(&self) -> &IdempotencyKey {
        &self.idempotency_key
    }

    #[must_use]
    pub fn request_hash(&self) -> &RequestHash {
        self.receipt_authority
            .as_ref()
            .map_or(&self.request_hash, WorkspaceMutationAuthority::request_hash)
    }

    #[must_use]
    pub fn receipt_surface(&self) -> &str {
        self.receipt_authority.as_ref().map_or_else(
            || self.action.surface().as_str(),
            |authority| authority.surface().as_str(),
        )
    }

    #[must_use]
    pub fn receipt_action(&self) -> &str {
        self.receipt_authority.as_ref().map_or_else(
            || self.action.as_str(),
            |authority| authority.action().as_str(),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse_scope() -> Result<WorkspaceScope, WorkspaceCommandError> {
        Ok(WorkspaceScope::new(
            TenantId::parse("tenant-1")?,
            ProjectId::parse("project-1")?,
            WorkspaceId::parse("workspace-1")?,
        ))
    }

    #[test]
    fn validated_ids_reject_blank_and_oversized_values() {
        assert!(matches!(
            TenantId::parse("  "),
            Err(WorkspaceCommandError::Blank { field: "tenant_id" })
        ));
        assert!(matches!(
            WorkspaceId::parse("w".repeat(SCOPE_ID_MAX_CHARS + 1)),
            Err(WorkspaceCommandError::TooLong {
                field: "workspace_id",
                ..
            })
        ));
    }

    #[test]
    fn validated_ids_count_unicode_characters_instead_of_bytes() {
        let value = "工".repeat(SCOPE_ID_MAX_CHARS);
        let workspace_id = WorkspaceId::parse(value.clone());

        assert!(matches!(workspace_id, Ok(id) if id.as_str() == value));
    }

    #[test]
    fn request_hash_requires_canonical_lowercase_sha256() {
        assert!(RequestHash::parse("a".repeat(SHA256_HEX_CHARS)).is_ok());
        assert!(matches!(
            RequestHash::parse("A".repeat(SHA256_HEX_CHARS)),
            Err(WorkspaceCommandError::InvalidRequestHash)
        ));
        assert!(matches!(
            RequestHash::parse("a".repeat(SHA256_HEX_CHARS - 1)),
            Err(WorkspaceCommandError::InvalidRequestHash)
        ));
    }

    #[test]
    fn mutation_actions_map_to_declared_structured_surfaces() {
        assert_eq!(
            WorkspaceMutationAction::UpdateWorkspace.surface(),
            WorkspaceMutationSurface::Settings
        );
        assert_eq!(
            WorkspaceMutationAction::UpdateMemberRole.surface(),
            WorkspaceMutationSurface::Members
        );
        assert_eq!(
            WorkspaceMutationAction::UpdateAgentBinding.surface(),
            WorkspaceMutationSurface::Collaboration
        );
    }

    #[test]
    fn member_roles_are_a_closed_protocol_set() {
        assert_eq!(
            WorkspaceMemberRole::parse("editor"),
            Ok(WorkspaceMemberRole::Editor)
        );
        assert_eq!(
            WorkspaceMemberRole::parse("admin"),
            Err(WorkspaceCommandError::InvalidMemberRole)
        );
    }

    #[test]
    fn command_envelope_preserves_scope_revision_and_idempotency()
    -> Result<(), WorkspaceCommandError> {
        let command = WorkspaceMutationCommand::new(
            parse_scope()?,
            WorkspaceActor::new(ActorId::parse("user-1")?, false),
            ContractVersion::parse("2.0.0")?,
            WorkspaceMutationAction::AddMember,
            ExpectedRevision::new(7),
            IdempotencyKey::parse("intent-1")?,
            RequestHash::parse("b".repeat(SHA256_HEX_CHARS))?,
        );

        assert_eq!(command.scope().workspace_id().as_str(), "workspace-1");
        assert_eq!(command.actor().actor_id().as_str(), "user-1");
        assert_eq!(command.expected_revision().get(), 7);
        assert_eq!(command.idempotency_key().as_str(), "intent-1");
        assert_eq!(
            command.action().surface(),
            WorkspaceMutationSurface::Members
        );
        Ok(())
    }

    #[test]
    fn create_profile_requires_object_metadata() -> Result<(), WorkspaceCommandError> {
        let result = WorkspaceCreateProfile::new(
            GroupId::parse("group-1")?,
            BcsEnvironment::parse("memstack")?,
            WorkspaceName::parse("Team Space")?,
            None,
            Value::Array(Vec::new()),
        );

        assert_eq!(result, Err(WorkspaceCommandError::MetadataNotObject));
        Ok(())
    }
}
