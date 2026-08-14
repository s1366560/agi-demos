//! Durable correlation and terminal authority for MemStack Agent Runtime calls.

use std::sync::Arc;

use axum::Json;
use axum::extract::{Extension, Path, Query};
use axum::http::HeaderMap;
use bcs_db_api::{
    DbRow, DbSqlFlavor, DbStatementBuilder, DbTransactionStep, DbTransactionStepResult,
};
use memstack_workspace_service::{
    PublicWorkspaceRuntimeTerminalContext, PublicWorkspaceRuntimeTerminalError,
    PublicWorkspaceRuntimeTerminalErrorKind, PublicWorkspaceRuntimeTerminalInput,
    PublicWorkspaceRuntimeTerminalService,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use super::{ApiError, TENANT_HEADER, WorkspaceCoreState, required_header};

const STATUS_RUNNING: &str = "running";
const STATUS_COMPLETED: &str = "completed";
const STATUS_FAILED: &str = "failed";
const STATUS_ABORTED: &str = "aborted";

#[derive(Debug, Deserialize)]
pub(super) struct RuntimeCorrelationRequest {
    correlation_id: String,
    project_id: String,
    workspace_id: String,
    user_id: String,
    #[serde(default)]
    task_id: Option<String>,
    #[serde(default)]
    attempt_id: Option<String>,
    #[serde(default)]
    plan_id: Option<String>,
    #[serde(default)]
    plan_node_id: Option<String>,
    conversation_id: String,
    bcs_session_id: String,
    bcs_group_id: String,
    #[serde(default)]
    bcs_message_id: Option<String>,
    #[serde(default)]
    state_machine_run_id: Option<String>,
    delivery_request_id: String,
    provider_run_id: String,
    provider_id: String,
    #[serde(default)]
    provider_bot_ref: String,
}

#[derive(Debug, Serialize)]
pub(super) struct RuntimeCorrelationResponse {
    correlation_id: String,
    status: String,
    created: bool,
}

#[derive(Debug, Deserialize)]
pub(super) struct RuntimeTerminalRequest {
    project_id: String,
    workspace_id: String,
    execution_status: String,
    terminal_message_id: String,
    terminal_event_id: String,
    report: Value,
}

#[derive(Debug, Serialize)]
pub(super) struct RuntimeTerminalResponse {
    correlation_id: String,
    status: String,
    outbox_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    terminal_id: Option<String>,
    report_hash: String,
    created: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RuntimeTerminalReadQuery {
    project_id: String,
    workspace_id: String,
}

#[derive(Debug, Serialize)]
pub(super) struct RuntimeTerminalReadResponse {
    correlation_id: String,
    status: String,
    outbox_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    terminal_id: Option<String>,
    terminal_message_id: String,
    terminal_event_id: String,
    report: Value,
    report_hash: String,
    persisted: bool,
}

struct RuntimeCorrelationRecord {
    correlation_id: String,
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    user_id: String,
    conversation_id: String,
    bcs_group_id: String,
    provider_run_id: String,
    provider_id: String,
    provider_bot_ref: String,
    status: String,
}

pub(super) async fn record_runtime_correlation(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    headers: HeaderMap,
    Json(request): Json<RuntimeCorrelationRequest>,
) -> Result<Json<RuntimeCorrelationResponse>, ApiError> {
    let tenant_id = required_header(&headers, TENANT_HEADER)?;
    validate_correlation_request(&request)?;
    let insert = build_correlation_insert(&tenant_id, &request);
    let select = build_correlation_select(&request.delivery_request_id);
    let results = state
        .db
        .transaction(vec![
            DbTransactionStep::Execute(insert),
            DbTransactionStep::Query(select),
        ])
        .await
        .map_err(ApiError::Database)?;
    let created = affected_rows(&results, 0)? > 0;
    let row = transaction_row(&results, 1)?.ok_or(ApiError::NotFound)?;
    let record = correlation_from_row(row)?;
    ensure_correlation_matches(&record, &tenant_id, &request)?;
    Ok(Json(RuntimeCorrelationResponse {
        correlation_id: record.correlation_id,
        status: record.status,
        created,
    }))
}

pub(super) async fn record_runtime_terminal(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path(correlation_id): Path<String>,
    headers: HeaderMap,
    Json(request): Json<RuntimeTerminalRequest>,
) -> Result<Json<RuntimeTerminalResponse>, ApiError> {
    let tenant_id = required_header(&headers, TENANT_HEADER)?;
    validate_required("correlation_id", &correlation_id)?;
    validate_terminal_request(&request)?;
    let outcome = PublicWorkspaceRuntimeTerminalService::new(state.db.as_ref(), state.sql_flavor)
        .record(
            &PublicWorkspaceRuntimeTerminalContext {
                tenant_id,
                project_id: request.project_id,
                workspace_id: request.workspace_id,
            },
            &correlation_id,
            &PublicWorkspaceRuntimeTerminalInput {
                execution_status: request.execution_status,
                terminal_message_id: request.terminal_message_id,
                terminal_event_id: request.terminal_event_id,
                report: request.report,
            },
        )
        .await
        .map_err(runtime_terminal_error)?;
    Ok(Json(RuntimeTerminalResponse {
        correlation_id,
        status: outcome.status,
        outbox_id: outcome.outbox_id,
        terminal_id: outcome.terminal_id,
        report_hash: outcome.report_hash,
        created: outcome.created,
    }))
}

pub(super) async fn read_runtime_terminal(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path(correlation_id): Path<String>,
    headers: HeaderMap,
    Query(query): Query<RuntimeTerminalReadQuery>,
) -> Result<Json<RuntimeTerminalReadResponse>, ApiError> {
    let tenant_id = required_header(&headers, TENANT_HEADER)?;
    for (name, value) in [
        ("correlation_id", correlation_id.as_str()),
        ("project_id", query.project_id.as_str()),
        ("workspace_id", query.workspace_id.as_str()),
    ] {
        validate_required(name, value)?;
    }
    let outcome = PublicWorkspaceRuntimeTerminalService::new(state.db.as_ref(), state.sql_flavor)
        .read(
            &PublicWorkspaceRuntimeTerminalContext {
                tenant_id,
                project_id: query.project_id,
                workspace_id: query.workspace_id,
            },
            &correlation_id,
        )
        .await
        .map_err(runtime_terminal_error)?;
    Ok(Json(RuntimeTerminalReadResponse {
        correlation_id: outcome.correlation_id,
        status: outcome.status,
        outbox_id: outcome.outbox_id,
        terminal_id: outcome.terminal_id,
        terminal_message_id: outcome.terminal_message_id,
        terminal_event_id: outcome.terminal_event_id,
        report: outcome.report,
        report_hash: outcome.report_hash,
        persisted: true,
    }))
}

fn runtime_terminal_error(error: PublicWorkspaceRuntimeTerminalError) -> ApiError {
    match error.kind() {
        PublicWorkspaceRuntimeTerminalErrorKind::InvalidRequest => {
            ApiError::InvalidRequest(error.to_string())
        }
        PublicWorkspaceRuntimeTerminalErrorKind::NotFound => ApiError::NotFound,
        PublicWorkspaceRuntimeTerminalErrorKind::Conflict => ApiError::Conflict(
            "Runtime terminal idempotency key was reused with different content".to_string(),
        ),
        PublicWorkspaceRuntimeTerminalErrorKind::Unavailable => {
            ApiError::InvalidDatabase(error.to_string())
        }
    }
}

fn build_correlation_insert(
    tenant_id: &str,
    request: &RuntimeCorrelationRequest,
) -> bcs_db_api::DbStatement {
    DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static(
            "INSERT INTO workspace_agent_runtime_correlations (\
             correlation_id, tenant_id, project_id, workspace_id, user_id, task_id, attempt_id, \
             plan_id, plan_node_id, conversation_id, bcs_session_id, bcs_group_id, bcs_message_id, \
             state_machine_run_id, delivery_request_id, provider_run_id, provider_id, \
             provider_bot_ref, status) \
             SELECT ",
        )
        .bind(request.correlation_id.as_str())
        .push_static(", ")
        .bind(tenant_id)
        .push_static(", ")
        .bind(request.project_id.as_str())
        .push_static(", ")
        .bind(request.workspace_id.as_str())
        .push_static(", ")
        .bind(request.user_id.as_str())
        .push_static(", ")
        .bind(request.task_id.as_deref())
        .push_static(", ")
        .bind(request.attempt_id.as_deref())
        .push_static(", ")
        .bind(request.plan_id.as_deref())
        .push_static(", ")
        .bind(request.plan_node_id.as_deref())
        .push_static(", ")
        .bind(request.conversation_id.as_str())
        .push_static(", ")
        .bind(request.bcs_session_id.as_str())
        .push_static(", ")
        .bind(request.bcs_group_id.as_str())
        .push_static(", ")
        .bind(request.bcs_message_id.as_deref())
        .push_static(", ")
        .bind(request.state_machine_run_id.as_deref())
        .push_static(", ")
        .bind(request.delivery_request_id.as_str())
        .push_static(", ")
        .bind(request.provider_run_id.as_str())
        .push_static(", ")
        .bind(request.provider_id.as_str())
        .push_static(", ")
        .bind(request.provider_bot_ref.as_str())
        .push_static(", ")
        .bind(STATUS_RUNNING)
        .push_static(
            " FROM workspace_profiles profile JOIN workspace_authorities authority \
             ON authority.tenant_id = profile.tenant_id \
             AND authority.project_id = profile.project_id \
             AND authority.workspace_id = profile.workspace_id \
             WHERE profile.tenant_id = ",
        )
        .bind(tenant_id)
        .push_static(" AND profile.project_id = ")
        .bind(request.project_id.as_str())
        .push_static(" AND profile.workspace_id = ")
        .bind(request.workspace_id.as_str())
        .push_static(" ON CONFLICT (delivery_request_id) DO NOTHING")
        .build()
}

fn build_correlation_select(delivery_request_id: &str) -> bcs_db_api::DbStatement {
    DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static(
            "SELECT correlation_id, tenant_id, project_id, workspace_id, user_id, \
             conversation_id, bcs_group_id, delivery_request_id, provider_run_id, provider_id, \
             provider_bot_ref, status, plan_id \
             FROM workspace_agent_runtime_correlations WHERE delivery_request_id = ",
        )
        .bind(delivery_request_id)
        .build()
}

fn validate_correlation_request(request: &RuntimeCorrelationRequest) -> Result<(), ApiError> {
    for (name, value) in [
        ("correlation_id", request.correlation_id.as_str()),
        ("project_id", request.project_id.as_str()),
        ("workspace_id", request.workspace_id.as_str()),
        ("user_id", request.user_id.as_str()),
        ("conversation_id", request.conversation_id.as_str()),
        ("bcs_session_id", request.bcs_session_id.as_str()),
        ("bcs_group_id", request.bcs_group_id.as_str()),
        ("delivery_request_id", request.delivery_request_id.as_str()),
        ("provider_run_id", request.provider_run_id.as_str()),
        ("provider_id", request.provider_id.as_str()),
    ] {
        validate_required(name, value)?;
    }
    Ok(())
}

fn validate_terminal_request(request: &RuntimeTerminalRequest) -> Result<(), ApiError> {
    for (name, value) in [
        ("project_id", request.project_id.as_str()),
        ("workspace_id", request.workspace_id.as_str()),
        ("execution_status", request.execution_status.as_str()),
        ("terminal_message_id", request.terminal_message_id.as_str()),
        ("terminal_event_id", request.terminal_event_id.as_str()),
    ] {
        validate_required(name, value)?;
    }
    let _ = terminal_status(&request.execution_status)?;
    if !request.report.is_object() {
        return Err(ApiError::InvalidRequest(
            "report must be a JSON object".to_string(),
        ));
    }
    Ok(())
}

fn validate_required(name: &str, value: &str) -> Result<(), ApiError> {
    if value.trim().is_empty() {
        return Err(ApiError::InvalidRequest(format!(
            "{name} must not be blank"
        )));
    }
    if value.len() > 191 {
        return Err(ApiError::InvalidRequest(format!("{name} is too long")));
    }
    Ok(())
}

fn terminal_status(value: &str) -> Result<&'static str, ApiError> {
    match value {
        "complete" | STATUS_COMPLETED => Ok(STATUS_COMPLETED),
        "error" | STATUS_FAILED => Ok(STATUS_FAILED),
        STATUS_ABORTED => Ok(STATUS_ABORTED),
        _ => Err(ApiError::InvalidRequest(
            "execution_status must be complete, error, or aborted".to_string(),
        )),
    }
}

fn correlation_from_row(row: &DbRow) -> Result<RuntimeCorrelationRecord, ApiError> {
    Ok(RuntimeCorrelationRecord {
        correlation_id: required_string(row, "correlation_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        user_id: required_string(row, "user_id")?,
        conversation_id: required_string(row, "conversation_id")?,
        bcs_group_id: required_string(row, "bcs_group_id")?,
        provider_run_id: required_string(row, "provider_run_id")?,
        provider_id: required_string(row, "provider_id")?,
        provider_bot_ref: required_string(row, "provider_bot_ref")?,
        status: required_string(row, "status")?,
    })
}

fn ensure_correlation_matches(
    record: &RuntimeCorrelationRecord,
    tenant_id: &str,
    request: &RuntimeCorrelationRequest,
) -> Result<(), ApiError> {
    if record.correlation_id != request.correlation_id
        || record.tenant_id != tenant_id
        || record.project_id != request.project_id
        || record.workspace_id != request.workspace_id
        || record.user_id != request.user_id
        || record.conversation_id != request.conversation_id
        || record.bcs_group_id != request.bcs_group_id
        || record.provider_run_id != request.provider_run_id
        || record.provider_id != request.provider_id
        || record.provider_bot_ref != request.provider_bot_ref
    {
        return Err(ApiError::Conflict(
            "Runtime delivery request was reused with different correlation data".to_string(),
        ));
    }
    Ok(())
}

fn required_string(row: &DbRow, name: &str) -> Result<String, ApiError> {
    row.get_string(name)
        .map_err(ApiError::Database)?
        .ok_or_else(|| ApiError::InvalidDatabase(format!("{name} is missing")))
}

fn affected_rows(results: &[DbTransactionStepResult], index: usize) -> Result<u64, ApiError> {
    match results.get(index) {
        Some(DbTransactionStepResult::Executed(result)) => Ok(result.affected_rows),
        _ => Err(ApiError::InvalidDatabase(
            "transaction execute result is missing".to_string(),
        )),
    }
}

fn transaction_row(
    results: &[DbTransactionStepResult],
    index: usize,
) -> Result<Option<&DbRow>, ApiError> {
    match results.get(index) {
        Some(DbTransactionStepResult::Rows(rows)) => Ok(rows.first()),
        _ => Err(ApiError::InvalidDatabase(
            "transaction query result is missing".to_string(),
        )),
    }
}
