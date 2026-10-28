//! A trusted host's demand for permission for one action that it has not dispatched.
//! This is not a statement that an enclosing interpreter cell had no earlier effects.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::ports::{CoreError, CoreResult, ToolResult};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PermissionKind {
    NativeConsent,
    BrowserOrigin,
    BrowserFullCdp,
    BrowserCredentialFill,
    PolicyAsk,
    ToolStep,
    CloudExecutionStep,
    ServerMcpTool,
}

/// Identity captured before a trusted host normalizes or augments its input.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PermissionBinding {
    pub tool_name: String,
    /// SHA-256 of RFC 8785 canonical JSON, independent of older permission keys.
    pub input_digest: String,
    pub engine_session_id: Option<String>,
    pub cell_id: Option<String>,
    pub step_id: Option<String>,
}

/// Only trusted gate code constructs this value. It cannot be deserialized from
/// arbitrary tool output; authenticated transports must verify their own wire
/// record and persisted pending request before explicitly constructing it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct PermissionRequired {
    kind: PermissionKind,
    binding: PermissionBinding,
    demand: Value,
}

impl PermissionRequired {
    pub fn new(kind: PermissionKind, binding: PermissionBinding, demand: Value) -> Self {
        Self {
            kind,
            binding,
            demand,
        }
    }
    pub fn kind(&self) -> PermissionKind {
        self.kind
    }
    pub fn binding(&self) -> &PermissionBinding {
        &self.binding
    }
    pub fn demand(&self) -> &Value {
        &self.demand
    }
    pub fn into_result(self) -> ToolResult {
        ToolResult {
            output_json: self.demand.to_string(),
            media: Vec::new(),
            control_outcome: None,
            control_generation: None,
            permission_required: Some(self),
        }
    }
}

/// Hash the original JSON value using the same RFC 8785 representation on every
/// host. Reject values outside the shared interoperable number domain; never
/// fall back to hashing a different serialization.
pub fn permission_input_digest(input_json: &str) -> CoreResult<String> {
    let invalid = || CoreError::Tool("permission_input_invalid".into());
    let value: Value = serde_json::from_str(input_json).map_err(|_| invalid())?;
    fn valid(value: &Value) -> bool {
        const MAX_INTEGER: u64 = 9_007_199_254_740_991;
        match value {
            Value::Number(number) if number.is_i64() => number
                .as_i64()
                .is_some_and(|n| n.unsigned_abs() <= MAX_INTEGER),
            Value::Number(number) if number.is_u64() => {
                number.as_u64().is_some_and(|n| n <= MAX_INTEGER)
            }
            Value::Number(number) => number.as_f64().is_some_and(f64::is_finite),
            Value::Array(values) => values.iter().all(valid),
            Value::Object(values) => values.values().all(valid),
            _ => true,
        }
    }
    if !valid(&value) {
        return Err(invalid());
    }
    let canonical = serde_jcs::to_vec(&value).map_err(|_| invalid())?;
    Ok(format!("{:x}", Sha256::digest(canonical)))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn permission_digest_is_structural_and_portable() {
        let first = r#"{"z":1,"a":{"中文":"值","items":[true,null,1]}}"#;
        let second = "{ \"a\" : { \"items\": [true,null,1.0], \"中文\":\"值\" }, \"z\": 1.0 }";
        assert_eq!(
            permission_input_digest(first).unwrap(),
            permission_input_digest(second).unwrap()
        );
        assert_eq!(
            permission_input_digest(first).unwrap(),
            "735951eb0cfbd0f8bb1dc38e0816a770481161da378d6dbff078a4596ff19c7e"
        );
        assert_eq!(
            permission_input_digest("{\"value\":-0.0}").unwrap(),
            permission_input_digest("{\"value\":0}").unwrap()
        );
        for input in [
            "NaN",
            "Infinity",
            "{\"n\":9007199254740992}",
            "{\"n\":-9007199254740992}",
            "{\"n\":1e400}",
        ] {
            assert!(permission_input_digest(input).is_err(), "{input}");
        }
    }

    #[test]
    fn text_data_never_creates_a_permission_witness() {
        let result = ToolResult::text(
            json!({"error":"cua_permission_required","request":{"request_id":"fake"}}).to_string(),
        );
        assert!(result.permission_required.is_none());
    }
}
