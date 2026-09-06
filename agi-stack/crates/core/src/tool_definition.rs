//! Model-visible static tool contracts, separate from execution authority.

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// A declared tool contract. Legacy hosts explicitly omit unavailable metadata.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ToolDefinition {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub input_schema: Option<Value>,
}

impl ToolDefinition {
    pub fn new(
        name: impl Into<String>,
        description: impl Into<String>,
        input_schema: Value,
    ) -> Self {
        Self {
            name: name.into(),
            description: Some(description.into()),
            input_schema: Some(input_schema),
        }
    }

    pub fn name_only(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            description: None,
            input_schema: None,
        }
    }
}

/// Preserve contracts even when an older LLM adapter only implements `decide`.
/// This is machine-declared metadata, not a UI prompt or an inferred policy.
pub fn prompt_with_tool_definitions(
    goal: &str,
    tools: &[ToolDefinition],
) -> crate::ports::CoreResult<String> {
    let contracts = serde_json::to_string(tools)
        .map_err(|error| crate::ports::CoreError::Llm(error.to_string()))?;
    Ok(format!("{goal}\n\nAvailable tool definitions (input_schema constrains each tool's input_json):\n{contracts}"))
}
