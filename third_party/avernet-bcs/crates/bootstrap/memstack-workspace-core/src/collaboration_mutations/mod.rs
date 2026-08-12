//! Canonical Collaboration mutation façade over the typed Workspace use cases.

#![allow(clippy::result_large_err)]

mod dispatch_primary;
mod dispatch_secondary;
mod models;
mod upload;

use std::fmt::Display;
use std::sync::Arc;

use axum::extract::rejection::JsonRejection;
use axum::extract::{DefaultBodyLimit, Path};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use axum::{Extension, Json, Router};
use bcs_db_api::DbStatementBuilder;
use memstack_workspace_service::{
    PublicWorkspaceBlackboardContext, PublicWorkspaceFileContext, PublicWorkspaceGeneContext,
    PublicWorkspaceMutationContext, PublicWorkspaceObjectiveContext, PublicWorkspaceTaskContext,
    PublicWorkspaceTopologyContext, WorkspaceMutationAuthority,
};
use serde::Serialize;
use serde::de::DeserializeOwned;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use self::models::{MutationAction, MutationRequest};
use super::public_api::{
    caller_from_headers, read_authority_revision, require_scoped_workspace_access,
};
use super::{ApiError, WorkspaceCoreState};

const CONTRACT_VERSION: &str = "2.0.0";
const EXPECTED_REVISION_HEADER: &str = "x-expected-revision";
const IDEMPOTENCY_HEADER: &str = "idempotency-key";
const USER_EMAIL_HEADER: &str = "x-memstack-user-email";
const ACTOR_TYPE_HEADER: &str = "x-memstack-actor-type";
const ACTOR_ID_HEADER: &str = "x-memstack-actor-id";
const MAX_COMMAND_BYTES: usize = 1024 * 1024;
const MAX_MULTIPART_BODY_SIZE: usize = 102 * 1024 * 1024;

pub(super) fn router() -> Router {
    Router::new()
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/collaboration/mutations",
            post(mutate_workspace_collaboration_surface),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/collaboration/mutations/files/upload",
            post(upload::upload_workspace_collaboration_file),
        )
        .layer(DefaultBodyLimit::max(MAX_MULTIPART_BODY_SIZE))
}

#[derive(Debug, Clone)]
pub(super) struct CommandContext {
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    user_id: String,
    is_superuser: bool,
    surface: String,
    action_name: String,
    action: MutationAction,
    expected_revision: u64,
    idempotency_key: String,
    request_hash: String,
}

impl CommandContext {
    fn receipt_authority(&self) -> Result<WorkspaceMutationAuthority, Response> {
        WorkspaceMutationAuthority::parse(
            CONTRACT_VERSION,
            self.surface.clone(),
            self.action_name.clone(),
            self.request_hash.clone(),
        )
        .map_err(|_| invalid_payload())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct AuthorityFacts {
    pub revision: u64,
    pub duplicate: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum FailureKind {
    InvalidRequest,
    NotFound,
    Forbidden,
    Conflict,
    Unavailable,
}

#[derive(Debug, Serialize)]
pub(super) struct MutationReceiptResponse {
    contract_version: &'static str,
    receipt_id: String,
    workspace_id: String,
    surface: String,
    action: String,
    revision: u64,
    duplicate: bool,
}

async fn mutate_workspace_collaboration_surface(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    headers: HeaderMap,
    request: Result<Json<MutationRequest>, JsonRejection>,
) -> Result<Json<MutationReceiptResponse>, Response> {
    let Json(request) = request.map_err(|_| invalid_payload())?;
    let command = command_context(
        &state,
        tenant_id,
        project_id,
        workspace_id,
        &headers,
        &request,
    )
    .await?;
    if command.action == MutationAction::UploadFile {
        return Err(error_response(
            StatusCode::UNPROCESSABLE_ENTITY,
            "workspace_collaboration_payload_invalid",
            "Invalid Workspace Collaboration mutation",
            None,
        ));
    }
    let facts = match command.action {
        MutationAction::CreateObjective
        | MutationAction::UpdateObjective
        | MutationAction::DeleteObjective
        | MutationAction::ProjectObjectiveToTask
        | MutationAction::CreateTask
        | MutationAction::UpdateTask
        | MutationAction::DeleteTask
        | MutationAction::AssignTaskAgent
        | MutationAction::UnassignTaskAgent
        | MutationAction::ApplyTaskRecoveryAction
        | MutationAction::CreatePost
        | MutationAction::UpdatePost
        | MutationAction::DeletePost
        | MutationAction::PinPost
        | MutationAction::UnpinPost
        | MutationAction::CreateReply
        | MutationAction::UpdateReply
        | MutationAction::DeleteReply => {
            dispatch_primary::dispatch(&state, &command, request.payload).await?
        }
        MutationAction::BindAgent
        | MutationAction::UpdateAgentBinding
        | MutationAction::UnbindAgent
        | MutationAction::AddMember
        | MutationAction::UpdateMemberRole
        | MutationAction::RemoveMember
        | MutationAction::CreateGene
        | MutationAction::UpdateGene
        | MutationAction::DeleteGene
        | MutationAction::CreateDirectory
        | MutationAction::UpdateFile
        | MutationAction::DeleteFile
        | MutationAction::CopyFile
        | MutationAction::CreateNode
        | MutationAction::UpdateNode
        | MutationAction::DeleteNode
        | MutationAction::CreateEdge
        | MutationAction::UpdateEdge
        | MutationAction::DeleteEdge
        | MutationAction::UpdateWorkspace => {
            dispatch_secondary::dispatch(&state, &command, &headers, request.payload).await?
        }
        MutationAction::UploadFile => unreachable!("upload actions are rejected above"),
    };
    Ok(Json(receipt(&state, &command, facts).await?))
}

async fn command_context(
    state: &WorkspaceCoreState,
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    headers: &HeaderMap,
    request: &MutationRequest,
) -> Result<CommandContext, Response> {
    if request.contract_version != CONTRACT_VERSION {
        return Err(invalid_payload());
    }
    let action = MutationAction::parse(request.surface.as_str(), request.action.as_str())
        .ok_or_else(invalid_payload)?;
    validate_idempotency_key(request.idempotency_key.as_str())?;
    let header_revision = required_revision(headers)?;
    let header_key = required_header(headers, IDEMPOTENCY_HEADER)?;
    if header_revision != request.expected_revision || header_key != request.idempotency_key {
        return Err(error_response(
            StatusCode::UNPROCESSABLE_ENTITY,
            "workspace_collaboration_authority_header_mismatch",
            "Invalid Workspace Collaboration mutation",
            None,
        ));
    }
    let canonical = canonical_command(request, &tenant_id, &project_id, &workspace_id)?;
    if !request.payload.is_object() || canonical.len() > MAX_COMMAND_BYTES {
        return Err(invalid_payload());
    }
    let request_hash = hex::encode(Sha256::digest(canonical));
    let caller = caller_from_headers(headers).map_err(IntoResponse::into_response)?;
    require_scoped_workspace_access(
        state,
        tenant_id.as_str(),
        project_id.as_str(),
        workspace_id.as_str(),
        &caller,
        true,
        "Workspace access required",
    )
    .await
    .map_err(collaboration_access_error)?;
    Ok(CommandContext {
        tenant_id,
        project_id,
        workspace_id,
        user_id: caller.user_id,
        is_superuser: caller.is_superuser,
        surface: request.surface.clone(),
        action_name: request.action.clone(),
        action,
        expected_revision: request.expected_revision,
        idempotency_key: request.idempotency_key.clone(),
        request_hash,
    })
}

pub(super) async fn resolve_service_result<T, E>(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    result: Result<T, E>,
    classify: impl FnOnce(&E) -> FailureKind,
) -> Result<T, Response>
where
    E: Display,
{
    let error = match result {
        Ok(value) => return Ok(value),
        Err(error) => error,
    };
    match classify(&error) {
        FailureKind::InvalidRequest => Err(invalid_payload()),
        FailureKind::NotFound => Err(error_response(
            StatusCode::NOT_FOUND,
            "workspace_collaboration_scope_mismatch",
            "Workspace Collaboration mutation rejected",
            None,
        )),
        FailureKind::Forbidden => Err(error_response(
            StatusCode::FORBIDDEN,
            "workspace_collaboration_access_denied",
            "Workspace Collaboration mutation rejected",
            None,
        )),
        FailureKind::Conflict => {
            if let Some(stored_hash) = read_receipt_hash(state, command).await? {
                if stored_hash != command.request_hash {
                    return Err(error_response(
                        StatusCode::CONFLICT,
                        "workspace_collaboration_idempotency_conflict",
                        "Workspace Collaboration mutation rejected",
                        None,
                    ));
                }
                tracing::error!(
                    workspace_id = %command.workspace_id,
                    "Workspace Collaboration matching receipt could not be replayed"
                );
                return Err(authority_unavailable());
            }
            let current = read_authority_revision(
                state,
                command.tenant_id.as_str(),
                command.project_id.as_str(),
                command.workspace_id.as_str(),
            )
            .await
            .map_err(IntoResponse::into_response)?
            .unwrap_or(0);
            if current != command.expected_revision {
                Err(error_response(
                    StatusCode::CONFLICT,
                    "workspace_collaboration_revision_conflict",
                    "Workspace Collaboration mutation rejected",
                    Some(json!({
                        "expected_revision": command.expected_revision,
                        "current_revision": current,
                    })),
                ))
            } else {
                Err(error_response(
                    StatusCode::CONFLICT,
                    "workspace_collaboration_idempotency_conflict",
                    "Workspace Collaboration mutation rejected",
                    None,
                ))
            }
        }
        FailureKind::Unavailable => {
            tracing::error!(error = %error, "Workspace Collaboration mutation failed");
            Err(error_response(
                StatusCode::SERVICE_UNAVAILABLE,
                "workspace_collaboration_authority_unavailable",
                "Workspace Collaboration mutation rejected",
                None,
            ))
        }
    }
}

async fn read_receipt_hash(
    state: &WorkspaceCoreState,
    command: &CommandContext,
) -> Result<Option<String>, Response> {
    let statement = DbStatementBuilder::new(state.sql_flavor)
        .push_static("SELECT request_hash FROM workspace_mutation_receipts WHERE tenant_id = ")
        .bind(command.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(command.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(command.workspace_id.as_str())
        .push_static(" AND actor_id = ")
        .bind(command.user_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(command.idempotency_key.as_str())
        .build();
    let rows = state.db.query(statement).await.map_err(|error| {
        tracing::error!(error = %error, "Workspace Collaboration receipt conflict lookup failed");
        authority_unavailable()
    })?;
    rows.first()
        .map(|row| {
            row.get_string("request_hash")
                .map_err(|_| authority_unavailable())?
                .ok_or_else(authority_unavailable)
        })
        .transpose()
}

pub(super) fn parse_payload<T: DeserializeOwned>(payload: Value) -> Result<T, Response> {
    serde_json::from_value(payload).map_err(|_| invalid_payload())
}

pub(super) fn mutation_context(command: &CommandContext) -> PublicWorkspaceMutationContext {
    PublicWorkspaceMutationContext {
        tenant_id: command.tenant_id.clone(),
        project_id: command.project_id.clone(),
        workspace_id: command.workspace_id.clone(),
        user_id: command.user_id.clone(),
        expected_revision: Some(command.expected_revision),
        idempotency_key: Some(command.idempotency_key.clone()),
    }
}

pub(super) fn task_context(command: &CommandContext) -> PublicWorkspaceTaskContext {
    PublicWorkspaceTaskContext {
        tenant_id: command.tenant_id.clone(),
        project_id: command.project_id.clone(),
        workspace_id: command.workspace_id.clone(),
        user_id: command.user_id.clone(),
        expected_revision: Some(command.expected_revision),
        idempotency_key: Some(command.idempotency_key.clone()),
    }
}

pub(super) fn blackboard_context(command: &CommandContext) -> PublicWorkspaceBlackboardContext {
    PublicWorkspaceBlackboardContext {
        tenant_id: command.tenant_id.clone(),
        project_id: command.project_id.clone(),
        workspace_id: command.workspace_id.clone(),
        user_id: command.user_id.clone(),
        expected_revision: Some(command.expected_revision),
        idempotency_key: Some(command.idempotency_key.clone()),
    }
}

pub(super) fn objective_context(command: &CommandContext) -> PublicWorkspaceObjectiveContext {
    PublicWorkspaceObjectiveContext {
        tenant_id: command.tenant_id.clone(),
        project_id: command.project_id.clone(),
        workspace_id: command.workspace_id.clone(),
        user_id: command.user_id.clone(),
        is_superuser: command.is_superuser,
        expected_revision: Some(command.expected_revision),
        idempotency_key: Some(command.idempotency_key.clone()),
    }
}

pub(super) fn gene_context(command: &CommandContext) -> PublicWorkspaceGeneContext {
    PublicWorkspaceGeneContext {
        tenant_id: command.tenant_id.clone(),
        project_id: command.project_id.clone(),
        workspace_id: command.workspace_id.clone(),
        user_id: command.user_id.clone(),
        is_superuser: command.is_superuser,
        expected_revision: Some(command.expected_revision),
        idempotency_key: Some(command.idempotency_key.clone()),
    }
}

pub(super) fn topology_context(command: &CommandContext) -> PublicWorkspaceTopologyContext {
    PublicWorkspaceTopologyContext {
        tenant_id: command.tenant_id.clone(),
        project_id: command.project_id.clone(),
        workspace_id: command.workspace_id.clone(),
        user_id: command.user_id.clone(),
        expected_revision: Some(command.expected_revision),
        idempotency_key: Some(command.idempotency_key.clone()),
    }
}

pub(super) fn file_context(
    command: &CommandContext,
    headers: &HeaderMap,
) -> Result<PublicWorkspaceFileContext, Response> {
    let user_name =
        optional_header(headers, USER_EMAIL_HEADER).unwrap_or_else(|| command.user_id.clone());
    let uploader_type =
        optional_header(headers, ACTOR_TYPE_HEADER).unwrap_or_else(|| "user".to_string());
    if !matches!(uploader_type.as_str(), "user" | "agent") {
        return Err(invalid_payload());
    }
    let uploader_id =
        optional_header(headers, ACTOR_ID_HEADER).unwrap_or_else(|| command.user_id.clone());
    Ok(PublicWorkspaceFileContext {
        tenant_id: command.tenant_id.clone(),
        project_id: command.project_id.clone(),
        workspace_id: command.workspace_id.clone(),
        user_id: command.user_id.clone(),
        user_name,
        uploader_type: uploader_type.clone(),
        uploader_id: uploader_id.clone(),
        uploader_actor_id: format!("{uploader_type}:{uploader_id}"),
        expected_revision: Some(command.expected_revision),
        idempotency_key: Some(command.idempotency_key.clone()),
    })
}

pub(super) async fn receipt(
    state: &WorkspaceCoreState,
    command: &CommandContext,
    facts: AuthorityFacts,
) -> Result<MutationReceiptResponse, Response> {
    let statement = DbStatementBuilder::new(state.sql_flavor)
        .push_static(
            "SELECT receipt_id, contract_version, surface, action, request_hash, \
             expected_revision, committed_revision FROM workspace_mutation_receipts WHERE \
             tenant_id = ",
        )
        .bind(command.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(command.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(command.workspace_id.as_str())
        .push_static(" AND actor_id = ")
        .bind(command.user_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(command.idempotency_key.as_str())
        .build();
    let rows = state.db.query(statement).await.map_err(|error| {
        tracing::error!(error = %error, "Workspace Collaboration receipt lookup failed");
        authority_unavailable()
    })?;
    let row = rows.first().ok_or_else(authority_unavailable)?;
    let receipt_id = row
        .get_string("receipt_id")
        .map_err(|_| authority_unavailable())?
        .ok_or_else(authority_unavailable)?;
    let contract_version = row
        .get_string("contract_version")
        .map_err(|_| authority_unavailable())?
        .ok_or_else(authority_unavailable)?;
    let surface = row
        .get_string("surface")
        .map_err(|_| authority_unavailable())?
        .ok_or_else(authority_unavailable)?;
    let action = row
        .get_string("action")
        .map_err(|_| authority_unavailable())?
        .ok_or_else(authority_unavailable)?;
    let request_hash = row
        .get_string("request_hash")
        .map_err(|_| authority_unavailable())?
        .ok_or_else(authority_unavailable)?;
    let expected_revision = row
        .get_i64("expected_revision")
        .map_err(|_| authority_unavailable())?
        .and_then(|value| u64::try_from(value).ok())
        .ok_or_else(authority_unavailable)?;
    let committed_revision = row
        .get_i64("committed_revision")
        .map_err(|_| authority_unavailable())?
        .and_then(|value| u64::try_from(value).ok())
        .ok_or_else(authority_unavailable)?;
    if contract_version != CONTRACT_VERSION
        || surface != command.surface
        || action != command.action_name
        || request_hash != command.request_hash
        || expected_revision != command.expected_revision
        || committed_revision != facts.revision
    {
        tracing::error!(
            workspace_id = %command.workspace_id,
            "Workspace Collaboration persisted receipt does not match the command"
        );
        return Err(authority_unavailable());
    }
    Ok(MutationReceiptResponse {
        contract_version: CONTRACT_VERSION,
        receipt_id,
        workspace_id: command.workspace_id.clone(),
        surface,
        action,
        revision: committed_revision,
        duplicate: facts.duplicate,
    })
}

fn authority_unavailable() -> Response {
    error_response(
        StatusCode::SERVICE_UNAVAILABLE,
        "workspace_collaboration_authority_unavailable",
        "Workspace Collaboration mutation rejected",
        None,
    )
}

fn collaboration_access_error(error: ApiError) -> Response {
    match error {
        ApiError::NotFound => error_response(
            StatusCode::NOT_FOUND,
            "workspace_collaboration_scope_mismatch",
            "Workspace Collaboration mutation rejected",
            None,
        ),
        ApiError::Forbidden(_) => error_response(
            StatusCode::FORBIDDEN,
            "workspace_collaboration_access_denied",
            "Workspace Collaboration mutation rejected",
            None,
        ),
        other => other.into_response(),
    }
}

pub(super) fn invalid_payload() -> Response {
    error_response(
        StatusCode::UNPROCESSABLE_ENTITY,
        "workspace_collaboration_payload_invalid",
        "Invalid Workspace Collaboration mutation",
        None,
    )
}

fn validate_idempotency_key(key: &str) -> Result<(), Response> {
    if (8..=256).contains(&key.len())
        && key == key.trim()
        && key.bytes().all(|byte| (33..=126).contains(&byte))
    {
        Ok(())
    } else {
        Err(invalid_payload())
    }
}

fn required_revision(headers: &HeaderMap) -> Result<u64, Response> {
    required_header(headers, EXPECTED_REVISION_HEADER)?
        .parse::<u64>()
        .map_err(|_| invalid_payload())
}

fn required_header(headers: &HeaderMap, name: &'static str) -> Result<String, Response> {
    headers
        .get(name)
        .and_then(|value| value.to_str().ok())
        .map(str::to_string)
        .ok_or_else(invalid_payload)
}

fn optional_header(headers: &HeaderMap, name: &'static str) -> Option<String> {
    headers
        .get(name)
        .and_then(|value| value.to_str().ok())
        .map(str::to_string)
}

fn canonical_command(
    request: &MutationRequest,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
) -> Result<Vec<u8>, Response> {
    serde_json::to_vec(&canonical_json(&json!({
        "contract_version": &request.contract_version,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "workspace_id": workspace_id,
        "surface": &request.surface,
        "action": &request.action,
        "expected_revision": request.expected_revision,
        "payload": &request.payload,
    })))
    .map_err(|_| invalid_payload())
}

fn canonical_json(value: &Value) -> Value {
    match value {
        Value::Object(values) => Value::Object(
            values
                .iter()
                .map(|(key, value)| (key.clone(), canonical_json(value)))
                .collect(),
        ),
        Value::Array(values) => Value::Array(values.iter().map(canonical_json).collect()),
        other => other.clone(),
    }
}

fn error_response(
    status: StatusCode,
    reason_code: &'static str,
    message: &'static str,
    extra: Option<Value>,
) -> Response {
    let mut detail = json!({"reason_code": reason_code, "message": message});
    if let Some(Value::Object(extra)) = extra
        && let Some(detail) = detail.as_object_mut()
    {
        detail.extend(extra);
    }
    (status, Json(json!({"detail": detail}))).into_response()
}
