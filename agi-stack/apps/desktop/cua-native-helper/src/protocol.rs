use crate::{
    backend::{Backend, NativeError, Result},
    session::Sessions,
};
use hmac::{Hmac, Mac};
use serde_json::{Value, json};
use sha2::Sha256;
use std::sync::Arc;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::sync::Mutex;

pub const VERSION: &str = "MemstackComputerUseIPC-2";
const MAX_FRAME: usize = 8 * 1024 * 1024;

pub fn proof(secret: &str, nonce: &str) -> String {
    let mut mac =
        Hmac::<Sha256>::new_from_slice(secret.as_bytes()).expect("HMAC accepts any key length");
    mac.update(nonce.as_bytes());
    mac.finalize()
        .into_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}
fn response(id: Value, result: Result<Value>) -> Value {
    match result {
        Ok(result) => json!({"jsonrpc":"2.0","id":id,"result":result}),
        Err(error) => {
            json!({"jsonrpc":"2.0","id":id,"error":{"code":-32000,"message":error.message,"data":{"kind":error.kind}}})
        }
    }
}
async fn write(output: &Mutex<tokio::io::Stdout>, value: Value) -> Result<()> {
    let payload = serde_json::to_vec(&value)
        .map_err(|_| NativeError::new("invalid_response", "cannot encode response"))?;
    if payload.len() > MAX_FRAME {
        return Err(NativeError::new(
            "response_too_large",
            "response exceeds IPC limit",
        ));
    }
    let mut output = output.lock().await;
    output
        .write_all(&(payload.len() as u32).to_le_bytes())
        .await
        .map_err(|_| NativeError::new("channel_closed", "output channel closed"))?;
    output
        .write_all(&payload)
        .await
        .map_err(|_| NativeError::new("channel_closed", "output channel closed"))?;
    output
        .flush()
        .await
        .map_err(|_| NativeError::new("channel_closed", "output channel closed"))
}

pub async fn run(backend: Arc<dyn Backend>) -> Result<()> {
    let sessions = Arc::new(Sessions::new(backend));
    let result = run_stdio(sessions.clone()).await;
    sessions.stop_all().await;
    result
}
async fn run_stdio(sessions: Arc<Sessions>) -> Result<()> {
    let output = Arc::new(Mutex::new(tokio::io::stdout()));
    let mut input = tokio::io::stdin();
    let mut initialized = false;
    let mut jobs = tokio::task::JoinSet::new();
    loop {
        let mut header = [0; 4];
        if input.read_exact(&mut header).await.is_err() {
            break;
        }
        let length = u32::from_le_bytes(header) as usize;
        if length > MAX_FRAME {
            break;
        }
        let mut bytes = vec![0; length];
        if input.read_exact(&mut bytes).await.is_err() {
            break;
        }
        let request: Value = match serde_json::from_slice(&bytes) {
            Ok(value) => value,
            Err(_) => {
                write(
                    &output,
                    response(
                        Value::Null,
                        Err(NativeError::new("invalid_request", "invalid JSON")),
                    ),
                )
                .await?;
                continue;
            }
        };
        let id = request.get("id").cloned().unwrap_or(Value::Null);
        let method = request.get("method").and_then(Value::as_str).unwrap_or("");
        let params = request.get("params").cloned().unwrap_or(Value::Null);
        if request.get("jsonrpc") != Some(&json!("2.0")) || !params.is_object() || !id.is_u64() {
            write(
                &output,
                response(
                    id,
                    Err(NativeError::new(
                        "invalid_request",
                        "expected JSON-RPC 2.0 request",
                    )),
                ),
            )
            .await?;
            continue;
        }
        if method == "initialize" {
            let nonce = params.get("nonce").and_then(Value::as_str).unwrap_or("");
            let secret = params.get("secret").and_then(Value::as_str).unwrap_or("");
            let result = if !initialized
                && id == json!(0)
                && params.get("client_api_version") == Some(&json!(VERSION))
                && nonce.len() >= 16
                && secret.len() >= 32
            {
                initialized = true;
                if params["native_status_notifications"] == true {
                    let sessions = sessions.clone();
                    let output = output.clone();
                    jobs.spawn(async move {
                        loop {
                            tokio::time::sleep(std::time::Duration::from_secs(1)).await;
                            for status in sessions.audio_notifications().await {
                                if write(&output, json!({"jsonrpc":"2.0","method":"native_status","params":status})).await.is_err() { return; }
                            }
                        }
                    });
                }
                Ok(json!({"server_api_version":VERSION,"nonce":nonce,"proof":proof(secret,nonce)}))
            } else {
                Err(NativeError::new(
                    "incompatible_client_version",
                    "invalid initialization",
                ))
            };
            write(&output, response(id, result)).await?;
            bytes.fill(0);
            continue;
        }
        if !initialized {
            write(
                &output,
                response(
                    id,
                    Err(NativeError::new(
                        "authentication_required",
                        "initialize the private channel first",
                    )),
                ),
            )
            .await?;
            continue;
        }
        if matches!(
            method,
            "stop_session" | "cancel" | "end_session" | "pause_session"
        ) {
            let mut cancellation = params.clone();
            if cancellation.get("end_reason").is_none() {
                cancellation["end_reason"] = json!(match method {
                    "pause_session" => "user_paused",
                    "cancel" => "cancelled",
                    _ => "session_ended",
                });
            }
            let _ = sessions.cancel_request(&cancellation).await;
        }
        while jobs.len() >= 64 {
            let _ = jobs.join_next().await;
        }
        let sessions = sessions.clone();
        let output = output.clone();
        let method = method.to_owned();
        jobs.spawn(async move {
            let result = sessions.dispatch(&method, &params).await;
            let _ = write(&output, response(id, result)).await;
        });
        while jobs.try_join_next().is_some() {}
    }
    jobs.abort_all();
    while jobs.join_next().await.is_some() {}
    Ok(())
}

#[cfg(test)]
mod tests {
    #[test]
    fn authentication_proof_uses_utf8_key_and_lowercase_hex() {
        assert_eq!(
            super::proof("key", "The quick brown fox jumps over the lazy dog"),
            "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8"
        );
    }
}
