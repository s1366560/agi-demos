//! Connector account metadata shares the existing native OAuth and encrypted MCP vault.
use super::Owner;
use crate::local_runtime::{
    mcp_supervisor::{self, McpScope, McpServerDefinitionInput, McpTransport},
    plugin_marketplace_v3::oauth,
    LocalRuntimeState,
};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::sync::Arc;
static MUTATION: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

#[derive(Clone, Serialize, Deserialize)]
pub(super) struct Account {
    pub id: String,
    pub provider: String,
    pub status: String,
    pub reason: Option<String>,
    pub authorization_url: Option<String>,
    pub expires_at: Option<i64>,
    #[serde(default)]
    pub client_id: String,
    #[serde(default)]
    pub flow: String,
}
pub(super) fn initialize(db: &Connection) -> Result<(), String> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS desktop_cua_accounts_v2 (
        id TEXT PRIMARY KEY,user_id TEXT NOT NULL,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,device_id TEXT NOT NULL,account_json TEXT NOT NULL);")
        .map_err(|error|error.to_string())
}
fn scope(owner: &Owner) -> McpScope {
    McpScope {
        tenant_id: owner.tenant_id.clone(),
        project_id: owner.project_id.clone(),
    }
}
fn save(state: &LocalRuntimeState, owner: &Owner, account: &Account) -> Result<(), String> {
    state
        .session_store
        .connection()?
        .execute(
            "INSERT OR REPLACE INTO desktop_cua_accounts_v2 VALUES(?1,?2,?3,?4,?5,?6)",
            params![
                account.id,
                owner.user_id,
                owner.tenant_id,
                owner.project_id,
                owner.device_id,
                serde_json::to_string(account).map_err(|_| "cua_account_invalid")?
            ],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}
fn records(state: &LocalRuntimeState, owner: &Owner) -> Result<Vec<Account>, String> {
    let db = state.session_store.connection()?;
    let mut query=db.prepare("SELECT account_json FROM desktop_cua_accounts_v2 WHERE user_id=?1 AND tenant_id=?2 AND project_id=?3 AND device_id=?4").map_err(|error|error.to_string())?;
    let rows = query
        .query_map(
            params![
                owner.user_id,
                owner.tenant_id,
                owner.project_id,
                owner.device_id
            ],
            |row| row.get::<_, String>(0),
        )
        .map_err(|error| error.to_string())?;
    rows.map(|row| {
        serde_json::from_str(&row.map_err(|error| error.to_string())?)
            .map_err(|_| "cua_account_invalid".into())
    })
    .collect()
}
pub(super) fn owned_ids(
    state: &LocalRuntimeState,
    owner: &Owner,
) -> Result<std::collections::BTreeSet<String>, String> {
    Ok(records(state, owner)?
        .into_iter()
        .map(|account| account.id)
        .collect())
}
fn account(state: &LocalRuntimeState, owner: &Owner, id: &str) -> Result<Account, String> {
    records(state, owner)?
        .into_iter()
        .find(|account| account.id == id)
        .ok_or("cua_account_not_found".into())
}
pub(super) fn list(state: &LocalRuntimeState, owner: &Owner) -> Result<Vec<Value>, String> {
    records(state,owner)?.into_iter().map(|mut account| {
        if account.status=="authorizing" && (!oauth::pending(&account.flow)||account.expires_at.is_none_or(|expires|expires<=chrono::Utc::now().timestamp())) {
            account.status="expired".into();account.authorization_url=None;account.flow.clear();save(state,owner,&account)?;
        }
        if account.status!="authorizing" {
            let status=state.mcp_supervisor.oauth_status(&account.id).map_err(|error|error.reason_code().to_owned())?;
            if status["status"]=="connected" {account.status="connected".into();}
        }
        Ok(json!({"account_id":account.id,"provider":account.provider,"status":account.status,"reason":account.reason,"authorization_url":account.authorization_url,"expires_at":account.expires_at}))
    }).collect()
}
pub(super) async fn connect(
    state: &Arc<LocalRuntimeState>,
    owner: &Owner,
    provider: &str,
    client_id: &str,
) -> Result<(), String> {
    let _guard = MUTATION.lock().await;
    if client_id.trim().is_empty() || client_id.len() > 1024 {
        return Err("oauth_client_configuration_required".into());
    }
    let metadata = provider_metadata(provider)?;
    let command = mcp_supervisor::stdio::bundled_cloud_connector_path()
        .ok_or("cua_connector_helper_unavailable")?
        .to_string_lossy()
        .into_owned();
    let id = uuid::Uuid::new_v4().to_string();
    let server = state
        .mcp_supervisor
        .create_server(
            &scope(owner),
            McpServerDefinitionInput {
                name: format!("cua-{provider}-{id}"),
                description: None,
                transport: McpTransport::Stdio,
                command: vec![command.clone(), "--provider".into(), provider.into()],
                cwd: None,
                vault_env_refs: Default::default(),
                enabled: false,
            },
            &format!("cua-account-{id}"),
        )
        .map_err(|error| error.reason_code().to_owned())?;
    save(
        state,
        owner,
        &Account {
            id: server.id.clone(),
            provider: provider.into(),
            status: "not_connected".into(),
            reason: None,
            authorization_url: None,
            expires_at: None,
            client_id: client_id.into(),
            flow: String::new(),
        },
    )?;
    oauth::begin_connector(
        state, owner, &server.id, &server.id, &command, client_id, metadata,
    )
    .await
}
pub(super) async fn action(
    state: &Arc<LocalRuntimeState>,
    owner: &Owner,
    id: &str,
    action: &str,
) -> Result<(), String> {
    let _guard = MUTATION.lock().await;
    let mut account = account(state, owner, id)?;
    oauth::cancel(&account.flow);
    account.flow.clear();
    account.authorization_url = None;
    if action == "start" {
        let server = state
            .mcp_supervisor
            .server(&scope(owner), id)
            .map_err(|error| error.reason_code().to_owned())?
            .ok_or("cua_account_not_found")?;
        if !mcp_supervisor::stdio::trusted_cloud_connector(&server) {
            return Err("cua_connector_target_changed".into());
        }
        save(state, owner, &account)?;
        return oauth::begin_connector(
            state,
            owner,
            id,
            id,
            &server.command[0],
            &account.client_id,
            provider_metadata(&account.provider)?,
        )
        .await;
    }
    if action == "disconnect" {
        state
            .mcp_supervisor
            .oauth_disconnect(id)
            .await
            .map_err(|error| error.reason_code().to_owned())?;
        set_enabled(state, owner, id, false)?;
    } else if action != "cancel" {
        return Err("oauth_action_invalid".into());
    }
    account.status = "not_connected".into();
    save(state, owner, &account)
}
pub(in crate::local_runtime) fn mark_authorizing(
    state: &LocalRuntimeState,
    owner: &Owner,
    id: &str,
    flow: &str,
    url: &str,
    expires: i64,
) -> Result<(), String> {
    let mut account = account(state, owner, id)?;
    account.status = "authorizing".into();
    account.reason = None;
    account.flow = flow.into();
    account.authorization_url = Some(url.into());
    account.expires_at = Some(expires);
    save(state, owner, &account)
}
#[allow(clippy::too_many_arguments)]
pub(in crate::local_runtime) async fn complete_oauth(
    state: &Arc<LocalRuntimeState>,
    owner: &Owner,
    id: &str,
    flow: &str,
    server_id: &str,
    client_id: &str,
    resource: &str,
    metadata: &Value,
    tokens: Result<Value, String>,
) -> Result<(), String> {
    let _guard = MUTATION.lock().await;
    let mut account = account(state, owner, id)?;
    if account.flow != flow
        || account.status != "authorizing"
        || account.id != server_id
        || account
            .expires_at
            .is_none_or(|expires| expires <= chrono::Utc::now().timestamp())
    {
        return Err("oauth_state_invalid".into());
    }
    account.flow.clear();
    account.authorization_url = None;
    account.status = "error".into();
    account.reason = Some("oauth_callback_interrupted".into());
    save(state, owner, &account)?;
    let outcome = async {
        let tokens = tokens?;
        state
            .mcp_supervisor
            .oauth_connect(&scope(owner), id, metadata, client_id, resource, &tokens)
            .map_err(|error| error.reason_code().to_owned())?;
        let instance = {
            let db = state.session_store.connection()?;
            super::store::instance(&db, owner)?
        };
        if instance.installed && instance.enabled {
            set_enabled(state, owner, id, true)?;
            state
                .mcp_supervisor
                .list_tools(&scope(owner), id)
                .await
                .map_err(|error| error.reason_code().to_owned())?;
        }
        Ok::<_, String>(())
    }
    .await;
    match &outcome {
        Ok(()) => {
            account.status = "connected".into();
            account.reason = None;
        }
        Err(error) => {
            let _ = set_enabled(state, owner, id, false);
            account.reason = Some(error.clone());
        }
    }
    save(state, owner, &account)?;
    outcome
}
pub(super) async fn plugin_enabled(
    state: &LocalRuntimeState,
    owner: &Owner,
    enabled: bool,
) -> Result<(), String> {
    let _guard = MUTATION.lock().await;
    for mut account in records(state, owner)? {
        if !enabled {
            oauth::cancel(&account.flow);
            account.flow.clear();
            account.authorization_url = None;
            if account.status == "authorizing" {
                account.status = "not_connected".into();
            }
            save(state, owner, &account)?;
        }
        let connected = state
            .mcp_supervisor
            .oauth_status(&account.id)
            .map_err(|error| error.reason_code().to_owned())?["status"]
            == "connected";
        set_enabled(state, owner, &account.id, enabled && connected)?;
        if enabled && connected {
            state
                .mcp_supervisor
                .list_tools(&scope(owner), &account.id)
                .await
                .map_err(|error| error.reason_code().to_owned())?;
        }
    }
    Ok(())
}
fn set_enabled(
    state: &LocalRuntimeState,
    owner: &Owner,
    id: &str,
    enabled: bool,
) -> Result<(), String> {
    let server = state
        .mcp_supervisor
        .server(&scope(owner), id)
        .map_err(|error| error.reason_code().to_owned())?
        .ok_or("cua_account_not_found")?;
    state
        .mcp_supervisor
        .update_server(
            &scope(owner),
            id,
            McpServerDefinitionInput {
                name: server.name,
                description: server.description,
                transport: server.transport,
                command: server.command,
                cwd: server.cwd,
                vault_env_refs: server.vault_env_refs,
                enabled,
            },
            server.revision,
            &format!("cua-account-enable-{}", uuid::Uuid::new_v4()),
        )
        .map(|_| ())
        .map_err(|error| error.reason_code().to_owned())
}
pub(in crate::local_runtime) fn provider_metadata(provider: &str) -> Result<Value, String> {
    match provider {
        "google" => Ok(
            json!({"authorization_endpoint":"https://accounts.google.com/o/oauth2/v2/auth","token_endpoint":"https://oauth2.googleapis.com/token","revocation_endpoint":"https://oauth2.googleapis.com/revoke","scope":"https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/contacts","_memstack_send_resource":false,"_memstack_google_offline":true}),
        ),
        "microsoft365" => Ok(
            json!({"authorization_endpoint":"https://login.microsoftonline.com/common/oauth2/v2.0/authorize","token_endpoint":"https://login.microsoftonline.com/common/oauth2/v2.0/token","scope":"offline_access https://graph.microsoft.com/Calendars.ReadWrite https://graph.microsoft.com/Contacts.ReadWrite","_memstack_send_resource":false}),
        ),
        _ => Err("cua_connector_provider_invalid".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn provider_metadata_is_explicit_delegated_and_excludes_path_resource() {
        let google = provider_metadata("google").unwrap();
        assert_eq!(google["_memstack_send_resource"], false);
        let microsoft = provider_metadata("microsoft365").unwrap();
        assert!(microsoft["scope"]
            .as_str()
            .unwrap()
            .contains("Calendars.ReadWrite"));
        assert!(microsoft["token_endpoint"]
            .as_str()
            .unwrap()
            .contains("/common/"));
        assert!(provider_metadata("name_contains_google").is_err());
    }
    #[test]
    fn account_records_are_scoped_to_native_owner() {
        let state = crate::local_runtime::tests::test_state("cua-account-owner");
        let owner = super::super::tests::owner(&state);
        save(
            &state,
            &owner,
            &Account {
                id: "account".into(),
                provider: "google".into(),
                status: "not_connected".into(),
                reason: None,
                authorization_url: None,
                expires_at: None,
                client_id: "public-client".into(),
                flow: String::new(),
            },
        )
        .unwrap();
        let mut other = owner.clone();
        other.user_id = "different-user".into();
        assert!(account(&state, &other, "account").is_err());
    }
}
