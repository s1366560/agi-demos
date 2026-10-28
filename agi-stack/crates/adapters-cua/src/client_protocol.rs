//! Framing response and authenticated input binding validation.
use super::*;
use hmac::{Hmac, Mac};
use sha2::Sha256;

pub(super) fn mutates(method: &str) -> bool {
    matches!(
        method,
        "perform_action"
            | "activate_app"
            | "launch_app"
            | "audio_start"
            | "clipboard_write"
            | "connector_call"
            | "locked_use_enable"
            | "locked_use_renew"
            | "locked_use_disable"
    )
}
pub(super) fn random_hex() -> Result<String, CuaError> {
    let mut bytes = [0u8; 32];
    getrandom::getrandom(&mut bytes)
        .map_err(|_| CuaError::HelperSpawnFailed("secure random unavailable".into()))?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}
pub(super) fn valid_proof(secret: &str, nonce: &str, proof: &str) -> bool {
    let Ok(mut mac) = Hmac::<Sha256>::new_from_slice(secret.as_bytes()) else {
        return false;
    };
    mac.update(nonce.as_bytes());
    if proof.len() != 64 || !proof.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return false;
    }
    let bytes = (0..32)
        .map(|i| u8::from_str_radix(&proof[i * 2..i * 2 + 2], 16))
        .collect::<Result<Vec<_>, _>>();
    bytes.is_ok_and(|bytes| mac.verify_slice(&bytes).is_ok())
}
pub(super) fn decode_response(raw: &[u8], id: u64) -> Result<Value, CuaError> {
    let response: Value = serde_json::from_slice(raw)
        .map_err(|_| CuaError::InvalidResponse("invalid JSON response".into()))?;
    if response.get("jsonrpc") != Some(&json!("2.0"))
        || response.get("id") != Some(&json!(id))
        || response.get("result").is_some() == response.get("error").is_some()
    {
        return Err(CuaError::InvalidResponse(
            "invalid JSON-RPC envelope".into(),
        ));
    }
    if let Some(error) = response.get("error") {
        let kind = error
            .pointer("/data/kind")
            .and_then(Value::as_str)
            .unwrap_or("helper_error");
        if kind == "incompatible_client_version" {
            return Err(CuaError::IncompatibleClientVersion {
                client: IPC_PROTOCOL_VERSION.into(),
                server: error
                    .pointer("/data/server_api_version")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown")
                    .into(),
            });
        }
        return Err(CuaError::from_rpc_kind(
            kind,
            error
                .get("message")
                .and_then(Value::as_str)
                .unwrap_or("helper request failed"),
        ));
    }
    response
        .get("result")
        .cloned()
        .ok_or_else(|| CuaError::InvalidResponse("missing result".into()))
}
impl From<agistack_core::CoreError> for CuaError {
    fn from(error: agistack_core::CoreError) -> Self {
        Self::Unreachable(error.to_string())
    }
}

pub(super) fn input_generation(
    result: &Value,
    context: &CuaCallContext,
) -> Result<String, CuaError> {
    let mode = serde_json::to_value(context.input_mode)
        .map_err(|_| CuaError::InvalidResponse("input mode invalid".into()))?;
    if result["input_mode"] != mode {
        return Err(CuaError::InvalidResponse(
            "native input mode mismatch".into(),
        ));
    }
    result["input_generation"]
        .as_str()
        .filter(|value| !value.is_empty() && value.len() <= 128)
        .map(str::to_owned)
        .ok_or_else(|| CuaError::InvalidResponse("native input generation missing".into()))
}
