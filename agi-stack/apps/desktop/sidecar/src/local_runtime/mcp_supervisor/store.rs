use rusqlite::{params, OptionalExtension, TransactionBehavior};
use serde_json::Value;
use sha2::{Digest, Sha256};
use uuid::Uuid;

use super::{
    storage_error, McpAppDefinition, McpResult, McpScope, McpServerDefinition,
    McpServerDefinitionInput, McpSupervisorError, McpTransport,
};
use crate::local_runtime::DesktopSessionStore;

const SCHEMA_SQL: &str = "
CREATE TABLE IF NOT EXISTS desktop_mcp_servers_v1 (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  transport TEXT NOT NULL,
  command_json TEXT NOT NULL,
  cwd TEXT,
  vault_env_refs_json TEXT NOT NULL,
  enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
  revision INTEGER NOT NULL CHECK(revision >= 1),
  runtime_status TEXT NOT NULL,
  reason_code TEXT,
  discovered_tools_json TEXT NOT NULL,
  server_info_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(tenant_id, project_id, name)
);
CREATE INDEX IF NOT EXISTS idx_desktop_mcp_servers_scope_v1
  ON desktop_mcp_servers_v1(tenant_id, project_id, enabled, name);
CREATE TABLE IF NOT EXISTS desktop_mcp_apps_v1 (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  server_id TEXT NOT NULL,
  server_name TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  resource_uri TEXT,
  ui_metadata_json TEXT NOT NULL,
  status TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK(revision >= 1),
  updated_at TEXT NOT NULL,
  UNIQUE(tenant_id, project_id, server_id, tool_name),
  FOREIGN KEY(server_id) REFERENCES desktop_mcp_servers_v1(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_desktop_mcp_apps_scope_v1
  ON desktop_mcp_apps_v1(tenant_id, project_id, status, server_name);
CREATE TABLE IF NOT EXISTS desktop_mcp_receipts_v1 (
  tenant_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  operation TEXT NOT NULL,
  target_id TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  response_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(tenant_id, project_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS desktop_mcp_credential_receipts_v1 (
  tenant_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  binding_reference TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(tenant_id, project_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS desktop_mcp_credential_bindings_v1 (
  tenant_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  binding_reference TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(tenant_id, project_id, binding_reference)
);
CREATE TABLE IF NOT EXISTS desktop_mcp_tool_call_leases_v2 (
  tenant_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  server_id TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending', 'completed')),
  lease_token TEXT NOT NULL,
  lease_expires_at_ms INTEGER NOT NULL,
  fence_token INTEGER NOT NULL CHECK(fence_token >= 1),
  response_json TEXT,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  PRIMARY KEY(tenant_id, project_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS desktop_mcp_tool_call_operations_v3 (
  tenant_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  server_id TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  status TEXT NOT NULL
    CHECK(status IN ('pre_dispatch', 'dispatched', 'indeterminate', 'completed')),
  lease_token TEXT NOT NULL,
  lease_expires_at_ms INTEGER NOT NULL,
  fence_token INTEGER NOT NULL CHECK(fence_token >= 1),
  response_json TEXT,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  PRIMARY KEY(tenant_id, project_id, idempotency_key)
);
INSERT OR IGNORE INTO desktop_mcp_tool_call_operations_v3(
  tenant_id, project_id, idempotency_key, server_id, request_hash, status,
  lease_token, lease_expires_at_ms, fence_token, response_json, created_at_ms, updated_at_ms
)
SELECT tenant_id, project_id, idempotency_key, server_id, request_hash,
       CASE status WHEN 'completed' THEN 'completed' ELSE 'indeterminate' END,
       lease_token, lease_expires_at_ms, fence_token, response_json, created_at_ms, updated_at_ms
FROM desktop_mcp_tool_call_leases_v2
;";

#[derive(Clone)]
pub(super) struct McpStore {
    pub(super) session_store: DesktopSessionStore,
}

impl McpStore {
    pub(super) fn new(session_store: DesktopSessionStore) -> Result<Self, String> {
        session_store.with_local_mcp_connection(|connection| {
            connection
                .execute_batch(SCHEMA_SQL)
                .map_err(|error| error.to_string())
        })?;
        Ok(Self { session_store })
    }

    pub(super) fn create_server(
        &self,
        scope: &McpScope,
        input: &McpServerDefinitionInput,
        idempotency_key: &str,
        request_hash: &str,
    ) -> McpResult<McpServerDefinition> {
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
                    return server_from_internal_json(&response_json)
                        .map_err(|error| error.to_string());
                }

                let now = chrono::Utc::now().to_rfc3339();
                let server = McpServerDefinition {
                    id: format!("local-mcp-{}", Uuid::new_v4()),
                    tenant_id: scope.tenant_id.clone(),
                    project_id: scope.project_id.clone(),
                    name: input.name.clone(),
                    description: input.description.clone(),
                    transport: input.transport,
                    command: input.command.clone(),
                    cwd: input.cwd.clone(),
                    vault_env_refs: input.vault_env_refs.clone(),
                    enabled: input.enabled,
                    revision: 1,
                    runtime_status: if input.enabled {
                        "stopped".to_string()
                    } else {
                        "disabled".to_string()
                    },
                    reason_code: None,
                    discovered_tools: Vec::new(),
                    server_info: None,
                    created_at: now.clone(),
                    updated_at: now.clone(),
                };
                transaction
                    .execute(
                        "INSERT INTO desktop_mcp_servers_v1(
                           id, tenant_id, project_id, name, description, transport, command_json,
                           cwd, vault_env_refs_json, enabled, revision, runtime_status,
                           reason_code, discovered_tools_json, server_info_json, created_at, updated_at
                         ) VALUES (
                           ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12,
                           NULL, '[]', NULL, ?13, ?13
                         )",
                        params![
                            server.id,
                            server.tenant_id,
                            server.project_id,
                            server.name,
                            server.description,
                            server.transport.as_str(),
                            serde_json::to_string(&server.command)
                                .map_err(|error| error.to_string())?,
                            server.cwd,
                            serde_json::to_string(&server.vault_env_refs)
                                .map_err(|error| error.to_string())?,
                            i64::from(server.enabled),
                            i64::try_from(server.revision)
                                .map_err(|_| "server revision is invalid".to_string())?,
                            server.runtime_status,
                            now,
                        ],
                    )
                    .map_err(|error| {
                        if error.to_string().contains("UNIQUE constraint failed") {
                            "server_name_conflict".to_string()
                        } else {
                            error.to_string()
                        }
                    })?;
                let response_json = server_internal_json(&server)?;
                transaction
                    .execute(
                        "INSERT INTO desktop_mcp_receipts_v1(
                           tenant_id, project_id, idempotency_key, operation, target_id,
                           request_hash, response_json, created_at
                         ) VALUES (?1, ?2, ?3, 'create_server', ?4, ?5, ?6, ?7)",
                        params![
                            scope.tenant_id,
                            scope.project_id,
                            idempotency_key,
                            server.id,
                            request_hash,
                            response_json,
                            now,
                        ],
                    )
                    .map_err(|error| error.to_string())?;
                transaction.commit().map_err(|error| error.to_string())?;
                Ok(server)
            })
            .map_err(map_store_error)
    }

    pub(super) fn list_servers(&self, scope: &McpScope) -> McpResult<Vec<McpServerDefinition>> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                let mut statement = connection
                    .prepare(
                        "SELECT id, tenant_id, project_id, name, description, transport,
                                command_json, cwd, vault_env_refs_json, enabled, revision,
                                runtime_status, reason_code, discovered_tools_json,
                                server_info_json, created_at, updated_at
                         FROM desktop_mcp_servers_v1
                         WHERE tenant_id = ?1 AND project_id = ?2
                         ORDER BY name, id",
                    )
                    .map_err(|error| error.to_string())?;
                let rows = statement
                    .query_map(params![scope.tenant_id, scope.project_id], server_from_row)
                    .map_err(|error| error.to_string())?;
                rows.collect::<rusqlite::Result<Vec<_>>>()
                    .map_err(|error| error.to_string())
            })
            .map_err(|_| storage_error())
    }

    pub(super) fn enabled_servers(&self) -> McpResult<Vec<McpServerDefinition>> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                let mut statement = connection
                    .prepare(
                        "SELECT id, tenant_id, project_id, name, description, transport,
                                command_json, cwd, vault_env_refs_json, enabled, revision,
                                runtime_status, reason_code, discovered_tools_json,
                                server_info_json, created_at, updated_at
                         FROM desktop_mcp_servers_v1
                         WHERE enabled = 1
                         ORDER BY tenant_id, project_id, name, id",
                    )
                    .map_err(|error| error.to_string())?;
                let rows = statement
                    .query_map([], server_from_row)
                    .map_err(|error| error.to_string())?;
                rows.collect::<rusqlite::Result<Vec<_>>>()
                    .map_err(|error| error.to_string())
            })
            .map_err(|_| storage_error())
    }

    pub(super) fn mark_enabled_recovery_pending(&self) -> McpResult<()> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                let transaction = connection
                    .transaction_with_behavior(TransactionBehavior::Immediate)
                    .map_err(|error| error.to_string())?;
                let now = chrono::Utc::now().to_rfc3339();
                transaction
                    .execute(
                        "UPDATE desktop_mcp_servers_v1
                         SET runtime_status = 'starting',
                             reason_code = 'local_mcp_recovery_pending',
                             updated_at = ?1
                         WHERE enabled = 1",
                        params![now],
                    )
                    .map_err(|error| error.to_string())?;
                transaction
                    .execute(
                        "UPDATE desktop_mcp_apps_v1
                         SET status = 'starting', revision = revision + 1, updated_at = ?1
                         WHERE server_id IN (
                           SELECT id FROM desktop_mcp_servers_v1 WHERE enabled = 1
                         )",
                        params![now],
                    )
                    .map_err(|error| error.to_string())?;
                transaction.commit().map_err(|error| error.to_string())
            })
            .map_err(|_| storage_error())
    }

    pub(super) fn credential_receipt(
        &self,
        scope: &McpScope,
        idempotency_key: &str,
    ) -> McpResult<Option<(String, String, bool)>> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                connection
                    .query_row(
                        "SELECT receipt.request_hash,
                                receipt.binding_reference,
                                CASE WHEN binding.idempotency_key = receipt.idempotency_key
                                          AND binding.request_hash = receipt.request_hash
                                     THEN 1 ELSE 0 END
                         FROM desktop_mcp_credential_receipts_v1 AS receipt
                         LEFT JOIN desktop_mcp_credential_bindings_v1 AS binding
                           ON binding.tenant_id = receipt.tenant_id
                          AND binding.project_id = receipt.project_id
                          AND binding.binding_reference = receipt.binding_reference
                         WHERE receipt.tenant_id = ?1
                           AND receipt.project_id = ?2
                           AND receipt.idempotency_key = ?3",
                        params![scope.tenant_id, scope.project_id, idempotency_key],
                        |row| {
                            Ok((
                                row.get::<_, String>(0)?,
                                row.get::<_, String>(1)?,
                                row.get::<_, i64>(2)? == 1,
                            ))
                        },
                    )
                    .optional()
                    .map_err(|error| error.to_string())
            })
            .map_err(|_| storage_error())
    }

    pub(super) fn record_credential_receipt(
        &self,
        scope: &McpScope,
        idempotency_key: &str,
        request_hash: &str,
        binding_reference: &str,
    ) -> McpResult<()> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                let transaction = connection
                    .transaction_with_behavior(TransactionBehavior::Immediate)
                    .map_err(|error| error.to_string())?;
                let now = chrono::Utc::now().to_rfc3339();
                transaction
                    .execute(
                        "INSERT INTO desktop_mcp_credential_receipts_v1(
                           tenant_id, project_id, idempotency_key, request_hash,
                           binding_reference, created_at
                         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                        params![
                            scope.tenant_id,
                            scope.project_id,
                            idempotency_key,
                            request_hash,
                            binding_reference,
                            now,
                        ],
                    )
                    .map_err(|error| error.to_string())?;
                transaction
                    .execute(
                        "INSERT INTO desktop_mcp_credential_bindings_v1(
                           tenant_id, project_id, binding_reference, idempotency_key,
                           request_hash, updated_at
                         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6)
                         ON CONFLICT(tenant_id, project_id, binding_reference)
                         DO UPDATE SET idempotency_key = excluded.idempotency_key,
                                       request_hash = excluded.request_hash,
                                       updated_at = excluded.updated_at",
                        params![
                            scope.tenant_id,
                            scope.project_id,
                            binding_reference,
                            idempotency_key,
                            request_hash,
                            now,
                        ],
                    )
                    .map_err(|error| error.to_string())?;
                transaction.commit().map_err(|error| error.to_string())
            })
            .map_err(|_| storage_error())
    }

    pub(super) fn server(
        &self,
        scope: &McpScope,
        server_id: &str,
    ) -> McpResult<Option<McpServerDefinition>> {
        self.query_server(
            "tenant_id = ?1 AND project_id = ?2 AND id = ?3",
            scope,
            server_id,
        )
    }

    pub(super) fn server_by_name(
        &self,
        scope: &McpScope,
        server_name: &str,
    ) -> McpResult<Option<McpServerDefinition>> {
        self.query_server(
            "tenant_id = ?1 AND project_id = ?2 AND name = ?3",
            scope,
            server_name,
        )
    }

    fn query_server(
        &self,
        predicate: &str,
        scope: &McpScope,
        value: &str,
    ) -> McpResult<Option<McpServerDefinition>> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                connection
                    .query_row(
                        &format!(
                            "SELECT id, tenant_id, project_id, name, description, transport,
                                    command_json, cwd, vault_env_refs_json, enabled, revision,
                                    runtime_status, reason_code, discovered_tools_json,
                                    server_info_json, created_at, updated_at
                             FROM desktop_mcp_servers_v1 WHERE {predicate}"
                        ),
                        params![scope.tenant_id, scope.project_id, value],
                        server_from_row,
                    )
                    .optional()
                    .map_err(|error| error.to_string())
            })
            .map_err(|_| storage_error())
    }

    pub(super) fn record_runtime_ready(
        &self,
        server: &McpServerDefinition,
        server_info: &Value,
    ) -> Result<(), String> {
        self.session_store.with_local_mcp_connection(|connection| {
            let transaction = connection
                .transaction_with_behavior(TransactionBehavior::Immediate)
                .map_err(|error| error.to_string())?;
            let now = chrono::Utc::now().to_rfc3339();
            let updated = transaction
                .execute(
                    "UPDATE desktop_mcp_servers_v1
                     SET runtime_status = 'healthy', reason_code = NULL, server_info_json = ?4,
                         updated_at = ?5
                     WHERE tenant_id = ?1 AND project_id = ?2 AND id = ?3",
                    params![
                        server.tenant_id,
                        server.project_id,
                        server.id,
                        server_info.to_string(),
                        now,
                    ],
                )
                .map_err(|error| error.to_string())?;
            if updated != 1 {
                return Err("MCP server runtime row was not found".to_string());
            }
            transaction
                .execute(
                    "UPDATE desktop_mcp_apps_v1
                     SET status = 'healthy', revision = revision + 1, updated_at = ?4
                     WHERE tenant_id = ?1 AND project_id = ?2 AND server_id = ?3",
                    params![server.tenant_id, server.project_id, server.id, now],
                )
                .map_err(|error| error.to_string())?;
            transaction.commit().map_err(|error| error.to_string())
        })
    }

    pub(super) fn record_runtime_error(
        &self,
        server: &McpServerDefinition,
        reason_code: &str,
    ) -> Result<(), String> {
        self.session_store.with_local_mcp_connection(|connection| {
            let transaction = connection
                .transaction_with_behavior(TransactionBehavior::Immediate)
                .map_err(|error| error.to_string())?;
            let now = chrono::Utc::now().to_rfc3339();
            let updated = transaction
                .execute(
                    "UPDATE desktop_mcp_servers_v1
                     SET runtime_status = 'error', reason_code = ?4, updated_at = ?5
                     WHERE tenant_id = ?1 AND project_id = ?2 AND id = ?3",
                    params![
                        server.tenant_id,
                        server.project_id,
                        server.id,
                        reason_code,
                        now,
                    ],
                )
                .map_err(|error| error.to_string())?;
            if updated != 1 {
                return Err("MCP server runtime row was not found".to_string());
            }
            transaction
                .execute(
                    "UPDATE desktop_mcp_apps_v1
                     SET status = 'error', revision = revision + 1, updated_at = ?4
                     WHERE tenant_id = ?1 AND project_id = ?2 AND server_id = ?3",
                    params![server.tenant_id, server.project_id, server.id, now],
                )
                .map_err(|error| error.to_string())?;
            transaction.commit().map_err(|error| error.to_string())
        })
    }

    pub(super) fn record_tools_and_apps(
        &self,
        server: &McpServerDefinition,
        tools: &[Value],
    ) -> Result<(), String> {
        self.session_store.with_local_mcp_connection(|connection| {
            let transaction = connection
                .transaction_with_behavior(TransactionBehavior::Immediate)
                .map_err(|error| error.to_string())?;
            let now = chrono::Utc::now().to_rfc3339();
            transaction
                .execute(
                    "UPDATE desktop_mcp_servers_v1
                     SET runtime_status = 'healthy', reason_code = NULL,
                         discovered_tools_json = ?4, updated_at = ?5
                     WHERE tenant_id = ?1 AND project_id = ?2 AND id = ?3",
                    params![
                        server.tenant_id,
                        server.project_id,
                        server.id,
                        serde_json::to_string(tools).map_err(|error| error.to_string())?,
                        now,
                    ],
                )
                .map_err(|error| error.to_string())?;
            transaction
                .execute(
                    "DELETE FROM desktop_mcp_apps_v1
                     WHERE tenant_id = ?1 AND project_id = ?2 AND server_id = ?3",
                    params![server.tenant_id, server.project_id, server.id],
                )
                .map_err(|error| error.to_string())?;
            for tool in tools {
                let Some(tool_name) = tool.get("name").and_then(Value::as_str) else {
                    continue;
                };
                let metadata = tool
                    .get("_meta")
                    .cloned()
                    .unwrap_or_else(|| Value::Object(serde_json::Map::new()));
                let resource_uri = metadata
                    .get("ui/resourceUri")
                    .or_else(|| metadata.get("mcp/ui/resourceUri"))
                    .and_then(Value::as_str);
                let Some(resource_uri) = resource_uri else {
                    continue;
                };
                let app_id = stable_app_id(
                    &server.tenant_id,
                    &server.project_id,
                    &server.id,
                    tool_name,
                    resource_uri,
                );
                transaction
                    .execute(
                        "INSERT INTO desktop_mcp_apps_v1(
                           id, tenant_id, project_id, server_id, server_name, tool_name,
                           resource_uri, ui_metadata_json, status, revision, updated_at
                         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, 'healthy', 1, ?9)",
                        params![
                            app_id,
                            server.tenant_id,
                            server.project_id,
                            server.id,
                            server.name,
                            tool_name,
                            resource_uri,
                            metadata.to_string(),
                            now,
                        ],
                    )
                    .map_err(|error| error.to_string())?;
            }
            transaction.commit().map_err(|error| error.to_string())
        })
    }

    pub(super) fn list_apps(&self, scope: &McpScope) -> McpResult<Vec<McpAppDefinition>> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                let mut statement = connection
                    .prepare(
                        "SELECT id, tenant_id, project_id, server_id, server_name, tool_name,
                                resource_uri, ui_metadata_json, status, revision
                         FROM desktop_mcp_apps_v1
                         WHERE tenant_id = ?1 AND project_id = ?2
                         ORDER BY server_name, tool_name, id",
                    )
                    .map_err(|error| error.to_string())?;
                let rows = statement
                    .query_map(params![scope.tenant_id, scope.project_id], app_from_row)
                    .map_err(|error| error.to_string())?;
                rows.collect::<rusqlite::Result<Vec<_>>>()
                    .map_err(|error| error.to_string())
            })
            .map_err(|_| storage_error())
    }

    pub(super) fn app(
        &self,
        scope: &McpScope,
        app_id: &str,
    ) -> McpResult<Option<McpAppDefinition>> {
        self.session_store
            .with_local_mcp_connection(|connection| {
                connection
                    .query_row(
                        "SELECT id, tenant_id, project_id, server_id, server_name, tool_name,
                                resource_uri, ui_metadata_json, status, revision
                         FROM desktop_mcp_apps_v1
                         WHERE tenant_id = ?1 AND project_id = ?2 AND id = ?3",
                        params![scope.tenant_id, scope.project_id, app_id],
                        app_from_row,
                    )
                    .optional()
                    .map_err(|error| error.to_string())
            })
            .map_err(|_| storage_error())
    }

    #[cfg(test)]
    pub(super) fn seed_route_contract_fixture(&self, scope: &McpScope) -> Result<(), String> {
        self.session_store.with_local_mcp_connection(|connection| {
            let transaction = connection
                .transaction_with_behavior(TransactionBehavior::Immediate)
                .map_err(|error| error.to_string())?;
            let now = chrono::Utc::now().to_rfc3339();
            transaction
                .execute(
                    "INSERT OR REPLACE INTO desktop_mcp_servers_v1(
                       id, tenant_id, project_id, name, description, transport, command_json,
                       cwd, vault_env_refs_json, enabled, revision, runtime_status,
                       reason_code, discovered_tools_json, server_info_json, created_at, updated_at
                     ) VALUES (
                       'route-contract-mcp-server', ?1, ?2, 'example', 'route fixture', 'stdio',
                       '[\"/missing\"]', '.', '{}', 0, 1, 'disabled', NULL, '[]', NULL, ?3, ?3
                     )",
                    params![scope.tenant_id, scope.project_id, now],
                )
                .map_err(|error| error.to_string())?;
            transaction
                .execute(
                    "INSERT OR REPLACE INTO desktop_mcp_apps_v1(
                       id, tenant_id, project_id, server_id, server_name, tool_name,
                       resource_uri, ui_metadata_json, status, revision, updated_at
                     ) VALUES (
                       'app-1', ?1, ?2, 'route-contract-mcp-server', 'example', 'example',
                       'ui://example/index.html',
                       '{\"ui/resourceUri\":\"ui://example/index.html\"}',
                       'degraded', 1, ?3
                     )",
                    params![scope.tenant_id, scope.project_id, now],
                )
                .map_err(|error| error.to_string())?;
            transaction.commit().map_err(|error| error.to_string())
        })
    }
}

fn server_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<McpServerDefinition> {
    let transport = parse_transport(&row.get::<_, String>(5)?).map_err(conversion_error)?;
    let command = serde_json::from_str(&row.get::<_, String>(6)?).map_err(conversion_error)?;
    let vault_env_refs =
        serde_json::from_str(&row.get::<_, String>(8)?).map_err(conversion_error)?;
    let discovered_tools =
        serde_json::from_str(&row.get::<_, String>(13)?).map_err(conversion_error)?;
    let server_info_json = row.get::<_, Option<String>>(14)?;
    let server_info = server_info_json
        .map(|value| serde_json::from_str(&value))
        .transpose()
        .map_err(conversion_error)?;
    let revision = u64::try_from(row.get::<_, i64>(10)?).map_err(conversion_error)?;
    Ok(McpServerDefinition {
        id: row.get(0)?,
        tenant_id: row.get(1)?,
        project_id: row.get(2)?,
        name: row.get(3)?,
        description: row.get(4)?,
        transport,
        command,
        cwd: row.get(7)?,
        vault_env_refs,
        enabled: row.get::<_, i64>(9)? != 0,
        revision,
        runtime_status: row.get(11)?,
        reason_code: row.get(12)?,
        discovered_tools,
        server_info,
        created_at: row.get(15)?,
        updated_at: row.get(16)?,
    })
}

fn app_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<McpAppDefinition> {
    Ok(McpAppDefinition {
        id: row.get(0)?,
        tenant_id: row.get(1)?,
        project_id: row.get(2)?,
        server_id: row.get(3)?,
        server_name: row.get(4)?,
        tool_name: row.get(5)?,
        resource_uri: row.get(6)?,
        ui_metadata: serde_json::from_str(&row.get::<_, String>(7)?).map_err(conversion_error)?,
        status: row.get(8)?,
        revision: u64::try_from(row.get::<_, i64>(9)?).map_err(conversion_error)?,
    })
}

fn parse_transport(value: &str) -> Result<McpTransport, String> {
    match value {
        "stdio" => Ok(McpTransport::Stdio),
        "http" => Ok(McpTransport::Http),
        "sse" => Ok(McpTransport::Sse),
        "websocket" => Ok(McpTransport::Websocket),
        _ => Err("stored MCP transport is invalid".to_string()),
    }
}

fn stable_app_id(
    tenant_id: &str,
    project_id: &str,
    server_id: &str,
    tool_name: &str,
    resource_uri: &str,
) -> String {
    let mut hasher = Sha256::new();
    hasher.update(tenant_id);
    hasher.update([0]);
    hasher.update(project_id);
    hasher.update([0]);
    hasher.update(server_id);
    hasher.update([0]);
    hasher.update(tool_name);
    hasher.update([0]);
    hasher.update(resource_uri);
    let digest = format!("{:x}", hasher.finalize());
    format!("local-mcp-app-{}", &digest[..32])
}

fn server_internal_json(server: &McpServerDefinition) -> Result<String, String> {
    Ok(serde_json::json!({
        "id": server.id,
        "tenant_id": server.tenant_id,
        "project_id": server.project_id,
        "name": server.name,
        "description": server.description,
        "transport": server.transport.as_str(),
        "command": server.command,
        "cwd": server.cwd,
        "vault_env_refs": server.vault_env_refs,
        "enabled": server.enabled,
        "revision": server.revision,
        "runtime_status": server.runtime_status,
        "reason_code": server.reason_code,
        "discovered_tools": server.discovered_tools,
        "server_info": server.server_info,
        "created_at": server.created_at,
        "updated_at": server.updated_at,
    })
    .to_string())
}

fn server_from_internal_json(value: &str) -> Result<McpServerDefinition, String> {
    let value: Value = serde_json::from_str(value).map_err(|error| error.to_string())?;
    let transport = parse_transport(
        value
            .get("transport")
            .and_then(Value::as_str)
            .ok_or_else(|| "stored MCP transport is missing".to_string())?,
    )?;
    Ok(McpServerDefinition {
        id: required_string(&value, "id")?,
        tenant_id: required_string(&value, "tenant_id")?,
        project_id: required_string(&value, "project_id")?,
        name: required_string(&value, "name")?,
        description: optional_string(&value, "description"),
        transport,
        command: serde_json::from_value(value.get("command").cloned().unwrap_or(Value::Null))
            .map_err(|error| error.to_string())?,
        cwd: optional_string(&value, "cwd"),
        vault_env_refs: serde_json::from_value(
            value
                .get("vault_env_refs")
                .cloned()
                .unwrap_or_else(|| serde_json::json!({})),
        )
        .map_err(|error| error.to_string())?,
        enabled: value
            .get("enabled")
            .and_then(Value::as_bool)
            .ok_or_else(|| "stored MCP enabled value is missing".to_string())?,
        revision: value
            .get("revision")
            .and_then(Value::as_u64)
            .ok_or_else(|| "stored MCP revision is missing".to_string())?,
        runtime_status: required_string(&value, "runtime_status")?,
        reason_code: optional_string(&value, "reason_code"),
        discovered_tools: serde_json::from_value(
            value
                .get("discovered_tools")
                .cloned()
                .unwrap_or_else(|| serde_json::json!([])),
        )
        .map_err(|error| error.to_string())?,
        server_info: value
            .get("server_info")
            .filter(|item| !item.is_null())
            .cloned(),
        created_at: required_string(&value, "created_at")?,
        updated_at: required_string(&value, "updated_at")?,
    })
}

fn required_string(value: &Value, field: &str) -> Result<String, String> {
    value
        .get(field)
        .and_then(Value::as_str)
        .map(ToString::to_string)
        .ok_or_else(|| format!("stored MCP field {field} is missing"))
}

fn optional_string(value: &Value, field: &str) -> Option<String> {
    value
        .get(field)
        .and_then(Value::as_str)
        .map(ToString::to_string)
}

fn conversion_error(error: impl std::fmt::Display) -> rusqlite::Error {
    rusqlite::Error::FromSqlConversionFailure(
        0,
        rusqlite::types::Type::Text,
        Box::new(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            error.to_string(),
        )),
    )
}

fn map_store_error(error: String) -> McpSupervisorError {
    match error.as_str() {
        "idempotency_conflict" => McpSupervisorError::new(
            "local_mcp_idempotency_conflict",
            "MCP idempotency key is already bound to a different request",
        ),
        "server_name_conflict" => McpSupervisorError::new(
            "local_mcp_server_name_conflict",
            "MCP server name already exists in this project",
        ),
        _ => storage_error(),
    }
}
