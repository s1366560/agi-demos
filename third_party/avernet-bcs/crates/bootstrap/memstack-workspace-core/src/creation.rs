//! Authenticated internal HTTP adapter for first-time Workspace creation.

use std::sync::Arc;

use axum::extract::Path;
use axum::extract::rejection::JsonRejection;
use axum::http::{HeaderMap, StatusCode};
use axum::{Extension, Json};
use memstack_workspace_service::{
    CreateWorkspaceContentInput, CreateWorkspaceErrorKind, CreateWorkspaceInput,
    CreateWorkspaceOwnerInput, CreateWorkspaceScopeInput, CreateWorkspaceServiceError,
    PublicCreateWorkspaceInput, PublicWorkspaceCreationError, PublicWorkspaceCreationService,
    WorkspaceCollaborationMode, WorkspaceCreationService, WorkspaceUseCase,
};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};

use super::public_api::caller_from_headers;
use super::{ApiError, WorkspaceCoreState, required_header};

const IDEMPOTENCY_HEADER: &str = "x-idempotency-key";
const PUBLIC_IDEMPOTENCY_HEADER: &str = "idempotency-key";
const USER_EMAIL_HEADER: &str = "x-memstack-user-email";
const PROJECT_MEMBERSHIP_ROLE_HEADER: &str = "x-memstack-project-membership-role";
const WORKSPACE_NAME_MAX_CHARS: usize = 255;

#[derive(Debug, Deserialize)]
pub(super) struct InternalCreateWorkspaceRequest {
    workspace_id: String,
    group_id: String,
    owner_member_id: String,
    name: String,
    description: Option<String>,
    #[serde(default = "empty_metadata")]
    metadata: Value,
}

#[derive(Debug, Serialize)]
pub(super) struct InternalCreateWorkspaceResponse {
    receipt_id: String,
    committed_revision: u64,
    replayed: bool,
    workspace: Value,
}

pub(super) async fn create_workspace(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id)): Path<(String, String)>,
    headers: HeaderMap,
    Json(request): Json<InternalCreateWorkspaceRequest>,
) -> Result<(StatusCode, Json<InternalCreateWorkspaceResponse>), ApiError> {
    let caller = caller_from_headers(&headers)?;
    let idempotency_key = required_header(&headers, IDEMPOTENCY_HEADER)?;
    let input = CreateWorkspaceInput {
        scope: CreateWorkspaceScopeInput {
            tenant_id,
            project_id,
            workspace_id: request.workspace_id,
            group_id: request.group_id,
        },
        owner: CreateWorkspaceOwnerInput {
            member_id: request.owner_member_id,
            user_id: caller.user_id,
            is_superuser: caller.is_superuser,
        },
        content: CreateWorkspaceContentInput {
            name: request.name,
            description: request.description,
            metadata: request.metadata,
        },
        idempotency_key,
    };
    let outcome = WorkspaceCreationService::new(state.db.as_ref(), state.sql_flavor)
        .create(&input)
        .await
        .map_err(map_service_error)?;
    Ok((
        StatusCode::CREATED,
        Json(InternalCreateWorkspaceResponse {
            receipt_id: outcome.receipt_id,
            committed_revision: outcome.committed_revision,
            replayed: outcome.replayed,
            workspace: outcome.response,
        }),
    ))
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PublicAutonomyProfile {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    debug: Option<Map<String, Value>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    workspace_type: Option<PublicWorkspaceType>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    completion_policy: Option<PublicCompletionPolicy>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PublicCompletionPolicy {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    debug: Option<Map<String, Value>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    allow_internal_task_artifacts: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    required_artifact_prefixes: Option<Vec<String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    requires_external_artifact: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    minimum_verification_grade: Option<PublicVerificationGrade>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum PublicWorkspaceType {
    General,
    SoftwareDevelopment,
    Research,
    Operations,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum PublicVerificationGrade {
    Pass,
    Warn,
    Fail,
}

pub(super) async fn create_public_workspace(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id)): Path<(String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<(StatusCode, Json<Value>), ApiError> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let caller = caller_from_headers(&headers)?;
    let owner_email = required_header(&headers, USER_EMAIL_HEADER)?;
    let owner_email = owner_email.trim();
    if owner_email.is_empty() {
        return Err(ApiError::InvalidRequest(format!(
            "invalid {USER_EMAIL_HEADER} header"
        )));
    }
    // Mirror the caller's project membership whenever the trusted proxy
    // vouches for a role. Local (desktop) callers must always send the
    // header; cloud callers are mirrored only when it is present, keeping
    // the fail-closed behaviour for unvouched requests.
    if state.authority == super::WorkspaceCoreAuthority::Local
        || headers.contains_key(PROJECT_MEMBERSHIP_ROLE_HEADER)
    {
        mirror_local_project_principal(
            state.as_ref(),
            tenant_id.as_str(),
            project_id.as_str(),
            caller.user_id.as_str(),
            &headers,
        )
        .await?;
    }
    let input = parse_public_create_request(
        tenant_id,
        project_id,
        caller.user_id,
        owner_email.to_string(),
        optional_header(&headers, PUBLIC_IDEMPOTENCY_HEADER)?,
        request,
    )?;
    let creation = PublicWorkspaceCreationService::new(state.db.as_ref(), state.sql_flavor);
    let outcome = if state.authority == super::WorkspaceCoreAuthority::Local {
        creation.create_with_autonomy_bootstrap(&input).await
    } else {
        creation.create(&input).await
    }
    .map_err(map_public_service_error)?;
    Ok((StatusCode::CREATED, Json(outcome.response)))
}

pub(super) async fn mirror_local_project_principal(
    state: &WorkspaceCoreState,
    tenant_id: &str,
    project_id: &str,
    user_id: &str,
    headers: &HeaderMap,
) -> Result<(), ApiError> {
    let role = required_header(headers, PROJECT_MEMBERSHIP_ROLE_HEADER)?;
    let role = role.trim();
    if !matches!(role, "owner" | "admin" | "editor" | "member" | "viewer") {
        return Err(ApiError::InvalidRequest(format!(
            "invalid {PROJECT_MEMBERSHIP_ROLE_HEADER} header"
        )));
    }
    let source_material = format!("{tenant_id}\0{project_id}\0{user_id}");
    let identity_authority = match state.authority {
        super::WorkspaceCoreAuthority::Local => "desktop-sidecar",
        super::WorkspaceCoreAuthority::Cloud => "memstack",
    };
    let source_membership_id = format!(
        "{identity_authority}:{}",
        hex::encode(Sha256::digest(source_material.as_bytes()))
    );
    let statement = bcs_db_api::DbStatementBuilder::new(state.sql_flavor)
        .push_static(
            "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, \
             participant_actor_id, source_membership_id, role, permissions_json, is_active, \
             identity_authority, source_created_at, source_updated_at) VALUES (",
        )
        .bind(tenant_id)
        .push_static(", ")
        .bind(project_id)
        .push_static(", ")
        .bind(user_id)
        .push_static(", ")
        .bind(user_id)
        .push_static(", ")
        .bind(source_membership_id)
        .push_static(", ")
        .bind(role)
        .push_static(", '{}', ")
        .bind(true)
        .push_static(", ")
        .bind(identity_authority)
        .push_static(
            ", CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) \
                      ON CONFLICT (tenant_id, project_id, user_id) DO UPDATE SET \
                      participant_actor_id = excluded.participant_actor_id, \
                      source_membership_id = excluded.source_membership_id, \
                      role = excluded.role, permissions_json = excluded.permissions_json, \
                      is_active = excluded.is_active, \
                      identity_authority = excluded.identity_authority, \
                      source_updated_at = CURRENT_TIMESTAMP",
        )
        .build();
    state
        .db
        .execute(statement)
        .await
        .map_err(ApiError::Database)?;
    Ok(())
}

pub(super) fn map_public_json_rejection(_error: JsonRejection) -> ApiError {
    ApiError::Validation(json!([{
        "type": "json_invalid",
        "loc": ["body", 0],
        "msg": "JSON decode error",
        "input": {},
        "ctx": {"error": "Invalid JSON"},
    }]))
}

fn parse_public_create_request(
    tenant_id: String,
    project_id: String,
    user_id: String,
    owner_email: String,
    idempotency_key: Option<String>,
    request: Value,
) -> Result<PublicCreateWorkspaceInput, ApiError> {
    let Some(fields) = request.as_object() else {
        return Err(body_validation_error(
            "model_attributes_type",
            None,
            "Input should be a valid dictionary or object to extract fields from",
            request,
            None,
        ));
    };
    let name_value = fields.get("name").ok_or_else(|| {
        body_validation_error(
            "missing",
            Some("name"),
            "Field required",
            request.clone(),
            None,
        )
    })?;
    let name = name_value.as_str().ok_or_else(|| {
        body_validation_error(
            "string_type",
            Some("name"),
            "Input should be a valid string",
            name_value.clone(),
            None,
        )
    })?;
    let name_chars = name.chars().count();
    if name_chars == 0 {
        return Err(body_validation_error(
            "string_too_short",
            Some("name"),
            "String should have at least 1 character",
            name_value.clone(),
            Some(json!({"min_length": 1})),
        ));
    }
    if name_chars > WORKSPACE_NAME_MAX_CHARS {
        return Err(body_validation_error(
            "string_too_long",
            Some("name"),
            "String should have at most 255 characters",
            name_value.clone(),
            Some(json!({"max_length": WORKSPACE_NAME_MAX_CHARS})),
        ));
    }

    let description = optional_string_field(fields, "description")?;
    let sandbox_code_root = optional_string_field(fields, "sandbox_code_root")?;
    let metadata = match fields.get("metadata") {
        None => json!({}),
        Some(value) if value.is_object() => value.clone(),
        Some(value) => {
            return Err(body_validation_error(
                "dict_type",
                Some("metadata"),
                "Input should be a valid dictionary",
                value.clone(),
                None,
            ));
        }
    };
    let use_case = parse_use_case(fields.get("use_case"))?;
    let collaboration_mode = parse_collaboration_mode(fields.get("collaboration_mode"))?;
    let autonomy_profile = parse_autonomy_profile(fields.get("autonomy_profile"))?;

    Ok(PublicCreateWorkspaceInput {
        tenant_id,
        project_id,
        user_id,
        owner_email,
        name: name.to_string(),
        description,
        metadata,
        use_case,
        collaboration_mode,
        autonomy_profile,
        sandbox_code_root,
        idempotency_key,
    })
}

pub(super) fn optional_string_field(
    fields: &Map<String, Value>,
    field: &'static str,
) -> Result<Option<String>, ApiError> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => Ok(Some(value.clone())),
        Some(value) => Err(body_validation_error(
            "string_type",
            Some(field),
            "Input should be a valid string",
            value.clone(),
            None,
        )),
    }
}

fn parse_use_case(value: Option<&Value>) -> Result<Option<WorkspaceUseCase>, ApiError> {
    let Some(value) = value else {
        return Ok(None);
    };
    if value.is_null() {
        return Ok(None);
    }
    let parsed = match value.as_str() {
        Some("general") => Some(WorkspaceUseCase::General),
        Some("programming") => Some(WorkspaceUseCase::Programming),
        Some("conversation") => Some(WorkspaceUseCase::Conversation),
        Some("research") => Some(WorkspaceUseCase::Research),
        Some("operations") => Some(WorkspaceUseCase::Operations),
        _ => None,
    };
    parsed.map(Some).ok_or_else(|| {
        body_validation_error(
            "literal_error",
            Some("use_case"),
            "Input should be 'general', 'programming', 'conversation', 'research' or 'operations'",
            value.clone(),
            Some(json!({
                "expected": "'general', 'programming', 'conversation', 'research' or 'operations'"
            })),
        )
    })
}

fn parse_collaboration_mode(
    value: Option<&Value>,
) -> Result<Option<WorkspaceCollaborationMode>, ApiError> {
    let Some(value) = value else {
        return Ok(None);
    };
    if value.is_null() {
        return Ok(None);
    }
    let parsed = match value.as_str() {
        Some("single_agent") => Some(WorkspaceCollaborationMode::SingleAgent),
        Some("multi_agent_shared") => Some(WorkspaceCollaborationMode::MultiAgentShared),
        Some("multi_agent_isolated") => Some(WorkspaceCollaborationMode::MultiAgentIsolated),
        Some("autonomous") => Some(WorkspaceCollaborationMode::Autonomous),
        _ => None,
    };
    parsed.map(Some).ok_or_else(|| {
        body_validation_error(
            "literal_error",
            Some("collaboration_mode"),
            "Input should be 'single_agent', 'multi_agent_shared', 'multi_agent_isolated' or 'autonomous'",
            value.clone(),
            Some(json!({
                "expected": "'single_agent', 'multi_agent_shared', 'multi_agent_isolated' or 'autonomous'"
            })),
        )
    })
}

fn parse_autonomy_profile(value: Option<&Value>) -> Result<Option<Value>, ApiError> {
    let Some(value) = value else {
        return Ok(None);
    };
    if value.is_null() {
        return Ok(None);
    }
    let profile = serde_json::from_value::<PublicAutonomyProfile>(value.clone()).map_err(|_| {
        body_validation_error(
            "value_error",
            Some("autonomy_profile"),
            "Value error, invalid autonomy profile",
            value.clone(),
            None,
        )
    })?;
    serde_json::to_value(profile)
        .map(Some)
        .map_err(ApiError::Json)
}

pub(super) fn body_validation_error(
    error_type: &'static str,
    field: Option<&'static str>,
    message: &str,
    input: Value,
    context: Option<Value>,
) -> ApiError {
    let mut location = vec![Value::String("body".to_string())];
    if let Some(field) = field {
        location.push(Value::String(field.to_string()));
    }
    let mut detail = json!({
        "type": error_type,
        "loc": location,
        "msg": message,
        "input": input,
    });
    if let Some(context) = context {
        detail["ctx"] = context;
    }
    ApiError::Validation(json!([detail]))
}

pub(super) fn optional_header(
    headers: &HeaderMap,
    name: &'static str,
) -> Result<Option<String>, ApiError> {
    headers
        .get(name)
        .map(|value| {
            value
                .to_str()
                .map(str::to_string)
                .map_err(|_| ApiError::InvalidRequest(format!("invalid {name} header")))
        })
        .transpose()
}

fn empty_metadata() -> Value {
    json!({})
}

fn map_service_error(error: CreateWorkspaceServiceError) -> ApiError {
    let kind = error.kind();
    let detail = error.to_string();
    match kind {
        CreateWorkspaceErrorKind::Validation => ApiError::Validation(json!([{
            "type": "value_error",
            "loc": ["body"],
            "msg": detail,
        }])),
        CreateWorkspaceErrorKind::Forbidden => ApiError::Forbidden("Access denied to project"),
        CreateWorkspaceErrorKind::Conflict => ApiError::Conflict(detail),
        CreateWorkspaceErrorKind::Unavailable => ApiError::InvalidDatabase(detail),
    }
}

fn map_public_service_error(error: PublicWorkspaceCreationError) -> ApiError {
    let PublicWorkspaceCreationError::Create(service_error) = error else {
        return ApiError::InvalidRequest("Invalid workspace request".to_string());
    };
    match service_error.kind() {
        CreateWorkspaceErrorKind::Validation => {
            ApiError::InvalidRequest("Invalid workspace request".to_string())
        }
        CreateWorkspaceErrorKind::Forbidden => ApiError::Forbidden("Access denied"),
        CreateWorkspaceErrorKind::Conflict => {
            ApiError::Conflict("Workspace already exists".to_string())
        }
        CreateWorkspaceErrorKind::Unavailable => {
            ApiError::InvalidDatabase(service_error.to_string())
        }
    }
}
