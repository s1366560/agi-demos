use std::sync::Arc;

use axum::extract::multipart::MultipartRejection;
use axum::extract::{Multipart, Path};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::{Extension, Json};
use memstack_workspace_service::{
    PublicWorkspaceFileError, PublicWorkspaceFileErrorKind, PublicWorkspaceFileService,
};
use serde_json::json;

use super::models::MutationRequest;
use super::{
    AuthorityFacts, FailureKind, MutationReceiptResponse, command_context, file_context, receipt,
    required_header, required_revision, resolve_service_result,
};
use crate::WorkspaceCoreState;

pub(super) async fn upload_workspace_collaboration_file(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    headers: HeaderMap,
    multipart: Result<Multipart, MultipartRejection>,
) -> Result<Json<MutationReceiptResponse>, Response> {
    reject_oversized_content_length(&headers)?;
    let expected_revision = required_revision(&headers)?;
    let idempotency_key = required_header(&headers, super::IDEMPOTENCY_HEADER)?;
    let preflight_request = MutationRequest {
        contract_version: super::CONTRACT_VERSION.to_string(),
        surface: "files".to_string(),
        action: "upload_file".to_string(),
        expected_revision,
        idempotency_key,
        payload: json!({}),
    };
    command_context(
        &state,
        tenant_id.clone(),
        project_id.clone(),
        workspace_id.clone(),
        &headers,
        &preflight_request,
    )
    .await?;
    let multipart = multipart.map_err(|_| super::invalid_payload())?;
    let staged = crate::files::stage_multipart(multipart)
        .await
        .map_err(map_staging_error)?;
    let request = MutationRequest {
        contract_version: super::CONTRACT_VERSION.to_string(),
        surface: "files".to_string(),
        action: "upload_file".to_string(),
        expected_revision,
        idempotency_key: preflight_request.idempotency_key,
        payload: json!({
            "parent_path": &staged.parent_path,
            "file_name": &staged.filename,
            "content_type": &staged.content_type,
            "size_bytes": staged.size_bytes,
            "sha256": &staged.checksum_sha256,
        }),
    };
    let command = match command_context(
        &state,
        tenant_id,
        project_id,
        workspace_id,
        &headers,
        &request,
    )
    .await
    {
        Ok(command) => command,
        Err(response) => {
            staged.cleanup().await;
            return Err(response);
        }
    };
    let body = match staged.byte_stream().await {
        Ok(body) => body,
        Err(error) => {
            staged.cleanup().await;
            return Err(map_staging_error(error));
        }
    };
    let context = file_context(&command, &headers)?;
    let result = PublicWorkspaceFileService::new(
        state.db.as_ref(),
        state.sql_flavor,
        Arc::clone(&state.object_store),
    )
    .with_mutation_authority(command.receipt_authority()?)
    .upload(
        &context,
        staged.parent_path.as_str(),
        staged.filename.as_str(),
        staged.content_type.as_str(),
        staged.size_bytes,
        staged.checksum_sha256.as_str(),
        body,
    )
    .await;
    staged.cleanup().await;
    let outcome = resolve_service_result(state.as_ref(), &command, result, file_error_kind).await?;
    Ok(Json(
        receipt(
            state.as_ref(),
            &command,
            AuthorityFacts {
                revision: outcome.committed_revision,
                duplicate: outcome.replayed,
            },
        )
        .await?,
    ))
}

fn reject_oversized_content_length(headers: &HeaderMap) -> Result<(), Response> {
    let Some(value) = headers.get(axum::http::header::CONTENT_LENGTH) else {
        return Ok(());
    };
    let size = value
        .to_str()
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .ok_or_else(super::invalid_payload)?;
    if size > super::MAX_MULTIPART_BODY_SIZE {
        return Err(upload_too_large());
    }
    Ok(())
}

fn map_staging_error(error: crate::files::FileHttpError) -> Response {
    let response = error.into_response();
    if response.status() == StatusCode::PAYLOAD_TOO_LARGE {
        upload_too_large()
    } else {
        super::invalid_payload()
    }
}

fn upload_too_large() -> Response {
    (
        StatusCode::PAYLOAD_TOO_LARGE,
        Json(json!({
            "detail": {
                "reason_code": "workspace_collaboration_upload_too_large",
                "message": "Workspace Collaboration upload is too large",
            }
        })),
    )
        .into_response()
}

fn file_error_kind(error: &PublicWorkspaceFileError) -> FailureKind {
    match error.kind() {
        PublicWorkspaceFileErrorKind::InvalidRequest => FailureKind::InvalidRequest,
        PublicWorkspaceFileErrorKind::NotFound => FailureKind::NotFound,
        PublicWorkspaceFileErrorKind::Forbidden => FailureKind::Forbidden,
        PublicWorkspaceFileErrorKind::Conflict => FailureKind::Conflict,
        PublicWorkspaceFileErrorKind::Unavailable => FailureKind::Unavailable,
    }
}
