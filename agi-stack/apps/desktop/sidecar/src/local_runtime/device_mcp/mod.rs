//! Explicit device-local MCP configuration for the selected trusted Cloud project.
use std::{sync::Arc, time::Instant};

use serde::Deserialize;
use serde_json::{json, Value};

use super::{
    mcp_supervisor::{McpScope, McpServerDefinition},
    parity_routes::device_mcp_contract as contract,
    LocalRuntimeState,
};
use crate::trusted_session::TrustedSessionBroker;

mod authority;
pub(super) use authority::claim_scope;
#[cfg(test)]
mod tests;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    tenant_id: String,
    project_id: String,
    context_token: Option<String>,
    operation: Operation,
}

#[derive(Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
enum Operation {
    List,
    Get { server_id: String },
    Create { body: Value },
    Update { server_id: String, body: Value },
    Delete { server_id: String, body: Value },
    Test { server_id: String },
    ProvisionCredential { body: Value },
}

fn server(
    state: &LocalRuntimeState,
    owner: &authority::CloudOwner,
    id: &str,
) -> Result<McpServerDefinition, String> {
    state
        .mcp_supervisor
        .server(&owner.scope, id)
        .map_err(|error| error.reason_code().to_owned())?
        .ok_or_else(|| "local_mcp_server_not_found".into())
}

fn response(owner: &authority::CloudOwner, server: &McpServerDefinition) -> Value {
    contract::response(server, &owner.tenant, &owner.project)
}

pub(super) async fn native_operation(
    state: &Arc<LocalRuntimeState>,
    broker: &TrustedSessionBroker,
    input: Value,
) -> Result<Value, String> {
    let input: Request = serde_json::from_value(input).map_err(|_| "device_mcp_request_invalid")?;
    let owner = authority::CloudOwner::resolve(
        broker,
        state.session_store.installation_id(),
        &input.tenant_id,
        &input.project_id,
    )
    .await?;
    if !matches!(input.operation, Operation::List)
        && input.context_token.as_deref() != Some(&owner.token)
    {
        return Err("device_mcp_context_changed".into());
    }
    if !matches!(input.operation, Operation::List | Operation::Get { .. }) && !owner.manager {
        return Err("device_mcp_manager_required".into());
    }
    let result = match input.operation {
        Operation::List => owner.fence(|| {
            let servers = state
                .mcp_supervisor
                .list_servers(&owner.scope)
                .map_err(|error| error.reason_code().to_owned())?;
            Ok(json!(servers
                .iter()
                .map(|server| response(&owner, server))
                .collect::<Vec<_>>()))
        })?,
        Operation::Get { server_id } => {
            owner.fence(|| Ok(response(&owner, &server(state, &owner, &server_id)?)))?
        }
        Operation::Create { body } => {
            let (definition, key) = contract::create(body, &owner.scope, &owner.project)?;
            owner.fence(|| {
                state
                    .mcp_supervisor
                    .create_server(&owner.scope, definition, &key)
                    .map(|server| response(&owner, &server))
                    .map_err(|error| error.reason_code().to_owned())
            })?
        }
        Operation::Update { server_id, body } => owner.fence(|| {
            let current = server(state, &owner, &server_id)?;
            let (definition, revision, key) =
                contract::update(body, current, &owner.scope, &owner.project)?;
            state
                .mcp_supervisor
                .update_server(&owner.scope, &server_id, definition, revision, &key)
                .map(|server| response(&owner, &server))
                .map_err(|error| error.reason_code().to_owned())
        })?,
        Operation::Delete { server_id, body } => {
            let (revision, key) = contract::delete(body, &owner.project)?;
            owner.fence(|| state.mcp_supervisor.delete_server(&owner.scope, &server_id, revision, &key)
                .map(|result| json!({"deleted":true,"id":result.id,"revision":result.revision,"duplicate":result.duplicate}))
                .map_err(|error| error.reason_code().to_owned()))?
        }
        Operation::ProvisionCredential { body } => {
            let (definition, secret, key) = contract::credential(body, &owner.project)?;
            owner.fence(|| {
                state
                    .mcp_supervisor
                    .provision_credential(&owner.scope, &definition, secret.as_str(), &key)
                    .map(|result| {
                        json!({"stored":true,"credential_kind":definition.kind,
                    "credential_name":definition.name,"duplicate":result.duplicate})
                    })
                    .map_err(|error| error.reason_code().to_owned())
            })?
        }
        Operation::Test { server_id } => test_server(state, &owner, &server_id).await?,
    };
    owner.fence(|| Ok(owner.response(result)))
}

async fn test_server(
    state: &LocalRuntimeState,
    owner: &authority::CloudOwner,
    id: &str,
) -> Result<Value, String> {
    owner.fence(|| {
        if !server(state, owner, id)?.enabled {
            return Err("local_mcp_server_disabled".into());
        }
        Ok(())
    })?;
    let started = Instant::now();
    let discovery = state.mcp_supervisor.list_tools(&owner.scope, id);
    let local_revoked = async {
        loop {
            tokio::time::sleep(std::time::Duration::from_millis(200)).await;
            owner.fence(|| Ok(()))?;
        }
        #[allow(unreachable_code)]
        Ok::<(), String>(())
    };
    let remote_revoked = async {
        loop {
            tokio::time::sleep(std::time::Duration::from_millis(200)).await;
            owner.recheck().await?;
        }
        #[allow(unreachable_code)]
        Ok::<(), String>(())
    };
    let outcome = tokio::select! {
        tools = discovery => tools.map_err(|error| error.reason_code().to_owned()),
        revoked = local_revoked => {
            let _ = state.mcp_supervisor.evict_runtime(id);
            return Err(revoked.err().unwrap_or_else(|| "device_mcp_context_changed".into()));
        }
        revoked = remote_revoked => {
            let _ = state.mcp_supervisor.evict_runtime(id);
            return Err(revoked.err().unwrap_or_else(|| "device_mcp_context_changed".into()));
        }
    };
    if let Err(error) = owner.recheck().await {
        let _ = state.mcp_supervisor.evict_runtime(id);
        return Err(error);
    }
    let tools = outcome?;
    owner.fence(|| Ok(json!({"success":true,"message":"MCP handshake succeeded",
        "tools_discovered":tools.len(),"connection_time_ms":started.elapsed().as_secs_f64()*1000.0,"errors":[]})))
}
