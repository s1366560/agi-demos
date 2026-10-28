//! Non-secret manual OAuth state. Tokens and PKCE verifiers never enter this table.
use rusqlite::{params, OptionalExtension};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

use super::{McpScope, McpStore};

#[derive(Clone, Default, Deserialize, Serialize)]
pub(in crate::local_runtime) struct ManualOAuthFlow {
    pub status: String,
    pub flow: String,
    pub expected_revision: u64,
    pub authorization_url: Option<String>,
    pub expires_at: Option<i64>,
    pub request_key: String,
    pub request_hash: String,
    #[serde(default)]
    pub requests: BTreeMap<String, String>,
    pub reason: Option<String>,
}

impl McpStore {
    pub(in crate::local_runtime::mcp_supervisor) fn manual_oauth_flow(
        &self,
        scope: &McpScope,
        server_id: &str,
        user_id: &str,
    ) -> Result<Option<ManualOAuthFlow>, String> {
        self.session_store.with_local_mcp_connection(|db| {
            let raw: Option<String> = db.query_row(
                "SELECT metadata_json FROM desktop_mcp_oauth_flows_v1 WHERE tenant_id=?1 AND project_id=?2 AND server_id=?3 AND user_id=?4",
                params![scope.tenant_id, scope.project_id, server_id, user_id], |row| row.get(0),
            ).optional().map_err(|error| error.to_string())?;
            raw.map(|value| serde_json::from_str(&value).map_err(|error| error.to_string())).transpose()
        })
    }

    pub(in crate::local_runtime::mcp_supervisor) fn save_manual_oauth_flow(
        &self,
        scope: &McpScope,
        server_id: &str,
        user_id: &str,
        flow: &ManualOAuthFlow,
    ) -> Result<(), String> {
        let raw = serde_json::to_string(flow).map_err(|error| error.to_string())?;
        self.session_store.with_local_mcp_connection(|db| {
            db.execute(
                "INSERT INTO desktop_mcp_oauth_flows_v1(tenant_id,project_id,server_id,user_id,metadata_json) VALUES(?1,?2,?3,?4,?5) ON CONFLICT(tenant_id,project_id,server_id,user_id) DO UPDATE SET metadata_json=excluded.metadata_json",
                params![scope.tenant_id, scope.project_id, server_id, user_id, raw],
            ).map_err(|error| error.to_string())?;
            Ok(())
        })
    }
}
