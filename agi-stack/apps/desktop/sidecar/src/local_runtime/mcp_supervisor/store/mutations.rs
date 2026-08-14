use rusqlite::{params, OptionalExtension, Transaction, TransactionBehavior};
use serde_json::Value;

use super::{
    credentials::{
        activate_credential_stages, resolve_credential_bindings, retire_removed_credentials,
    },
    map_store_error, server_from_internal_json, server_from_row, server_internal_json, McpStore,
};
use crate::local_runtime::mcp_supervisor::{
    McpResult, McpScope, McpServerDefinition, McpServerDefinitionInput,
};

pub(in crate::local_runtime::mcp_supervisor) struct McpStoredServerUpdate {
    pub(in crate::local_runtime::mcp_supervisor) server: McpServerDefinition,
}

pub(in crate::local_runtime::mcp_supervisor) struct McpStoredServerDeletion {
    pub(in crate::local_runtime::mcp_supervisor) server: McpServerDefinition,
    pub(in crate::local_runtime::mcp_supervisor) duplicate: bool,
}

impl McpStore {
    pub(in crate::local_runtime::mcp_supervisor) fn update_server(
        &self,
        scope: &McpScope,
        server_id: &str,
        input: &McpServerDefinitionInput,
        expected_revision: u64,
        idempotency_key: &str,
        request_hash: &str,
    ) -> McpResult<McpStoredServerUpdate> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                let transaction = connection
                    .transaction_with_behavior(TransactionBehavior::Immediate)
                    .map_err(|error| error.to_string())?;
                if let Some((stored_hash, response_json)) = transaction
                    .query_row(
                        "SELECT request_hash, response_json
                         FROM desktop_mcp_receipts_v1
                         WHERE tenant_id = ?1 AND project_id = ?2 AND idempotency_key = ?3",
                        params![scope.tenant_id, scope.project_id, idempotency_key],
                        |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
                    )
                    .optional()
                    .map_err(|error| error.to_string())?
                {
                    if stored_hash != request_hash {
                        return Err("idempotency_conflict".to_string());
                    }
                    let (server, _) = mutation_response(&response_json)?;
                    return Ok(McpStoredServerUpdate { server });
                }

                let current = transaction
                    .query_row(
                        "SELECT id, tenant_id, project_id, name, description, transport,
                                command_json, cwd, vault_env_refs_json, enabled, revision,
                                runtime_status, reason_code, discovered_tools_json,
                                server_info_json, created_at, updated_at
                         FROM desktop_mcp_servers_v1
                         WHERE tenant_id = ?1 AND project_id = ?2 AND id = ?3",
                        params![scope.tenant_id, scope.project_id, server_id],
                        server_from_row,
                    )
                    .optional()
                    .map_err(|error| error.to_string())?
                    .ok_or_else(|| "server_not_found".to_string())?;
                if current.revision != expected_revision {
                    return Err("revision_conflict".to_string());
                }
                let revision = current
                    .revision
                    .checked_add(1)
                    .ok_or_else(|| "revision_overflow".to_string())?;
                let now = chrono::Utc::now().to_rfc3339();
                let (vault_env_refs, activated_stage_references) = resolve_credential_bindings(
                    &transaction,
                    scope,
                    idempotency_key,
                    input,
                    Some(&current),
                )?;
                let runtime_status = if input.enabled { "stopped" } else { "disabled" };
                let server = McpServerDefinition {
                    id: current.id.clone(),
                    tenant_id: current.tenant_id.clone(),
                    project_id: current.project_id.clone(),
                    name: input.name.clone(),
                    description: input.description.clone(),
                    transport: input.transport,
                    command: input.command.clone(),
                    cwd: input.cwd.clone(),
                    vault_env_refs,
                    enabled: input.enabled,
                    revision,
                    runtime_status: runtime_status.to_string(),
                    reason_code: None,
                    discovered_tools: Vec::new(),
                    server_info: None,
                    created_at: current.created_at,
                    updated_at: now.clone(),
                };
                update_server_row(
                    &transaction,
                    scope,
                    server_id,
                    expected_revision,
                    &server,
                    &now,
                )?;
                activate_credential_stages(
                    &transaction,
                    scope,
                    server_id,
                    &activated_stage_references,
                    &now,
                )?;
                transaction
                    .execute(
                        "DELETE FROM desktop_mcp_apps_v1
                         WHERE tenant_id = ?1 AND project_id = ?2 AND server_id = ?3",
                        params![scope.tenant_id, scope.project_id, server_id],
                    )
                    .map_err(|error| error.to_string())?;

                let mut removed_vault_refs = current
                    .vault_env_refs
                    .values()
                    .filter(|reference| {
                        !server
                            .vault_env_refs
                            .values()
                            .any(|item| item == *reference)
                    })
                    .cloned()
                    .collect::<Vec<_>>();
                removed_vault_refs.sort();
                removed_vault_refs.dedup();
                retire_removed_credentials(
                    &transaction,
                    scope,
                    &removed_vault_refs,
                    idempotency_key,
                    &now,
                )?;
                record_mutation(
                    &transaction,
                    scope,
                    idempotency_key,
                    "update_server",
                    request_hash,
                    &server,
                    &removed_vault_refs,
                    &now,
                )?;
                transaction.commit().map_err(|error| error.to_string())?;
                Ok(McpStoredServerUpdate { server })
            })
            .map_err(map_store_error)
    }

    pub(in crate::local_runtime::mcp_supervisor) fn delete_server(
        &self,
        scope: &McpScope,
        server_id: &str,
        expected_revision: u64,
        idempotency_key: &str,
        request_hash: &str,
    ) -> McpResult<McpStoredServerDeletion> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                let transaction = connection
                    .transaction_with_behavior(TransactionBehavior::Immediate)
                    .map_err(|error| error.to_string())?;
                if let Some((stored_hash, response_json)) = transaction
                    .query_row(
                        "SELECT request_hash, response_json
                         FROM desktop_mcp_receipts_v1
                         WHERE tenant_id = ?1 AND project_id = ?2 AND idempotency_key = ?3",
                        params![scope.tenant_id, scope.project_id, idempotency_key],
                        |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
                    )
                    .optional()
                    .map_err(|error| error.to_string())?
                {
                    if stored_hash != request_hash {
                        return Err("idempotency_conflict".to_string());
                    }
                    let (server, _) = mutation_response(&response_json)?;
                    return Ok(McpStoredServerDeletion {
                        server,
                        duplicate: true,
                    });
                }

                let server = transaction
                    .query_row(
                        "SELECT id, tenant_id, project_id, name, description, transport,
                                command_json, cwd, vault_env_refs_json, enabled, revision,
                                runtime_status, reason_code, discovered_tools_json,
                                server_info_json, created_at, updated_at
                         FROM desktop_mcp_servers_v1
                         WHERE tenant_id = ?1 AND project_id = ?2 AND id = ?3",
                        params![scope.tenant_id, scope.project_id, server_id],
                        server_from_row,
                    )
                    .optional()
                    .map_err(|error| error.to_string())?
                    .ok_or_else(|| "server_not_found".to_string())?;
                if server.revision != expected_revision {
                    return Err("revision_conflict".to_string());
                }
                let mut removed_vault_refs =
                    server.vault_env_refs.values().cloned().collect::<Vec<_>>();
                removed_vault_refs.sort();
                removed_vault_refs.dedup();
                let now = chrono::Utc::now().to_rfc3339();

                transaction
                    .execute(
                        "DELETE FROM desktop_mcp_apps_v1
                         WHERE tenant_id = ?1 AND project_id = ?2 AND server_id = ?3",
                        params![scope.tenant_id, scope.project_id, server_id],
                    )
                    .map_err(|error| error.to_string())?;
                retire_removed_credentials(
                    &transaction,
                    scope,
                    &removed_vault_refs,
                    idempotency_key,
                    &now,
                )?;
                let deleted = transaction
                    .execute(
                        "DELETE FROM desktop_mcp_servers_v1
                         WHERE tenant_id = ?1 AND project_id = ?2 AND id = ?3 AND revision = ?4",
                        params![
                            scope.tenant_id,
                            scope.project_id,
                            server_id,
                            i64::try_from(expected_revision)
                                .map_err(|_| "server revision is invalid".to_string())?,
                        ],
                    )
                    .map_err(|error| error.to_string())?;
                if deleted != 1 {
                    return Err("revision_conflict".to_string());
                }
                record_mutation(
                    &transaction,
                    scope,
                    idempotency_key,
                    "delete_server",
                    request_hash,
                    &server,
                    &removed_vault_refs,
                    &now,
                )?;
                transaction.commit().map_err(|error| error.to_string())?;
                Ok(McpStoredServerDeletion {
                    server,
                    duplicate: false,
                })
            })
            .map_err(map_store_error)
    }
}

fn update_server_row(
    transaction: &Transaction<'_>,
    scope: &McpScope,
    server_id: &str,
    expected_revision: u64,
    server: &McpServerDefinition,
    now: &str,
) -> Result<(), String> {
    let updated = transaction
        .execute(
            "UPDATE desktop_mcp_servers_v1
             SET name = ?4, description = ?5, transport = ?6, command_json = ?7,
                 cwd = ?8, vault_env_refs_json = ?9, enabled = ?10, revision = ?11,
                 runtime_status = ?12, reason_code = NULL, discovered_tools_json = '[]',
                 server_info_json = NULL, updated_at = ?13
             WHERE tenant_id = ?1 AND project_id = ?2 AND id = ?3 AND revision = ?14",
            params![
                scope.tenant_id,
                scope.project_id,
                server_id,
                server.name,
                server.description,
                server.transport.as_str(),
                serde_json::to_string(&server.command).map_err(|error| error.to_string())?,
                server.cwd,
                serde_json::to_string(&server.vault_env_refs).map_err(|error| error.to_string())?,
                i64::from(server.enabled),
                i64::try_from(server.revision)
                    .map_err(|_| "server revision is invalid".to_string())?,
                server.runtime_status,
                now,
                i64::try_from(expected_revision)
                    .map_err(|_| "server revision is invalid".to_string())?,
            ],
        )
        .map_err(|error| {
            if error.to_string().contains("UNIQUE constraint failed") {
                "server_name_conflict".to_string()
            } else {
                error.to_string()
            }
        })?;
    if updated != 1 {
        return Err("revision_conflict".to_string());
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn record_mutation(
    transaction: &Transaction<'_>,
    scope: &McpScope,
    idempotency_key: &str,
    operation: &str,
    request_hash: &str,
    server: &McpServerDefinition,
    removed_vault_refs: &[String],
    now: &str,
) -> Result<(), String> {
    let response_json = mutation_response_json(server, removed_vault_refs)?;
    transaction
        .execute(
            "INSERT INTO desktop_mcp_receipts_v1(
               tenant_id, project_id, idempotency_key, operation, target_id,
               request_hash, response_json, created_at
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            params![
                scope.tenant_id,
                scope.project_id,
                idempotency_key,
                operation,
                server.id,
                request_hash,
                response_json,
                now,
            ],
        )
        .map_err(|error| error.to_string())?;
    Ok(())
}

fn mutation_response_json(
    server: &McpServerDefinition,
    removed_vault_refs: &[String],
) -> Result<String, String> {
    let server: Value =
        serde_json::from_str(&server_internal_json(server)?).map_err(|error| error.to_string())?;
    Ok(serde_json::json!({
        "server": server,
        "removed_vault_refs": removed_vault_refs,
    })
    .to_string())
}

fn mutation_response(value: &str) -> Result<(McpServerDefinition, Vec<String>), String> {
    let value: Value = serde_json::from_str(value).map_err(|error| error.to_string())?;
    let server = value
        .get("server")
        .ok_or_else(|| "stored MCP mutation server is missing".to_string())?;
    let server = server_from_internal_json(&server.to_string())?;
    let removed_vault_refs = serde_json::from_value(
        value
            .get("removed_vault_refs")
            .cloned()
            .unwrap_or_else(|| serde_json::json!([])),
    )
    .map_err(|error| error.to_string())?;
    Ok((server, removed_vault_refs))
}
