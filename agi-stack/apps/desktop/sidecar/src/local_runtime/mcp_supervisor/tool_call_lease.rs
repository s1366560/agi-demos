use std::time::Duration;

use rusqlite::{params, OptionalExtension, TransactionBehavior};
use serde_json::Value;
use tokio::time::{sleep, Instant};
use uuid::Uuid;

use super::{
    storage_error, store::McpStore, validate_tool_call_result, McpResult, McpScope,
    McpServerDefinition, McpSupervisor, McpSupervisorError, McpToolCallOutcome,
};

#[derive(Clone, Debug)]
pub(super) struct ToolCallLease {
    tenant_id: String,
    project_id: String,
    idempotency_key: String,
    server_id: String,
    request_hash: String,
    lease_token: String,
    fence_token: i64,
}

pub(super) enum ToolCallReservation {
    Acquired(ToolCallLease),
    Replay(Value),
    Pending,
    Indeterminate,
}

pub(super) async fn execute_tool_call(
    supervisor: &McpSupervisor,
    scope: &McpScope,
    server: &McpServerDefinition,
    tool_name: &str,
    arguments: Value,
    idempotency_key: &str,
    request_hash: &str,
) -> McpResult<McpToolCallOutcome> {
    let wait_deadline = Instant::now() + supervisor.limits.tool_call_wait_timeout;
    let minimum_lease = supervisor
        .limits
        .initialize_timeout
        .saturating_add(supervisor.limits.request_timeout)
        .saturating_add(Duration::from_secs(2));
    let lease_duration = supervisor
        .limits
        .tool_call_lease_duration
        .max(minimum_lease);
    loop {
        match supervisor.store.reserve_tool_call(
            scope,
            idempotency_key,
            request_hash,
            &server.id,
            now_millis(),
            lease_duration,
        )? {
            ToolCallReservation::Replay(result) => {
                let (content, is_error) = validate_tool_call_result(&result)?;
                return Ok(McpToolCallOutcome {
                    result,
                    content,
                    is_error,
                    duplicate: true,
                });
            }
            ToolCallReservation::Acquired(lease) => {
                supervisor
                    .store
                    .mark_tool_call_dispatched(&lease, now_millis())?;
                let result = match supervisor
                    .request(
                        server,
                        "tools/call",
                        serde_json::json!({ "name": tool_name, "arguments": arguments }),
                    )
                    .await
                {
                    Ok(result) => result,
                    Err(_) => {
                        let _ = supervisor
                            .store
                            .mark_tool_call_indeterminate(&lease, now_millis());
                        return Err(tool_call_indeterminate());
                    }
                };
                let (content, is_error) = match validate_tool_call_result(&result) {
                    Ok(validated) => validated,
                    Err(_) => {
                        let _ = supervisor
                            .store
                            .mark_tool_call_indeterminate(&lease, now_millis());
                        return Err(tool_call_indeterminate());
                    }
                };
                if supervisor
                    .store
                    .complete_tool_call(&lease, &result)
                    .is_err()
                {
                    let _ = supervisor
                        .store
                        .mark_tool_call_indeterminate(&lease, now_millis());
                    return Err(tool_call_indeterminate());
                }
                return Ok(McpToolCallOutcome {
                    result,
                    content,
                    is_error,
                    duplicate: false,
                });
            }
            ToolCallReservation::Pending => {
                if Instant::now() >= wait_deadline {
                    return Err(tool_call_in_progress());
                }
                let remaining = wait_deadline.saturating_duration_since(Instant::now());
                sleep(supervisor.limits.tool_call_poll_interval.min(remaining)).await;
            }
            ToolCallReservation::Indeterminate => return Err(tool_call_indeterminate()),
        }
    }
}

impl McpStore {
    pub(super) fn reserve_tool_call(
        &self,
        scope: &McpScope,
        idempotency_key: &str,
        request_hash: &str,
        server_id: &str,
        now_ms: i64,
        lease_duration: Duration,
    ) -> McpResult<ToolCallReservation> {
        let lease_millis = i64::try_from(lease_duration.as_millis())
            .map_err(|_| storage_error())?
            .max(1);
        let lease_expires_at_ms = now_ms.checked_add(lease_millis).ok_or_else(storage_error)?;
        self.session_store
            .with_local_mcp_connection(|connection| {
                let transaction = connection
                    .transaction_with_behavior(TransactionBehavior::Immediate)
                    .map_err(|error| error.to_string())?;
                if let Some((operation, target_id, stored_hash, response_json)) = transaction
                    .query_row(
                        "SELECT operation, target_id, request_hash, response_json
                         FROM desktop_mcp_receipts_v1
                         WHERE tenant_id = ?1 AND project_id = ?2 AND idempotency_key = ?3",
                        params![scope.tenant_id, scope.project_id, idempotency_key],
                        |row| {
                            Ok((
                                row.get::<_, String>(0)?,
                                row.get::<_, String>(1)?,
                                row.get::<_, String>(2)?,
                                row.get::<_, String>(3)?,
                            ))
                        },
                    )
                    .optional()
                    .map_err(|error| error.to_string())?
                {
                    if operation != "tools_call"
                        || target_id != server_id
                        || stored_hash != request_hash
                    {
                        return Err("idempotency_conflict".to_string());
                    }
                    let response =
                        serde_json::from_str(&response_json).map_err(|error| error.to_string())?;
                    transaction.commit().map_err(|error| error.to_string())?;
                    return Ok(ToolCallReservation::Replay(response));
                }

                let existing = transaction
                    .query_row(
                        "SELECT server_id, request_hash, status, lease_expires_at_ms,
                                fence_token, response_json
                         FROM desktop_mcp_tool_call_operations_v3
                         WHERE tenant_id = ?1 AND project_id = ?2 AND idempotency_key = ?3",
                        params![scope.tenant_id, scope.project_id, idempotency_key],
                        |row| {
                            Ok((
                                row.get::<_, String>(0)?,
                                row.get::<_, String>(1)?,
                                row.get::<_, String>(2)?,
                                row.get::<_, i64>(3)?,
                                row.get::<_, i64>(4)?,
                                row.get::<_, Option<String>>(5)?,
                            ))
                        },
                    )
                    .optional()
                    .map_err(|error| error.to_string())?;
                let lease_token = Uuid::new_v4().to_string();
                let fence_token = match existing {
                    Some((
                        stored_server,
                        stored_hash,
                        status,
                        stored_expiry,
                        stored_fence,
                        response_json,
                    )) => {
                        if stored_server != server_id || stored_hash != request_hash {
                            return Err("idempotency_conflict".to_string());
                        }
                        if status == "completed" {
                            let response = response_json
                                .ok_or_else(|| "completed lease has no response".to_string())
                                .and_then(|value| {
                                    serde_json::from_str(&value).map_err(|error| error.to_string())
                                })?;
                            transaction.commit().map_err(|error| error.to_string())?;
                            return Ok(ToolCallReservation::Replay(response));
                        }
                        if status == "indeterminate" {
                            transaction.commit().map_err(|error| error.to_string())?;
                            return Ok(ToolCallReservation::Indeterminate);
                        }
                        if status == "dispatched" {
                            if stored_expiry > now_ms {
                                transaction.commit().map_err(|error| error.to_string())?;
                                return Ok(ToolCallReservation::Pending);
                            }
                            let updated = transaction
                                .execute(
                                    "UPDATE desktop_mcp_tool_call_operations_v3
                                     SET status = 'indeterminate', updated_at_ms = ?4
                                     WHERE tenant_id = ?1 AND project_id = ?2
                                       AND idempotency_key = ?3 AND status = 'dispatched'",
                                    params![
                                        scope.tenant_id,
                                        scope.project_id,
                                        idempotency_key,
                                        now_ms,
                                    ],
                                )
                                .map_err(|error| error.to_string())?;
                            if updated != 1 {
                                return Err("tool_call_lease_lost".to_string());
                            }
                            transaction.commit().map_err(|error| error.to_string())?;
                            return Ok(ToolCallReservation::Indeterminate);
                        }
                        if status != "pre_dispatch" {
                            return Err("stored tool call lease status is invalid".to_string());
                        }
                        if stored_expiry > now_ms {
                            transaction.commit().map_err(|error| error.to_string())?;
                            return Ok(ToolCallReservation::Pending);
                        }
                        let next_fence = stored_fence
                            .checked_add(1)
                            .ok_or_else(|| "tool call fence is exhausted".to_string())?;
                        let updated = transaction
                            .execute(
                                "UPDATE desktop_mcp_tool_call_operations_v3
                                 SET lease_token = ?4, lease_expires_at_ms = ?5,
                                     fence_token = ?6, updated_at_ms = ?7
                                 WHERE tenant_id = ?1 AND project_id = ?2
                                   AND idempotency_key = ?3 AND status = 'pre_dispatch'
                                   AND fence_token = ?8 AND lease_expires_at_ms <= ?7",
                                params![
                                    scope.tenant_id,
                                    scope.project_id,
                                    idempotency_key,
                                    lease_token,
                                    lease_expires_at_ms,
                                    next_fence,
                                    now_ms,
                                    stored_fence,
                                ],
                            )
                            .map_err(|error| error.to_string())?;
                        if updated != 1 {
                            return Err("tool_call_lease_lost".to_string());
                        }
                        next_fence
                    }
                    None => {
                        transaction
                            .execute(
                                "INSERT INTO desktop_mcp_tool_call_operations_v3(
                                   tenant_id, project_id, idempotency_key, server_id,
                                   request_hash, status, lease_token, lease_expires_at_ms,
                                   fence_token, response_json, created_at_ms, updated_at_ms
                                 ) VALUES (
                                   ?1, ?2, ?3, ?4, ?5, 'pre_dispatch', ?6, ?7, 1, NULL, ?8, ?8
                                 )",
                                params![
                                    scope.tenant_id,
                                    scope.project_id,
                                    idempotency_key,
                                    server_id,
                                    request_hash,
                                    lease_token,
                                    lease_expires_at_ms,
                                    now_ms,
                                ],
                            )
                            .map_err(|error| error.to_string())?;
                        1
                    }
                };
                transaction.commit().map_err(|error| error.to_string())?;
                Ok(ToolCallReservation::Acquired(ToolCallLease {
                    tenant_id: scope.tenant_id.clone(),
                    project_id: scope.project_id.clone(),
                    idempotency_key: idempotency_key.to_string(),
                    server_id: server_id.to_string(),
                    request_hash: request_hash.to_string(),
                    lease_token,
                    fence_token,
                }))
            })
            .map_err(map_lease_store_error)
    }

    pub(super) fn mark_tool_call_dispatched(
        &self,
        lease: &ToolCallLease,
        now_ms: i64,
    ) -> McpResult<()> {
        self.update_tool_call_status(lease, "pre_dispatch", "dispatched", now_ms)
    }

    pub(super) fn mark_tool_call_indeterminate(
        &self,
        lease: &ToolCallLease,
        now_ms: i64,
    ) -> McpResult<()> {
        self.update_tool_call_status(lease, "dispatched", "indeterminate", now_ms)
    }

    fn update_tool_call_status(
        &self,
        lease: &ToolCallLease,
        expected_status: &str,
        next_status: &str,
        now_ms: i64,
    ) -> McpResult<()> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                let updated = connection
                    .execute(
                        "UPDATE desktop_mcp_tool_call_operations_v3
                         SET status = ?8, updated_at_ms = ?9
                         WHERE tenant_id = ?1 AND project_id = ?2 AND idempotency_key = ?3
                           AND server_id = ?4 AND request_hash = ?5 AND status = ?7
                           AND lease_token = ?6 AND fence_token = ?10",
                        params![
                            lease.tenant_id,
                            lease.project_id,
                            lease.idempotency_key,
                            lease.server_id,
                            lease.request_hash,
                            lease.lease_token,
                            expected_status,
                            next_status,
                            now_ms,
                            lease.fence_token,
                        ],
                    )
                    .map_err(|error| error.to_string())?;
                if updated != 1 {
                    return Err("tool_call_lease_lost".to_string());
                }
                Ok(())
            })
            .map_err(map_lease_store_error)
    }

    pub(super) fn complete_tool_call(
        &self,
        lease: &ToolCallLease,
        response: &Value,
    ) -> McpResult<()> {
        let response_json = response.to_string();
        self.session_store
            .with_local_mcp_connection(|connection| {
                let transaction = connection
                    .transaction_with_behavior(TransactionBehavior::Immediate)
                    .map_err(|error| error.to_string())?;
                let now_ms = now_millis();
                let updated = transaction
                    .execute(
                        "UPDATE desktop_mcp_tool_call_operations_v3
                         SET status = 'completed', response_json = ?8, updated_at_ms = ?9
                         WHERE tenant_id = ?1 AND project_id = ?2 AND idempotency_key = ?3
                           AND server_id = ?4 AND request_hash = ?5 AND status = 'dispatched'
                           AND lease_token = ?6 AND fence_token = ?7",
                        params![
                            lease.tenant_id,
                            lease.project_id,
                            lease.idempotency_key,
                            lease.server_id,
                            lease.request_hash,
                            lease.lease_token,
                            lease.fence_token,
                            response_json,
                            now_ms,
                        ],
                    )
                    .map_err(|error| error.to_string())?;
                if updated != 1 {
                    return Err("tool_call_lease_lost".to_string());
                }
                transaction
                    .execute(
                        "INSERT INTO desktop_mcp_receipts_v1(
                           tenant_id, project_id, idempotency_key, operation, target_id,
                           request_hash, response_json, created_at
                         ) VALUES (?1, ?2, ?3, 'tools_call', ?4, ?5, ?6, ?7)",
                        params![
                            lease.tenant_id,
                            lease.project_id,
                            lease.idempotency_key,
                            lease.server_id,
                            lease.request_hash,
                            response_json,
                            chrono::Utc::now().to_rfc3339(),
                        ],
                    )
                    .map_err(|error| error.to_string())?;
                transaction.commit().map_err(|error| error.to_string())
            })
            .map_err(map_lease_store_error)
    }
}

fn now_millis() -> i64 {
    chrono::Utc::now().timestamp_millis()
}

fn map_lease_store_error(error: String) -> McpSupervisorError {
    match error.as_str() {
        "idempotency_conflict" => McpSupervisorError::new(
            "local_mcp_idempotency_conflict",
            "MCP idempotency key is already bound to a different request",
        ),
        "tool_call_lease_lost" => McpSupervisorError::new(
            "local_mcp_tool_call_lease_lost",
            "MCP tool call lease was superseded by a newer owner",
        ),
        _ => storage_error(),
    }
}

fn tool_call_in_progress() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_tool_call_in_progress",
        "MCP tool call with this idempotency key is still in progress",
    )
}

fn tool_call_indeterminate() -> McpSupervisorError {
    McpSupervisorError::new(
        "local_mcp_tool_call_indeterminate",
        "MCP tool call dispatch completed without a verifiable local receipt",
    )
}
