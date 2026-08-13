use std::sync::Arc;

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Extension, Json,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use super::{
    automation_dispatcher::{self, AutomationLedgerError, ManualRunCommand, SystemAutomationClock},
    automation_executor,
    automation_store::{self, AutomationStoreError},
    ensure_active_project, now_iso, AuthenticatedContext, LocalJsonResult, LocalRuntimeState,
};
use validation::{validate_create, validate_idempotency_key, validate_run, validate_update};

mod validation;

const DEFAULT_PAGE_SIZE: i64 = 50;
const DEFAULT_TIMEOUT_SECONDS: u64 = 300;
const AUTOMATION_RUN_CONTRACT_VERSION: u64 = 2;
const LOCAL_AUTOMATION_SERVICE_VERSION: &str = "0.1.0";
const LOCAL_AUTOMATION_CONTRACT_VERSION: &str = "2.0.0";

#[derive(Debug, Default, Deserialize)]
pub(super) struct ListQuery {
    include_disabled: Option<bool>,
    limit: Option<i64>,
    offset: Option<i64>,
}

#[derive(Debug, Default, Deserialize)]
pub(super) struct RunListQuery {
    limit: Option<i64>,
    offset: Option<i64>,
}

#[derive(Debug, Default, Deserialize)]
pub(super) struct CapabilityQuery {
    workspace_id: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct AutomationConfig {
    kind: String,
    config: Map<String, Value>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CreateAutomationRequest {
    idempotency_key: String,
    name: String,
    #[serde(default)]
    description: Option<String>,
    #[serde(default = "default_true")]
    enabled: bool,
    #[serde(default)]
    delete_after_run: bool,
    schedule: AutomationConfig,
    payload: AutomationConfig,
    #[serde(default = "default_delivery")]
    delivery: AutomationConfig,
    #[serde(default = "default_conversation_mode")]
    conversation_mode: String,
    #[serde(default)]
    workspace_id: Option<String>,
    #[serde(default)]
    conversation_id: Option<String>,
    #[serde(default = "default_timezone")]
    timezone: String,
    #[serde(default)]
    stagger_seconds: u64,
    #[serde(default = "default_timeout_seconds")]
    timeout_seconds: u64,
    #[serde(default)]
    max_retries: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct UpdateAutomationRequest {
    idempotency_key: String,
    expected_revision: u64,
    #[serde(default)]
    name: Option<String>,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    enabled: Option<bool>,
    #[serde(default)]
    delete_after_run: Option<bool>,
    #[serde(default)]
    schedule: Option<AutomationConfig>,
    #[serde(default)]
    payload: Option<AutomationConfig>,
    #[serde(default)]
    delivery: Option<AutomationConfig>,
    #[serde(default)]
    conversation_mode: Option<String>,
    #[serde(default)]
    workspace_id: Option<String>,
    #[serde(default)]
    conversation_id: Option<String>,
    #[serde(default)]
    timezone: Option<String>,
    #[serde(default)]
    stagger_seconds: Option<u64>,
    #[serde(default)]
    timeout_seconds: Option<u64>,
    #[serde(default)]
    max_retries: Option<u64>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ToggleAutomationRequest {
    idempotency_key: String,
    expected_revision: u64,
    enabled: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct DeleteAutomationRequest {
    idempotency_key: String,
    expected_revision: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RunAutomationRequest {
    #[serde(default = "default_run_contract_version")]
    contract_version: u64,
    expected_revision: u64,
    idempotency_key: String,
    #[serde(default)]
    conversation_id: Option<String>,
}

fn validate_page(limit: Option<i64>, offset: Option<i64>) -> Result<(), (StatusCode, Json<Value>)> {
    for (field, value) in [
        ("limit", limit.unwrap_or(DEFAULT_PAGE_SIZE)),
        ("offset", offset.unwrap_or_default()),
    ] {
        if value < 0 {
            return Err(error(
                StatusCode::UNPROCESSABLE_ENTITY,
                format!("{field} must be greater than or equal to 0"),
            ));
        }
    }
    Ok(())
}

pub(super) async fn list(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
    Query(query): Query<ListQuery>,
) -> LocalJsonResult {
    ensure_active_project(&authenticated, &project_id)?;
    validate_page(query.limit, query.offset)?;
    let (items, total) = automation_store::list(
        &state.session_store,
        &project_id,
        query.include_disabled.unwrap_or(false),
        query.limit.unwrap_or(DEFAULT_PAGE_SIZE),
        query.offset.unwrap_or_default(),
    )
    .map_err(store_error)?;
    Ok(Json(json!({ "items": items, "total": total })))
}

pub(super) async fn capabilities(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
    Query(query): Query<CapabilityQuery>,
) -> LocalJsonResult {
    ensure_active_project(&authenticated, &project_id)?;
    let workspace_id = query
        .workspace_id
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty());
    let durable_execution = match workspace_id {
        Some(workspace_id) => {
            state
                .automation_runtime_available_for_workspace(
                    &authenticated.workspace.tenant_id,
                    &project_id,
                    workspace_id,
                )
                .await
        }
        None => false,
    };
    let reason_code = if durable_execution {
        Value::Null
    } else if workspace_id.is_none() {
        json!("automation_workspace_scope_unavailable")
    } else {
        json!("durable_automation_execution_unavailable")
    };
    Ok(Json(json!({
        "service_version": LOCAL_AUTOMATION_SERVICE_VERSION,
        "contract_version": LOCAL_AUTOMATION_CONTRACT_VERSION,
        "schema_version": 2,
        "read": true,
        "revision_guarded": true,
        "idempotency_guarded": true,
        "durable_execution": durable_execution,
        "supported_read_trigger_kinds": ["manual", "schedule", "event"],
        "create": { "allowed": true },
        "edit": { "allowed": true },
        "toggle": { "allowed": true },
        "run_now": {
            "allowed": durable_execution,
            "reason_code": reason_code,
        },
        "delete": { "allowed": true },
    })))
}

pub(super) async fn create(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
    Json(request): Json<CreateAutomationRequest>,
) -> Result<Response, (StatusCode, Json<Value>)> {
    ensure_active_project(&authenticated, &project_id)?;
    validate_create(&request)?;
    let now = now_iso();
    let job = json!({
        "id": Uuid::new_v4().to_string(),
        "project_id": project_id,
        "tenant_id": authenticated.workspace.tenant_id,
        "name": request.name.trim(),
        "description": request.description.as_deref().map(str::trim),
        "enabled": request.enabled,
        "delete_after_run": request.delete_after_run,
        "revision": 1,
        "schedule_revision": 1,
        "trigger": trigger_projection(&request.schedule),
        "schedule": request.schedule,
        "payload": request.payload,
        "delivery": request.delivery,
        "conversation_mode": request.conversation_mode,
        "workspace_id": request.workspace_id,
        "conversation_id": request.conversation_id,
        "timezone": request.timezone,
        "stagger_seconds": request.stagger_seconds,
        "timeout_seconds": request.timeout_seconds,
        "max_retries": request.max_retries,
        "state": {},
        "created_by": authenticated.user.user_id,
        "created_at": now,
        "updated_at": Value::Null,
    });
    let request_hash = request_hash(&request)?;
    validate_explicit_target_scope(
        &state,
        &authenticated.workspace.tenant_id,
        &project_id,
        &job,
    )
    .await?;
    let outcome = automation_store::create(
        &state.session_store,
        &authenticated.user.user_id,
        &project_id,
        request.idempotency_key.trim(),
        &request_hash,
        &job,
        &now,
    )
    .map_err(store_error)?;
    let status = if outcome.replayed {
        StatusCode::OK
    } else {
        StatusCode::CREATED
    };
    Ok((status, Json(outcome.value)).into_response())
}

pub(super) async fn get(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((project_id, automation_id)): Path<(String, String)>,
) -> LocalJsonResult {
    ensure_active_project(&authenticated, &project_id)?;
    let job = automation_store::get(&state.session_store, &project_id, &automation_id)
        .map_err(store_error)?;
    Ok(Json(job))
}

pub(super) async fn update(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((project_id, automation_id)): Path<(String, String)>,
    Json(request): Json<UpdateAutomationRequest>,
) -> LocalJsonResult {
    ensure_active_project(&authenticated, &project_id)?;
    validate_update(&request)?;
    let request_hash = request_hash(&request)?;
    let operation = format!("update:{automation_id}");
    let schedule_changed = request.schedule.is_some()
        || request.workspace_id.is_some()
        || request.conversation_id.is_some();
    let outcome = automation_store::update(
        &state.session_store,
        &authenticated.user.user_id,
        &project_id,
        &automation_id,
        &operation,
        request.idempotency_key.trim(),
        &request_hash,
        request.expected_revision,
        &now_iso(),
        |job| {
            apply_update(job, &request)?;
            if schedule_changed {
                increment_schedule_revision(job)?;
            }
            Ok(())
        },
    )
    .map_err(store_error)?;
    Ok(Json(outcome.value))
}

pub(super) async fn toggle(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((project_id, automation_id)): Path<(String, String)>,
    Json(request): Json<ToggleAutomationRequest>,
) -> LocalJsonResult {
    ensure_active_project(&authenticated, &project_id)?;
    validate_idempotency_key(&request.idempotency_key)?;
    let request_hash = request_hash(&request)?;
    let operation = format!("toggle:{automation_id}");
    let outcome = automation_store::update(
        &state.session_store,
        &authenticated.user.user_id,
        &project_id,
        &automation_id,
        &operation,
        request.idempotency_key.trim(),
        &request_hash,
        request.expected_revision,
        &now_iso(),
        |job| set_field(job, "enabled", Value::Bool(request.enabled)),
    )
    .map_err(store_error)?;
    Ok(Json(outcome.value))
}

pub(super) async fn delete(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((project_id, automation_id)): Path<(String, String)>,
    Json(request): Json<DeleteAutomationRequest>,
) -> Result<StatusCode, (StatusCode, Json<Value>)> {
    ensure_active_project(&authenticated, &project_id)?;
    validate_idempotency_key(&request.idempotency_key)?;
    let request_hash = request_hash(&request)?;
    automation_store::delete(
        &state.session_store,
        &authenticated.user.user_id,
        &project_id,
        &automation_id,
        request.idempotency_key.trim(),
        &request_hash,
        request.expected_revision,
        &now_iso(),
    )
    .map_err(store_error)?;
    Ok(StatusCode::NO_CONTENT)
}

pub(super) async fn list_runs(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((project_id, automation_id)): Path<(String, String)>,
    Query(query): Query<RunListQuery>,
) -> LocalJsonResult {
    ensure_active_project(&authenticated, &project_id)?;
    validate_page(query.limit, query.offset)?;
    automation_store::get(&state.session_store, &project_id, &automation_id)
        .map_err(store_error)?;
    let (items, total) = automation_dispatcher::list_runs(
        &state.session_store,
        &project_id,
        &automation_id,
        query.limit.unwrap_or(DEFAULT_PAGE_SIZE),
        query.offset.unwrap_or_default(),
    )
    .map_err(ledger_error)?;
    Ok(Json(json!({ "items": items, "total": total })))
}

pub(super) async fn run(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((project_id, automation_id)): Path<(String, String)>,
    Json(request): Json<RunAutomationRequest>,
) -> Result<Response, (StatusCode, Json<Value>)> {
    ensure_active_project(&authenticated, &project_id)?;
    validate_run(&request)?;
    let request_hash = request_hash(&request)?;
    let command = ManualRunCommand {
        user_id: &authenticated.user.user_id,
        project_id: &project_id,
        job_id: &automation_id,
        expected_revision: request.expected_revision,
        idempotency_key: request.idempotency_key.trim(),
        request_hash: &request_hash,
        conversation_id: request.conversation_id.as_deref(),
    };
    if let Some(receipt) =
        automation_dispatcher::lookup_manual_run_receipt(&state.session_store, command)
            .map_err(ledger_error)?
    {
        return Ok((StatusCode::ACCEPTED, Json(receipt)).into_response());
    }
    let job = automation_store::get(&state.session_store, &project_id, &automation_id)
        .map_err(store_error)?;
    if let Err(reason_code) = state
        .validate_automation_execution_authority(
            &authenticated.workspace.tenant_id,
            &project_id,
            &job,
            request.conversation_id.as_deref(),
        )
        .await
    {
        return Err(error_with_code(
            StatusCode::SERVICE_UNAVAILABLE,
            reason_code,
            "local automation execution authority is unavailable for the requested scope",
        ));
    }
    let receipt = automation_dispatcher::enqueue_manual_run(
        &state.session_store,
        command,
        &SystemAutomationClock,
    )
    .map_err(ledger_error)?;
    Ok((StatusCode::ACCEPTED, Json(receipt)).into_response())
}

async fn validate_explicit_target_scope(
    state: &LocalRuntimeState,
    tenant_id: &str,
    project_id: &str,
    job: &Value,
) -> Result<(), (StatusCode, Json<Value>)> {
    let has_explicit_target = job
        .get("workspace_id")
        .and_then(Value::as_str)
        .is_some_and(|value| !value.trim().is_empty())
        || job
            .get("conversation_id")
            .and_then(Value::as_str)
            .is_some_and(|value| !value.trim().is_empty());
    if !has_explicit_target {
        return Ok(());
    }
    automation_executor::execution_workspace_id(state, tenant_id, project_id, job, None)
        .await
        .map(|_| ())
        .map_err(|reason_code| {
            error_with_code(
                StatusCode::UNPROCESSABLE_ENTITY,
                reason_code,
                "automation execution target is outside the active scope or unavailable",
            )
        })
}

fn apply_update(
    job: &mut Value,
    request: &UpdateAutomationRequest,
) -> Result<(), AutomationStoreError> {
    if let Some(value) = request.name.as_deref() {
        set_field(job, "name", Value::from(value.trim()))?;
    }
    if let Some(value) = request.description.as_deref() {
        set_field(job, "description", Value::from(value.trim()))?;
    }
    for (field, value) in [
        ("enabled", request.enabled),
        ("delete_after_run", request.delete_after_run),
    ] {
        if let Some(value) = value {
            set_field(job, field, Value::Bool(value))?;
        }
    }
    for (field, value) in [
        ("schedule", request.schedule.as_ref()),
        ("payload", request.payload.as_ref()),
        ("delivery", request.delivery.as_ref()),
    ] {
        if let Some(value) = value {
            set_field(
                job,
                field,
                serde_json::to_value(value)
                    .map_err(|error| AutomationStoreError::InvalidRecord(error.to_string()))?,
            )?;
        }
    }
    if let Some(schedule) = request.schedule.as_ref() {
        set_field(job, "trigger", trigger_projection(schedule))?;
    }
    if let Some(value) = request.conversation_mode.as_deref() {
        set_field(job, "conversation_mode", Value::from(value))?;
    }
    if let Some(value) = request.workspace_id.as_deref() {
        set_field(job, "workspace_id", Value::from(value))?;
    }
    if let Some(value) = request.conversation_id.as_deref() {
        set_field(job, "conversation_id", Value::from(value))?;
    }
    if let Some(value) = request.timezone.as_deref() {
        set_field(job, "timezone", Value::from(value))?;
    }
    for (field, value) in [
        ("stagger_seconds", request.stagger_seconds),
        ("timeout_seconds", request.timeout_seconds),
        ("max_retries", request.max_retries),
    ] {
        if let Some(value) = value {
            set_field(job, field, Value::from(value))?;
        }
    }
    Ok(())
}

fn increment_schedule_revision(job: &mut Value) -> Result<(), AutomationStoreError> {
    let revision = job
        .get("schedule_revision")
        .and_then(Value::as_u64)
        .ok_or_else(|| {
            AutomationStoreError::InvalidRecord("schedule_revision must be an integer".into())
        })?;
    set_field(job, "schedule_revision", Value::from(revision + 1))
}

fn set_field(job: &mut Value, field: &str, value: Value) -> Result<(), AutomationStoreError> {
    job.as_object_mut()
        .ok_or_else(|| AutomationStoreError::InvalidRecord("automation must be an object".into()))?
        .insert(field.into(), value);
    Ok(())
}

fn request_hash<T: Serialize>(request: &T) -> Result<String, (StatusCode, Json<Value>)> {
    let encoded = serde_json::to_vec(request).map_err(|encode_error| {
        error(
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("failed to encode automation request: {encode_error}"),
        )
    })?;
    Ok(lower_hex(&Sha256::digest(encoded)))
}

fn lower_hex(bytes: &[u8]) -> String {
    let mut encoded = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        use std::fmt::Write;
        let _ = write!(&mut encoded, "{byte:02x}");
    }
    encoded
}

fn trigger_projection(schedule: &AutomationConfig) -> Value {
    json!({ "kind": "schedule", "schedule": schedule })
}

fn store_error(error_value: AutomationStoreError) -> (StatusCode, Json<Value>) {
    match error_value {
        AutomationStoreError::NotFound => error(StatusCode::NOT_FOUND, "Cron job not found"),
        AutomationStoreError::RevisionConflict { expected, actual } => error(
            StatusCode::CONFLICT,
            format!("automation revision conflict: expected {expected}, found {actual}"),
        ),
        AutomationStoreError::IdempotencyConflict => error(
            StatusCode::CONFLICT,
            "automation idempotency key is already bound to a different request",
        ),
        AutomationStoreError::InvalidRecord(detail) | AutomationStoreError::Storage(detail) => {
            error(StatusCode::INTERNAL_SERVER_ERROR, detail)
        }
    }
}

fn ledger_error(error_value: AutomationLedgerError) -> (StatusCode, Json<Value>) {
    match error_value {
        AutomationLedgerError::NotFound => error_with_code(
            StatusCode::NOT_FOUND,
            "automation_not_found",
            "Cron job not found",
        ),
        AutomationLedgerError::RevisionConflict { expected, actual } => error_with_code(
            StatusCode::CONFLICT,
            "automation_revision_conflict",
            format!("automation revision conflict: expected {expected}, found {actual}"),
        ),
        AutomationLedgerError::IdempotencyConflict => error_with_code(
            StatusCode::CONFLICT,
            "automation_idempotency_conflict",
            "automation idempotency key is already bound to a different request",
        ),
        AutomationLedgerError::LeaseLost => error_with_code(
            StatusCode::CONFLICT,
            "automation_operation_lease_lost",
            "automation operation lease is no longer authoritative",
        ),
        AutomationLedgerError::InvalidRecord(_) => error_with_code(
            StatusCode::INTERNAL_SERVER_ERROR,
            "local_automation_record_invalid",
            "local automation record is invalid",
        ),
        AutomationLedgerError::Storage(_) => error_with_code(
            StatusCode::INTERNAL_SERVER_ERROR,
            "local_automation_storage_error",
            "local automation storage is unavailable",
        ),
    }
}

fn error(status: StatusCode, detail: impl Into<String>) -> (StatusCode, Json<Value>) {
    (status, Json(json!({ "detail": detail.into() })))
}

fn error_with_code(
    status: StatusCode,
    code: &str,
    detail: impl Into<String>,
) -> (StatusCode, Json<Value>) {
    (
        status,
        Json(json!({ "code": code, "detail": detail.into() })),
    )
}

fn default_true() -> bool {
    true
}

fn default_delivery() -> AutomationConfig {
    AutomationConfig {
        kind: "none".into(),
        config: Map::new(),
    }
}

fn default_conversation_mode() -> String {
    "fresh".into()
}

fn default_timezone() -> String {
    "UTC".into()
}

fn default_timeout_seconds() -> u64 {
    DEFAULT_TIMEOUT_SECONDS
}

fn default_run_contract_version() -> u64 {
    AUTOMATION_RUN_CONTRACT_VERSION
}
