//! Legacy-compatible public Workspace creation orchestration.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use serde_json::{Map, Value};
use thiserror::Error;
use uuid::Uuid;

use crate::{
    CreateWorkspaceContentInput, CreateWorkspaceInput, CreateWorkspaceOutcome,
    CreateWorkspaceOwnerInput, CreateWorkspaceScopeInput, CreateWorkspaceServiceError,
    WorkspaceCreationService,
};

const PUBLIC_CREATE_NAMESPACE: Uuid = Uuid::from_u128(0x5eef_a128_9d3f_4cd4_b537_b51a_6aa1_31d2);
const DEFAULT_SANDBOX_ROOT: &str = "/workspace";

/// Legacy Workspace scenario selected by the public request.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkspaceUseCase {
    General,
    Programming,
    Conversation,
    Research,
    Operations,
}

impl WorkspaceUseCase {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::General => "general",
            Self::Programming => "programming",
            Self::Conversation => "conversation",
            Self::Research => "research",
            Self::Operations => "operations",
        }
    }
}

/// Legacy collaboration mode selected by the public request.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkspaceCollaborationMode {
    SingleAgent,
    MultiAgentShared,
    MultiAgentIsolated,
    Autonomous,
}

impl WorkspaceCollaborationMode {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::SingleAgent => "single_agent",
            Self::MultiAgentShared => "multi_agent_shared",
            Self::MultiAgentIsolated => "multi_agent_isolated",
            Self::Autonomous => "autonomous",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum WorkspaceType {
    General,
    SoftwareDevelopment,
    Research,
    Operations,
}

impl WorkspaceType {
    #[must_use]
    const fn as_str(self) -> &'static str {
        match self {
            Self::General => "general",
            Self::SoftwareDevelopment => "software_development",
            Self::Research => "research",
            Self::Operations => "operations",
        }
    }
}

/// Authenticated primitive input accepted by the public compatibility use case.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicCreateWorkspaceInput {
    pub tenant_id: String,
    pub project_id: String,
    pub user_id: String,
    pub owner_email: String,
    pub name: String,
    pub description: Option<String>,
    pub metadata: Value,
    pub use_case: Option<WorkspaceUseCase>,
    pub collaboration_mode: Option<WorkspaceCollaborationMode>,
    pub autonomy_profile: Option<Value>,
    pub sandbox_code_root: Option<String>,
    pub idempotency_key: Option<String>,
}

/// Public creation failed before or during the atomic Workspace command.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceCreationError {
    #[error("invalid legacy Workspace metadata: {0}")]
    InvalidMetadata(&'static str),

    #[error(transparent)]
    Create(#[from] CreateWorkspaceServiceError),
}

/// Legacy public Create adapter over the shared atomic application service.
pub struct PublicWorkspaceCreationService<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> PublicWorkspaceCreationService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Generate compatible IDs, compose legacy metadata, and execute the
    /// shared atomic Create Workspace command.
    ///
    /// An explicit idempotency key deterministically derives the generated IDs
    /// so a transport retry addresses the same mutation receipt. Old clients
    /// may omit the header; those calls receive fresh UUIDv4 identifiers and an
    /// internal per-Workspace intent key.
    ///
    /// # Errors
    ///
    /// Returns a metadata validation error or a structured application error.
    pub async fn create(
        &self,
        input: &PublicCreateWorkspaceInput,
    ) -> Result<CreateWorkspaceOutcome, PublicWorkspaceCreationError> {
        self.create_inner(input, false).await
    }

    /// Create a public Workspace and atomically enqueue autonomous root
    /// bootstrap when the resolved collaboration mode is autonomous.
    ///
    /// # Errors
    ///
    /// Returns the same structured errors as [`Self::create`].
    pub async fn create_with_autonomy_bootstrap(
        &self,
        input: &PublicCreateWorkspaceInput,
    ) -> Result<CreateWorkspaceOutcome, PublicWorkspaceCreationError> {
        self.create_inner(input, true).await
    }

    async fn create_inner(
        &self,
        input: &PublicCreateWorkspaceInput,
        enqueue_autonomy_bootstrap: bool,
    ) -> Result<CreateWorkspaceOutcome, PublicWorkspaceCreationError> {
        let identifiers = creation_identifiers(input);
        let metadata = compose_workspace_metadata(input)?;
        let is_autonomous =
            metadata.get("collaboration_mode").and_then(Value::as_str) == Some("autonomous");
        let command = CreateWorkspaceInput {
            scope: CreateWorkspaceScopeInput {
                tenant_id: input.tenant_id.clone(),
                project_id: input.project_id.clone(),
                workspace_id: identifiers.workspace_id,
                group_id: identifiers.group_id,
            },
            owner: CreateWorkspaceOwnerInput {
                member_id: identifiers.owner_member_id,
                user_id: input.user_id.clone(),
                // The legacy public route always requires Project membership,
                // including for a globally privileged user. Internal service
                // calls retain the explicit superuser bypass.
                is_superuser: false,
            },
            content: CreateWorkspaceContentInput {
                name: input.name.clone(),
                description: input.description.clone(),
                metadata,
            },
            idempotency_key: identifiers.idempotency_key,
        };
        let creation = WorkspaceCreationService::new(self.db, self.flavor);
        if enqueue_autonomy_bootstrap && is_autonomous {
            creation
                .create_with_owner_identity_and_autonomy_bootstrap(
                    &command,
                    input.owner_email.as_str(),
                )
                .await
                .map_err(PublicWorkspaceCreationError::Create)
        } else {
            creation
                .create_with_owner_identity(&command, input.owner_email.as_str())
                .await
                .map_err(PublicWorkspaceCreationError::Create)
        }
    }
}

struct CreationIdentifiers {
    workspace_id: String,
    group_id: String,
    owner_member_id: String,
    idempotency_key: String,
}

fn creation_identifiers(input: &PublicCreateWorkspaceInput) -> CreationIdentifiers {
    let (workspace_id, idempotency_key) = if let Some(idempotency_key) = &input.idempotency_key {
        let mut material = Vec::new();
        for part in [
            input.tenant_id.as_str(),
            input.project_id.as_str(),
            input.user_id.as_str(),
            idempotency_key.as_str(),
        ] {
            let part_len = u64::try_from(part.len()).map_or(u64::MAX, |length| length);
            material.extend_from_slice(&part_len.to_be_bytes());
            material.extend_from_slice(part.as_bytes());
        }
        (
            Uuid::new_v5(&PUBLIC_CREATE_NAMESPACE, &material).to_string(),
            idempotency_key.clone(),
        )
    } else {
        let workspace_id = Uuid::new_v4().to_string();
        let idempotency_key = format!("legacy-create:{workspace_id}");
        (workspace_id, idempotency_key)
    };
    let owner_member_id = Uuid::new_v5(
        &PUBLIC_CREATE_NAMESPACE,
        format!("owner:{workspace_id}:{}", input.user_id).as_bytes(),
    )
    .to_string();
    CreationIdentifiers {
        group_id: format!("group-{workspace_id}"),
        workspace_id,
        owner_member_id,
        idempotency_key,
    }
}

fn compose_workspace_metadata(
    input: &PublicCreateWorkspaceInput,
) -> Result<Value, PublicWorkspaceCreationError> {
    let Some(mut metadata) = input.metadata.as_object().cloned() else {
        return Err(PublicWorkspaceCreationError::InvalidMetadata(
            "metadata must be an object",
        ));
    };
    let use_case = resolve_use_case(input.use_case, &metadata);
    let workspace_type = workspace_type_for_use_case(use_case);
    let collaboration_mode = resolve_collaboration_mode(input.collaboration_mode, &metadata);

    let mut profile = object_value(metadata.get("autonomy_profile"));
    if let Some(explicit_profile) = &input.autonomy_profile {
        let Some(explicit_profile) = explicit_profile.as_object() else {
            return Err(PublicWorkspaceCreationError::InvalidMetadata(
                "autonomy_profile must be an object",
            ));
        };
        profile.extend(explicit_profile.clone());
    }
    profile.insert(
        "workspace_type".to_string(),
        Value::String(workspace_type.as_str().to_string()),
    );

    metadata.insert(
        "workspace_use_case".to_string(),
        Value::String(use_case.as_str().to_string()),
    );
    metadata.insert(
        "workspace_type".to_string(),
        Value::String(workspace_type.as_str().to_string()),
    );
    metadata.insert(
        "collaboration_mode".to_string(),
        Value::String(collaboration_mode.as_str().to_string()),
    );
    metadata.insert(
        "agent_conversation_mode".to_string(),
        Value::String(collaboration_mode.as_str().to_string()),
    );
    metadata.insert("autonomy_profile".to_string(), Value::Object(profile));

    let sandbox_candidate = match input.sandbox_code_root.as_deref() {
        Some("") | None => metadata.get("sandbox_code_root").and_then(Value::as_str),
        value => value,
    };
    if let Some(sandbox_code_root) = sandbox_candidate.and_then(normalize_sandbox_code_root) {
        let mut code_context = object_value(metadata.get("code_context"));
        code_context.insert(
            "sandbox_code_root".to_string(),
            Value::String(sandbox_code_root.clone()),
        );
        metadata.insert(
            "sandbox_code_root".to_string(),
            Value::String(sandbox_code_root),
        );
        metadata.insert("code_context".to_string(), Value::Object(code_context));
    }

    if workspace_type == WorkspaceType::SoftwareDevelopment {
        let sandbox_code_root = resolve_sandbox_code_root(&metadata);
        if !sandbox_code_root
            .is_some_and(|path| path != DEFAULT_SANDBOX_ROOT && path.starts_with("/workspace/"))
        {
            return Err(PublicWorkspaceCreationError::InvalidMetadata(
                "software development requires an isolated sandbox code root",
            ));
        }
    }
    Ok(Value::Object(metadata))
}

fn resolve_use_case(
    explicit: Option<WorkspaceUseCase>,
    metadata: &Map<String, Value>,
) -> WorkspaceUseCase {
    if let Some(explicit) = explicit {
        return explicit;
    }
    let profile = metadata.get("autonomy_profile").and_then(Value::as_object);
    for value in [
        metadata.get("workspace_use_case"),
        metadata.get("use_case"),
        metadata.get("workspace_type"),
        profile.and_then(|profile| profile.get("workspace_type")),
    ]
    .into_iter()
    .flatten()
    {
        if let Some(use_case) = coerce_use_case(value) {
            return use_case;
        }
        if let Some(workspace_type) = coerce_workspace_type(value) {
            return match workspace_type {
                WorkspaceType::SoftwareDevelopment => WorkspaceUseCase::Programming,
                WorkspaceType::Research => WorkspaceUseCase::Research,
                WorkspaceType::Operations => WorkspaceUseCase::Operations,
                WorkspaceType::General => WorkspaceUseCase::General,
            };
        }
    }
    WorkspaceUseCase::General
}

fn coerce_use_case(value: &Value) -> Option<WorkspaceUseCase> {
    match value.as_str()? {
        "general" => Some(WorkspaceUseCase::General),
        "programming" | "software_development" => Some(WorkspaceUseCase::Programming),
        "conversation" => Some(WorkspaceUseCase::Conversation),
        "research" => Some(WorkspaceUseCase::Research),
        "operations" => Some(WorkspaceUseCase::Operations),
        _ => None,
    }
}

fn workspace_type_for_use_case(use_case: WorkspaceUseCase) -> WorkspaceType {
    match use_case {
        WorkspaceUseCase::General | WorkspaceUseCase::Conversation => WorkspaceType::General,
        WorkspaceUseCase::Programming => WorkspaceType::SoftwareDevelopment,
        WorkspaceUseCase::Research => WorkspaceType::Research,
        WorkspaceUseCase::Operations => WorkspaceType::Operations,
    }
}

fn coerce_workspace_type(value: &Value) -> Option<WorkspaceType> {
    match value.as_str()? {
        "general" => Some(WorkspaceType::General),
        "software_development" => Some(WorkspaceType::SoftwareDevelopment),
        "research" => Some(WorkspaceType::Research),
        "operations" => Some(WorkspaceType::Operations),
        _ => None,
    }
}

fn resolve_collaboration_mode(
    explicit: Option<WorkspaceCollaborationMode>,
    metadata: &Map<String, Value>,
) -> WorkspaceCollaborationMode {
    if let Some(explicit) = explicit {
        return explicit;
    }
    for value in [
        metadata.get("collaboration_mode"),
        metadata.get("agent_conversation_mode"),
    ]
    .into_iter()
    .flatten()
    {
        if let Some(mode) = coerce_collaboration_mode(value) {
            return mode;
        }
    }
    WorkspaceCollaborationMode::SingleAgent
}

fn coerce_collaboration_mode(value: &Value) -> Option<WorkspaceCollaborationMode> {
    match value.as_str()? {
        "single_agent" => Some(WorkspaceCollaborationMode::SingleAgent),
        "multi_agent_shared" => Some(WorkspaceCollaborationMode::MultiAgentShared),
        "multi_agent_isolated" => Some(WorkspaceCollaborationMode::MultiAgentIsolated),
        "autonomous" => Some(WorkspaceCollaborationMode::Autonomous),
        _ => None,
    }
}

fn object_value(value: Option<&Value>) -> Map<String, Value> {
    value
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default()
}

fn normalize_sandbox_code_root(value: &str) -> Option<String> {
    let raw = value.trim();
    if raw.is_empty() {
        return None;
    }
    if raw.starts_with("//") && !raw.starts_with("///") {
        return None;
    }
    let absolute = if raw.starts_with('/') {
        raw.to_string()
    } else {
        format!("{DEFAULT_SANDBOX_ROOT}/{raw}")
    };
    let mut segments = Vec::new();
    for segment in absolute.split('/') {
        match segment {
            "" | "." => {}
            ".." => {
                segments.pop();
            }
            segment => segments.push(segment),
        }
    }
    let normalized = format!("/{}", segments.join("/"));
    (normalized == DEFAULT_SANDBOX_ROOT || normalized.starts_with("/workspace/"))
        .then_some(normalized)
}

fn resolve_sandbox_code_root(metadata: &Map<String, Value>) -> Option<String> {
    let code_context = metadata.get("code_context").and_then(Value::as_object);
    for value in [
        metadata.get("sandbox_code_root"),
        code_context.and_then(|context| context.get("sandbox_code_root")),
    ]
    .into_iter()
    .flatten()
    {
        if let Some(normalized) = value.as_str().and_then(normalize_sandbox_code_root) {
            return Some(normalized);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn input() -> PublicCreateWorkspaceInput {
        PublicCreateWorkspaceInput {
            tenant_id: "tenant-1".to_string(),
            project_id: "project-1".to_string(),
            user_id: "user-1".to_string(),
            owner_email: "user-1@example.com".to_string(),
            name: "Workspace".to_string(),
            description: None,
            metadata: json!({}),
            use_case: None,
            collaboration_mode: None,
            autonomy_profile: None,
            sandbox_code_root: None,
            idempotency_key: None,
        }
    }

    #[test]
    fn explicit_idempotency_derives_stable_generated_ids() {
        let mut first = input();
        first.idempotency_key = Some("intent-1".to_string());
        let second = first.clone();

        let first = creation_identifiers(&first);
        let second = creation_identifiers(&second);

        assert_eq!(first.workspace_id, second.workspace_id);
        assert_eq!(first.owner_member_id, second.owner_member_id);
        assert_eq!(first.group_id, second.group_id);
    }

    #[test]
    fn programming_metadata_requires_an_isolated_normalized_root() {
        let mut request = input();
        request.use_case = Some(WorkspaceUseCase::Programming);
        request.sandbox_code_root = Some("../escape".to_string());
        assert!(compose_workspace_metadata(&request).is_err());

        request.sandbox_code_root = Some("repo/./src/..".to_string());
        let metadata = compose_workspace_metadata(&request);
        assert!(matches!(
            metadata,
            Ok(value) if value["sandbox_code_root"] == "/workspace/repo"
        ));
    }
}
