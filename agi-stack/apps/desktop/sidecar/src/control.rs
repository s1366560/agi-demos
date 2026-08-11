//! Private JSON-lines control protocol between Electron main and the sidecar.

use std::{path::PathBuf, process};

use agistack_adapters_browser::protocol::{
    PROTOCOL_MAX as BRIDGE_PROTOCOL_MAX, PROTOCOL_MIN as BRIDGE_PROTOCOL_MIN,
};
use base64::{
    engine::general_purpose::{URL_SAFE, URL_SAFE_NO_PAD},
    Engine as _,
};
use hmac::{Hmac, Mac};
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use serde_json::Value;
use sha2::Sha256;
use tokio::{
    io::{self, AsyncBufReadExt, AsyncWriteExt, BufReader, Lines, Stdin, Stdout},
    task,
};
use zeroize::Zeroize;

use crate::{
    application_vault::ApplicationCredentialVault,
    data_migration::migrate_legacy_data,
    local_runtime::{browser_bridge, LocalRuntimeConfig, LocalRuntimeService},
    native_host,
    oauth_pending_attempt::{OAuthPendingAttemptBroker, OAuthPendingAttemptRecord},
    trusted_session::{
        deserialize_local_record, serialize_local_record, TrustedSessionBroker,
        TrustedSessionRecord,
    },
};

const PROTOCOL_VERSION: u16 = 1;
const SECRET_BYTES: usize = 32;
const MAX_INITIALIZE_BYTES: usize = 64 * 1024;
const MAX_REQUEST_BYTES: usize = 4 * 1024 * 1024;
const MAX_LEGACY_DIRECTORIES: usize = 8;

type HmacSha256 = Hmac<Sha256>;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct InitializeRequest {
    #[serde(rename = "type")]
    message_type: String,
    protocol_version: u16,
    nonce: String,
    secret: String,
    data_directory: PathBuf,
    workspace_root: PathBuf,
    legacy_data_directories: Vec<PathBuf>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ReadyResponse {
    #[serde(rename = "type")]
    message_type: &'static str,
    protocol_version: u16,
    nonce: String,
    pid: u32,
    api_base_url: String,
    api_token: String,
    proof: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ControlRequest {
    #[serde(rename = "type")]
    message_type: String,
    id: String,
    command: String,
    #[serde(default)]
    args: Option<Value>,
}

#[derive(Debug, Serialize)]
#[serde(deny_unknown_fields)]
struct ControlResponse {
    #[serde(rename = "type")]
    message_type: &'static str,
    id: String,
    ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
}

struct ControlState {
    runtime: LocalRuntimeService,
    oauth_pending_attempts: OAuthPendingAttemptBroker,
    trusted_sessions: TrustedSessionBroker,
}

pub(crate) async fn run() -> Result<(), String> {
    let mut input = BufReader::new(io::stdin()).lines();
    let mut output = io::stdout();
    let mut initialize = read_initialize(&mut input).await?;
    let validation_result = validate_initialize(&initialize);
    if let Err(error) = validation_result {
        initialize.secret.zeroize();
        return Err(error);
    }
    let secret_result = decode_secret(&initialize.secret);
    initialize.secret.zeroize();
    let mut secret = secret_result?;

    migrate_legacy_data(
        &initialize.data_directory,
        &initialize.legacy_data_directories,
    )?;
    let credential_vault = ApplicationCredentialVault::open(&initialize.data_directory)
        .map_err(|error| error.to_string())?;
    let runtime = LocalRuntimeService::start(
        initialize.data_directory,
        initialize.workspace_root,
        credential_vault.clone(),
    )
    .await?;
    let oauth_pending_attempts = OAuthPendingAttemptBroker::new(credential_vault.clone());
    let trusted_sessions = TrustedSessionBroker::native(credential_vault);
    let status = runtime.status();
    let ready = ready_response(
        &initialize.nonce,
        &status.api_base_url,
        &status.api_token,
        &secret,
    )?;
    secret.zeroize();
    write_json_line(&mut output, &ready).await?;

    let state = ControlState {
        runtime,
        oauth_pending_attempts,
        trusted_sessions,
    };
    while let Some(line) = read_bounded_line(&mut input, MAX_REQUEST_BYTES).await? {
        let response = match serde_json::from_str::<ControlRequest>(&line) {
            Ok(request) => execute_request(&state, request).await,
            Err(_) => ControlResponse {
                message_type: "response",
                id: String::new(),
                ok: false,
                result: None,
                error: Some("sidecar control request is invalid".to_string()),
            },
        };
        write_json_line(&mut output, &response).await?;
    }
    state.runtime.shutdown().await;
    Ok(())
}

async fn read_initialize(input: &mut Lines<BufReader<Stdin>>) -> Result<InitializeRequest, String> {
    let line = read_bounded_line(input, MAX_INITIALIZE_BYTES)
        .await?
        .ok_or_else(|| "sidecar initialization request is missing".to_string())?;
    serde_json::from_str(&line).map_err(|_| "sidecar initialization request is invalid".to_string())
}

async fn read_bounded_line(
    input: &mut Lines<BufReader<Stdin>>,
    max_bytes: usize,
) -> Result<Option<String>, String> {
    let line = input
        .next_line()
        .await
        .map_err(|error| format!("failed to read sidecar control channel: {error}"))?;
    if line.as_ref().is_some_and(|value| value.len() > max_bytes) {
        return Err("sidecar control message exceeds the size limit".to_string());
    }
    Ok(line)
}

fn validate_initialize(initialize: &InitializeRequest) -> Result<(), String> {
    if initialize.message_type != "initialize"
        || initialize.protocol_version != PROTOCOL_VERSION
        || initialize.nonce.len() < 32
        || initialize.nonce.len() > 128
        || !initialize.data_directory.is_absolute()
        || !initialize.workspace_root.is_absolute()
        || initialize.legacy_data_directories.len() > MAX_LEGACY_DIRECTORIES
        || initialize
            .legacy_data_directories
            .iter()
            .any(|path| !path.is_absolute())
    {
        return Err("sidecar initialization request is invalid".to_string());
    }
    Ok(())
}

fn decode_secret(encoded: &str) -> Result<Vec<u8>, String> {
    let decoded = URL_SAFE_NO_PAD
        .decode(encoded)
        .or_else(|_| URL_SAFE.decode(encoded))
        .map_err(|_| "sidecar initialization secret is invalid".to_string())?;
    if decoded.len() != SECRET_BYTES {
        return Err("sidecar initialization secret is invalid".to_string());
    }
    Ok(decoded)
}

fn ready_response(
    nonce: &str,
    api_base_url: &str,
    api_token: &str,
    secret: &[u8],
) -> Result<ReadyResponse, String> {
    let pid = process::id();
    let message = ready_proof_message(PROTOCOL_VERSION, nonce, pid, api_base_url, api_token);
    let mut hmac = HmacSha256::new_from_slice(secret)
        .map_err(|_| "sidecar initialization secret is invalid".to_string())?;
    hmac.update(message.as_bytes());
    Ok(ReadyResponse {
        message_type: "ready",
        protocol_version: PROTOCOL_VERSION,
        nonce: nonce.to_string(),
        pid,
        api_base_url: api_base_url.to_string(),
        api_token: api_token.to_string(),
        proof: URL_SAFE_NO_PAD.encode(hmac.finalize().into_bytes()),
    })
}

fn ready_proof_message(
    protocol_version: u16,
    nonce: &str,
    pid: u32,
    api_base_url: &str,
    api_token: &str,
) -> String {
    format!("{protocol_version}\n{nonce}\n{pid}\n{api_base_url}\n{api_token}")
}

async fn execute_request(state: &ControlState, request: ControlRequest) -> ControlResponse {
    let id = request.id;
    if request.message_type != "request" || id.is_empty() || id.len() > 128 {
        return failure(id, "sidecar control request is invalid");
    }
    let result = match request.command.as_str() {
        "local_runtime_status" => {
            serde_json::to_value(state.runtime.status()).map_err(|error| error.to_string())
        }
        "local_runtime_configure" => {
            let runtime = state.runtime.clone();
            parse_arg::<LocalRuntimeConfig>(request.args.as_ref(), "config")
                .and_then(|config| task::block_in_place(|| runtime.configure(config)))
                .and_then(|status| serde_json::to_value(status).map_err(|error| error.to_string()))
        }
        "trusted_session_save" => {
            let broker = state.trusted_sessions.clone();
            parse_arg::<TrustedSessionRecord>(request.args.as_ref(), "input").and_then(|record| {
                task::block_in_place(|| broker.save(record))
                    .map_err(|error| error.to_string())
                    .map(|()| Value::Null)
            })
        }
        "trusted_session_load" => {
            let broker = state.trusted_sessions.clone();
            task::block_in_place(|| broker.load())
                .map_err(|error| error.to_string())
                .and_then(|record| serde_json::to_value(record).map_err(|error| error.to_string()))
        }
        "trusted_session_clear" => {
            let broker = state.trusted_sessions.clone();
            task::block_in_place(|| broker.clear())
                .map_err(|error| error.to_string())
                .map(|()| Value::Null)
        }
        "oauth_pending_attempt_save" => {
            let broker = state.oauth_pending_attempts.clone();
            parse_arg::<OAuthPendingAttemptRecord>(request.args.as_ref(), "input").and_then(
                |record| {
                    task::block_in_place(|| broker.save(record))
                        .map_err(|error| error.to_string())
                        .map(|()| Value::Null)
                },
            )
        }
        "oauth_pending_attempt_load" => {
            let broker = state.oauth_pending_attempts.clone();
            task::block_in_place(|| broker.load())
                .map_err(|error| error.to_string())
                .and_then(|record| serde_json::to_value(record).map_err(|error| error.to_string()))
        }
        "oauth_pending_attempt_clear" => {
            let broker = state.oauth_pending_attempts.clone();
            task::block_in_place(|| broker.clear())
                .map_err(|error| error.to_string())
                .map(|()| Value::Null)
        }
        "local_trusted_session_save" => {
            parse_arg::<TrustedSessionRecord>(request.args.as_ref(), "input")
                .and_then(|record| {
                    serialize_local_record(&record).map_err(|error| error.to_string())
                })
                .and_then(|serialized| {
                    task::block_in_place(|| state.runtime.save_local_trusted_session(&serialized))
                        .map(|()| Value::Null)
                })
        }
        "local_trusted_session_load" => task::block_in_place(|| {
            let Some(serialized) = state.runtime.load_local_trusted_session()? else {
                return Ok(Value::Null);
            };
            match deserialize_local_record(&serialized) {
                Ok(record) => serde_json::to_value(record).map_err(|error| error.to_string()),
                Err(error) => {
                    state.runtime.clear_local_trusted_session()?;
                    Err(error.to_string())
                }
            }
        }),
        "local_trusted_session_clear" => {
            task::block_in_place(|| state.runtime.clear_local_trusted_session())
                .map(|()| Value::Null)
        }
        "browser_bridge_install" => task::block_in_place(native_host::install_manifests)
            .and_then(|result| serde_json::to_value(result).map_err(|error| error.to_string())),
        "browser_bridge_uninstall" => task::block_in_place(native_host::uninstall_manifests)
            .and_then(|result| serde_json::to_value(result).map_err(|error| error.to_string())),
        "browser_bridge_status" => browser_bridge_status_payload(&state.runtime),
        "browser_bridge_dev_call" => match parse_arg::<String>(request.args.as_ref(), "method") {
            Ok(method) => {
                let params = request
                    .args
                    .as_ref()
                    .and_then(Value::as_object)
                    .and_then(|object| object.get("params"))
                    .cloned()
                    .unwrap_or(Value::Null);
                state.runtime.browser_bridge_dev_call(&method, params).await
            }
            Err(error) => Err(error),
        },
        _ => Err("desktop command is not supported".to_string()),
    };

    match result {
        Ok(value) => ControlResponse {
            message_type: "response",
            id,
            ok: true,
            result: Some(value),
            error: None,
        },
        Err(error) => failure(id, &error),
    }
}

fn parse_arg<T: DeserializeOwned>(args: Option<&Value>, key: &str) -> Result<T, String> {
    let value = args
        .and_then(Value::as_object)
        .and_then(|object| object.get(key))
        .cloned()
        .ok_or_else(|| "desktop command arguments are invalid".to_string())?;
    serde_json::from_value(value).map_err(|_| "desktop command arguments are invalid".to_string())
}

/// `browser_bridge_status` payload: runtime state (from the local runtime)
/// plus manifest probes and the registry location. Keys are camelCase per the
/// bridge contract.
fn browser_bridge_status_payload(runtime: &LocalRuntimeService) -> Result<Value, String> {
    let status = runtime.status();
    let registry_path = browser_bridge::registry_path()?;
    Ok(serde_json::json!({
        "enabled": status.browser_bridge.enabled,
        "port": status.browser_bridge.port,
        "brokerConnected": status.browser_bridge.broker_connected,
        "extensionId": status.browser_bridge.extension_id,
        "extensionVersion": status.browser_bridge.extension_version,
        "hostVersion": env!("CARGO_PKG_VERSION"),
        "protocolMin": BRIDGE_PROTOCOL_MIN,
        "protocolMax": BRIDGE_PROTOCOL_MAX,
        "manifests": native_host::manifest_statuses(),
        "registryPath": registry_path,
        "extensionIds": status.browser_bridge.extension_ids,
    }))
}

fn failure(id: String, error: &str) -> ControlResponse {
    ControlResponse {
        message_type: "response",
        id,
        ok: false,
        result: None,
        error: Some(error.to_string()),
    }
}

async fn write_json_line<T: Serialize>(output: &mut Stdout, value: &T) -> Result<(), String> {
    let mut serialized = serde_json::to_vec(value).map_err(|error| error.to_string())?;
    serialized.push(b'\n');
    output
        .write_all(&serialized)
        .await
        .map_err(|error| format!("failed to write sidecar control channel: {error}"))?;
    output
        .flush()
        .await
        .map_err(|error| format!("failed to flush sidecar control channel: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    #[test]
    fn ready_proof_uses_the_documented_cross_runtime_message() {
        let response = ready_response(
            "nonce-for-electron-supervisor-contract",
            "http://127.0.0.1:41234",
            "sidecar-api-token",
            &[7_u8; SECRET_BYTES],
        )
        .expect("build ready response");
        let message = ready_proof_message(
            response.protocol_version,
            &response.nonce,
            response.pid,
            &response.api_base_url,
            &response.api_token,
        );
        let mut hmac = HmacSha256::new_from_slice(&[7_u8; SECRET_BYTES]).expect("hmac key");
        hmac.update(message.as_bytes());

        assert_eq!(
            response.proof,
            URL_SAFE_NO_PAD.encode(hmac.finalize().into_bytes())
        );
    }

    #[test]
    fn initialization_rejects_relative_authority_paths() {
        let initialize = InitializeRequest {
            message_type: "initialize".to_string(),
            protocol_version: PROTOCOL_VERSION,
            nonce: "a".repeat(32),
            secret: URL_SAFE_NO_PAD.encode([0_u8; SECRET_BYTES]),
            data_directory: Path::new("relative-data").to_path_buf(),
            workspace_root: Path::new("/absolute/workspace").to_path_buf(),
            legacy_data_directories: Vec::new(),
        };

        assert_eq!(
            validate_initialize(&initialize),
            Err("sidecar initialization request is invalid".to_string())
        );
    }
}
