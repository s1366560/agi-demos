//! Exact native schema commands; raw document JSON reaches the core validator unchanged.
use super::super::project_schema::{
    self, contracts::*, response, ProjectSchemaOperationError, ProjectSchemaOperationV2,
    SchemaAction, MAX_DOCUMENT_BYTES, MAX_REQUEST_BYTES,
};
use super::*;
use agistack_adapters_device::knowledge::project_schema::{
    ProjectSchemaMutation, ProjectSchemaStorageError,
};
use agistack_core::project_schema::{ProjectSchemaDocument, ProjectSchemaError, MAX_REVISION};
use axum::{
    body::Bytes,
    extract::{rejection::BytesRejection, DefaultBodyLimit, OriginalUri},
};
use serde::de::DeserializeOwned;
use std::cell::RefCell;

type SchemaResult = Result<Response, SchemaRpcError>;

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route(SchemaAction::Read.path(), post(read))
        .route(SchemaAction::Bootstrap.path(), post(bootstrap))
        .route(SchemaAction::Replace.path(), post(replace))
        .route(SchemaAction::Receipt.path(), post(receipt))
        .route(SchemaAction::History.path(), post(history))
        .route("/api/v1/knowledge/schema/capabilities", get(capabilities))
        .layer(DefaultBodyLimit::max(MAX_REQUEST_BYTES))
}

pub(super) struct SchemaRpcError(StatusCode, &'static str);
impl From<ProjectSchemaOperationError> for SchemaRpcError {
    fn from(error: ProjectSchemaOperationError) -> Self {
        match error {
            ProjectSchemaOperationError::Authority(error) => error.into(),
            ProjectSchemaOperationError::Storage(error) => error.into(),
        }
    }
}
impl From<KnowledgeAuthorityErrorV2> for SchemaRpcError {
    fn from(error: KnowledgeAuthorityErrorV2) -> Self {
        use KnowledgeAuthorityErrorV2::*;
        match error {
            Forbidden | ScopeMismatch => Self(StatusCode::FORBIDDEN, "project_schema_forbidden"),
            GenerationMismatch => Self(StatusCode::CONFLICT, "project_schema_generation_changed"),
            Storage(_) | Knowledge(_) => Self(
                StatusCode::INTERNAL_SERVER_ERROR,
                "project_schema_storage_failed",
            ),
            _ => Self(
                StatusCode::SERVICE_UNAVAILABLE,
                "project_schema_unavailable",
            ),
        }
    }
}
impl From<ProjectSchemaStorageError> for SchemaRpcError {
    fn from(error: ProjectSchemaStorageError) -> Self {
        use ProjectSchemaStorageError::*;
        match error {
            ScopeMismatch | AdmissionChanged => {
                Self(StatusCode::FORBIDDEN, "project_schema_forbidden")
            }
            ChangeIdReused | SyncConflict | Document(ProjectSchemaError::RevisionConflict) => {
                Self(StatusCode::CONFLICT, "project_schema_conflict")
            }
            ResponseTooLarge => Self(
                StatusCode::PAYLOAD_TOO_LARGE,
                "project_schema_response_too_large",
            ),
            InvalidInput | Document(_) => Self(
                StatusCode::UNPROCESSABLE_ENTITY,
                "project_schema_invalid_input",
            ),
            CorruptStorage | Storage(_) => Self(
                StatusCode::INTERNAL_SERVER_ERROR,
                "project_schema_storage_failed",
            ),
        }
    }
}
impl IntoResponse for SchemaRpcError {
    fn into_response(self) -> Response {
        (self.0, Json(json!({"error":{"code":self.1}}))).into_response()
    }
}
fn invalid() -> SchemaRpcError {
    SchemaRpcError(
        StatusCode::UNPROCESSABLE_ENTITY,
        "project_schema_invalid_input",
    )
}
fn reply(bytes: Vec<u8>) -> Response {
    (
        StatusCode::OK,
        [(axum::http::header::CONTENT_TYPE, "application/json")],
        bytes,
    )
        .into_response()
}
fn parse<T: DeserializeOwned>(
    headers: &HeaderMap,
    uri: &axum::http::Uri,
    bytes: Result<Bytes, BytesRejection>,
) -> Result<T, SchemaRpcError> {
    if uri.query().is_some()
        || [
            "idempotency-key",
            "x-expected-revision",
            "if-match",
            "if-none-match",
        ]
        .iter()
        .any(|name| headers.contains_key(*name))
    {
        return Err(invalid());
    }
    if !headers
        .get(axum::http::header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        .is_some_and(|value| {
            value
                .split(';')
                .next()
                .is_some_and(|kind| kind.trim().eq_ignore_ascii_case("application/json"))
        })
    {
        return Err(invalid());
    }
    let bytes = bytes
        .map_err(|error| SchemaRpcError(error.status(), "project_schema_request_too_large"))?;
    serde_json::from_slice(&bytes).map_err(|error| {
        SchemaRpcError(
            if error.is_syntax() || error.is_eof() {
                StatusCode::BAD_REQUEST
            } else {
                StatusCode::UNPROCESSABLE_ENTITY
            },
            "project_schema_invalid_json",
        )
    })
}
fn check_scope(scope: &KnowledgeOperationScopeV2) -> Result<(), SchemaRpcError> {
    let bounded = |value: &str, max: usize| {
        !value.is_empty()
            && value.trim() == value
            && value.len() <= max
            && !value.chars().any(char::is_control)
    };
    if !bounded(&scope.tenant_id, 512)
        || !bounded(&scope.project_id, 512)
        || !bounded(&scope.profile_id, 512)
        || !(0..=9_007_199_254_740_991).contains(&scope.context_revision)
        || !(1..=9_007_199_254_740_991).contains(&scope.generation)
        || scope.digest.len() != 64
        || !scope
            .digest
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(invalid());
    }
    Ok(())
}
fn admit(
    state: &LocalRuntimeState,
    lease: Arc<ActivePlatformPluginGenerationLeaseV2>,
    auth: &AuthenticatedContext,
    scope: &KnowledgeOperationScopeV2,
    action: SchemaAction,
) -> Result<ProjectSchemaOperationV2, SchemaRpcError> {
    check_scope(scope)?;
    ProjectSchemaOperationV2::admit_action(state, lease, auth, scope, action).map_err(Into::into)
}
async fn read(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    headers: HeaderMap,
    OriginalUri(uri): OriginalUri,
    bytes: Result<Bytes, BytesRejection>,
) -> SchemaResult {
    let request: SchemaReadRequest = parse(&headers, &uri, bytes)?;
    let operation = admit(&state, lease, &auth, &request.scope, SchemaAction::Read)?;
    #[derive(serde::Serialize)]
    struct Read {
        document: Option<ProjectSchemaDocument>,
    }
    Ok(reply(response::encode(
        &auth.user.user_id,
        &request.scope,
        SchemaAction::Read,
        Read {
            document: operation.read(&state, &auth)?,
        },
    )?))
}
async fn receipt(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    headers: HeaderMap,
    OriginalUri(uri): OriginalUri,
    bytes: Result<Bytes, BytesRejection>,
) -> SchemaResult {
    let request: SchemaReceiptRequest = parse(&headers, &uri, bytes)?;
    let operation = admit(&state, lease, &auth, &request.scope, SchemaAction::Receipt)?;
    let receipt = operation.receipt(&state, &auth, &request.change_id)?;
    Ok(reply(response::receipt(
        &auth.user.user_id,
        &request.scope,
        SchemaAction::Receipt,
        receipt.as_ref(),
    )?))
}
async fn history(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    headers: HeaderMap,
    OriginalUri(uri): OriginalUri,
    bytes: Result<Bytes, BytesRejection>,
) -> SchemaResult {
    let request: SchemaHistoryRequest = parse(&headers, &uri, bytes)?;
    if request.after_revision > MAX_REVISION || !(1..=100).contains(&request.limit) {
        return Err(invalid());
    }
    let operation = admit(&state, lease, &auth, &request.scope, SchemaAction::History)?;
    let page = operation.history_bounded(
        &state,
        &auth,
        request.after_revision,
        request.limit,
        &|page| response::item_budget(&auth.user.user_id, &request.scope, page),
    )?;
    Ok(reply(response::history(
        &auth.user.user_id,
        &request.scope,
        &page,
    )?))
}
async fn bootstrap(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    headers: HeaderMap,
    OriginalUri(uri): OriginalUri,
    bytes: Result<Bytes, BytesRejection>,
) -> SchemaResult {
    let request: SchemaBootstrapRequest = parse(&headers, &uri, bytes)?;
    mutate(
        &state,
        lease,
        &auth,
        &request.scope,
        request.change_id,
        request.expected_revision,
        &request.document,
        SchemaAction::Bootstrap,
    )
}
async fn replace(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    headers: HeaderMap,
    OriginalUri(uri): OriginalUri,
    bytes: Result<Bytes, BytesRejection>,
) -> SchemaResult {
    let request: SchemaReplaceRequest = parse(&headers, &uri, bytes)?;
    mutate(
        &state,
        lease,
        &auth,
        &request.scope,
        request.change_id,
        request.expected_revision,
        &request.document,
        SchemaAction::Replace,
    )
}
#[allow(clippy::too_many_arguments)]
fn mutate(
    state: &LocalRuntimeState,
    lease: Arc<ActivePlatformPluginGenerationLeaseV2>,
    auth: &AuthenticatedContext,
    scope: &KnowledgeOperationScopeV2,
    change_id: String,
    expected_revision: u32,
    raw: &serde_json::value::RawValue,
    action: SchemaAction,
) -> SchemaResult {
    if raw.get().len() > MAX_DOCUMENT_BYTES {
        return Err(SchemaRpcError(
            StatusCode::PAYLOAD_TOO_LARGE,
            "project_schema_document_too_large",
        ));
    }
    if (action == SchemaAction::Bootstrap && expected_revision != 0)
        || (action == SchemaAction::Replace && !(1..=MAX_REVISION).contains(&expected_revision))
    {
        return Err(invalid());
    }
    let document = ProjectSchemaDocument::from_json(raw.get()).map_err(|_| invalid())?;
    let operation = admit(state, lease, auth, scope, action)?;
    let command = ProjectSchemaMutation {
        document,
        change_id,
        expected_revision,
    };
    let prepared = RefCell::new(None);
    let check =
        |receipt: &agistack_adapters_device::knowledge::project_schema::ProjectSchemaReceipt| {
            *prepared.borrow_mut() = Some(response::receipt(
                &auth.user.user_id,
                scope,
                action,
                Some(receipt),
            )?);
            Ok(())
        };
    if action == SchemaAction::Bootstrap {
        operation.bootstrap_checked(state, auth, &command, &check)?;
    } else {
        operation.replace_checked(state, auth, &command, &check)?;
    }
    Ok(reply(
        prepared
            .into_inner()
            .ok_or(ProjectSchemaStorageError::CorruptStorage)?,
    ))
}
async fn capabilities(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    OriginalUri(uri): OriginalUri,
    bytes: Result<Bytes, BytesRejection>,
) -> SchemaResult {
    let bytes = bytes
        .map_err(|error| SchemaRpcError(error.status(), "project_schema_request_too_large"))?;
    if uri.query().is_some() || !bytes.is_empty() {
        return Err(invalid());
    }
    Ok(Json(project_schema::capabilities::observe(
        &state, &lease, &auth,
    )?)
    .into_response())
}
