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
    automation_store::{self, AutomationStoreError},
    ensure_active_project, now_iso, AuthenticatedContext, LocalJsonResult, LocalRuntimeState,
};

const DEFAULT_PAGE_SIZE: i64 = 50;
const DEFAULT_TIMEOUT_SECONDS: u64 = 300;

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
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
) -> LocalJsonResult {
    ensure_active_project(&authenticated, &project_id)?;
    Ok(Json(json!({
        "schema_version": 1,
        "read": true,
        "revision_guarded": true,
        "idempotency_guarded": true,
        "durable_execution": false,
        "supported_read_trigger_kinds": ["manual", "schedule", "event"],
        "create": { "allowed": true },
        "edit": { "allowed": true },
        "toggle": { "allowed": true },
        "run_now": {
            "allowed": false,
            "reason_code": "durable_automation_execution_unavailable",
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
    let schedule_changed = request.schedule.is_some();
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
    Ok(Json(json!({ "items": [], "total": 0 })))
}

fn validate_create(request: &CreateAutomationRequest) -> Result<(), (StatusCode, Json<Value>)> {
    validate_idempotency_key(&request.idempotency_key)?;
    validate_name(&request.name)?;
    validate_config(&request.schedule, &["at", "every", "cron"], "schedule")?;
    validate_config(&request.payload, &["system_event", "agent_turn"], "payload")?;
    validate_config(
        &request.delivery,
        &["none", "announce", "webhook"],
        "delivery",
    )?;
    validate_conversation_mode(&request.conversation_mode)?;
    validate_runtime_limits(request.timeout_seconds, request.max_retries)
}

fn validate_update(request: &UpdateAutomationRequest) -> Result<(), (StatusCode, Json<Value>)> {
    validate_idempotency_key(&request.idempotency_key)?;
    if let Some(name) = request.name.as_deref() {
        validate_name(name)?;
    }
    if let Some(schedule) = request.schedule.as_ref() {
        validate_config(schedule, &["at", "every", "cron"], "schedule")?;
    }
    if let Some(payload) = request.payload.as_ref() {
        validate_config(payload, &["system_event", "agent_turn"], "payload")?;
    }
    if let Some(delivery) = request.delivery.as_ref() {
        validate_config(delivery, &["none", "announce", "webhook"], "delivery")?;
    }
    if let Some(mode) = request.conversation_mode.as_deref() {
        validate_conversation_mode(mode)?;
    }
    validate_runtime_limits(
        request.timeout_seconds.unwrap_or(DEFAULT_TIMEOUT_SECONDS),
        request.max_retries.unwrap_or_default(),
    )
}

fn validate_idempotency_key(value: &str) -> Result<(), (StatusCode, Json<Value>)> {
    if value.trim().is_empty() || value.len() > 200 {
        return Err(error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "idempotency_key must contain between 1 and 200 characters",
        ));
    }
    Ok(())
}

fn validate_name(value: &str) -> Result<(), (StatusCode, Json<Value>)> {
    if value.trim().is_empty() || value.len() > 200 {
        return Err(error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "name must contain between 1 and 200 characters",
        ));
    }
    Ok(())
}

fn validate_config(
    config: &AutomationConfig,
    allowed: &[&str],
    field: &str,
) -> Result<(), (StatusCode, Json<Value>)> {
    if !allowed.contains(&config.kind.as_str()) {
        return Err(error(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("unsupported {field} kind"),
        ));
    }
    Ok(())
}

fn validate_conversation_mode(value: &str) -> Result<(), (StatusCode, Json<Value>)> {
    if !matches!(value, "reuse" | "fresh") {
        return Err(error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "conversation_mode must be reuse or fresh",
        ));
    }
    Ok(())
}

fn validate_runtime_limits(
    timeout_seconds: u64,
    max_retries: u64,
) -> Result<(), (StatusCode, Json<Value>)> {
    if timeout_seconds == 0 || timeout_seconds > 86_400 {
        return Err(error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "timeout_seconds must be between 1 and 86400",
        ));
    }
    if max_retries > 20 {
        return Err(error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "max_retries must be less than or equal to 20",
        ));
    }
    Ok(())
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

fn error(status: StatusCode, detail: impl Into<String>) -> (StatusCode, Json<Value>) {
    (status, Json(json!({ "detail": detail.into() })))
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
