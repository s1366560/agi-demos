//! Standalone JSON-RPC 2.0 codec for the bridge wire format.
//!
//! The validation semantics mirror the sidecar's established MCP-supervisor
//! codec (`remote_common.rs`): strict `jsonrpc == "2.0"`, exactly one of
//! `result` / `error` on responses, `params` must be object or array when
//! present, and **batches are rejected** (the bridge never sends them). The
//! codec is deliberately transport-agnostic so both the WebSocket client and
//! the broker's stdio framing share one validation path.

use serde_json::{json, Value};
use thiserror::Error;

use crate::protocol::RpcErrorObject;

/// JSON-RPC codec failures. All malformed input collapses to
/// [`JsonRpcError::Malformed`] — the wire gives no partial credit.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum JsonRpcError {
    #[error("invalid JSON: {0}")]
    Parse(String),
    #[error("malformed JSON-RPC message")]
    Malformed,
    #[error("JSON-RPC batch messages are not supported by the bridge")]
    BatchUnsupported,
}

/// A decoded, validated JSON-RPC 2.0 message.
#[derive(Debug, Clone, PartialEq)]
pub enum JsonRpcMessage {
    /// A request: `id` + `method` (+ optional `params`).
    Request {
        id: u64,
        method: String,
        params: Value,
    },
    /// A notification: `method` (+ optional `params`), no `id`.
    Notification { method: String, params: Value },
    /// A response correlated by `id`; `Err` carries the JSON-RPC error object.
    Response {
        id: u64,
        result: Result<Value, RpcErrorObject>,
    },
}

/// Encode a request frame (`params` may be `Value::Null` to omit the field).
pub fn encode_request(id: u64, method: &str, params: Value) -> String {
    let mut frame = json!({ "jsonrpc": "2.0", "id": id, "method": method });
    if !params.is_null() {
        frame["params"] = params;
    }
    frame.to_string()
}

/// Encode a notification frame (no `id`).
pub fn encode_notification(method: &str, params: Value) -> String {
    let mut frame = json!({ "jsonrpc": "2.0", "method": method });
    if !params.is_null() {
        frame["params"] = params;
    }
    frame.to_string()
}

/// Decode and validate one JSON-RPC message. Batches and non-object payloads
/// are rejected outright.
pub fn decode(payload: &str) -> Result<JsonRpcMessage, JsonRpcError> {
    let value: Value =
        serde_json::from_str(payload).map_err(|e| JsonRpcError::Parse(e.to_string()))?;
    decode_value(&value)
}

/// Decode and validate an already-parsed JSON value.
pub fn decode_value(value: &Value) -> Result<JsonRpcMessage, JsonRpcError> {
    let object = match value {
        Value::Object(map) => map,
        Value::Array(_) => return Err(JsonRpcError::BatchUnsupported),
        _ => return Err(JsonRpcError::Malformed),
    };
    if object.get("jsonrpc").and_then(Value::as_str) != Some("2.0") {
        return Err(JsonRpcError::Malformed);
    }

    if let Some(method) = object.get("method") {
        // Request or notification: non-empty method, no result/error keys,
        // params must be object/array when present.
        let method = method
            .as_str()
            .filter(|m| !m.is_empty())
            .ok_or(JsonRpcError::Malformed)?;
        if object.contains_key("result") || object.contains_key("error") {
            return Err(JsonRpcError::Malformed);
        }
        if object
            .get("params")
            .is_some_and(|p| !p.is_object() && !p.is_array())
        {
            return Err(JsonRpcError::Malformed);
        }
        let params = object.get("params").cloned().unwrap_or(Value::Null);
        return match object.get("id") {
            None | Some(Value::Null) => Ok(JsonRpcMessage::Notification {
                method: method.to_string(),
                params,
            }),
            Some(id) => {
                let id = id.as_u64().ok_or(JsonRpcError::Malformed)?;
                Ok(JsonRpcMessage::Request {
                    id,
                    method: method.to_string(),
                    params,
                })
            }
        };
    }

    // Response: id + exactly one of result/error.
    let id = object
        .get("id")
        .and_then(Value::as_u64)
        .ok_or(JsonRpcError::Malformed)?;
    let has_result = object.contains_key("result");
    let has_error = object.contains_key("error");
    if has_result == has_error {
        return Err(JsonRpcError::Malformed);
    }
    if has_error {
        let error = object
            .get("error")
            .and_then(Value::as_object)
            .ok_or(JsonRpcError::Malformed)?;
        let code = error
            .get("code")
            .and_then(Value::as_i64)
            .ok_or(JsonRpcError::Malformed)?;
        let message = error
            .get("message")
            .and_then(Value::as_str)
            .ok_or(JsonRpcError::Malformed)?;
        return Ok(JsonRpcMessage::Response {
            id,
            result: Err(RpcErrorObject {
                code,
                message: message.to_string(),
            }),
        });
    }
    Ok(JsonRpcMessage::Response {
        id,
        result: Ok(object.get("result").cloned().unwrap_or(Value::Null)),
    })
}

/// Correlate a decoded message against a pending request id: `Some` only when
/// the message is a response carrying exactly that id.
pub fn correlated_result(
    message: &JsonRpcMessage,
    request_id: u64,
) -> Option<Result<Value, RpcErrorObject>> {
    match message {
        JsonRpcMessage::Response { id, result } if *id == request_id => Some(result.clone()),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_round_trip() {
        let frame = encode_request(7, "ping", json!({}));
        assert_eq!(
            decode(&frame).unwrap(),
            JsonRpcMessage::Request {
                id: 7,
                method: "ping".into(),
                params: json!({})
            }
        );
    }

    #[test]
    fn notification_omits_id() {
        let frame = encode_notification("onCDPDetach", json!({"tabId": 3, "reason": "x"}));
        assert!(!frame.contains("\"id\""));
        assert_eq!(
            decode(&frame).unwrap(),
            JsonRpcMessage::Notification {
                method: "onCDPDetach".into(),
                params: json!({"tabId": 3, "reason": "x"})
            }
        );
    }

    #[test]
    fn response_with_result_decodes() {
        let msg = decode(r#"{"jsonrpc":"2.0","id":1,"result":{}}"#).unwrap();
        assert_eq!(
            correlated_result(&msg, 1),
            Some(Ok(json!({}))),
            "response must correlate by id"
        );
        assert_eq!(correlated_result(&msg, 2), None);
    }

    #[test]
    fn response_with_error_decodes() {
        let msg =
            decode(r#"{"jsonrpc":"2.0","id":9,"error":{"code":-32601,"message":"no method"}}"#)
                .unwrap();
        assert_eq!(
            correlated_result(&msg, 9),
            Some(Err(RpcErrorObject {
                code: -32601,
                message: "no method".into()
            }))
        );
    }

    #[test]
    fn rejects_batches_and_scalars() {
        assert_eq!(decode("[]"), Err(JsonRpcError::BatchUnsupported));
        assert_eq!(
            decode(r#"[{"jsonrpc":"2.0","id":1,"result":{}}]"#),
            Err(JsonRpcError::BatchUnsupported)
        );
        assert_eq!(decode("42"), Err(JsonRpcError::Malformed));
        assert!(matches!(decode("{nope"), Err(JsonRpcError::Parse(_))));
    }

    #[test]
    fn rejects_bad_envelopes() {
        // wrong version
        assert_eq!(
            decode(r#"{"jsonrpc":"1.0","id":1,"result":{}}"#),
            Err(JsonRpcError::Malformed)
        );
        // both result and error
        assert_eq!(
            decode(r#"{"jsonrpc":"2.0","id":1,"result":{},"error":{"code":1,"message":"x"}}"#),
            Err(JsonRpcError::Malformed)
        );
        // response without id
        assert_eq!(
            decode(r#"{"jsonrpc":"2.0","result":{}}"#),
            Err(JsonRpcError::Malformed)
        );
        // scalar params
        assert_eq!(
            decode(r#"{"jsonrpc":"2.0","id":1,"method":"m","params":3}"#),
            Err(JsonRpcError::Malformed)
        );
        // method + result together
        assert_eq!(
            decode(r#"{"jsonrpc":"2.0","id":1,"method":"m","result":{}}"#),
            Err(JsonRpcError::Malformed)
        );
        // error object missing message
        assert_eq!(
            decode(r#"{"jsonrpc":"2.0","id":1,"error":{"code":1}}"#),
            Err(JsonRpcError::Malformed)
        );
    }
}
