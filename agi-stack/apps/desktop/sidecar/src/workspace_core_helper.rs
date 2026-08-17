//! Supervision boundary for the Avernet-backed Workspace Core helper.

use std::{
    path::{Path, PathBuf},
    process::Stdio,
    sync::Arc,
    time::{Duration, Instant},
};

use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use hmac::{Hmac, Mac};
use serde::Deserialize;
use serde::Serialize;
use sha2::Sha256;
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader},
    process::{Child, ChildStdin, ChildStdout, Command},
    sync::{watch, Mutex},
    task::JoinHandle,
    time::{sleep, timeout},
};
use zeroize::Zeroizing;

use crate::local_runtime::LocalRuntimeService;
use crate::private_file_permissions::{
    set_private_directory_permissions, set_private_file_permissions,
};
use crate::workspace_core_cutover::{
    load_cutover_marker, persist_cutover_marker, staged_snapshot_from_marker,
    WorkspaceCoreCutoverState,
};
use crate::workspace_core_legacy_import::stage_legacy_workspace_snapshot;

const DEFAULT_MAX_RESTART_ATTEMPTS: usize = 4;
const DESKTOP_CONTROL_PROTOCOL_VERSION: u16 = 1;
const MAX_READY_BYTES: usize = 64 * 1024;
const DEFAULT_RESTART_DELAYS: [Duration; 4] = [
    Duration::from_millis(250),
    Duration::from_secs(1),
    Duration::from_secs(4),
    Duration::from_secs(10),
];
const DEFAULT_RESTART_STABILITY: Duration = Duration::from_secs(60);
const STARTUP_TIMEOUT: Duration = Duration::from_secs(30);
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(35);

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct WorkspaceCoreHelperStatus {
    state: &'static str,
    pid: Option<u32>,
    api_base_url: Option<String>,
    restart_attempts: usize,
    restart_generation: usize,
    failure_reason: Option<&'static str>,
    cutover_state: WorkspaceCoreCutoverState,
}

impl WorkspaceCoreHelperStatus {
    fn starting(
        restart_attempts: usize,
        restart_generation: usize,
        cutover_state: WorkspaceCoreCutoverState,
    ) -> Self {
        Self {
            state: "starting",
            pid: None,
            api_base_url: None,
            restart_attempts,
            restart_generation,
            failure_reason: None,
            cutover_state,
        }
    }

    fn stopped(restart_generation: usize, cutover_state: WorkspaceCoreCutoverState) -> Self {
        Self {
            state: "stopped",
            pid: None,
            api_base_url: None,
            restart_attempts: 0,
            restart_generation,
            failure_reason: None,
            cutover_state,
        }
    }
}

struct WorkspaceCoreLaunchConfig {
    binary_path: PathBuf,
    runtime_directory: PathBuf,
    config_path: PathBuf,
    api_base_url: String,
    service_token: Zeroizing<String>,
    agent_registry_token: Zeroizing<String>,
    provider_webhook_token: Zeroizing<String>,
    provider_event_token: Zeroizing<String>,
    sidecar_api_base_url: String,
    legacy_import_path: PathBuf,
    legacy_import_sha256: String,
    cutover_snapshot: crate::workspace_core_legacy_import::StagedLegacyWorkspaceSnapshot,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopInitialize<'a> {
    #[serde(rename = "type")]
    message_type: &'static str,
    protocol_version: u16,
    nonce: &'a str,
    secret: &'a str,
    config_path: &'a Path,
    mode: &'static str,
    service_token: &'a str,
    agent_registry_url: &'a str,
    agent_registry_token: &'a str,
    provider_webhook_url: String,
    provider_webhook_token: &'a str,
    provider_event_token: &'a str,
    plan_dispatch_url: String,
    instance_id: String,
    legacy_import_path: &'a Path,
    legacy_import_sha256: &'a str,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct DesktopReady {
    #[serde(rename = "type")]
    message_type: String,
    protocol_version: u16,
    nonce: String,
    pid: u32,
    api_base_url: String,
    proof: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopShutdown<'a> {
    #[serde(rename = "type")]
    message_type: &'static str,
    protocol_version: u16,
    nonce: &'a str,
}

struct SupervisedChild {
    child: Child,
    input: ChildStdin,
    nonce: Zeroizing<String>,
}

pub(crate) struct WorkspaceCoreSupervisor {
    status: Arc<Mutex<WorkspaceCoreHelperStatus>>,
    shutdown: watch::Sender<bool>,
    monitor: JoinHandle<()>,
}

struct WorkspaceCoreAuthorityLease {
    runtime: LocalRuntimeService,
    generation: u64,
}

impl Drop for WorkspaceCoreAuthorityLease {
    fn drop(&mut self) {
        self.runtime.clear_workspace_core_authority(self.generation);
    }
}

impl WorkspaceCoreSupervisor {
    pub(crate) async fn start(
        binary_path: PathBuf,
        data_directory: &Path,
        sidecar_api_base_url: &str,
        runtime: LocalRuntimeService,
    ) -> Result<Self, String> {
        validate_binary_path(&binary_path)?;
        let runtime_directory = data_directory.join("workspace-core");
        tokio::fs::create_dir_all(&runtime_directory)
            .await
            .map_err(|error| format!("failed to create Workspace Core data directory: {error}"))?;
        set_private_directory_permissions(&runtime_directory)
            .map_err(|error| format!("failed to secure Workspace Core data directory: {error}"))?;
        let port = reserve_loopback_port().await?;
        let api_base_url = format!("http://127.0.0.1:{port}");
        let config_path = runtime_directory.join("bcs-config.toml");
        write_config(&config_path, &runtime_directory, port).await?;
        let existing_marker = load_cutover_marker(&runtime_directory).await?;
        if existing_marker
            .as_ref()
            .is_some_and(|marker| marker.state.is_cutover())
        {
            runtime.mark_workspace_core_cutover();
        }
        let legacy_import = match existing_marker.as_ref() {
            Some(marker) if marker.state.is_cutover() => {
                staged_snapshot_from_marker(&runtime_directory, marker).await?
            }
            _ => {
                let snapshot =
                    stage_legacy_workspace_snapshot(&runtime, &runtime_directory).await?;
                persist_cutover_marker(
                    &runtime_directory,
                    WorkspaceCoreCutoverState::Importing,
                    Some(&snapshot),
                )
                .await?;
                runtime.mark_workspace_core_cutover();
                snapshot
            }
        };

        let initial_cutover_state = existing_marker
            .as_ref()
            .map_or(WorkspaceCoreCutoverState::Importing, |marker| marker.state);
        let launch = Arc::new(WorkspaceCoreLaunchConfig {
            binary_path,
            runtime_directory,
            config_path,
            api_base_url,
            service_token: random_secret()?,
            agent_registry_token: random_secret()?,
            provider_webhook_token: random_secret()?,
            provider_event_token: random_secret()?,
            sidecar_api_base_url: sidecar_api_base_url.to_string(),
            legacy_import_path: legacy_import.path.clone(),
            legacy_import_sha256: legacy_import.sha256.clone(),
            cutover_snapshot: legacy_import,
        });
        let authority_generation = runtime.install_workspace_core_authority(
            launch.api_base_url.clone(),
            launch.service_token.as_str().to_string(),
            launch.agent_registry_token.as_str().to_string(),
            launch.provider_webhook_token.as_str().to_string(),
            launch.provider_event_token.as_str().to_string(),
        )?;
        let authority_lease = WorkspaceCoreAuthorityLease {
            runtime,
            generation: authority_generation,
        };
        let status = Arc::new(Mutex::new(WorkspaceCoreHelperStatus::starting(
            0,
            0,
            initial_cutover_state,
        )));
        let (shutdown, shutdown_rx) = watch::channel(false);
        let monitor = tokio::spawn(monitor_helper(
            Arc::clone(&launch),
            Arc::clone(&status),
            shutdown_rx,
            authority_lease,
        ));
        Ok(Self {
            status,
            shutdown,
            monitor,
        })
    }

    pub(crate) async fn status(&self) -> WorkspaceCoreHelperStatus {
        self.status.lock().await.clone()
    }

    pub(crate) async fn shutdown(self) {
        let _ = self.shutdown.send(true);
        let _ = self.monitor.await;
    }
}

async fn monitor_helper(
    launch: Arc<WorkspaceCoreLaunchConfig>,
    status: Arc<Mutex<WorkspaceCoreHelperStatus>>,
    mut shutdown: watch::Receiver<bool>,
    authority_lease: WorkspaceCoreAuthorityLease,
) {
    let mut restart_attempts = 0;
    let mut restart_generation = 0;
    let mut cutover_state = status.lock().await.cutover_state;
    loop {
        if *shutdown.borrow() {
            *status.lock().await =
                WorkspaceCoreHelperStatus::stopped(restart_generation, cutover_state);
            return;
        }
        restart_generation += 1;
        *status.lock().await = WorkspaceCoreHelperStatus::starting(
            restart_attempts,
            restart_generation,
            cutover_state,
        );
        let launch_result = tokio::select! {
            _ = shutdown.changed() => {
                *status.lock().await = WorkspaceCoreHelperStatus::stopped(
                    restart_generation,
                    cutover_state,
                );
                return;
            }
            result = launch_helper(&launch) => result,
        };
        let mut child = match launch_result {
            Ok(child) => child,
            Err(error) => {
                if !schedule_retry(
                    &status,
                    &mut shutdown,
                    &mut restart_attempts,
                    restart_generation,
                    &launch,
                    cutover_state,
                    RetryFailure {
                        reason: "workspace_core_launch_failed",
                        detail: error,
                    },
                )
                .await
                {
                    return;
                }
                continue;
            }
        };
        let started_at = Instant::now();
        if let Err(error) = authority_lease
            .runtime
            .replay_workspace_core_terminal_callbacks()
            .await
        {
            tracing::error!(
                error = %error,
                "Workspace Core pending terminal callback replay failed"
            );
        }
        if let Err(error) = authority_lease.runtime.resume_workspace_task_runs().await {
            tracing::error!(
                error = %error,
                "Workspace Task pre-launch recovery failed"
            );
        }
        if let Err(error) = persist_cutover_marker(
            &launch.runtime_directory,
            WorkspaceCoreCutoverState::CoreAuthoritative,
            Some(&launch.cutover_snapshot),
        )
        .await
        {
            tracing::error!(error = %error, "Workspace Core authoritative cutover marker failed");
            shutdown_child(&mut child).await;
            *status.lock().await = WorkspaceCoreHelperStatus {
                state: "failed",
                pid: None,
                api_base_url: None,
                restart_attempts,
                restart_generation,
                failure_reason: Some("workspace_core_cutover_marker_failed"),
                cutover_state: WorkspaceCoreCutoverState::CoreUnavailable,
            };
            return;
        }
        cutover_state = WorkspaceCoreCutoverState::CoreAuthoritative;
        *status.lock().await = WorkspaceCoreHelperStatus {
            state: "running",
            pid: child.child.id(),
            api_base_url: Some(launch.api_base_url.clone()),
            restart_attempts,
            restart_generation,
            failure_reason: None,
            cutover_state,
        };
        tokio::select! {
            _ = shutdown.changed() => {
                shutdown_child(&mut child).await;
                *status.lock().await = WorkspaceCoreHelperStatus::stopped(
                    restart_generation,
                    cutover_state,
                );
                return;
            }
            _ = child.child.wait() => {}
        }
        if started_at.elapsed() >= DEFAULT_RESTART_STABILITY {
            restart_attempts = 0;
        }
        if let Err(error) = persist_cutover_marker(
            &launch.runtime_directory,
            WorkspaceCoreCutoverState::CoreUnavailable,
            Some(&launch.cutover_snapshot),
        )
        .await
        {
            tracing::error!(error = %error, "Workspace Core unavailable cutover marker failed");
        }
        cutover_state = WorkspaceCoreCutoverState::CoreUnavailable;
        if !schedule_retry(
            &status,
            &mut shutdown,
            &mut restart_attempts,
            restart_generation,
            &launch,
            cutover_state,
            RetryFailure {
                reason: "workspace_core_exited_unexpectedly",
                detail: "Workspace Core helper exited unexpectedly".to_string(),
            },
        )
        .await
        {
            return;
        }
    }
}

async fn schedule_retry(
    status: &Arc<Mutex<WorkspaceCoreHelperStatus>>,
    shutdown: &mut watch::Receiver<bool>,
    restart_attempts: &mut usize,
    restart_generation: usize,
    launch: &WorkspaceCoreLaunchConfig,
    cutover_state: WorkspaceCoreCutoverState,
    failure: RetryFailure,
) -> bool {
    if *restart_attempts >= DEFAULT_MAX_RESTART_ATTEMPTS {
        if let Err(error) = persist_cutover_marker(
            &launch.runtime_directory,
            WorkspaceCoreCutoverState::CoreUnavailable,
            Some(&launch.cutover_snapshot),
        )
        .await
        {
            tracing::error!(error = %error, "Workspace Core unavailable cutover marker failed");
        }
        *status.lock().await = WorkspaceCoreHelperStatus {
            state: "failed",
            pid: None,
            api_base_url: None,
            restart_attempts: *restart_attempts,
            restart_generation,
            failure_reason: Some(failure.reason),
            cutover_state: WorkspaceCoreCutoverState::CoreUnavailable,
        };
        tracing::error!(detail = %failure.detail, "Workspace Core helper exhausted restart attempts");
        return false;
    }
    let delay = DEFAULT_RESTART_DELAYS
        .get(*restart_attempts)
        .copied()
        .unwrap_or(Duration::from_secs(10));
    *restart_attempts += 1;
    *status.lock().await = WorkspaceCoreHelperStatus {
        state: "restartScheduled",
        pid: None,
        api_base_url: None,
        restart_attempts: *restart_attempts,
        restart_generation,
        failure_reason: Some(failure.reason),
        cutover_state,
    };
    tokio::select! {
        _ = sleep(delay) => true,
        _ = shutdown.changed() => false,
    }
}

struct RetryFailure {
    reason: &'static str,
    detail: String,
}

async fn launch_helper(config: &WorkspaceCoreLaunchConfig) -> Result<SupervisedChild, String> {
    let nonce = random_secret()?;
    let handshake_secret = random_secret_bytes()?;
    let provider_url = format!(
        "{}/internal/v1/workspace-core/provider",
        config.sidecar_api_base_url.trim_end_matches('/')
    );
    let plan_dispatch_url = format!(
        "{}/internal/v1/workspace-core/plan-dispatch",
        config.sidecar_api_base_url.trim_end_matches('/')
    );
    let mut child = Command::new(&config.binary_path)
        .arg("--desktop-control")
        .current_dir(&config.runtime_directory)
        .env_clear()
        // The core's agent-registry HTTP client doubles as the Workspace
        // judge transport, and desktop judge calls run an LLM round-trip
        // synchronously. The 5s default guaranteed judge transport failures
        // (and endless scheduler retries) for any real model; 60s is the
        // core's documented upper bound and exceeds the sidecar's own 45s
        // per-candidate LLM timeout, so the judge verdict always settles
        // first.
        .env("WORKSPACE_CORE_AGENT_REGISTRY_TIMEOUT_SECONDS", "60")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        // Inherit the sidecar's stderr so Workspace Core diagnostics remain
        // visible to whoever captures sidecar logs; the Electron supervisor
        // still drains that pipe without forwarding it to app logs.
        .stderr(Stdio::inherit())
        .kill_on_drop(true)
        .spawn()
        .map_err(|error| format!("failed to launch Workspace Core helper: {error}"))?;
    let Some(mut input) = child.stdin.take() else {
        let _ = child.kill().await;
        return Err("Workspace Core helper stdin is unavailable".to_string());
    };
    let Some(output) = child.stdout.take() else {
        let _ = child.kill().await;
        return Err("Workspace Core helper stdout is unavailable".to_string());
    };
    let encoded_handshake_secret =
        Zeroizing::new(URL_SAFE_NO_PAD.encode(handshake_secret.as_ref()));
    let initialize = DesktopInitialize {
        message_type: "desktop_initialize",
        protocol_version: DESKTOP_CONTROL_PROTOCOL_VERSION,
        nonce: nonce.as_str(),
        secret: encoded_handshake_secret.as_str(),
        config_path: &config.config_path,
        mode: "desktop-local",
        service_token: config.service_token.as_str(),
        agent_registry_url: &config.sidecar_api_base_url,
        agent_registry_token: config.agent_registry_token.as_str(),
        provider_webhook_url: provider_url,
        provider_webhook_token: config.provider_webhook_token.as_str(),
        provider_event_token: config.provider_event_token.as_str(),
        plan_dispatch_url,
        instance_id: format!("desktop-sidecar:{}", std::process::id()),
        legacy_import_path: &config.legacy_import_path,
        legacy_import_sha256: &config.legacy_import_sha256,
    };
    let mut encoded = Zeroizing::new(
        serde_json::to_string(&initialize)
            .map_err(|_| "failed to encode Workspace Core initialization".to_string())?,
    );
    encoded.push('\n');
    if let Err(error) = input.write_all(encoded.as_bytes()).await {
        terminate_unverified_child(&mut child).await;
        return Err(format!(
            "failed to initialize Workspace Core helper: {error}"
        ));
    }
    if let Err(error) = input.flush().await {
        terminate_unverified_child(&mut child).await;
        return Err(format!(
            "failed to flush Workspace Core initialization: {error}"
        ));
    }

    let ready = match timeout(STARTUP_TIMEOUT, read_ready(output)).await {
        Ok(Ok(ready)) => ready,
        Ok(Err(error)) => {
            terminate_unverified_child(&mut child).await;
            return Err(error);
        }
        Err(_) => {
            terminate_unverified_child(&mut child).await;
            return Err("Workspace Core helper readiness timed out".to_string());
        }
    };
    if let Err(error) = verify_ready(
        config,
        nonce.as_str(),
        handshake_secret.as_ref(),
        child.id(),
        &ready,
    ) {
        terminate_unverified_child(&mut child).await;
        return Err(error);
    }
    Ok(SupervisedChild {
        child,
        input,
        nonce,
    })
}

async fn read_ready(output: ChildStdout) -> Result<DesktopReady, String> {
    let mut reader = BufReader::new(output);
    let mut line = String::new();
    let bytes = (&mut reader)
        .take((MAX_READY_BYTES + 1) as u64)
        .read_line(&mut line)
        .await
        .map_err(|error| format!("failed to read Workspace Core readiness: {error}"))?;
    if bytes == 0 || bytes > MAX_READY_BYTES || !line.ends_with('\n') {
        return Err("Workspace Core readiness frame is invalid".to_string());
    }
    line.pop();
    if line.ends_with('\r') {
        line.pop();
    }
    serde_json::from_str(&line).map_err(|_| "Workspace Core readiness frame is invalid".to_string())
}

fn verify_ready(
    config: &WorkspaceCoreLaunchConfig,
    nonce: &str,
    handshake_secret: &[u8],
    child_pid: Option<u32>,
    ready: &DesktopReady,
) -> Result<(), String> {
    if ready.message_type != "desktop_ready"
        || ready.protocol_version != DESKTOP_CONTROL_PROTOCOL_VERSION
        || ready.nonce != nonce
        || Some(ready.pid) != child_pid
        || ready.api_base_url != config.api_base_url
    {
        return Err("Workspace Core readiness did not match the launched helper".to_string());
    }
    let proof = decode_lower_hex_proof(&ready.proof)?;
    let canonical = format!(
        "{}\n{}\n{}\n{}",
        DESKTOP_CONTROL_PROTOCOL_VERSION, ready.nonce, ready.pid, ready.api_base_url
    );
    let mut mac = Hmac::<Sha256>::new_from_slice(handshake_secret)
        .map_err(|_| "Workspace Core readiness proof is invalid".to_string())?;
    mac.update(canonical.as_bytes());
    mac.verify_slice(&proof)
        .map_err(|_| "Workspace Core readiness proof is invalid".to_string())
}

fn decode_lower_hex_proof(value: &str) -> Result<[u8; 32], String> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("Workspace Core readiness proof is invalid".to_string());
    }
    let mut proof = [0_u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        let high = hex_nibble(pair[0]);
        let low = hex_nibble(pair[1]);
        proof[index] = (high << 4) | low;
    }
    Ok(proof)
}

fn hex_nibble(byte: u8) -> u8 {
    match byte {
        b'0'..=b'9' => byte - b'0',
        b'a'..=b'f' => byte - b'a' + 10,
        _ => 0,
    }
}

async fn shutdown_child(child: &mut SupervisedChild) {
    let shutdown = DesktopShutdown {
        message_type: "desktop_shutdown",
        protocol_version: DESKTOP_CONTROL_PROTOCOL_VERSION,
        nonce: child.nonce.as_str(),
    };
    let frame = serde_json::to_string(&shutdown)
        .map(|value| format!("{value}\n"))
        .unwrap_or_default();
    let sent = !frame.is_empty()
        && child.input.write_all(frame.as_bytes()).await.is_ok()
        && child.input.flush().await.is_ok();
    if sent
        && matches!(
            timeout(SHUTDOWN_TIMEOUT, child.child.wait()).await,
            Ok(Ok(_))
        )
    {
        return;
    }
    terminate_unverified_child(&mut child.child).await;
}

async fn terminate_unverified_child(child: &mut Child) {
    if child.id().is_some() {
        let _ = child.kill().await;
    }
    let _ = child.wait().await;
}

async fn reserve_loopback_port() -> Result<u16, String> {
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
        .await
        .map_err(|error| format!("failed to reserve Workspace Core port: {error}"))?;
    let port = listener
        .local_addr()
        .map_err(|error| format!("failed to inspect Workspace Core port: {error}"))?
        .port();
    drop(listener);
    Ok(port)
}

fn random_secret() -> Result<Zeroizing<String>, String> {
    let mut bytes = zeroize::Zeroizing::new([0_u8; 32]);
    getrandom::getrandom(bytes.as_mut())
        .map_err(|_| "failed to generate Workspace Core credential".to_string())?;
    Ok(Zeroizing::new(URL_SAFE_NO_PAD.encode(bytes.as_ref())))
}

fn random_secret_bytes() -> Result<Zeroizing<[u8; 32]>, String> {
    let mut bytes = Zeroizing::new([0_u8; 32]);
    getrandom::getrandom(bytes.as_mut())
        .map_err(|_| "failed to generate Workspace Core credential".to_string())?;
    Ok(bytes)
}

fn validate_binary_path(binary_path: &Path) -> Result<(), String> {
    if !binary_path.is_absolute() {
        return Err("Workspace Core helper path must be absolute".to_string());
    }
    let metadata = std::fs::symlink_metadata(binary_path)
        .map_err(|_| "Workspace Core helper is unavailable".to_string())?;
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err("Workspace Core helper must be a regular file".to_string());
    }
    Ok(())
}

async fn write_config(path: &Path, runtime_directory: &Path, port: u16) -> Result<(), String> {
    let database_path = toml_string(&runtime_directory.join("avernet-workspace.db"))?;
    let bots_path = toml_string(&runtime_directory.join("bots"))?;
    let files_path = toml_string(&runtime_directory.join("files"))?;
    let endpoint = format!("http://127.0.0.1:{port}");
    let source = format!(
        "bind = \"127.0.0.1\"\nport = {port}\nbots_base_dir = \"{bots_path}\"\n\
         bcs_endpoint = \"{endpoint}\"\nstore_messages = true\nstrict_container_validation = false\n\
         api_keys = []\nallowed_switch_provider_ids = []\n\
         [database]\ntype = \"sqlite\"\n[database.sqlite]\npath = \"{database_path}\"\n\
         [leader_election]\nenabled = false\n\
         [secret]\nprovider = \"env\"\n[secret.providers.env]\nprefix = \"BCS_SECRET_\"\n\
         [gateway_principal]\nissuer = \"desktop-sidecar\"\naudience = \"workspace-core\"\nkey_id = \"desktop-local\"\nsigning_key_env = \"AVERNET_SECRET_PRINCIPAL_SIGNING_KEY_VALUE\"\n\
         [session_files]\nstorage_backend = \"local\"\n[session_files.backend]\ndata_dir = \"{files_path}\"\n\
         [auth]\nchain = [\"local\"]\nrequire_authentication = false\nallow_mock_headers = false\n\
         [metrics]\nenabled = false\n\
         [logging]\ndefault_level = \"warn\"\nconsole = true\n"
    );
    tokio::fs::write(path, source)
        .await
        .map_err(|error| format!("failed to write Workspace Core configuration: {error}"))?;
    set_private_file_permissions(path)
        .map_err(|error| format!("failed to secure Workspace Core configuration: {error}"))
}

fn toml_string(path: &Path) -> Result<String, String> {
    let value = path
        .to_str()
        .ok_or_else(|| "Workspace Core path is not valid UTF-8".to_string())?;
    Ok(value.replace('\\', "\\\\").replace('"', "\\\""))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn launch_config() -> WorkspaceCoreLaunchConfig {
        WorkspaceCoreLaunchConfig {
            binary_path: PathBuf::from("/tmp/memstack-workspace-core"),
            runtime_directory: PathBuf::from("/tmp/workspace-core"),
            config_path: PathBuf::from("/tmp/workspace-core/bcs-config.toml"),
            api_base_url: "http://127.0.0.1:21000".to_string(),
            service_token: Zeroizing::new("s".repeat(43)),
            agent_registry_token: Zeroizing::new("r".repeat(43)),
            provider_webhook_token: Zeroizing::new("w".repeat(43)),
            provider_event_token: Zeroizing::new("e".repeat(43)),
            sidecar_api_base_url: "http://127.0.0.1:31000".to_string(),
            legacy_import_path: PathBuf::from("/tmp/workspace-core/legacy-import.json"),
            legacy_import_sha256: "a".repeat(64),
            cutover_snapshot: crate::workspace_core_legacy_import::StagedLegacyWorkspaceSnapshot {
                path: PathBuf::from("/tmp/workspace-core/legacy-import.json"),
                sha256: "a".repeat(64),
            },
        }
    }

    fn valid_ready(config: &WorkspaceCoreLaunchConfig, nonce: &str, pid: u32) -> DesktopReady {
        let canonical = format!(
            "{}\n{}\n{}\n{}",
            DESKTOP_CONTROL_PROTOCOL_VERSION, nonce, pid, config.api_base_url
        );
        let mut mac = Hmac::<Sha256>::new_from_slice(&[7_u8; 32]).expect("HMAC key");
        mac.update(canonical.as_bytes());
        let proof = mac
            .finalize()
            .into_bytes()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        DesktopReady {
            message_type: "desktop_ready".to_string(),
            protocol_version: DESKTOP_CONTROL_PROTOCOL_VERSION,
            nonce: nonce.to_string(),
            pid,
            api_base_url: config.api_base_url.clone(),
            proof,
        }
    }

    #[test]
    fn helper_status_never_contains_credentials() {
        let status = WorkspaceCoreHelperStatus {
            state: "running",
            pid: Some(42),
            api_base_url: Some("http://127.0.0.1:21000".to_string()),
            restart_attempts: 1,
            restart_generation: 2,
            failure_reason: None,
            cutover_state: WorkspaceCoreCutoverState::CoreAuthoritative,
        };
        let encoded = serde_json::to_string(&status).expect("serialize helper status");
        assert!(!encoded.contains("token"));
        assert!(!encoded.contains("credential"));
    }

    #[test]
    fn helper_path_must_be_absolute_and_regular() {
        assert_eq!(
            validate_binary_path(Path::new("relative/helper")),
            Err("Workspace Core helper path must be absolute".to_string())
        );
    }

    #[test]
    fn restart_budget_is_finite() {
        assert_eq!(DEFAULT_MAX_RESTART_ATTEMPTS, DEFAULT_RESTART_DELAYS.len());
        assert_eq!(
            DEFAULT_RESTART_DELAYS.last(),
            Some(&Duration::from_secs(10))
        );
    }

    #[test]
    fn ready_proof_binds_the_exact_child_and_api_endpoint() {
        let config = launch_config();
        let nonce = "nonce-0123456789abcdef";
        let ready = valid_ready(&config, nonce, 42);
        assert!(verify_ready(&config, nonce, &[7_u8; 32], Some(42), &ready).is_ok());

        let mut forged_pid = valid_ready(&config, nonce, 42);
        forged_pid.pid = 43;
        assert!(verify_ready(&config, nonce, &[7_u8; 32], Some(42), &forged_pid).is_err());

        let mut forged_url = valid_ready(&config, nonce, 42);
        forged_url.api_base_url = "http://127.0.0.1:21001".to_string();
        assert!(verify_ready(&config, nonce, &[7_u8; 32], Some(42), &forged_url).is_err());

        let mut forged_nonce = valid_ready(&config, nonce, 42);
        forged_nonce.nonce = "nonce-from-another-session".to_string();
        assert!(verify_ready(&config, nonce, &[7_u8; 32], Some(42), &forged_nonce).is_err());
    }

    #[test]
    fn readiness_proof_requires_lowercase_sha256_hex() {
        assert!(decode_lower_hex_proof(&"a0".repeat(32)).is_ok());
        assert!(decode_lower_hex_proof(&"A0".repeat(32)).is_err());
        assert!(decode_lower_hex_proof(&"a0".repeat(31)).is_err());
    }
}
