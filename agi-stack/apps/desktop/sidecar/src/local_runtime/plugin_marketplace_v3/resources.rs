use super::super::{
    mcp_supervisor::{
        self, McpCredentialKind, McpCredentialProvisionInput, McpScope, McpServerDefinitionInput,
        McpTransport,
    },
    ManagedResourceKind,
};
use super::{
    package::{self, Result},
    AuthenticatedContext, Installation, LocalRuntimeState,
};
use serde_json::{json, Value};
use std::collections::BTreeMap;

fn scope(auth: &AuthenticatedContext) -> McpScope {
    McpScope {
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
    }
}
fn expand(value: &str, installation: &Installation) -> String {
    value
        .replace(
            "${PLUGIN_ROOT}",
            &installation.package.root.to_string_lossy(),
        )
        .replace(
            "${CLAUDE_PLUGIN_ROOT}",
            &installation.package.root.to_string_lossy(),
        )
}
fn executable(raw: String) -> Result<String> {
    let path = std::path::Path::new(&raw);
    if path.is_absolute() {
        return Ok(raw);
    }
    if path.components().count() != 1 {
        return Err("MCP executable must be absolute or a PATH command".into());
    }
    let search = std::env::var_os("PATH").ok_or("command PATH is unavailable")?;
    for directory in std::env::split_paths(&search) {
        let candidate = directory.join(&raw);
        if candidate.is_file() {
            return std::fs::canonicalize(candidate)
                .map(|p| p.to_string_lossy().into_owned())
                .map_err(|e| e.to_string());
        }
    }
    Err(format!("MCP executable {raw} is unavailable"))
}
fn input(
    installation: &Installation,
    name: &str,
    config: &Value,
) -> Result<McpServerDefinitionInput> {
    let remote = config.get("url").and_then(Value::as_str);
    let transport = if remote.is_some() {
        match config.get("type").and_then(Value::as_str).unwrap_or("http") {
            "http" | "streamable-http" => McpTransport::Http,
            "sse" => McpTransport::Sse,
            "websocket" => McpTransport::Websocket,
            _ => return Err("unsupported MCP transport".into()),
        }
    } else {
        McpTransport::Stdio
    };
    let command = if let Some(url) = remote {
        vec![url.to_owned()]
    } else {
        let mut args = vec![executable(expand(
            config
                .get("command")
                .and_then(Value::as_str)
                .ok_or("MCP command required")?,
            installation,
        ))?];
        if let Some(values) = config.get("args").and_then(Value::as_array) {
            for value in values {
                args.push(expand(
                    value.as_str().ok_or("MCP arguments must be strings")?,
                    installation,
                ));
            }
        }
        args
    };
    Ok(McpServerDefinitionInput {
        name: format!("plugin-{}-{name}", installation.id),
        description: Some(installation.package.descriptor.description.clone()),
        transport,
        command,
        cwd: None,
        vault_env_refs: BTreeMap::new(),
        enabled: false,
    })
}
pub(super) fn register(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    installation: &mut Installation,
) -> Result<()> {
    let result = (|| {
        for (name, body) in &installation.package.skills {
            let id = format!("plugin:{}:{name}", installation.id);
            if state
                .session_store
                .managed_resource(
                    ManagedResourceKind::Skill,
                    "project",
                    &auth.workspace.project_id,
                    &id,
                )?
                .is_some()
            {
                return Err("owned skill identifier already exists".into());
            }
            state.session_store.put_managed_resource(ManagedResourceKind::Skill,"project",&auth.workspace.project_id,&id,"disabled",None,json!({"id":id,"name":name,"description":installation.package.descriptor.description,"full_content":body,"status":"disabled","tools":["*"],"scope":"project","tenant_id":auth.workspace.tenant_id,"project_id":auth.workspace.project_id,"is_system_skill":false,"plugin_id":installation.plugin_id,"plugin_version":installation.version}),chrono::Utc::now().timestamp_millis()).map_err(|e|e.to_string())?;
            installation.skill_ids.push(id);
        }
        for (name, config) in &installation.package.servers {
            let server = state
                .mcp_supervisor
                .create_server(
                    &scope(auth),
                    input(installation, name, config)?,
                    &format!("market-install-{}-{name}", installation.id),
                )
                .map_err(|e| e.to_string())?;
            installation.server_ids.push(server.id);
            state
                .mcp_supervisor
                .stage_marketplace_server(
                    &scope(auth),
                    installation
                        .server_ids
                        .last()
                        .ok_or("server registration missing")?,
                )
                .map_err(|e| e.to_string())?;
            state
                .mcp_supervisor
                .bind_marketplace_snapshot(
                    installation.server_ids.last().ok_or("server missing")?,
                    &installation.package.root,
                )
                .map_err(|e| e.to_string())?;
        }
        Ok(())
    })();
    if result.is_err() {
        let _ = remove(state, auth, installation);
    }
    result
}
pub(super) fn publish(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    current: &Installation,
    previous: Option<&Installation>,
) -> Result<()> {
    for id in current
        .server_ids
        .iter()
        .chain(previous.into_iter().flat_map(|old| old.server_ids.iter()))
    {
        state
            .mcp_supervisor
            .stage_marketplace_server(&scope(auth), id)
            .map_err(|e| e.to_string())?;
    }
    state
        .mcp_supervisor
        .publish_marketplace_generation(
            &scope(auth),
            &current.server_ids,
            previous.map(|old| old.server_ids.as_slice()).unwrap_or(&[]),
        )
        .map_err(|e| e.to_string())?;
    for id in &current.skill_ids {
        skill_status(
            state,
            &auth.workspace.tenant_id,
            &auth.workspace.project_id,
            current,
            id,
            "active",
        )?;
    }
    if let Some(previous) = previous {
        for id in &previous.skill_ids {
            skill_status(
                state,
                &auth.workspace.tenant_id,
                &auth.workspace.project_id,
                previous,
                id,
                "deleted",
            )?;
        }
    }
    Ok(())
}
pub(super) fn skill_status(
    state: &LocalRuntimeState,
    tenant_id: &str,
    project_id: &str,
    installation: &Installation,
    id: &str,
    status: &str,
) -> Result<()> {
    let mut value = state
        .session_store
        .managed_resource(ManagedResourceKind::Skill, "project", project_id, id)?
        .ok_or("owned skill is missing")?;
    if package::text(&value, "plugin_id") != installation.plugin_id
        || package::text(&value, "plugin_version") != installation.version
    {
        return Err("skill ownership changed".into());
    }
    value["tenant_id"] = json!(tenant_id);
    value["project_id"] = json!(project_id);
    value["is_system_skill"] = json!(false);
    value["status"] = json!(status);
    value["enabled"] = json!(status == "active");
    let revision = value.get("revision").and_then(Value::as_u64);
    state
        .session_store
        .put_managed_resource(
            ManagedResourceKind::Skill,
            "project",
            project_id,
            id,
            status,
            revision,
            value,
            chrono::Utc::now().timestamp_millis(),
        )
        .map_err(|e| e.to_string())?;
    Ok(())
}
pub(super) fn set_enabled(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    installation: &mut Installation,
    enabled: bool,
) -> Result<()> {
    let scope = scope(auth);
    for (index, id) in installation.server_ids.iter().enumerate() {
        let mut server = state
            .mcp_supervisor
            .server(&scope, id)
            .map_err(|e| e.to_string())?
            .ok_or("owned MCP server is missing")?;
        if enabled {
            let name = installation
                .package
                .servers
                .keys()
                .nth(index)
                .map(String::as_str)
                .unwrap_or_default();
            if super::oauth::declared(&installation.package.servers[name]).is_some()
                && state
                    .mcp_supervisor
                    .oauth_status(id)
                    .map_err(|e| e.to_string())?["status"]
                    == "not_connected"
            {
                return Err("oauth_authorization_required".into());
            }
            // Count bindings from the persisted declaration instead of inspecting secret values.
            let missing = installation
                .package
                .required
                .get(name)
                .into_iter()
                .flatten()
                .any(|key| {
                    key.split_once(':')
                        .is_none_or(|(_, binding)| !server.vault_env_refs.contains_key(binding))
                });
            if missing {
                return Err("configure required plugin credentials first".into());
            }
            if server.transport == McpTransport::Stdio {
                let command = server
                    .command
                    .first_mut()
                    .ok_or("owned MCP command is missing")?;
                // Recover installations created before portable PATH commands were resolved.
                // Keep existing absolute identities so vault bindings remain stable.
                if !std::path::Path::new(command).is_absolute() {
                    *command = executable(command.clone())?;
                }
            }
        }
        state
            .mcp_supervisor
            .update_server(
                &scope,
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
                &format!("market-toggle-{}", uuid::Uuid::new_v4()),
            )
            .map_err(|e| e.to_string())?;
    }
    if !enabled {
        for id in &installation.skill_ids {
            skill_status(
                state,
                &auth.workspace.tenant_id,
                &auth.workspace.project_id,
                installation,
                id,
                "disabled",
            )?;
        }
    }
    installation.status = if enabled { "enabled" } else { "disabled" }.into();
    installation.error = None;
    Ok(())
}
pub(super) fn remove(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    installation: &mut Installation,
) -> Result<()> {
    let mut retired = Vec::new();
    for id in &installation.server_ids {
        if state
            .mcp_supervisor
            .server(&scope(auth), id)
            .map_err(|e| e.to_string())?
            .is_some()
        {
            state
                .mcp_supervisor
                .stage_marketplace_server(&scope(auth), id)
                .map_err(|e| e.to_string())?;
            retired.push(id.clone());
        }
    }
    state
        .mcp_supervisor
        .publish_marketplace_generation(&scope(auth), &[], &retired)
        .map_err(|e| e.to_string())?;
    for id in &installation.skill_ids {
        skill_status(
            state,
            &auth.workspace.tenant_id,
            &auth.workspace.project_id,
            installation,
            id,
            "deleted",
        )?;
    }
    installation.status = "uninstalled".into();
    installation.error = None;
    Ok(())
}
fn credential_source<'a>(
    previous: Option<&'a Installation>,
    name: &str,
    field: &str,
    binding: &str,
    placeholder: &str,
) -> Option<&'a str> {
    let previous = previous?;
    if previous
        .package
        .servers
        .get(name)?
        .get(field)?
        .get(binding)?
        .as_str()?
        != placeholder
    {
        return None;
    }
    let index = previous
        .package
        .servers
        .keys()
        .position(|key| key == name)?;
    previous.server_ids.get(index).map(String::as_str)
}
pub(super) fn missing_credentials(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    package: &package::Package,
    previous: Option<&Installation>,
) -> Result<Vec<String>> {
    let mut missing = std::collections::BTreeSet::new();
    for (name, bindings) in &package.required {
        for key in bindings {
            let (field, binding) = key.split_once(':').ok_or("invalid binding")?;
            let placeholder = package.servers[name][field][binding]
                .as_str()
                .ok_or("invalid placeholder")?;
            let exists =
                if let Some(id) = credential_source(previous, name, field, binding, placeholder) {
                    state
                        .mcp_supervisor
                        .server(&scope(auth), id)
                        .map_err(|e| e.to_string())?
                        .is_some_and(|server| server.vault_env_refs.contains_key(binding))
                } else {
                    false
                };
            if !exists {
                missing.insert(
                    placeholder
                        .trim_start_matches("${")
                        .trim_end_matches('}')
                        .to_owned(),
                );
            }
        }
    }
    Ok(missing.into_iter().collect())
}
pub(super) fn configure(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    installation: &mut Installation,
    credentials: &BTreeMap<String, String>,
) -> Result<()> {
    configure_generation(state, auth, installation, credentials, None)
}
pub(super) fn configure_generation(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    installation: &mut Installation,
    credentials: &BTreeMap<String, String>,
    previous: Option<&Installation>,
) -> Result<()> {
    let missing = missing_credentials(state, auth, &installation.package, previous)?;
    if let Some(variable) = missing.iter().find(|name| !credentials.contains_key(*name)) {
        return Err(format!(
            "needs_configuration: credential {variable} is required"
        ));
    }
    for (index, (name, config)) in installation.package.servers.iter().enumerate() {
        let Some(required) = installation.package.required.get(name) else {
            continue;
        };
        let server_id = installation
            .server_ids
            .get(index)
            .ok_or("owned MCP server is missing")?;
        let server = state
            .mcp_supervisor
            .server(&scope(auth), server_id)
            .map_err(|e| e.to_string())?
            .ok_or("owned MCP server is missing")?;
        let mut input = input(installation, name, config)?;
        input.name = server.name;
        input.vault_env_refs = server.vault_env_refs;
        let mutation = format!("market-configure-{}", uuid::Uuid::new_v4());
        for key in required {
            let (field, binding) = key.split_once(':').ok_or("invalid credential binding")?;
            let placeholder = config[field][binding]
                .as_str()
                .ok_or("invalid credential placeholder")?;
            let variable = placeholder.trim_start_matches("${").trim_end_matches('}');
            let kind = if field == "env" {
                McpCredentialKind::Env
            } else {
                McpCredentialKind::Header
            };
            let provision = McpCredentialProvisionInput {
                server_name: input.name.clone(),
                transport: input.transport,
                command: input.command.clone(),
                cwd: input.cwd.clone(),
                kind,
                name: binding.into(),
                mutation_idempotency_key: Some(mutation.clone()),
            };
            let key = format!("market-secret-{}", uuid::Uuid::new_v4());
            if let Some(secret) = credentials.get(variable) {
                state
                    .mcp_supervisor
                    .provision_credential(&scope(auth), &provision, secret, &key)
                    .map_err(|e| e.to_string())?;
            } else {
                let inherited = if let Some(source) =
                    credential_source(previous, name, field, binding, placeholder)
                {
                    state
                        .mcp_supervisor
                        .inherit_marketplace_credential(
                            &scope(auth),
                            source,
                            binding,
                            &provision,
                            &key,
                        )
                        .map_err(|e| e.to_string())?
                } else {
                    false
                };
                if !inherited {
                    return Err(format!(
                        "needs_configuration: credential {variable} is required"
                    ));
                }
            }
            let reference = mcp_supervisor::credential_reference(
                &scope(auth),
                &input.name,
                input.transport,
                &input.command,
                input.cwd.as_deref(),
                kind,
                binding,
            )
            .map_err(|e| e.to_string())?;
            input.vault_env_refs.insert(binding.into(), reference);
        }
        state
            .mcp_supervisor
            .update_server(&scope(auth), server_id, input, server.revision, &mutation)
            .map_err(|e| e.to_string())?;
    }
    set_enabled(state, auth, installation, true)
}
pub(super) async fn verify(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    installation: &Installation,
) -> Result<()> {
    for id in &installation.server_ids {
        state
            .mcp_supervisor
            .list_tools(&scope(auth), id)
            .await
            .map_err(|e| e.to_string())?;
    }
    for id in &installation.skill_ids {
        let resource = state
            .session_store
            .managed_resource(
                ManagedResourceKind::Skill,
                "project",
                &auth.workspace.project_id,
                id,
            )?
            .ok_or("installed skill unavailable")?;
        if package::text(&resource, "full_content").is_empty() {
            return Err("installed skill content unavailable".into());
        }
    }
    Ok(())
}
