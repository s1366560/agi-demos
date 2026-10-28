//! Native device management reuses the local MCP transport and credential contracts.
use super::*;

fn invalid() -> String {
    "device_mcp_request_invalid".into()
}

fn reason(error: (StatusCode, Json<Value>)) -> String {
    error.1["reason_code"]
        .as_str()
        .unwrap_or("device_mcp_request_invalid")
        .to_owned()
}

fn project(actual: &str, expected: &str) -> Result<(), String> {
    if actual == expected {
        Ok(())
    } else {
        Err("device_mcp_scope_mismatch".into())
    }
}

fn plaintext(config: &TransportConfigBody) -> Result<(), String> {
    if config.environment.is_some() || config.env.is_some() {
        Err("local_mcp_plaintext_environment_rejected".into())
    } else {
        Ok(())
    }
}

pub(in crate::local_runtime) fn create(
    mut value: Value,
    scope: &McpScope,
    project_id: &str,
) -> Result<(McpServerDefinitionInput, String), String> {
    let object = value.as_object_mut().ok_or_else(invalid)?;
    object.entry("enabled").or_insert(json!(false));
    let body: CreateServerBody = serde_json::from_value(value).map_err(|_| invalid())?;
    project(&body.project_id, project_id)?;
    plaintext(&body.transport_config)?;
    if body.enabled {
        return Err("device_mcp_create_must_be_disabled".into());
    }
    let key = body.idempotency_key.clone().ok_or_else(invalid)?;
    Ok((definition_input(body, scope).map_err(reason)?, key))
}

pub(in crate::local_runtime) fn update(
    value: Value,
    current: McpServerDefinition,
    scope: &McpScope,
    project_id: &str,
) -> Result<(McpServerDefinitionInput, u64, String), String> {
    let body: UpdateServerBody = serde_json::from_value(value).map_err(|_| invalid())?;
    project(&body.project_id, project_id)?;
    if let Some(config) = &body.transport_config {
        plaintext(config)?;
    }
    let revision = body.expected_revision;
    let key = body.idempotency_key.clone().ok_or_else(invalid)?;
    Ok((
        update_definition_input(body, current, scope).map_err(reason)?,
        revision,
        key,
    ))
}

pub(in crate::local_runtime) fn delete(
    value: Value,
    project_id: &str,
) -> Result<(u64, String), String> {
    let body: DeleteServerBody = serde_json::from_value(value).map_err(|_| invalid())?;
    project(&body.project_id, project_id)?;
    Ok((
        body.expected_revision,
        body.idempotency_key.ok_or_else(invalid)?,
    ))
}

pub(in crate::local_runtime) fn credential(
    value: Value,
    project_id: &str,
) -> Result<(McpCredentialProvisionInput, Zeroizing<String>, String), String> {
    let body: ProvisionCredentialBody = serde_json::from_value(value).map_err(|_| invalid())?;
    project(&body.project_id, project_id)?;
    let secret = Zeroizing::new(body.secret);
    let input = credential_provision_input(
        body.server_name,
        body.server_type,
        body.transport_config,
        body.credential_kind,
        body.credential_name,
        body.mutation_idempotency_key,
    )
    .map_err(reason)?;
    Ok((input, secret, body.idempotency_key))
}

pub(in crate::local_runtime) fn response(
    server: &McpServerDefinition,
    tenant_id: &str,
    project_id: &str,
) -> Value {
    let mut result = server_response(server);
    result["tenant_id"] = json!(tenant_id);
    result["project_id"] = json!(project_id);
    result["location"] = json!("device");
    result
}
