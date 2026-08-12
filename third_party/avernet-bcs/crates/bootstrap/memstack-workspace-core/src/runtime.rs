//! Durable correlation and terminal authority for MemStack Agent Runtime calls.

use std::collections::BTreeMap;
use std::sync::Arc;

use axum::Json;
use axum::extract::{Extension, Path, Query};
use axum::http::HeaderMap;
use bcs_db_api::{
    DbCountExpectation, DbPlugin, DbRow, DbSqlFlavor, DbStatementBuilder, DbTransactionStep,
    DbTransactionStepResult,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

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
    delivery_request_id: String,
    provider_run_id: String,
    provider_id: String,
    provider_bot_ref: String,
    status: String,
    plan_id: Option<String>,
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
    let correlation = read_correlation(
        state.db.as_ref(),
        &tenant_id,
        &request.project_id,
        &request.workspace_id,
        &correlation_id,
    )
    .await?
    .ok_or(ApiError::NotFound)?;

    let terminal_status = terminal_status(&request.execution_status)?;
    let report_hash = canonical_json_hash(&request.report)?;
    let terminal_id = format!("runtime-terminal-{correlation_id}");
    let outbox_id = format!("runtime-outbox-{correlation_id}");
    let plan_event_id = format!("runtime-plan-event-{correlation_id}");
    let idempotency_key = format!("runtime-terminal:{correlation_id}");
    let payload = terminal_payload(&correlation, &request, terminal_status, &report_hash);
    let metadata = json!({"report_hash": &report_hash});

    let mut steps = vec![DbTransactionStep::Execute(build_authority_revision_update(
        &correlation,
        &idempotency_key,
    ))];
    if correlation.plan_id.is_some() {
        steps.push(DbTransactionStep::Execute(build_plan_event_insert(
            &correlation,
            &plan_event_id,
            &payload,
            &idempotency_key,
        )?));
    }
    steps.push(DbTransactionStep::Execute(build_outbox_insert(
        &correlation,
        &outbox_id,
        &idempotency_key,
        terminal_status,
        &payload,
        &metadata,
    )?));
    if correlation.plan_id.is_some() {
        steps.push(DbTransactionStep::Execute(build_terminal_insert(
            &correlation,
            &terminal_id,
            &outbox_id,
            &request,
            terminal_status,
            &report_hash,
        )));
    }
    steps.push(DbTransactionStep::Execute(
        build_correlation_terminal_update(&correlation_id, terminal_status),
    ));
    let final_query_index = steps.len();
    steps.push(DbTransactionStep::QueryChecked {
        statement: build_terminal_result_select(&correlation_id, &idempotency_key),
        expected_rows: DbCountExpectation::exactly(1),
    });

    let results = state
        .db
        .transaction(steps)
        .await
        .map_err(ApiError::Database)?;
    let row = transaction_row(&results, final_query_index)?
        .ok_or_else(|| ApiError::InvalidDatabase("terminal result is missing".to_string()))?;
    let stored_status = required_string(row, "status")?;
    let stored_outbox_id = required_string(row, "outbox_id")?;
    let stored_hash = required_string(row, "report_hash")?;
    let stored_terminal_id = optional_string(row, "terminal_id")?;
    if stored_status != terminal_status
        || stored_outbox_id != outbox_id
        || stored_hash != report_hash
        || (correlation.plan_id.is_some()
            && stored_terminal_id.as_deref() != Some(terminal_id.as_str()))
    {
        return Err(ApiError::Conflict(
            "Runtime terminal idempotency key was reused with different content".to_string(),
        ));
    }
    let created = affected_rows(&results, 0)? > 0;
    Ok(Json(RuntimeTerminalResponse {
        correlation_id,
        status: stored_status,
        outbox_id: stored_outbox_id,
        terminal_id: stored_terminal_id,
        report_hash: stored_hash,
        created,
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
    let idempotency_key = format!("runtime-terminal:{correlation_id}");
    let rows = state
        .db
        .query(build_terminal_read_select(
            &correlation_id,
            &tenant_id,
            &query.project_id,
            &query.workspace_id,
            &idempotency_key,
        ))
        .await
        .map_err(ApiError::Database)?;
    let row = rows.first().ok_or(ApiError::NotFound)?;
    let status = required_string(row, "status")?;
    let payload_status = required_string(row, "execution_status")?;
    let report = required_json(row, "report_json")?;
    let report_hash = required_string(row, "report_hash")?;
    if !matches!(
        status.as_str(),
        STATUS_COMPLETED | STATUS_FAILED | STATUS_ABORTED
    ) || payload_status != status
        || canonical_json_hash(&report)? != report_hash
    {
        return Err(ApiError::InvalidDatabase(
            "persisted runtime terminal proof is inconsistent".to_string(),
        ));
    }
    Ok(Json(RuntimeTerminalReadResponse {
        correlation_id: required_string(row, "correlation_id")?,
        status,
        outbox_id: required_string(row, "outbox_id")?,
        terminal_id: optional_string(row, "terminal_id")?,
        terminal_message_id: required_string(row, "terminal_message_id")?,
        terminal_event_id: required_string(row, "terminal_event_id")?,
        report,
        report_hash,
        persisted: true,
    }))
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

async fn read_correlation(
    db: &dyn DbPlugin,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
    correlation_id: &str,
) -> Result<Option<RuntimeCorrelationRecord>, ApiError> {
    let statement = DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static(
            "SELECT correlation_id, tenant_id, project_id, workspace_id, user_id, \
             conversation_id, bcs_group_id, delivery_request_id, provider_run_id, provider_id, \
             provider_bot_ref, status, plan_id \
             FROM workspace_agent_runtime_correlations WHERE correlation_id = ",
        )
        .bind(correlation_id)
        .push_static(" AND tenant_id = ")
        .bind(tenant_id)
        .push_static(" AND project_id = ")
        .bind(project_id)
        .push_static(" AND workspace_id = ")
        .bind(workspace_id)
        .build();
    let rows = db.query(statement).await.map_err(ApiError::Database)?;
    rows.first().map(correlation_from_row).transpose()
}

fn build_authority_revision_update(
    correlation: &RuntimeCorrelationRecord,
    idempotency_key: &str,
) -> bcs_db_api::DbStatement {
    DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static(
            "UPDATE workspace_authorities SET revision = revision + 1, \
             updated_at = CURRENT_TIMESTAMP WHERE tenant_id = ",
        )
        .bind(correlation.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(correlation.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(correlation.workspace_id.as_str())
        .push_static(
            " AND NOT EXISTS (SELECT 1 FROM workspace_outbox \
             WHERE workspace_id = ",
        )
        .bind(correlation.workspace_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(idempotency_key)
        .push_static(")")
        .build()
}

fn build_plan_event_insert(
    correlation: &RuntimeCorrelationRecord,
    event_id: &str,
    payload: &Value,
    idempotency_key: &str,
) -> Result<bcs_db_api::DbStatement, ApiError> {
    let payload_json = serde_json::to_string(payload).map_err(ApiError::Json)?;
    Ok(DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static(
            "INSERT INTO workspace_plan_events (event_id, tenant_id, project_id, workspace_id, \
             plan_id, event_sequence, node_id, attempt_id, event_type, source, payload_json) \
             SELECT ",
        )
        .bind(event_id)
        .push_static(
            ", c.tenant_id, c.project_id, c.workspace_id, c.plan_id, \
             COALESCE((SELECT MAX(event_sequence) + 1 FROM workspace_plan_events \
             WHERE plan_id = c.plan_id), 0), c.plan_node_id, c.attempt_id, \
             'agent_runtime_terminal', 'avernet_provider', ",
        )
        .bind(payload_json)
        .push_static(
            "::jsonb FROM workspace_agent_runtime_correlations c \
             WHERE c.correlation_id = ",
        )
        .bind(correlation.correlation_id.as_str())
        .push_static(
            " AND c.plan_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM workspace_outbox \
             WHERE workspace_id = c.workspace_id AND idempotency_key = ",
        )
        .bind(idempotency_key)
        .push_static(") ON CONFLICT (event_id) DO NOTHING")
        .build())
}

#[allow(clippy::too_many_arguments)]
fn build_outbox_insert(
    correlation: &RuntimeCorrelationRecord,
    outbox_id: &str,
    idempotency_key: &str,
    terminal_status: &str,
    payload: &Value,
    metadata: &Value,
) -> Result<bcs_db_api::DbStatement, ApiError> {
    let payload_json = serde_json::to_string(payload).map_err(ApiError::Json)?;
    let metadata_json = serde_json::to_string(metadata).map_err(ApiError::Json)?;
    let event_type = match terminal_status {
        STATUS_COMPLETED => "workspace.execution.completed",
        STATUS_FAILED => "workspace.execution.failed",
        STATUS_ABORTED => "workspace.execution.aborted",
        _ => {
            return Err(ApiError::InvalidRequest(
                "invalid terminal status".to_string(),
            ));
        }
    };
    Ok(DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static(
            "INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, \
             aggregate_type, aggregate_id, event_type, stream_name, event_sequence, \
             payload_json, metadata_json, correlation_id, idempotency_key) SELECT ",
        )
        .bind(outbox_id)
        .push_static(", c.tenant_id, c.project_id, c.workspace_id, 'agent_runtime', ")
        .bind(correlation.correlation_id.as_str())
        .push_static(", ")
        .bind(event_type)
        .push_static(", ")
        .bind(format!("workspace:{}:events", correlation.workspace_id))
        .push_static(", a.revision, ")
        .bind(payload_json)
        .push_static("::jsonb, ")
        .bind(metadata_json)
        .push_static("::jsonb, ")
        .bind(correlation.correlation_id.as_str())
        .push_static(", ")
        .bind(idempotency_key)
        .push_static(
            " FROM workspace_agent_runtime_correlations c JOIN workspace_authorities a \
             ON a.tenant_id = c.tenant_id AND a.project_id = c.project_id \
             AND a.workspace_id = c.workspace_id WHERE c.correlation_id = ",
        )
        .bind(correlation.correlation_id.as_str())
        .push_static(" ON CONFLICT (workspace_id, idempotency_key) DO NOTHING")
        .build())
}

fn build_terminal_insert(
    correlation: &RuntimeCorrelationRecord,
    terminal_id: &str,
    outbox_id: &str,
    request: &RuntimeTerminalRequest,
    terminal_status: &str,
    report_hash: &str,
) -> bcs_db_api::DbStatement {
    DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static(
            "INSERT INTO workspace_execution_terminals (terminal_id, tenant_id, project_id, \
             workspace_id, correlation_id, execution_status, terminal_message_id, \
             terminal_event_id, plan_event_id, completion_outbox_id, report_hash, \
             completed_at) SELECT ",
        )
        .bind(terminal_id)
        .push_static(", tenant_id, project_id, workspace_id, correlation_id, ")
        .bind(terminal_status)
        .push_static(", ")
        .bind(request.terminal_message_id.as_str())
        .push_static(", ")
        .bind(request.terminal_event_id.as_str())
        .push_static(", ")
        .bind(format!("runtime-plan-event-{}", correlation.correlation_id))
        .push_static(", ")
        .bind(outbox_id)
        .push_static(", ")
        .bind(report_hash)
        .push_static(
            ", CURRENT_TIMESTAMP FROM workspace_agent_runtime_correlations \
             WHERE correlation_id = ",
        )
        .bind(correlation.correlation_id.as_str())
        .push_static(" AND plan_id IS NOT NULL ON CONFLICT (correlation_id) DO NOTHING")
        .build()
}

fn build_correlation_terminal_update(
    correlation_id: &str,
    terminal_status: &str,
) -> bcs_db_api::DbStatement {
    DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static("UPDATE workspace_agent_runtime_correlations SET status = ")
        .bind(terminal_status)
        .push_static(
            ", completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP), \
             recovery_lease_owner = NULL, recovery_lease_expires_at = NULL, \
             recovery_disposition = 'terminal', updated_at = CURRENT_TIMESTAMP \
             WHERE correlation_id = ",
        )
        .bind(correlation_id)
        .push_static(" AND status IN ('pending', 'running', ")
        .bind(terminal_status)
        .push_static(")")
        .build()
}

fn build_terminal_result_select(
    correlation_id: &str,
    idempotency_key: &str,
) -> bcs_db_api::DbStatement {
    DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static(
            "SELECT c.status, o.outbox_id, t.terminal_id, \
             o.metadata_json->>'report_hash' AS report_hash \
             FROM workspace_agent_runtime_correlations c JOIN workspace_outbox o \
             ON o.correlation_id = c.correlation_id LEFT JOIN workspace_execution_terminals t \
             ON t.correlation_id = c.correlation_id WHERE c.correlation_id = ",
        )
        .bind(correlation_id)
        .push_static(" AND o.idempotency_key = ")
        .bind(idempotency_key)
        .build()
}

fn build_terminal_read_select(
    correlation_id: &str,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
    idempotency_key: &str,
) -> bcs_db_api::DbStatement {
    DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static(
            "SELECT c.correlation_id, c.status, o.outbox_id, t.terminal_id, \
             o.payload_json->>'execution_status' AS execution_status, \
             o.payload_json->>'terminal_message_id' AS terminal_message_id, \
             o.payload_json->>'terminal_event_id' AS terminal_event_id, \
             o.payload_json->'report' AS report_json, \
             o.metadata_json->>'report_hash' AS report_hash \
             FROM workspace_agent_runtime_correlations c JOIN workspace_outbox o \
             ON o.correlation_id = c.correlation_id LEFT JOIN workspace_execution_terminals t \
             ON t.correlation_id = c.correlation_id WHERE c.correlation_id = ",
        )
        .bind(correlation_id)
        .push_static(" AND c.tenant_id = ")
        .bind(tenant_id)
        .push_static(" AND c.project_id = ")
        .bind(project_id)
        .push_static(" AND c.workspace_id = ")
        .bind(workspace_id)
        .push_static(" AND o.idempotency_key = ")
        .bind(idempotency_key)
        .build()
}

fn terminal_payload(
    correlation: &RuntimeCorrelationRecord,
    request: &RuntimeTerminalRequest,
    status: &str,
    report_hash: &str,
) -> Value {
    json!({
        "correlation_id": &correlation.correlation_id,
        "provider_run_id": &correlation.provider_run_id,
        "delivery_request_id": &correlation.delivery_request_id,
        "conversation_id": &correlation.conversation_id,
        "execution_status": status,
        "terminal_message_id": &request.terminal_message_id,
        "terminal_event_id": &request.terminal_event_id,
        "report_hash": report_hash,
        "report": &request.report,
    })
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

fn canonical_json_hash(value: &Value) -> Result<String, ApiError> {
    let canonical = canonical_json(value);
    let bytes = serde_json::to_vec(&canonical).map_err(ApiError::Json)?;
    Ok(hex::encode(Sha256::digest(bytes)))
}

fn canonical_json(value: &Value) -> Value {
    match value {
        Value::Array(items) => Value::Array(items.iter().map(canonical_json).collect()),
        Value::Object(items) => {
            let sorted = items
                .iter()
                .map(|(key, value)| (key.clone(), canonical_json(value)))
                .collect::<BTreeMap<_, _>>();
            Value::Object(sorted.into_iter().collect())
        }
        _ => value.clone(),
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
        delivery_request_id: required_string(row, "delivery_request_id")?,
        provider_run_id: required_string(row, "provider_run_id")?,
        provider_id: required_string(row, "provider_id")?,
        provider_bot_ref: required_string(row, "provider_bot_ref")?,
        status: required_string(row, "status")?,
        plan_id: optional_string(row, "plan_id")?,
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

fn optional_string(row: &DbRow, name: &str) -> Result<Option<String>, ApiError> {
    row.get_string(name).map_err(ApiError::Database)
}

fn required_json(row: &DbRow, name: &str) -> Result<Value, ApiError> {
    let value = required_string(row, name)?;
    serde_json::from_str(&value).map_err(ApiError::Json)
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_hash_is_stable_for_object_key_order() -> Result<(), ApiError> {
        let left = json!({"b": 2, "a": {"d": 4, "c": 3}});
        let right = json!({"a": {"c": 3, "d": 4}, "b": 2});

        assert_eq!(canonical_json_hash(&left)?, canonical_json_hash(&right)?);
        Ok(())
    }

    #[test]
    fn terminal_status_is_structurally_bounded() {
        assert_eq!(terminal_status("complete").ok(), Some(STATUS_COMPLETED));
        assert_eq!(terminal_status("error").ok(), Some(STATUS_FAILED));
        assert!(terminal_status("subjective_guess").is_err());
    }
}
