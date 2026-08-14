//! Dialect-aware SQL and persisted row validation for Runtime terminal convergence.

use std::collections::BTreeMap;

use bcs_db_api::{DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder, DbTransactionStepResult};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use super::{
    WorkspaceRuntimeTerminalOutcome, WorkspaceRuntimeTerminalScope,
    WorkspaceRuntimeTerminalStoreError, WorkspaceRuntimeTerminalWrite,
};

const STATUS_COMPLETED: &str = "completed";
const STATUS_FAILED: &str = "failed";
const STATUS_ABORTED: &str = "aborted";
const WORKSPACE_RUNTIME_PROVIDER_ID: &str = "memstack-workspace-agent-runtime";

#[derive(Debug)]
pub(super) struct RuntimeCorrelation {
    correlation_id: String,
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    conversation_id: String,
    delivery_request_id: String,
    provider_run_id: String,
    pub(super) task_id: Option<String>,
    pub(super) attempt_id: Option<String>,
    pub(super) plan_id: Option<String>,
}
pub(super) fn correlation_select(
    flavor: DbSqlFlavor,
    scope: &WorkspaceRuntimeTerminalScope,
    correlation_id: &str,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT correlation_id, tenant_id, project_id, workspace_id, conversation_id, \
             delivery_request_id, provider_run_id, task_id, attempt_id, plan_id FROM \
             workspace_agent_runtime_correlations WHERE correlation_id = ",
        )
        .bind(correlation_id)
        .push_static(" AND tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .build()
}

pub(super) fn authority_revision_update(
    flavor: DbSqlFlavor,
    correlation: &RuntimeCorrelation,
    idempotency_key: &str,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_authorities SET revision = revision + 1, \
             updated_at = CURRENT_TIMESTAMP WHERE tenant_id = ",
        )
        .bind(correlation.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(correlation.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(correlation.workspace_id.as_str())
        .push_static(" AND NOT EXISTS (SELECT 1 FROM workspace_outbox WHERE workspace_id = ")
        .bind(correlation.workspace_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(idempotency_key)
        .push_static(")")
        .build()
}

pub(super) fn task_terminal_update(
    flavor: DbSqlFlavor,
    correlation: &RuntimeCorrelation,
    task_id: &str,
    idempotency_key: &str,
    write: &WorkspaceRuntimeTerminalWrite,
) -> DbStatement {
    let target = task_status(write.execution_status.as_str());
    let builder = DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_tasks SET status = CASE WHEN NOT EXISTS (SELECT 1 FROM workspace_outbox WHERE workspace_id = ")
        .bind(correlation.workspace_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(idempotency_key)
        .push_static(") THEN ")
        .bind(target)
        .push_static(" ELSE status END, blocker_reason = CASE WHEN NOT EXISTS (SELECT 1 FROM workspace_outbox WHERE workspace_id = ")
        .bind(correlation.workspace_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(idempotency_key)
        .push_static(") THEN ")
        .bind(write.failure_reason.as_deref())
        .push_static(" ELSE blocker_reason END, updated_at = CASE WHEN NOT EXISTS (SELECT 1 FROM workspace_outbox WHERE workspace_id = ")
        .bind(correlation.workspace_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(idempotency_key)
        .push_static(") THEN CURRENT_TIMESTAMP ELSE updated_at END, completed_at = CASE WHEN NOT EXISTS (SELECT 1 FROM workspace_outbox WHERE workspace_id = ")
        .bind(correlation.workspace_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(idempotency_key);
    let builder = if target == "done" {
        builder
            .push_static(") THEN COALESCE(completed_at, CURRENT_TIMESTAMP) ELSE completed_at END")
    } else {
        builder.push_static(") THEN NULL ELSE completed_at END")
    };
    let builder = builder
        .push_static(" WHERE tenant_id = ")
        .bind(correlation.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(correlation.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(correlation.workspace_id.as_str())
        .push_static(" AND task_id = ")
        .bind(task_id);
    let builder = task_role_predicate(builder, flavor, "metadata_json");
    let builder = if let Some(attempt_id) = correlation.attempt_id.as_deref() {
        task_current_attempt_predicate(builder, flavor, "metadata_json", attempt_id)
    } else {
        builder
    };
    builder
        .push_static(" AND ((NOT EXISTS (SELECT 1 FROM workspace_outbox WHERE workspace_id = ")
        .bind(correlation.workspace_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(idempotency_key)
        .push_static(") AND status = 'in_progress') OR (EXISTS (SELECT 1 FROM workspace_outbox WHERE workspace_id = ")
        .bind(correlation.workspace_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(idempotency_key)
        .push_static(") AND status = ")
        .bind(target)
        .push_static("))")
        .build()
}

pub(super) fn attempt_terminal_update(
    flavor: DbSqlFlavor,
    correlation: &RuntimeCorrelation,
    attempt_id: &str,
    idempotency_key: &str,
    write: &WorkspaceRuntimeTerminalWrite,
) -> DbStatement {
    let target = attempt_status(write.execution_status.as_str());
    let builder = DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_task_attempts SET status = CASE WHEN NOT EXISTS (SELECT 1 FROM workspace_outbox WHERE workspace_id = ")
        .bind(correlation.workspace_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(idempotency_key)
        .push_static(") THEN ")
        .bind(target)
        .push_static(" ELSE status END, adjudication_reason = CASE WHEN NOT EXISTS (SELECT 1 FROM workspace_outbox WHERE workspace_id = ")
        .bind(correlation.workspace_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(idempotency_key)
        .push_static(") THEN ")
        .bind(write.failure_reason.as_deref())
        .push_static(" ELSE adjudication_reason END, updated_at = CASE WHEN NOT EXISTS (SELECT 1 FROM workspace_outbox WHERE workspace_id = ")
        .bind(correlation.workspace_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(idempotency_key)
        .push_static(") THEN CURRENT_TIMESTAMP ELSE updated_at END, completed_at = CASE WHEN NOT EXISTS (SELECT 1 FROM workspace_outbox WHERE workspace_id = ")
        .bind(correlation.workspace_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(idempotency_key)
        .push_static(") THEN COALESCE(completed_at, CURRENT_TIMESTAMP) ELSE completed_at END WHERE tenant_id = ")
        .bind(correlation.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(correlation.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(correlation.workspace_id.as_str())
        .push_static(" AND attempt_id = ")
        .bind(attempt_id)
        .push_static(" AND task_id = ")
        .bind(correlation.task_id.as_deref())
        .push_static(" AND ((NOT EXISTS (SELECT 1 FROM workspace_outbox WHERE workspace_id = ")
        .bind(correlation.workspace_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(idempotency_key)
        .push_static(") AND status IN ('pending', 'running', 'awaiting_leader_adjudication')) OR (EXISTS (SELECT 1 FROM workspace_outbox WHERE workspace_id = ")
        .bind(correlation.workspace_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(idempotency_key)
        .push_static(") AND status = ")
        .bind(target)
        .push_static(")) AND EXISTS (SELECT 1 FROM workspace_tasks task WHERE task.tenant_id = workspace_task_attempts.tenant_id AND task.project_id = workspace_task_attempts.project_id AND task.workspace_id = workspace_task_attempts.workspace_id AND task.task_id = workspace_task_attempts.task_id");
    let builder = task_role_predicate(builder, flavor, "task.metadata_json");
    task_attempt_authority_predicates(builder, flavor)
        .push_static(")")
        .build()
}

fn task_role_predicate(
    builder: DbStatementBuilder,
    flavor: DbSqlFlavor,
    metadata_column: &'static str,
) -> DbStatementBuilder {
    match flavor {
        DbSqlFlavor::Postgres => builder
            .push_static(" AND ")
            .push_static(metadata_column)
            .push_static(" ->> 'task_role' = 'execution_task'"),
        DbSqlFlavor::Sqlite => builder
            .push_static(" AND json_extract(")
            .push_static(metadata_column)
            .push_static(", '$.task_role') = 'execution_task'"),
        DbSqlFlavor::Mysql => builder.push_static(" AND 1 = 0"),
    }
}

fn task_current_attempt_predicate(
    builder: DbStatementBuilder,
    flavor: DbSqlFlavor,
    metadata_column: &'static str,
    attempt_id: &str,
) -> DbStatementBuilder {
    match flavor {
        DbSqlFlavor::Postgres => builder
            .push_static(" AND ")
            .push_static(metadata_column)
            .push_static(" ->> 'current_attempt_id' = ")
            .bind(attempt_id),
        DbSqlFlavor::Sqlite => builder
            .push_static(" AND json_extract(")
            .push_static(metadata_column)
            .push_static(", '$.current_attempt_id') = ")
            .bind(attempt_id),
        DbSqlFlavor::Mysql => builder.push_static(" AND 1 = 0"),
    }
}

fn task_attempt_authority_predicates(
    builder: DbStatementBuilder,
    flavor: DbSqlFlavor,
) -> DbStatementBuilder {
    match flavor {
        DbSqlFlavor::Postgres => builder.push_static(
            " AND task.metadata_json ->> 'current_attempt_id' = \
             workspace_task_attempts.attempt_id AND task.metadata_json ->> 'root_goal_task_id' = \
             workspace_task_attempts.root_goal_task_id",
        ),
        DbSqlFlavor::Sqlite => builder.push_static(
            " AND json_extract(task.metadata_json, '$.current_attempt_id') = \
             workspace_task_attempts.attempt_id AND json_extract(task.metadata_json, \
             '$.root_goal_task_id') = workspace_task_attempts.root_goal_task_id",
        ),
        DbSqlFlavor::Mysql => builder.push_static(" AND 1 = 0"),
    }
}

pub(super) fn plan_event_insert(
    flavor: DbSqlFlavor,
    correlation: &RuntimeCorrelation,
    event_id: &str,
    payload_json: &str,
    idempotency_key: &str,
) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_plan_events (event_id, tenant_id, project_id, workspace_id, \
             plan_id, event_sequence, node_id, attempt_id, event_type, source, payload_json) \
             SELECT ",
        )
        .bind(event_id)
        .push_static(", c.tenant_id, c.project_id, c.workspace_id, c.plan_id, COALESCE((SELECT MAX(event_sequence) + 1 FROM workspace_plan_events WHERE plan_id = c.plan_id), 0), c.plan_node_id, c.attempt_id, 'agent_runtime_terminal', 'avernet_provider', ");
    json_value(builder, flavor, payload_json)
        .push_static(" FROM workspace_agent_runtime_correlations c WHERE c.correlation_id = ")
        .bind(correlation.correlation_id.as_str())
        .push_static(" AND c.plan_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM workspace_outbox WHERE workspace_id = c.workspace_id AND idempotency_key = ")
        .bind(idempotency_key)
        .push_static(") ON CONFLICT (event_id) DO NOTHING")
        .build()
}

pub(super) struct RuntimeOutboxInsert<'a> {
    correlation: &'a RuntimeCorrelation,
    outbox_id: &'a str,
    idempotency_key: &'a str,
    terminal_status: &'a str,
    payload_json: &'a str,
    metadata_json: &'a str,
}

impl<'a> RuntimeOutboxInsert<'a> {
    pub(super) const fn new(
        correlation: &'a RuntimeCorrelation,
        outbox_id: &'a str,
        idempotency_key: &'a str,
        terminal_status: &'a str,
        payload_json: &'a str,
        metadata_json: &'a str,
    ) -> Self {
        Self {
            correlation,
            outbox_id,
            idempotency_key,
            terminal_status,
            payload_json,
            metadata_json,
        }
    }
}

pub(super) fn outbox_insert(
    flavor: DbSqlFlavor,
    insert: RuntimeOutboxInsert<'_>,
) -> Result<DbStatement, WorkspaceRuntimeTerminalStoreError> {
    let RuntimeOutboxInsert {
        correlation,
        outbox_id,
        idempotency_key,
        terminal_status,
        payload_json,
        metadata_json,
    } = insert;
    let event_type = match terminal_status {
        STATUS_COMPLETED => "workspace.execution.completed",
        STATUS_FAILED => "workspace.execution.failed",
        STATUS_ABORTED => "workspace.execution.aborted",
        _ => {
            return Err(WorkspaceRuntimeTerminalStoreError::InvalidRecord(
                "execution_status",
            ));
        }
    };
    let builder = DbStatementBuilder::new(flavor)
        .push_static("INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, metadata_json, correlation_id, idempotency_key) SELECT ")
        .bind(outbox_id)
        .push_static(", c.tenant_id, c.project_id, c.workspace_id, 'agent_runtime', ")
        .bind(correlation.correlation_id.as_str())
        .push_static(", ")
        .bind(event_type)
        .push_static(", ")
        .bind(format!("workspace:{}:events", correlation.workspace_id))
        .push_static(", a.revision, ");
    let builder = json_value(builder, flavor, payload_json).push_static(", ");
    let statement = json_value(builder, flavor, metadata_json)
        .push_static(", ")
        .bind(correlation.correlation_id.as_str())
        .push_static(", ")
        .bind(idempotency_key)
        .push_static(" FROM workspace_agent_runtime_correlations c JOIN workspace_authorities a ON a.tenant_id = c.tenant_id AND a.project_id = c.project_id AND a.workspace_id = c.workspace_id WHERE c.correlation_id = ")
        .bind(correlation.correlation_id.as_str())
        .push_static(" ON CONFLICT (workspace_id, idempotency_key) DO NOTHING")
        .build();
    Ok(statement)
}

pub(super) fn terminal_insert(
    flavor: DbSqlFlavor,
    correlation: &RuntimeCorrelation,
    terminal_id: &str,
    plan_event_id: &str,
    outbox_id: &str,
    write: &WorkspaceRuntimeTerminalWrite,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("INSERT INTO workspace_execution_terminals (terminal_id, tenant_id, project_id, workspace_id, correlation_id, execution_status, terminal_message_id, terminal_event_id, plan_event_id, completion_outbox_id, report_hash, completed_at) SELECT ")
        .bind(terminal_id)
        .push_static(", tenant_id, project_id, workspace_id, correlation_id, ")
        .bind(write.execution_status.as_str())
        .push_static(", ")
        .bind(write.terminal_message_id.as_str())
        .push_static(", ")
        .bind(write.terminal_event_id.as_str())
        .push_static(", ")
        .bind(plan_event_id)
        .push_static(", ")
        .bind(outbox_id)
        .push_static(", ")
        .bind(write.report_hash.as_str())
        .push_static(", CURRENT_TIMESTAMP FROM workspace_agent_runtime_correlations WHERE correlation_id = ")
        .bind(correlation.correlation_id.as_str())
        .push_static(" AND plan_id IS NOT NULL ON CONFLICT (correlation_id) DO NOTHING")
        .build()
}

pub(super) fn correlation_terminal_update(
    flavor: DbSqlFlavor,
    correlation_id: &str,
    terminal_status: &str,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_agent_runtime_correlations SET status = ")
        .bind(terminal_status)
        .push_static(", completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP), recovery_lease_owner = NULL, recovery_lease_expires_at = NULL, recovery_disposition = 'terminal', updated_at = CURRENT_TIMESTAMP WHERE correlation_id = ")
        .bind(correlation_id)
        .push_static(" AND status IN ('pending', 'running', ")
        .bind(terminal_status)
        .push_static(")")
        .build()
}

pub(super) fn terminal_result_select(
    flavor: DbSqlFlavor,
    selector: &'static str,
    value: &str,
    idempotency_key: &str,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("SELECT c.correlation_id, c.provider_run_id, c.delivery_request_id, c.status, c.provider_event_hash, c.provider_event_ingested_at, c.plan_id, c.task_id, c.attempt_id, o.outbox_id, o.payload_json, o.metadata_json, t.terminal_id, task.status AS task_status, attempt.status AS attempt_status FROM workspace_agent_runtime_correlations c JOIN workspace_outbox o ON o.correlation_id = c.correlation_id LEFT JOIN workspace_execution_terminals t ON t.correlation_id = c.correlation_id LEFT JOIN workspace_tasks task ON task.tenant_id = c.tenant_id AND task.project_id = c.project_id AND task.workspace_id = c.workspace_id AND task.task_id = c.task_id LEFT JOIN workspace_task_attempts attempt ON attempt.tenant_id = c.tenant_id AND attempt.project_id = c.project_id AND attempt.workspace_id = c.workspace_id AND attempt.attempt_id = c.attempt_id WHERE ")
        .push_static(selector)
        .push_static(" = ")
        .bind(value)
        .push_static(" AND o.idempotency_key = ")
        .bind(idempotency_key)
        .build()
}

pub(super) fn terminal_read_select(
    flavor: DbSqlFlavor,
    scope: &WorkspaceRuntimeTerminalScope,
    correlation_id: &str,
    idempotency_key: &str,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("SELECT c.correlation_id, c.provider_run_id, c.delivery_request_id, c.status, c.provider_event_hash, c.provider_event_ingested_at, c.plan_id, c.task_id, c.attempt_id, o.outbox_id, o.payload_json, o.metadata_json, t.terminal_id, task.status AS task_status, attempt.status AS attempt_status FROM workspace_agent_runtime_correlations c JOIN workspace_outbox o ON o.correlation_id = c.correlation_id LEFT JOIN workspace_execution_terminals t ON t.correlation_id = c.correlation_id LEFT JOIN workspace_tasks task ON task.tenant_id = c.tenant_id AND task.project_id = c.project_id AND task.workspace_id = c.workspace_id AND task.task_id = c.task_id LEFT JOIN workspace_task_attempts attempt ON attempt.tenant_id = c.tenant_id AND attempt.project_id = c.project_id AND attempt.workspace_id = c.workspace_id AND attempt.attempt_id = c.attempt_id WHERE c.correlation_id = ")
        .bind(correlation_id)
        .push_static(" AND o.idempotency_key = ")
        .bind(idempotency_key)
        .push_static(" AND c.tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND c.project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND c.workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .build()
}

pub(super) fn provider_terminal_select(flavor: DbSqlFlavor, provider_run_id: &str) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("SELECT c.correlation_id, c.provider_run_id, c.delivery_request_id, c.status, c.provider_event_hash, c.provider_event_ingested_at, c.plan_id, c.task_id, c.attempt_id, o.outbox_id, o.payload_json, o.metadata_json, t.terminal_id, task.status AS task_status, attempt.status AS attempt_status FROM workspace_agent_runtime_correlations c JOIN workspace_outbox o ON o.correlation_id = c.correlation_id AND o.idempotency_key = ")
        .bind(format!("runtime-terminal:{}", ""))
        .push_static(" || c.correlation_id LEFT JOIN workspace_execution_terminals t ON t.correlation_id = c.correlation_id LEFT JOIN workspace_tasks task ON task.tenant_id = c.tenant_id AND task.project_id = c.project_id AND task.workspace_id = c.workspace_id AND task.task_id = c.task_id LEFT JOIN workspace_task_attempts attempt ON attempt.tenant_id = c.tenant_id AND attempt.project_id = c.project_id AND attempt.workspace_id = c.workspace_id AND attempt.attempt_id = c.attempt_id WHERE c.provider_run_id = ")
        .bind(provider_run_id)
        .push_static(" AND c.provider_id = ")
        .bind(WORKSPACE_RUNTIME_PROVIDER_ID)
        .build()
}

pub(super) fn provider_event_hash_bind(
    flavor: DbSqlFlavor,
    provider_run_id: &str,
    expected_status: &str,
    expected_event_hash: &str,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_agent_runtime_correlations SET provider_event_hash = \
             COALESCE(provider_event_hash, ",
        )
        .bind(expected_event_hash)
        .push_static(") WHERE provider_run_id = ")
        .bind(provider_run_id)
        .push_static(" AND provider_id = ")
        .bind(WORKSPACE_RUNTIME_PROVIDER_ID)
        .push_static(" AND status = ")
        .bind(expected_status)
        .push_static(" AND (provider_event_hash IS NULL OR provider_event_hash = ")
        .bind(expected_event_hash)
        .push_static(")")
        .build()
}

pub(super) fn provider_event_ingested_update(
    flavor: DbSqlFlavor,
    provider_run_id: &str,
    expected_event_hash: &str,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_agent_runtime_correlations SET provider_event_ingested_at = \
             COALESCE(provider_event_ingested_at, CURRENT_TIMESTAMP), updated_at = \
             CURRENT_TIMESTAMP WHERE provider_run_id = ",
        )
        .bind(provider_run_id)
        .push_static(" AND provider_id = ")
        .bind(WORKSPACE_RUNTIME_PROVIDER_ID)
        .push_static(" AND status IN ('completed', 'failed', 'aborted') AND provider_event_hash = ")
        .bind(expected_event_hash)
        .build()
}

pub(super) fn terminal_payload(
    correlation: &RuntimeCorrelation,
    write: &WorkspaceRuntimeTerminalWrite,
) -> Value {
    json!({
        "correlation_id": &correlation.correlation_id,
        "provider_run_id": &correlation.provider_run_id,
        "delivery_request_id": &correlation.delivery_request_id,
        "conversation_id": &correlation.conversation_id,
        "execution_status": &write.execution_status,
        "terminal_message_id": &write.terminal_message_id,
        "terminal_event_id": &write.terminal_event_id,
        "report_hash": &write.report_hash,
        "report": &write.report,
    })
}

pub(super) fn outcome_from_row(
    row: &DbRow,
    expected: Option<&WorkspaceRuntimeTerminalWrite>,
    created: bool,
) -> Result<WorkspaceRuntimeTerminalOutcome, WorkspaceRuntimeTerminalStoreError> {
    let status = required_string(row, "status")?;
    let plan_id = optional_string(row, "plan_id")?;
    let task_id = optional_string(row, "task_id")?;
    let attempt_id = optional_string(row, "attempt_id")?;
    let task_status_value = optional_string(row, "task_status")?;
    let attempt_status_value = optional_string(row, "attempt_status")?;
    let terminal_id = optional_string(row, "terminal_id")?;
    let provider_event_hash = optional_string(row, "provider_event_hash")?;
    let provider_event_ingested = optional_string(row, "provider_event_ingested_at")?.is_some();
    let payload = required_json(row, "payload_json")?;
    let metadata = required_json(row, "metadata_json")?;
    let report = payload
        .get("report")
        .cloned()
        .ok_or(WorkspaceRuntimeTerminalStoreError::InvalidRecord("report"))?;
    let report_hash = json_string(&payload, "report_hash")?;
    let terminal_message_id = json_string(&payload, "terminal_message_id")?;
    let terminal_event_id = json_string(&payload, "terminal_event_id")?;
    if json_string(&payload, "execution_status")? != status
        || json_string(&metadata, "report_hash")? != report_hash
        || canonical_json_hash(&report)? != report_hash
        || task_id.is_some() != task_status_value.is_some()
        || attempt_id.is_some() != attempt_status_value.is_some()
        || task_status_value.as_deref() != task_id.as_ref().map(|_| task_status(&status))
        || attempt_status_value.as_deref() != attempt_id.as_ref().map(|_| attempt_status(&status))
        || plan_id.is_some() != terminal_id.is_some()
        || provider_event_hash
            .as_deref()
            .is_some_and(|hash| !is_sha256_hex(hash))
        || (provider_event_ingested && provider_event_hash.is_none())
    {
        return Err(WorkspaceRuntimeTerminalStoreError::InvalidRecord(
            "terminal convergence",
        ));
    }
    if let Some(expected) = expected
        && (expected.execution_status != status
            || expected.terminal_message_id != terminal_message_id
            || expected.terminal_event_id != terminal_event_id
            || expected.report_hash != report_hash)
    {
        return Err(WorkspaceRuntimeTerminalStoreError::Conflict);
    }
    Ok(WorkspaceRuntimeTerminalOutcome {
        correlation_id: required_string(row, "correlation_id")?,
        provider_run_id: required_string(row, "provider_run_id")?,
        delivery_request_id: required_string(row, "delivery_request_id")?,
        status,
        outbox_id: required_string(row, "outbox_id")?,
        terminal_id,
        terminal_message_id,
        terminal_event_id,
        report,
        report_hash,
        task_status: task_status_value,
        attempt_status: attempt_status_value,
        provider_event_hash,
        provider_event_ingested,
        created,
    })
}

pub(super) fn ensure_write_hash(
    write: &WorkspaceRuntimeTerminalWrite,
) -> Result<(), WorkspaceRuntimeTerminalStoreError> {
    if canonical_json_hash(&write.report)? == write.report_hash {
        Ok(())
    } else {
        Err(WorkspaceRuntimeTerminalStoreError::InvalidRecord(
            "report_hash",
        ))
    }
}

fn canonical_json_hash(value: &Value) -> Result<String, WorkspaceRuntimeTerminalStoreError> {
    let canonical = canonical_json(value);
    let bytes =
        serde_json::to_vec(&canonical).map_err(WorkspaceRuntimeTerminalStoreError::InvalidJson)?;
    Ok(hex::encode(Sha256::digest(bytes)))
}

fn canonical_json(value: &Value) -> Value {
    match value {
        Value::Array(items) => Value::Array(items.iter().map(canonical_json).collect()),
        Value::Object(items) => Value::Object(
            items
                .iter()
                .map(|(key, value)| (key.clone(), canonical_json(value)))
                .collect::<BTreeMap<_, _>>()
                .into_iter()
                .collect(),
        ),
        _ => value.clone(),
    }
}

fn is_sha256_hex(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn task_status(status: &str) -> &'static str {
    if status == STATUS_COMPLETED {
        "done"
    } else {
        "blocked"
    }
}

fn attempt_status(status: &str) -> &'static str {
    if status == STATUS_COMPLETED {
        "completed"
    } else {
        "blocked"
    }
}

fn json_value(builder: DbStatementBuilder, flavor: DbSqlFlavor, value: &str) -> DbStatementBuilder {
    let builder = builder.bind(value);
    if flavor == DbSqlFlavor::Postgres {
        builder.push_static("::jsonb")
    } else {
        builder
    }
}

pub(super) fn correlation_from_row(
    row: &DbRow,
) -> Result<RuntimeCorrelation, WorkspaceRuntimeTerminalStoreError> {
    Ok(RuntimeCorrelation {
        correlation_id: required_string(row, "correlation_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        conversation_id: required_string(row, "conversation_id")?,
        delivery_request_id: required_string(row, "delivery_request_id")?,
        provider_run_id: required_string(row, "provider_run_id")?,
        task_id: optional_string(row, "task_id")?,
        attempt_id: optional_string(row, "attempt_id")?,
        plan_id: optional_string(row, "plan_id")?,
    })
}

fn required_string(
    row: &DbRow,
    column: &'static str,
) -> Result<String, WorkspaceRuntimeTerminalStoreError> {
    row.get_string(column)?
        .ok_or(WorkspaceRuntimeTerminalStoreError::InvalidRecord(column))
}

fn optional_string(
    row: &DbRow,
    column: &'static str,
) -> Result<Option<String>, WorkspaceRuntimeTerminalStoreError> {
    row.get_string(column).map_err(Into::into)
}

fn required_json(
    row: &DbRow,
    column: &'static str,
) -> Result<Value, WorkspaceRuntimeTerminalStoreError> {
    serde_json::from_str(required_string(row, column)?.as_str())
        .map_err(WorkspaceRuntimeTerminalStoreError::InvalidJson)
}

fn json_string(
    value: &Value,
    key: &'static str,
) -> Result<String, WorkspaceRuntimeTerminalStoreError> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or(WorkspaceRuntimeTerminalStoreError::InvalidRecord(key))
}

pub(super) fn affected_rows(
    results: &[DbTransactionStepResult],
    index: usize,
) -> Result<u64, WorkspaceRuntimeTerminalStoreError> {
    match results.get(index) {
        Some(DbTransactionStepResult::Executed(result)) => Ok(result.affected_rows),
        _ => Err(WorkspaceRuntimeTerminalStoreError::InvalidRecord(
            "transaction execute",
        )),
    }
}

pub(super) fn transaction_row(
    results: &[DbTransactionStepResult],
    index: usize,
) -> Result<Option<&DbRow>, WorkspaceRuntimeTerminalStoreError> {
    match results.get(index) {
        Some(DbTransactionStepResult::Rows(rows)) => Ok(rows.first()),
        _ => Err(WorkspaceRuntimeTerminalStoreError::InvalidRecord(
            "transaction query",
        )),
    }
}
