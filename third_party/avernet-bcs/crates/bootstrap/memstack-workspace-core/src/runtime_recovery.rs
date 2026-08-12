//! Deterministic leases and auditable Agent judgments for runtime recovery.

use std::sync::Arc;

use axum::Json;
use axum::extract::{Extension, Path};
use axum::http::HeaderMap;
use bcs_db_api::{
    DbRow, DbSqlFlavor, DbStatementBuilder, DbTransactionStep, DbTransactionStepResult,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use super::{ApiError, TENANT_HEADER, WorkspaceCoreState, required_header};

const STATUS_RUNNING: &str = "running";
const STATUS_COMPLETED: &str = "completed";
const STATUS_FAILED: &str = "failed";
const STATUS_ABORTED: &str = "aborted";
const MAX_STALE_AFTER_SECONDS: u64 = 86_400;
const MAX_LEASE_SECONDS: u64 = 3_600;
const MAX_CLAIM_LIMIT: u32 = 100;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RuntimeRecoveryClaimRequest {
    lease_owner: String,
    stale_after_seconds: u64,
    lease_seconds: u64,
    limit: u32,
}

#[derive(Debug, Serialize)]
pub(super) struct RuntimeRecoveryClaimResponse {
    recoveries: Vec<RuntimeRecoveryItem>,
}

#[derive(Debug, Serialize)]
struct RuntimeRecoveryItem {
    correlation_id: String,
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    user_id: String,
    task_id: Option<String>,
    plan_id: Option<String>,
    plan_node_id: Option<String>,
    conversation_id: String,
    bcs_session_id: String,
    bcs_group_id: String,
    delivery_request_id: String,
    provider_run_id: String,
    provider_id: String,
    provider_bot_ref: String,
    status: String,
    recovery_attempt_count: u64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RuntimeCallbackAckRequest {
    project_id: String,
    workspace_id: String,
}

#[derive(Debug, Serialize)]
pub(super) struct RuntimeCallbackAckResponse {
    correlation_id: String,
    status: String,
    acknowledged: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RuntimeRecoveryJudgmentRequest {
    audit_id: String,
    project_id: String,
    workspace_id: String,
    lease_owner: String,
    action: String,
    agent_id: String,
    tool_name: String,
    input_json: Value,
    output_json: Value,
    rationale: String,
    latency_ms: u64,
}

#[derive(Debug, Serialize)]
pub(super) struct RuntimeRecoveryJudgmentResponse {
    audit_id: String,
    correlation_id: String,
    action: String,
    recorded: bool,
}

pub(super) async fn claim_runtime_recoveries(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Json(request): Json<RuntimeRecoveryClaimRequest>,
) -> Result<Json<RuntimeRecoveryClaimResponse>, ApiError> {
    validate_claim_request(&request)?;
    let rows = state
        .db
        .query(build_recovery_claim(&request))
        .await
        .map_err(ApiError::Database)?;
    let recoveries = rows
        .iter()
        .map(recovery_from_row)
        .collect::<Result<Vec<_>, _>>()?;
    Ok(Json(RuntimeRecoveryClaimResponse { recoveries }))
}

pub(super) async fn acknowledge_runtime_callback(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path(correlation_id): Path<String>,
    headers: HeaderMap,
    Json(request): Json<RuntimeCallbackAckRequest>,
) -> Result<Json<RuntimeCallbackAckResponse>, ApiError> {
    let tenant_id = required_header(&headers, TENANT_HEADER)?;
    for (name, value) in [
        ("correlation_id", correlation_id.as_str()),
        ("project_id", request.project_id.as_str()),
        ("workspace_id", request.workspace_id.as_str()),
    ] {
        validate_required(name, value)?;
    }
    let rows = state
        .db
        .query(build_callback_ack(
            &correlation_id,
            &tenant_id,
            &request.project_id,
            &request.workspace_id,
        ))
        .await
        .map_err(ApiError::Database)?;
    let row = rows.first().ok_or(ApiError::NotFound)?;
    let status = required_string(row, "status")?;
    if !is_terminal_status(&status) {
        return Err(ApiError::InvalidDatabase(
            "callback acknowledgement returned a non-terminal status".to_string(),
        ));
    }
    Ok(Json(RuntimeCallbackAckResponse {
        correlation_id: required_string(row, "correlation_id")?,
        status,
        acknowledged: true,
    }))
}

pub(super) async fn record_runtime_recovery_judgment(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path(correlation_id): Path<String>,
    headers: HeaderMap,
    Json(request): Json<RuntimeRecoveryJudgmentRequest>,
) -> Result<Json<RuntimeRecoveryJudgmentResponse>, ApiError> {
    let tenant_id = required_header(&headers, TENANT_HEADER)?;
    validate_judgment_request(&correlation_id, &request)?;
    let results = state
        .db
        .transaction(vec![
            DbTransactionStep::Execute(build_judgment_insert(
                &correlation_id,
                &tenant_id,
                &request,
            )?),
            DbTransactionStep::Execute(build_judgment_release(
                &correlation_id,
                &tenant_id,
                &request,
            )),
            DbTransactionStep::Query(build_judgment_select(
                &correlation_id,
                &tenant_id,
                &request.audit_id,
            )),
        ])
        .await
        .map_err(ApiError::Database)?;
    let row = transaction_row(&results, 2)?.ok_or(ApiError::NotFound)?;
    let stored_action = required_string(row, "status")?;
    let stored_agent_id = required_string(row, "agent_id")?;
    let stored_tool_name = required_string(row, "tool_name")?;
    if stored_action != request.action
        || stored_agent_id != request.agent_id
        || stored_tool_name != request.tool_name
    {
        return Err(ApiError::Conflict(
            "Runtime recovery audit id was reused with different content".to_string(),
        ));
    }
    Ok(Json(RuntimeRecoveryJudgmentResponse {
        audit_id: required_string(row, "audit_id")?,
        correlation_id,
        action: stored_action,
        recorded: true,
    }))
}

fn build_recovery_claim(request: &RuntimeRecoveryClaimRequest) -> bcs_db_api::DbStatement {
    DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static(
            "WITH candidates AS (SELECT correlation_id FROM \
             workspace_agent_runtime_correlations WHERE ((status = 'running') OR \
             (status IN ('completed', 'failed', 'aborted') AND callback_completed_at IS NULL)) \
             AND updated_at <= CURRENT_TIMESTAMP - (CAST(",
        )
        .bind(request.stale_after_seconds)
        .push_static(
            " AS BIGINT) * INTERVAL '1 second') AND user_id IS NOT NULL \
             AND bcs_group_id IS NOT NULL AND provider_id IS NOT NULL \
             AND (recovery_lease_expires_at IS NULL OR \
             recovery_lease_expires_at <= CURRENT_TIMESTAMP) ORDER BY updated_at, correlation_id \
             FOR UPDATE SKIP LOCKED LIMIT ",
        )
        .bind(request.limit)
        .push_static(") UPDATE workspace_agent_runtime_correlations c SET recovery_lease_owner = ")
        .bind(request.lease_owner.as_str())
        .push_static(", recovery_lease_expires_at = CURRENT_TIMESTAMP + (CAST(")
        .bind(request.lease_seconds)
        .push_static(
            " AS BIGINT) * INTERVAL '1 second'), recovery_attempt_count = \
             recovery_attempt_count + 1 FROM candidates WHERE c.correlation_id = \
             candidates.correlation_id RETURNING c.correlation_id, c.tenant_id, c.project_id, \
             c.workspace_id, c.user_id, c.task_id, c.plan_id, c.plan_node_id, c.conversation_id, \
             c.bcs_session_id, c.bcs_group_id, c.delivery_request_id, c.provider_run_id, \
             c.provider_id, c.provider_bot_ref, c.status, c.recovery_attempt_count",
        )
        .build()
}

fn build_callback_ack(
    correlation_id: &str,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
) -> bcs_db_api::DbStatement {
    DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static(
            "UPDATE workspace_agent_runtime_correlations SET callback_completed_at = \
             COALESCE(callback_completed_at, CURRENT_TIMESTAMP), callback_attempt_count = \
             callback_attempt_count + 1, recovery_lease_owner = NULL, \
             recovery_lease_expires_at = NULL, updated_at = CURRENT_TIMESTAMP \
             WHERE correlation_id = ",
        )
        .bind(correlation_id)
        .push_static(" AND tenant_id = ")
        .bind(tenant_id)
        .push_static(" AND project_id = ")
        .bind(project_id)
        .push_static(" AND workspace_id = ")
        .bind(workspace_id)
        .push_static(
            " AND status IN ('completed', 'failed', 'aborted') \
             RETURNING correlation_id, status",
        )
        .build()
}

fn build_judgment_insert(
    correlation_id: &str,
    tenant_id: &str,
    request: &RuntimeRecoveryJudgmentRequest,
) -> Result<bcs_db_api::DbStatement, ApiError> {
    let input_json = serde_json::to_string(&request.input_json).map_err(ApiError::Json)?;
    let output_json = serde_json::to_string(&request.output_json).map_err(ApiError::Json)?;
    Ok(DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static(
            "INSERT INTO workspace_judge_audits (audit_id, tenant_id, project_id, workspace_id, \
             plan_id, plan_node_id, judgment_type, agent_id, tool_name, input_json, output_json, \
             rationale, latency_ms, status) SELECT ",
        )
        .bind(request.audit_id.as_str())
        .push_static(
            ", c.tenant_id, c.project_id, c.workspace_id, c.plan_id, c.plan_node_id, \
             'runtime_recovery', ",
        )
        .bind(request.agent_id.as_str())
        .push_static(", ")
        .bind(request.tool_name.as_str())
        .push_static(", ")
        .bind(input_json)
        .push_static("::jsonb, ")
        .bind(output_json)
        .push_static("::jsonb, ")
        .bind(request.rationale.as_str())
        .push_static(", ")
        .bind(request.latency_ms)
        .push_static(", ")
        .bind(request.action.as_str())
        .push_static(" FROM workspace_agent_runtime_correlations c WHERE c.correlation_id = ")
        .bind(correlation_id)
        .push_static(" AND c.tenant_id = ")
        .bind(tenant_id)
        .push_static(" AND c.project_id = ")
        .bind(request.project_id.as_str())
        .push_static(" AND c.workspace_id = ")
        .bind(request.workspace_id.as_str())
        .push_static(" AND c.status = 'running' AND c.recovery_lease_owner = ")
        .bind(request.lease_owner.as_str())
        .push_static(" ON CONFLICT (audit_id) DO NOTHING")
        .build())
}

fn build_judgment_release(
    correlation_id: &str,
    tenant_id: &str,
    request: &RuntimeRecoveryJudgmentRequest,
) -> bcs_db_api::DbStatement {
    DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static("UPDATE workspace_agent_runtime_correlations SET recovery_disposition = ")
        .bind(request.action.as_str())
        .push_static(
            ", recovery_lease_owner = NULL, recovery_lease_expires_at = NULL, \
             updated_at = CURRENT_TIMESTAMP WHERE correlation_id = ",
        )
        .bind(correlation_id)
        .push_static(" AND tenant_id = ")
        .bind(tenant_id)
        .push_static(" AND project_id = ")
        .bind(request.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(request.workspace_id.as_str())
        .push_static(" AND status = 'running' AND recovery_lease_owner = ")
        .bind(request.lease_owner.as_str())
        .build()
}

fn build_judgment_select(
    correlation_id: &str,
    tenant_id: &str,
    audit_id: &str,
) -> bcs_db_api::DbStatement {
    DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static(
            "SELECT a.audit_id, a.agent_id, a.tool_name, a.status FROM workspace_judge_audits a \
             JOIN workspace_agent_runtime_correlations c ON c.tenant_id = a.tenant_id \
             AND c.project_id = a.project_id AND c.workspace_id = a.workspace_id \
             WHERE a.audit_id = ",
        )
        .bind(audit_id)
        .push_static(" AND a.tenant_id = ")
        .bind(tenant_id)
        .push_static(" AND c.correlation_id = ")
        .bind(correlation_id)
        .build()
}

fn validate_claim_request(request: &RuntimeRecoveryClaimRequest) -> Result<(), ApiError> {
    validate_required("lease_owner", &request.lease_owner)?;
    if request.stale_after_seconds == 0 || request.stale_after_seconds > MAX_STALE_AFTER_SECONDS {
        return Err(ApiError::InvalidRequest(
            "stale_after_seconds must be in 1..=86400".to_string(),
        ));
    }
    if request.lease_seconds == 0 || request.lease_seconds > MAX_LEASE_SECONDS {
        return Err(ApiError::InvalidRequest(
            "lease_seconds must be in 1..=3600".to_string(),
        ));
    }
    if request.limit == 0 || request.limit > MAX_CLAIM_LIMIT {
        return Err(ApiError::InvalidRequest(
            "limit must be in 1..=100".to_string(),
        ));
    }
    Ok(())
}

fn validate_judgment_request(
    correlation_id: &str,
    request: &RuntimeRecoveryJudgmentRequest,
) -> Result<(), ApiError> {
    for (name, value) in [
        ("correlation_id", correlation_id),
        ("audit_id", request.audit_id.as_str()),
        ("project_id", request.project_id.as_str()),
        ("workspace_id", request.workspace_id.as_str()),
        ("lease_owner", request.lease_owner.as_str()),
        ("agent_id", request.agent_id.as_str()),
        ("tool_name", request.tool_name.as_str()),
        ("rationale", request.rationale.as_str()),
    ] {
        validate_required(name, value)?;
    }
    if request.tool_name != "decide_runtime_recovery" {
        return Err(ApiError::InvalidRequest(
            "tool_name must be decide_runtime_recovery".to_string(),
        ));
    }
    if !matches!(request.action.as_str(), "continue" | "fail" | "escalate") {
        return Err(ApiError::InvalidRequest(
            "action must be continue, fail, or escalate".to_string(),
        ));
    }
    if !request.input_json.is_object() || !request.output_json.is_object() {
        return Err(ApiError::InvalidRequest(
            "judgment input_json and output_json must be JSON objects".to_string(),
        ));
    }
    Ok(())
}

fn recovery_from_row(row: &DbRow) -> Result<RuntimeRecoveryItem, ApiError> {
    let status = required_string(row, "status")?;
    if status != STATUS_RUNNING && !is_terminal_status(&status) {
        return Err(ApiError::InvalidDatabase(
            "recovery claim returned an unsupported status".to_string(),
        ));
    }
    let recovery_attempt_count = row
        .get_i64("recovery_attempt_count")
        .map_err(ApiError::Database)?
        .and_then(|value| u64::try_from(value).ok())
        .ok_or_else(|| {
            ApiError::InvalidDatabase("recovery_attempt_count is missing or negative".to_string())
        })?;
    Ok(RuntimeRecoveryItem {
        correlation_id: required_string(row, "correlation_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        user_id: required_string(row, "user_id")?,
        task_id: optional_string(row, "task_id")?,
        plan_id: optional_string(row, "plan_id")?,
        plan_node_id: optional_string(row, "plan_node_id")?,
        conversation_id: required_string(row, "conversation_id")?,
        bcs_session_id: required_string(row, "bcs_session_id")?,
        bcs_group_id: required_string(row, "bcs_group_id")?,
        delivery_request_id: required_string(row, "delivery_request_id")?,
        provider_run_id: required_string(row, "provider_run_id")?,
        provider_id: required_string(row, "provider_id")?,
        provider_bot_ref: required_string(row, "provider_bot_ref")?,
        status,
        recovery_attempt_count,
    })
}

fn is_terminal_status(status: &str) -> bool {
    matches!(status, STATUS_COMPLETED | STATUS_FAILED | STATUS_ABORTED)
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

fn required_string(row: &DbRow, name: &str) -> Result<String, ApiError> {
    row.get_string(name)
        .map_err(ApiError::Database)?
        .ok_or_else(|| ApiError::InvalidDatabase(format!("{name} is missing")))
}

fn optional_string(row: &DbRow, name: &str) -> Result<Option<String>, ApiError> {
    row.get_string(name).map_err(ApiError::Database)
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
    fn claim_bounds_are_structural() {
        let valid = RuntimeRecoveryClaimRequest {
            lease_owner: "worker-1".to_string(),
            stale_after_seconds: 60,
            lease_seconds: 30,
            limit: 20,
        };
        assert!(validate_claim_request(&valid).is_ok());

        let invalid = RuntimeRecoveryClaimRequest { limit: 0, ..valid };
        assert!(validate_claim_request(&invalid).is_err());
    }

    #[test]
    fn judgment_action_is_closed_and_tool_bound() {
        let request = RuntimeRecoveryJudgmentRequest {
            audit_id: "audit-1".to_string(),
            project_id: "project-1".to_string(),
            workspace_id: "workspace-1".to_string(),
            lease_owner: "worker-1".to_string(),
            action: "continue".to_string(),
            agent_id: "agent-1".to_string(),
            tool_name: "decide_runtime_recovery".to_string(),
            input_json: serde_json::json!({}),
            output_json: serde_json::json!({"action": "continue"}),
            rationale: "execution may still be active".to_string(),
            latency_ms: 1,
        };
        assert!(validate_judgment_request("correlation-1", &request).is_ok());

        let invalid = RuntimeRecoveryJudgmentRequest {
            action: "guess".to_string(),
            ..request
        };
        assert!(validate_judgment_request("correlation-1", &invalid).is_err());
    }
}
