//! A refused native request closes its whole trusted run; transport changes cannot reset consent.
use super::*;
use rusqlite::{params, Connection};
pub(super) fn initialize(db: &Connection) -> Result<(), String> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS desktop_cua_denials_v2(user_id TEXT NOT NULL,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,device_id TEXT NOT NULL,run_id TEXT NOT NULL,request_id TEXT NOT NULL,PRIMARY KEY(user_id,tenant_id,project_id,device_id,run_id));").map_err(|error|error.to_string())
}
pub(super) fn deny(db: &Connection, owner: &Owner, run: &str, request: &str) -> Result<(), String> {
    db.execute(
        "INSERT OR IGNORE INTO desktop_cua_denials_v2 VALUES(?1,?2,?3,?4,?5,?6)",
        params![
            owner.user_id,
            owner.tenant_id,
            owner.project_id,
            owner.device_id,
            run,
            request
        ],
    )
    .map(|_| ())
    .map_err(|error| error.to_string())
}
pub(super) fn ensure(db: &Connection, owner: &Owner, run: &str) -> CoreResult<()> {
    let denied:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM desktop_cua_denials_v2 WHERE user_id=?1 AND tenant_id=?2 AND project_id=?3 AND device_id=?4 AND run_id=?5)",params![owner.user_id,owner.tenant_id,owner.project_id,owner.device_id,run],|row|row.get(0)).map_err(|error|CoreError::Storage(error.to_string()))?;
    if denied {
        Err(CoreError::Tool("cua_permission_denied_run: the user refused native access for this run; changing tools, target applications, connectors, rounds, or sessions cannot authorize a fallback".into()))
    } else {
        Ok(())
    }
}
pub(in crate::local_runtime) fn ensure_mcp_run(
    state: &LocalRuntimeState,
    conversation_id: &str,
    run_id: &str,
) -> CoreResult<()> {
    let conversation = state
        .session_store
        .conversation(conversation_id)
        .map_err(CoreError::Storage)?
        .ok_or(CoreError::NotFound)?;
    let run = state
        .session_store
        .run(run_id)
        .map_err(CoreError::Storage)?
        .ok_or(CoreError::NotFound)?;
    let identity = PluginNativeIdentityV2::capture(state, &conversation, Some(&run))
        .ok_or_else(|| CoreError::Tool("cua_native_run_identity_required".into()))?;
    let owner = Owner {
        user_id: identity.auth().user.user_id.clone(),
        tenant_id: conversation.tenant_id,
        project_id: conversation.project_id,
        device_id: state.session_store.installation_id().into(),
    };
    ensure(
        &*state
            .session_store
            .connection()
            .map_err(CoreError::Storage)?,
        &owner,
        run_id,
    )
}
pub(super) struct DeniedHost;
#[async_trait::async_trait]
impl ToolHost for DeniedHost {
    fn list_tools(&self) -> Vec<String> {
        agistack_adapters_cua::tool_names()
            .into_iter()
            .map(str::to_owned)
            .collect()
    }
    fn tool_definition(&self, tool: &str) -> Option<ToolDefinition> {
        let definitions = agistack_adapters_cua::tool_definitions();
        let definition = definitions.get(tool)?;
        Some(ToolDefinition::new(
            tool,
            definition["description"].as_str().unwrap_or_default(),
            definition["inputSchema"].clone(),
        ))
    }
    async fn call(&self, _: &str, _: &str) -> CoreResult<String> {
        Err(CoreError::Tool("cua_permission_denied_run".into()))
    }
}
