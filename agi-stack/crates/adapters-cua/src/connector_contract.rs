//! Closed operation effects declared by the trusted device, never by model input.
use crate::CuaToolEffect;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeSet;

pub const CONNECTOR_OPERATION_EFFECTS: &str = "x-cua-operation-effects";

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ConnectorOperationEffect {
    pub provider: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub account_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub server_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub server_name: Option<String>,
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub managed_account: bool,
    pub connector: String,
    pub operation: String,
    pub effect: String,
}

/// Native operations are a protocol roster, not a classification of tool names.
pub fn native_connector_operations() -> Vec<ConnectorOperationEffect> {
    [
        ("calendar", "list", "read"),
        ("calendar", "create", "mutate"),
        ("calendar", "update", "mutate"),
        ("calendar", "delete", "mutate"),
        ("contacts", "list", "read"),
        ("contacts", "create", "mutate"),
        ("contacts", "update", "mutate"),
        ("contacts", "delete", "mutate"),
        ("messages", "list", "read"),
        ("messages", "services", "read"),
        ("messages", "resolve_recipient", "read"),
        ("messages", "send", "mutate"),
    ]
    .into_iter()
    .map(|(connector, operation, effect)| ConnectorOperationEffect {
        provider: "native".into(),
        account_id: None,
        server_id: None,
        server_name: None,
        managed_account: false,
        connector: connector.into(),
        operation: operation.into(),
        effect: effect.into(),
    })
    .collect()
}

pub fn validate_connector_operations(
    schema: &Value,
) -> Result<Vec<ConnectorOperationEffect>, &'static str> {
    let Some(value) = schema.get(CONNECTOR_OPERATION_EFFECTS) else {
        return Ok(vec![]);
    };
    let rows: Vec<ConnectorOperationEffect> =
        serde_json::from_value(value.clone()).map_err(|_| "cua_connector_effects_invalid")?;
    if value.as_array().is_some_and(|rows| {
        rows.iter().any(|row| {
            row["provider"] == "native"
                && ["server_id", "server_name", "managed_account"]
                    .iter()
                    .any(|key| row.get(*key).is_some())
        })
    }) {
        return Err("cua_connector_effects_invalid");
    }
    if rows.len() > 512 {
        return Err("cua_connector_effects_invalid");
    }
    let native = native_connector_operations();
    let mut seen = BTreeSet::new();
    for row in &rows {
        if !matches!(
            row.provider.as_str(),
            "native" | "google" | "microsoft365" | "configured_mcp"
        ) || !matches!(row.connector.as_str(), "calendar" | "contacts" | "messages")
            || !matches!(row.effect.as_str(), "read" | "mutate")
            || row.operation.is_empty()
            || row.operation.len() > 256
            || row
                .account_id
                .as_ref()
                .is_some_and(|id| id.is_empty() || id.len() > 256)
            || row
                .server_id
                .as_ref()
                .is_some_and(|id| id.is_empty() || id.len() > 256)
            || row
                .server_name
                .as_ref()
                .is_some_and(|id| id.is_empty() || id.len() > 256)
            || (row.managed_account && !matches!(row.provider.as_str(), "google" | "microsoft365"))
            || (row.provider == "native" && !native.contains(row))
            || (row.provider != "native" && row.account_id.is_none())
            || !seen.insert((
                &row.provider,
                &row.account_id,
                &row.connector,
                &row.operation,
            ))
        {
            return Err("cua_connector_effects_invalid");
        }
    }
    Ok(rows)
}
pub fn connector_operation_allowed(
    schema: &Value,
    input: &Value,
    allowed_servers: &[String],
) -> bool {
    let Ok(rows) = validate_connector_operations(schema) else {
        return false;
    };
    let provider = input
        .get("provider")
        .and_then(Value::as_str)
        .unwrap_or("native");
    if provider == "native" {
        return true;
    }
    let matching = rows
        .iter()
        .filter(|row| {
            (row.provider == provider || provider == "configured_mcp")
                && row.provider != "native"
                && input.get("connector").and_then(Value::as_str) == Some(row.connector.as_str())
                && input.get("operation").and_then(Value::as_str) == Some(row.operation.as_str())
                && input
                    .get("account_id")
                    .and_then(Value::as_str)
                    .is_none_or(|id| row.account_id.as_deref() == Some(id))
        })
        .collect::<Vec<_>>();
    !matching.is_empty()
        && matching.iter().all(|row| {
            row.managed_account
                || ((row.server_id.is_some() || row.server_name.is_some())
                    && allowed_servers.iter().any(|server| {
                        server == "*"
                            || row.server_id.as_deref() == Some(server)
                            || row.server_name.as_deref() == Some(server)
                    }))
        })
}

pub fn connector_operation_effect(schema: &Value, input: &Value) -> CuaToolEffect {
    let Ok(rows) = validate_connector_operations(schema) else {
        return CuaToolEffect::Mutate;
    };
    let candidates = rows
        .iter()
        .filter(|row| {
            input.get("connector").and_then(Value::as_str) == Some(row.connector.as_str())
                && input.get("operation").and_then(Value::as_str) == Some(row.operation.as_str())
                && {
                    let provider = input
                        .get("provider")
                        .and_then(Value::as_str)
                        .unwrap_or("native");
                    provider == row.provider
                        || (provider == "configured_mcp" && row.provider != "native")
                }
                && (row.provider == "native"
                    || input
                        .get("account_id")
                        .and_then(Value::as_str)
                        .is_none_or(|account| row.account_id.as_deref() == Some(account)))
        })
        .collect::<Vec<_>>();
    if !candidates.is_empty() && candidates.iter().all(|row| row.effect == "read") {
        CuaToolEffect::Read
    } else {
        CuaToolEffect::Mutate
    }
}

pub fn has_read_connector_operation(schema: &Value) -> bool {
    validate_connector_operations(schema)
        .is_ok_and(|rows| rows.iter().any(|row| row.effect == "read"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn connector_validation_rejects_extra_target_and_host_identity_before_dispatch() {
        let input = json!({"provider":"google","account_id":"account","connector":"calendar","operation":"opaque.17","arguments":{}});
        crate::validate_tool_input("computer_connector_call", &input).unwrap();
        for key in ["app", "_cua_call_id", "_cua_expected_identity", "effect"] {
            let mut invalid = input.clone();
            invalid[key] = json!("model-supplied");
            assert!(crate::validate_tool_input("computer_connector_call", &invalid).is_err());
        }
        let mut invalid = input;
        invalid["arguments"] = json!("not-an-object");
        assert!(crate::validate_tool_input("computer_connector_call", &invalid).is_err());
    }
    #[test]
    fn exact_roster_controls_read_and_unknown_remains_mutating() {
        let schema = json!({CONNECTOR_OPERATION_EFFECTS:native_connector_operations()});
        for connector in ["calendar", "contacts", "messages"] {
            assert_eq!(
                connector_operation_effect(
                    &schema,
                    &json!({"provider":"native","connector":connector,"operation":"list"})
                ),
                CuaToolEffect::Read
            );
        }
        for operation in ["create", "delete", "list_everything", "calendar_list"] {
            assert_eq!(
                connector_operation_effect(
                    &schema,
                    &json!({"connector":"calendar","operation":operation})
                ),
                CuaToolEffect::Mutate
            );
        }
        assert_eq!(
            connector_operation_effect(
                &schema,
                &json!({"provider":"google","connector":"calendar","operation":"list"})
            ),
            CuaToolEffect::Mutate
        );
    }
    #[test]
    fn metadata_is_closed_and_bound_to_exact_account_and_operation() {
        let row = json!({"provider":"google","account_id":"account-a","connector":"calendar","operation":"opaque.17","effect":"read"});
        let schema = json!({CONNECTOR_OPERATION_EFFECTS:[row]});
        assert_eq!(
            connector_operation_effect(
                &schema,
                &json!({"provider":"google","account_id":"account-a","connector":"calendar","operation":"opaque.17"})
            ),
            CuaToolEffect::Read
        );
        assert_eq!(
            connector_operation_effect(
                &schema,
                &json!({"provider":"google","account_id":"account-b","connector":"calendar","operation":"opaque.17"})
            ),
            CuaToolEffect::Mutate
        );
        let mut invalid = schema.clone();
        invalid[CONNECTOR_OPERATION_EFFECTS][0]["effect"] = json!("probably-safe");
        assert!(validate_connector_operations(&invalid).is_err());
        invalid = schema;
        invalid[CONNECTOR_OPERATION_EFFECTS][0]["provider"] = json!("native");
        assert!(validate_connector_operations(&invalid).is_err());
    }
}
