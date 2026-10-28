//! Host-declared tool schemas; semantic effects never come from remote annotations.
use super::*;
use agistack_adapters_browser::facade::{
    operation_effect, FacadeEffect, TOOL_CDP, TOOL_READ, TOOL_WRITE,
};

pub(super) const MCP_BINDING: &str = "x-cua-mcp-binding";
pub(super) const STEP_ONLY: &str = "x-cua-step-only";
pub(super) const EXECUTE: [&str; 3] = ["cua_repl_js", "cua_repl_reset", "cua_repl_add_module_dir"];
#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Effect {
    Read,
    Mutate,
    Execute,
}
fn fail() -> CoreError {
    CoreError::Tool("computer_use_tool_contract_mismatch".into())
}

pub(super) fn mcp_binding(schema: &Value) -> CoreResult<Option<&Value>> {
    let Some(binding) = schema.get(MCP_BINDING) else {
        return Ok(None);
    };
    let valid = binding.as_object().is_some_and(|object| object.len() == 4)
        && ["server_id", "server_name", "catalog_digest"]
            .iter()
            .all(|key| {
                binding[*key]
                    .as_str()
                    .is_some_and(|s| !s.is_empty() && s.len() <= 256)
            })
        && binding["revision"]
            .as_u64()
            .is_some_and(|revision| revision > 0);
    if !valid {
        return Err(fail());
    }
    Ok(Some(binding))
}
fn local_schema(schema: &Value) -> CoreResult<()> {
    let mut nodes = vec![schema];
    while let Some(node) = nodes.pop() {
        if let Some(object) = node.as_object() {
            for key in ["$ref", "$dynamicRef", "$recursiveRef"] {
                if object
                    .get(key)
                    .is_some_and(|value| !value.as_str().is_some_and(|s| s.starts_with('#')))
                {
                    return Err(fail());
                }
            }
            nodes.extend(object.values());
        } else if let Some(array) = node.as_array() {
            nodes.extend(array);
        }
    }
    jsonschema::validator_for(schema).map_err(|_| fail())?;
    Ok(())
}
pub(super) fn validate_definition(tool: &Value) -> CoreResult<ToolDefinition> {
    let name = tool["name"]
        .as_str()
        .filter(|s| !s.is_empty() && s.len() <= 256)
        .ok_or_else(fail)?;
    let schema = &tool["inputSchema"];
    if schema["type"] != "object" {
        return Err(fail());
    }
    let binding = mcp_binding(schema)?;
    let native = agistack_adapters_cua::tool_definitions();
    let browser = [TOOL_READ, TOOL_WRITE, TOOL_CDP].contains(&name);
    if let Some(contract) = native.get(name) {
        let mut standard = schema.clone();
        if let Some(object) = standard.as_object_mut() {
            object.remove(STEP_ONLY);
        }
        if name == "computer_connector_call" {
            agistack_adapters_cua::validate_connector_operations(&standard).map_err(|_| fail())?;
            if let Some(object) = standard.as_object_mut() {
                object.remove(agistack_adapters_cua::CONNECTOR_OPERATION_EFFECTS);
            }
        }
        if standard != contract["inputSchema"] || binding.is_some() {
            return Err(fail());
        }
    } else if EXECUTE.contains(&name) || browser {
        if binding.is_some() {
            return Err(fail());
        }
    } else if binding.is_none() {
        return Err(fail());
    }
    if schema.get(STEP_ONLY).is_some_and(|v| !v.is_boolean()) {
        return Err(fail());
    }
    local_schema(schema)?;
    Ok(ToolDefinition::new(
        name,
        tool["description"].as_str().ok_or_else(fail)?,
        schema.clone(),
    ))
}
pub(super) fn effect(definition: &ToolDefinition, input: &Value) -> CoreResult<Effect> {
    let name = definition.name.as_str();
    if EXECUTE.contains(&name) {
        return Ok(Effect::Execute);
    }
    if [TOOL_READ, TOOL_WRITE, TOOL_CDP].contains(&name) {
        let effect = operation_effect(input)?;
        if effect.tool() != name {
            return Err(fail());
        }
        return Ok(if effect == FacadeEffect::Read {
            Effect::Read
        } else {
            Effect::Mutate
        });
    }
    if name == "computer_connector_call" {
        return Ok(
            if agistack_adapters_cua::connector_operation_effect(
                definition.input_schema.as_ref().unwrap_or(&Value::Null),
                input,
            ) == agistack_adapters_cua::CuaToolEffect::Read
            {
                Effect::Read
            } else {
                Effect::Mutate
            },
        );
    }
    if let Some(effect) = agistack_adapters_cua::tool_effects().get(name) {
        return Ok(if *effect == agistack_adapters_cua::CuaToolEffect::Read {
            Effect::Read
        } else {
            Effect::Mutate
        });
    }
    if mcp_binding(definition.input_schema.as_ref().unwrap_or(&Value::Null))?.is_some() {
        return Ok(Effect::Mutate);
    }
    Err(fail())
}
pub(super) fn validate_call(
    definition: &ToolDefinition,
    input: &Value,
    allowed: &[String],
) -> CoreResult<Effect> {
    let schema = definition.input_schema.as_ref().ok_or_else(fail)?;
    if !input.is_object()
        || !jsonschema::validator_for(schema)
            .map_err(|_| fail())?
            .is_valid(input)
    {
        return Err(fail());
    }
    if let Some(binding) = mcp_binding(schema)? {
        if !allowed.iter().any(|server| {
            server == "*" || binding["server_id"] == *server || binding["server_name"] == *server
        }) {
            return Err(CoreError::Tool("computer_use_mcp_server_denied".into()));
        }
    }
    if definition.name == "computer_connector_call"
        && !agistack_adapters_cua::connector_operation_allowed(schema, input, allowed)
    {
        return Err(CoreError::Tool(
            "computer_use_connector_not_allowed_by_agent".into(),
        ));
    }
    effect(definition, input)
}

/// The transport outlives the bounded cell, while ordinary device calls retain their limit.
pub(super) fn request_timeout(tool: &str, input: &str) -> CoreResult<std::time::Duration> {
    if tool != "cua_repl_js" {
        return Ok(std::time::Duration::from_secs(90));
    }
    let value: Value = serde_json::from_str(input).map_err(|_| fail())?;
    let milliseconds = match value.get("timeout_ms") {
        Some(value) => value.as_u64().ok_or_else(fail)?,
        None => 30_000,
    }
    .clamp(1, 300_000);
    Ok(std::time::Duration::from_secs(
        90.max(milliseconds.div_ceil(1000) + 15),
    ))
}
