//! Background reconciliation from the Python plugin control plane.

use std::{
    collections::{BTreeMap, BTreeSet},
    io::{Cursor, Read},
    sync::Arc,
    time::Duration,
};

use rusqlite::Connection;
use serde::Deserialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use tokio::sync::watch;
use url::Url;
use zip::ZipArchive;

use crate::{
    plugin_snapshots::{self, RequestedPluginSnapshot},
    trusted_session::{
        TrustedSessionBroker, TrustedSessionCredentialKind, TrustedSessionRecord,
        TrustedSessionRuntimeMode,
    },
};

use super::mcp_supervisor::McpScope;
use super::workspace_core_bridge::platform_plugin_payload_digest;
use super::LocalRuntimeState;

const SUCCESS_INTERVAL: Duration = Duration::from_secs(30);
const INITIAL_ERROR_INTERVAL: Duration = Duration::from_secs(2);
const MAX_ERROR_INTERVAL: Duration = Duration::from_secs(60);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_SNAPSHOT_BYTES: usize = 4 * 1024 * 1024;
const MAX_OCI_MANIFEST_BYTES: usize = 2 * 1024 * 1024;
const MAX_PLUGIN_ARCHIVE_BYTES: usize = 64 * 1024 * 1024;
const MAX_ARCHIVE_FILES: usize = 512;
const MAX_ARCHIVE_UNCOMPRESSED_BYTES: usize = 128 * 1024 * 1024;
const OCI_MANIFEST_MEDIA_TYPE: &str = "application/vnd.oci.image.manifest.v1+json";
const MEMSTACK_ARTIFACT_TYPE: &str = "application/vnd.memstack.plugin.v1";
const MEMSTACK_LAYER_TYPE: &str = "application/vnd.memstack.plugin.bundle.v1+zip";

#[derive(Debug)]
pub(crate) struct PlatformPluginControlPlaneReconciler {
    shutdown: watch::Sender<bool>,
    task: tokio::task::JoinHandle<()>,
}

impl PlatformPluginControlPlaneReconciler {
    pub(super) fn start(
        state: Arc<LocalRuntimeState>,
        trusted_sessions: TrustedSessionBroker,
    ) -> Self {
        Self::start_with_intervals(
            state,
            trusted_sessions,
            SUCCESS_INTERVAL,
            INITIAL_ERROR_INTERVAL,
        )
    }

    fn start_with_intervals(
        state: Arc<LocalRuntimeState>,
        trusted_sessions: TrustedSessionBroker,
        success_interval: Duration,
        initial_error_interval: Duration,
    ) -> Self {
        let (shutdown, shutdown_rx) = watch::channel(false);
        let task = tokio::spawn(reconcile_loop(
            state,
            trusted_sessions,
            shutdown_rx,
            success_interval,
            initial_error_interval,
        ));
        Self { shutdown, task }
    }

    pub(crate) async fn shutdown(self) {
        let _ = self.shutdown.send(true);
        let _ = self.task.await;
    }
}

async fn reconcile_loop(
    state: Arc<LocalRuntimeState>,
    trusted_sessions: TrustedSessionBroker,
    mut shutdown_rx: watch::Receiver<bool>,
    success_interval: Duration,
    mut error_interval: Duration,
) {
    loop {
        match reconcile_once(&state, &trusted_sessions).await {
            Ok(()) => {
                error_interval = INITIAL_ERROR_INTERVAL;
                tokio::select! {
                    _ = shutdown_rx.changed() => break,
                    _ = tokio::time::sleep(success_interval) => {}
                }
            }
            Err(error) => {
                tracing::warn!(error = %error, "platform plugin control-plane poll failed");
                tokio::select! {
                    _ = shutdown_rx.changed() => break,
                    _ = tokio::time::sleep(error_interval) => {}
                }
                error_interval =
                    std::cmp::min(error_interval.saturating_mul(2), MAX_ERROR_INTERVAL);
            }
        }
    }
}

async fn reconcile_once(
    state: &LocalRuntimeState,
    trusted_sessions: &TrustedSessionBroker,
) -> Result<(), String> {
    let Some(record) = trusted_sessions.load().map_err(|error| error.to_string())? else {
        return Ok(());
    };
    if !matches!(
        (record.runtime_mode, record.credential_kind),
        (
            TrustedSessionRuntimeMode::Cloud,
            TrustedSessionCredentialKind::CloudBearer
        )
    ) {
        return Ok(());
    }
    let base_url = validate_cloud_base_url(&record)?;
    let client = reqwest::Client::builder()
        .timeout(REQUEST_TIMEOUT)
        .build()
        .map_err(|error| format!("plugin control-plane client unavailable: {error}"))?;
    let snapshot =
        fetch_control_plane_snapshot(&client, &base_url, record.credential.as_str()).await?;
    validate_snapshot(&snapshot)?;
    let previous_last_good = {
        let connection = state.session_store.connection()?;
        plugin_snapshots::initialize_schema(&connection)?;
        plugin_snapshots::read_last_good(&connection)?
    };
    let receipt = match prepare_runtime_artifacts(&state, &client, &snapshot).await {
        Ok(()) => prepare_local_snapshot(state, &snapshot)?,
        Err(reason) => Some(reject_local_snapshot(state, &snapshot, reason)),
    };
    if receipt.as_ref().is_some_and(|item| item.3 == "nack") {
        reconcile_mcp_servers(&state, previous_last_good.as_ref(), None)?;
    } else {
        reconcile_mcp_servers(&state, Some(&snapshot.payload), previous_last_good.as_ref())?;
    }
    let Some((requested_version, applied_version, digest, status, error_message)) = receipt else {
        return Ok(());
    };
    post_receipt(
        &client,
        &base_url,
        record.credential.as_str(),
        requested_version,
        applied_version,
        digest.as_str(),
        status.as_str(),
        error_message.as_deref(),
    )
    .await
    .and_then(|()| {
        if status == "nack" {
            Err(error_message.unwrap_or_else(|| {
                "platform plugin preparation failed without a reason".to_string()
            }))
        } else {
            Ok(())
        }
    })
}

fn reject_local_snapshot(
    state: &LocalRuntimeState,
    snapshot: &ControlPlaneSnapshot,
    reason: String,
) -> (u64, u64, String, String, Option<String>) {
    let connection = state
        .session_store
        .connection()
        .map_err(|error| error.to_string())
        .and_then(|connection| {
            plugin_snapshots::initialize_schema(&connection)?;
            Ok(connection)
        });
    let connection = match connection {
        Ok(connection) => connection,
        Err(storage_error) => {
            return (
                snapshot.version,
                0,
                snapshot.digest.clone(),
                "nack".to_string(),
                Some(format!("{reason}; storage error: {storage_error}")),
            );
        }
    };
    let previous = plugin_snapshots::read_apply_record(&connection)
        .ok()
        .flatten()
        .map_or(0, |record| record.applied_version);
    let requested = RequestedPluginSnapshot {
        version: snapshot.version,
        nonce: snapshot.nonce.clone(),
        digest: snapshot.digest.clone(),
        payload: snapshot.payload.clone(),
    };
    if let Err(storage_error) = plugin_snapshots::record_requested(
        &connection,
        requested.version,
        &requested.nonce,
        &requested.digest,
        &requested.payload.to_string(),
    ) {
        return (
            snapshot.version,
            previous,
            snapshot.digest.clone(),
            "nack".to_string(),
            Some(format!("{reason}; storage error: {storage_error}")),
        );
    }
    if let Err(storage_error) = plugin_snapshots::record_nack(&connection, &reason) {
        return (
            snapshot.version,
            previous,
            snapshot.digest.clone(),
            "nack".to_string(),
            Some(format!("{reason}; storage error: {storage_error}")),
        );
    }
    (
        snapshot.version,
        previous,
        snapshot.digest.clone(),
        "nack".to_string(),
        Some(reason),
    )
}

type ControlPlaneReceipt = Option<(u64, u64, String, String, Option<String>)>;

fn reconcile_mcp_servers(
    state: &LocalRuntimeState,
    desired_payload: Option<&Value>,
    previous_payload: Option<&Value>,
) -> Result<(), String> {
    let workspace = state
        .session_store
        .workspace_context(super::auth_context::LOCAL_USER_ID)?;
    let scope = McpScope {
        tenant_id: workspace.tenant_id,
        project_id: workspace.project_id,
    };
    reconcile_mcp_servers_for_scope(state, &scope, desired_payload, previous_payload)
}

pub(super) fn ensure_platform_mcp_runtime(
    state: &LocalRuntimeState,
    scope: &McpScope,
    plugin: &Value,
    artifact: &plugin_snapshots::RuntimeArtifact,
) -> Result<(), String> {
    let plugin_id = plugin
        .get("id")
        .and_then(Value::as_str)
        .ok_or_else(|| "MCP plugin id is missing".to_string())?;
    let definition = serde_json::from_slice::<Value>(&artifact.bytes)
        .map_err(|_| format!("MCP plugin {plugin_id} runtime JSON is invalid"))?;
    state
        .mcp_supervisor
        .ensure_platform_plugin_server(scope, plugin_id, &definition, &artifact.digest)
        .map_err(|error| format!("{}: {}", error.reason_code(), error.detail()))?;
    Ok(())
}

fn reconcile_mcp_servers_for_scope(
    state: &LocalRuntimeState,
    scope: &McpScope,
    desired_payload: Option<&Value>,
    previous_payload: Option<&Value>,
) -> Result<(), String> {
    let mut desired_ids = BTreeSet::new();
    if let Some(payload) = desired_payload {
        let plugins = payload
            .get("plugins")
            .and_then(Value::as_array)
            .ok_or_else(|| "control-plane snapshot plugins are invalid".to_string())?;
        for plugin in plugins {
            let runtime = plugin
                .get("runtime")
                .and_then(Value::as_str)
                .unwrap_or_default();
            if runtime != "mcp" {
                continue;
            }
            let plugin_id = plugin
                .get("id")
                .and_then(Value::as_str)
                .ok_or_else(|| "MCP plugin id is missing".to_string())?;
            let artifact_digest = plugin
                .get("config")
                .and_then(Value::as_object)
                .and_then(|config| config.get("artifact"))
                .and_then(Value::as_object)
                .and_then(|artifact| artifact.get("layer_sha256"))
                .and_then(Value::as_str)
                .ok_or_else(|| format!("MCP plugin {plugin_id} has no artifact digest"))?;
            let artifact = {
                let connection = state.session_store.connection()?;
                plugin_snapshots::read_runtime_artifact(&connection, plugin_id, artifact_digest)?
                    .ok_or_else(|| {
                        format!("MCP plugin {plugin_id} runtime artifact is unavailable")
                    })?
            };
            ensure_platform_mcp_runtime(state, scope, plugin, &artifact)?;
            desired_ids.insert(plugin_id.to_string());
        }
    }

    let servers = state
        .mcp_supervisor
        .platform_plugin_servers()
        .map_err(|error| format!("{}: {}", error.reason_code(), error.detail()))?;
    let mut known_plugin_ids = desired_ids.clone();
    if let Some(payload) = previous_payload {
        if let Some(plugins) = payload.get("plugins").and_then(Value::as_array) {
            for plugin in plugins {
                if plugin.get("runtime").and_then(Value::as_str) == Some("mcp") {
                    if let Some(plugin_id) = plugin.get("id").and_then(Value::as_str) {
                        known_plugin_ids.insert(plugin_id.to_string());
                    }
                }
            }
        }
    }
    for server in servers {
        let Some(plugin_id) = server.name.strip_prefix("platform-plugin-") else {
            continue;
        };
        let scope_changed =
            server.tenant_id != scope.tenant_id || server.project_id != scope.project_id;
        if known_plugin_ids.contains(plugin_id)
            && (scope_changed || !desired_ids.contains(plugin_id))
        {
            let server_scope = McpScope {
                tenant_id: server.tenant_id.clone(),
                project_id: server.project_id.clone(),
            };
            state
                .mcp_supervisor
                .remove_platform_plugin_server(&server_scope, plugin_id)
                .map_err(|error| format!("{}: {}", error.reason_code(), error.detail()))?;
        }
    }
    Ok(())
}

async fn prepare_runtime_artifacts(
    state: &LocalRuntimeState,
    client: &reqwest::Client,
    snapshot: &ControlPlaneSnapshot,
) -> Result<(), String> {
    let plugins = snapshot
        .payload
        .get("plugins")
        .and_then(Value::as_array)
        .ok_or_else(|| "control-plane snapshot plugins are invalid".to_string())?;
    struct ArtifactReference {
        plugin: Value,
        plugin_id: String,
        runtime: String,
        registry: String,
        repository: String,
        manifest_digest: String,
        layer_digest: String,
    }

    let mut references = Vec::new();
    {
        let connection = state.session_store.connection()?;
        plugin_snapshots::initialize_schema(&connection)?;

        for plugin in plugins {
            let object = plugin
                .as_object()
                .ok_or_else(|| "control-plane plugin must be an object".to_string())?;
            let runtime = bounded_field(object.get("runtime"), 32, "plugin runtime")?;
            if runtime == "python-trusted" {
                continue;
            }
            let plugin_id = bounded_field(object.get("id"), 255, "plugin id")?;
            let artifact = object
                .get("config")
                .and_then(Value::as_object)
                .and_then(|config| config.get("artifact"))
                .and_then(Value::as_object)
                .ok_or_else(|| format!("plugin {plugin_id} has no runtime artifact reference"))?;
            let registry = bounded_field(artifact.get("registry"), 512, "artifact registry")?;
            let repository = bounded_field(artifact.get("repository"), 255, "artifact repository")?;
            let manifest_digest =
                hex_digest(artifact.get("manifest_sha256"), "OCI manifest digest")?;
            let layer_digest = hex_digest(artifact.get("layer_sha256"), "OCI layer digest")?;

            if plugin_snapshots::read_runtime_artifact(&connection, &plugin_id, &layer_digest)?
                .is_some()
            {
                continue;
            }
            references.push(ArtifactReference {
                plugin: plugin.clone(),
                plugin_id,
                runtime,
                registry,
                repository,
                manifest_digest,
                layer_digest,
            });
        }
    }

    for reference in references {
        let archive = fetch_verified_plugin_layer(
            client,
            &reference.registry,
            &reference.repository,
            &reference.manifest_digest,
            &reference.layer_digest,
        )
        .await?;
        let (runtime_path, runtime_bytes) = verify_plugin_archive(&archive, &reference.plugin)
            .map_err(|error| {
                format!(
                    "plugin {} artifact {}: {}",
                    reference.plugin_id, reference.layer_digest, error
                )
            })?;
        let connection = state.session_store.connection()?;
        plugin_snapshots::store_runtime_artifact(
            &connection,
            &plugin_snapshots::RuntimeArtifact {
                plugin_id: reference.plugin_id,
                digest: reference.layer_digest,
                runtime: reference.runtime,
                path: runtime_path,
                bytes: runtime_bytes,
            },
        )?;
    }
    Ok(())
}

fn prepare_local_snapshot(
    state: &LocalRuntimeState,
    snapshot: &ControlPlaneSnapshot,
) -> Result<ControlPlaneReceipt, String> {
    let mut connection = state.session_store.connection()?;
    plugin_snapshots::initialize_schema(&connection)?;
    let existing = plugin_snapshots::read_apply_record(&connection)?;
    if let Some(existing) = existing.as_ref() {
        if existing.applied_digest.as_deref() == Some(snapshot.digest.as_str())
            && existing.applied_version == snapshot.version
        {
            return Ok(Some((
                snapshot.version,
                snapshot.version,
                snapshot.digest.clone(),
                "ack".to_string(),
                None,
            )));
        }
        if existing.requested_digest == snapshot.digest && existing.status == "nack" {
            return Ok(None);
        }
        if snapshot.version <= existing.applied_version {
            let reason = "control-plane snapshot version is stale".to_string();
            record_control_plane_nack(&mut connection, snapshot, &reason)?;
            return Ok(Some((
                snapshot.version,
                existing.applied_version,
                snapshot.digest.clone(),
                "nack".to_string(),
                Some(reason),
            )));
        }
    }

    let requested = RequestedPluginSnapshot {
        version: snapshot.version,
        nonce: snapshot.nonce.clone(),
        digest: snapshot.digest.clone(),
        payload: snapshot.payload.clone(),
    };
    plugin_snapshots::record_requested(
        &connection,
        requested.version,
        &requested.nonce,
        &requested.digest,
        &requested.payload.to_string(),
    )?;
    match plugin_snapshots::record_ack(&mut connection, &requested) {
        Ok(_) => Ok(Some((
            requested.version,
            requested.version,
            requested.digest.clone(),
            "ack".to_string(),
            None,
        ))),
        Err(error) => {
            plugin_snapshots::record_nack(&connection, &error)?;
            let previous = existing.as_ref().map_or(0, |record| record.applied_version);
            Ok(Some((
                requested.version,
                previous,
                requested.digest,
                "nack".to_string(),
                Some(error),
            )))
        }
    }
}

#[derive(Debug, Deserialize)]
struct ControlPlaneSnapshot {
    version: u64,
    nonce: String,
    profile_id: String,
    digest: String,
    payload: Value,
}

async fn fetch_control_plane_snapshot(
    client: &reqwest::Client,
    base_url: &Url,
    credential: &str,
) -> Result<ControlPlaneSnapshot, String> {
    let url = control_plane_url(base_url, "platform-plugins/snapshot")?;
    let response = client
        .get(url)
        .bearer_auth(credential)
        .send()
        .await
        .map_err(|error| format!("control-plane snapshot fetch failed: {error}"))?;
    let status = response.status();
    if status.as_u16() == 404 {
        return Err("control-plane snapshot is not published".to_string());
    }
    if !status.is_success() {
        return Err(format!("control-plane snapshot fetch returned {status}"));
    }
    let bytes = response
        .bytes()
        .await
        .map_err(|error| format!("control-plane snapshot body failed: {error}"))?;
    if bytes.len() > MAX_SNAPSHOT_BYTES {
        return Err("control-plane snapshot exceeds its size limit".to_string());
    }
    serde_json::from_slice::<ControlPlaneSnapshot>(&bytes)
        .map_err(|error| format!("control-plane snapshot contract is invalid: {error}"))
}

async fn fetch_verified_plugin_layer(
    client: &reqwest::Client,
    registry: &str,
    repository: &str,
    manifest_digest: &str,
    layer_digest: &str,
) -> Result<Vec<u8>, String> {
    let registry_url =
        Url::parse(registry).map_err(|_| "plugin artifact registry URL is invalid".to_string())?;
    validate_registry_url(&registry_url)?;
    validate_repository(repository)?;
    let registry_origin = registry_url.as_str().trim_end_matches('/');
    let manifest_url =
        format!("{registry_origin}/v2/{repository}/manifests/sha256:{manifest_digest}");
    let manifest_response = client
        .get(&manifest_url)
        .header(
            "Accept",
            format!("{OCI_MANIFEST_MEDIA_TYPE}, {MEMSTACK_ARTIFACT_TYPE}"),
        )
        .send()
        .await
        .map_err(|error| format!("OCI manifest fetch failed: {error}"))?;
    check_registry_response(
        manifest_response.status(),
        &format!("OCI manifest {manifest_url}"),
    )?;
    let manifest_bytes =
        bounded_response_bytes(manifest_response, MAX_OCI_MANIFEST_BYTES, "OCI manifest").await?;
    ensure_digest(&manifest_bytes, manifest_digest, "OCI manifest")?;
    let manifest: Value = serde_json::from_slice(&manifest_bytes)
        .map_err(|_| "OCI manifest JSON is invalid".to_string())?;
    let actual_layer_digest = validate_oci_manifest(&manifest)?;
    if actual_layer_digest != layer_digest {
        return Err("requested layer digest does not match OCI manifest".to_string());
    }

    let blob_url = format!("{registry_origin}/v2/{repository}/blobs/sha256:{layer_digest}");
    let layer_response = client
        .get(blob_url)
        .send()
        .await
        .map_err(|error| format!("OCI plugin layer fetch failed: {error}"))?;
    check_registry_response(layer_response.status(), "OCI plugin layer")?;
    let archive =
        bounded_response_bytes(layer_response, MAX_PLUGIN_ARCHIVE_BYTES, "OCI plugin layer")
            .await?;
    ensure_digest(&archive, layer_digest, "OCI plugin layer")?;
    Ok(archive)
}

fn verify_plugin_archive(archive: &[u8], plugin: &Value) -> Result<(String, Vec<u8>), String> {
    let mut zip = ZipArchive::new(Cursor::new(archive))
        .map_err(|_| "plugin artifact is not a valid zip archive".to_string())?;
    if zip.len() as usize > MAX_ARCHIVE_FILES {
        return Err("plugin archive contains too many files".to_string());
    }
    let mut files: BTreeMap<String, Vec<u8>> = BTreeMap::new();
    let mut total_uncompressed = 0_usize;
    for index in 0..zip.len() {
        let mut entry = zip
            .by_index(index)
            .map_err(|error| format!("plugin archive entry is invalid: {error}"))?;
        if entry.is_dir() {
            continue;
        }
        let name = safe_archive_name(entry.name())?;
        if entry
            .unix_mode()
            .is_some_and(|mode| mode & 0o170000 == 0o120000)
        {
            return Err(format!("plugin archive entry {name} is a symbolic link"));
        }
        total_uncompressed = total_uncompressed.saturating_add(entry.size() as usize);
        if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED_BYTES {
            return Err("plugin archive expands beyond its size limit".to_string());
        }
        let mut bytes = Vec::with_capacity(entry.size() as usize);
        entry
            .read_to_end(&mut bytes)
            .map_err(|error| format!("plugin archive entry {name} could not be read: {error}"))?;
        if files.insert(name.clone(), bytes).is_some() {
            return Err(format!("plugin archive contains duplicate entry {name}"));
        }
    }

    let mut manifest = read_archive_object(&files, "plugin.manifest.json")?;
    let checksums = read_archive_object(&files, "checksums.json")?;
    if let Some(object) = manifest.as_object_mut() {
        object.remove("config");
        object.remove("layer_id");
    }
    let mut comparable_plugin = plugin.clone();
    if let Some(object) = comparable_plugin.as_object_mut() {
        object.remove("config");
        object.remove("layer_id");
    }
    if manifest != comparable_plugin {
        return Err("plugin archive manifest differs from control plane".to_string());
    }
    for (name, bytes) in &files {
        if name == "checksums.json" {
            continue;
        }
        let expected = checksums
            .get(name)
            .and_then(Value::as_str)
            .ok_or_else(|| format!("plugin archive file {name} has no checksum"))?;
        ensure_digest(bytes, expected, "plugin archive file")?;
    }

    let runtime = plugin
        .get("runtime")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let expected_name = match runtime {
        "wasm" => "runtime/plugin.wasm",
        "mcp" => "runtime/plugin.json",
        "subprocess" => "runtime/plugin.json",
        "frontend" => "runtime/plugin.json",
        _ => {
            return Err(format!(
                "plugin runtime {runtime} has no runtime artifact mapping"
            ))
        }
    };
    let bytes = files
        .remove(expected_name)
        .ok_or_else(|| format!("plugin archive is missing {expected_name}"))?;
    Ok((expected_name.to_string(), bytes))
}

async fn post_receipt(
    client: &reqwest::Client,
    base_url: &Url,
    credential: &str,
    requested_version: u64,
    applied_version: u64,
    digest: &str,
    status: &str,
    error_message: Option<&str>,
) -> Result<(), String> {
    let url = control_plane_url(base_url, "platform-plugins/data-plane-state")?;
    let body = serde_json::json!({
        "data_plane_id": "desktop-local",
        "snapshot_digest": digest,
        "requested_version": requested_version,
        "applied_version": applied_version,
        "status": status,
        "error_message": error_message,
    });
    let response = client
        .post(url)
        .bearer_auth(credential)
        .json(&body)
        .send()
        .await
        .map_err(|error| format!("control-plane receipt post failed: {error}"))?;
    if !response.status().is_success() {
        return Err(format!(
            "control-plane receipt post returned {}",
            response.status()
        ));
    }
    Ok(())
}

fn record_control_plane_nack(
    connection: &Connection,
    snapshot: &ControlPlaneSnapshot,
    reason: &str,
) -> Result<(), String> {
    plugin_snapshots::record_requested(
        connection,
        snapshot.version,
        &snapshot.nonce,
        &snapshot.digest,
        &snapshot.payload.to_string(),
    )?;
    plugin_snapshots::record_nack(connection, reason)
}

fn bounded_field(value: Option<&Value>, limit: usize, label: &str) -> Result<String, String> {
    let text = value
        .and_then(Value::as_str)
        .ok_or_else(|| format!("{label} must be a string"))?;
    if text.trim().is_empty() || text.len() > limit || text != text.trim() {
        return Err(format!("{label} is invalid"));
    }
    Ok(text.to_string())
}

fn hex_digest(value: Option<&Value>, label: &str) -> Result<String, String> {
    let digest = bounded_field(value, 64, label)?;
    if digest
        .chars()
        .any(|character| !character.is_ascii_hexdigit())
    {
        return Err(format!("{label} must be lowercase hexadecimal"));
    }
    Ok(digest)
}

fn validate_registry_url(url: &Url) -> Result<(), String> {
    let loopback = matches!(url.host_str(), Some("127.0.0.1" | "localhost" | "::1"));
    if !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || url.path() != "/"
        || !((url.scheme() == "https" && !loopback) || (url.scheme() == "http" && loopback))
    {
        return Err("plugin artifact registry URL is unsafe".to_string());
    }
    Ok(())
}

fn validate_repository(repository: &str) -> Result<(), String> {
    let invalid = repository.is_empty()
        || repository.len() > 255
        || repository.starts_with('/')
        || repository.ends_with('/')
        || repository.split('/').any(|segment| {
            segment.is_empty()
                || segment == "."
                || segment == ".."
                || !segment.chars().all(|character| {
                    character.is_ascii_lowercase()
                        || character.is_ascii_digit()
                        || matches!(character, '.' | '_' | '-')
                })
        });
    if invalid {
        return Err("plugin artifact repository is invalid".to_string());
    }
    Ok(())
}

fn check_registry_response(status: reqwest::StatusCode, label: &str) -> Result<(), String> {
    if !status.is_success() {
        return Err(format!("{label} fetch returned {status}"));
    }
    Ok(())
}

async fn bounded_response_bytes(
    response: reqwest::Response,
    limit: usize,
    label: &str,
) -> Result<Vec<u8>, String> {
    let mut bytes = Vec::new();
    let mut response = response;
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|error| format!("{label} body failed: {error}"))?
    {
        bytes.extend_from_slice(&chunk);
        if bytes.len() > limit {
            return Err(format!("{label} exceeds its size limit"));
        }
    }
    Ok(bytes)
}

fn ensure_digest(bytes: &[u8], expected: &str, label: &str) -> Result<(), String> {
    let actual = Sha256::digest(bytes);
    let actual = actual
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    if !actual.eq_ignore_ascii_case(expected) {
        return Err(format!("{label} digest mismatch"));
    }
    Ok(())
}

fn validate_oci_manifest(manifest: &Value) -> Result<String, String> {
    let layer = manifest
        .get("layers")
        .and_then(Value::as_array)
        .and_then(|layers| layers.first())
        .ok_or_else(|| "OCI manifest has no plugin layer".to_string())?;
    let digest = layer
        .get("digest")
        .and_then(Value::as_str)
        .and_then(|value| value.strip_prefix("sha256:"))
        .ok_or_else(|| "OCI plugin layer digest is invalid".to_string())?;
    if manifest.get("schemaVersion").and_then(Value::as_u64) != Some(2)
        || manifest.get("mediaType").and_then(Value::as_str) != Some(OCI_MANIFEST_MEDIA_TYPE)
        || manifest.get("artifactType").and_then(Value::as_str) != Some(MEMSTACK_ARTIFACT_TYPE)
        || layer.get("mediaType").and_then(Value::as_str) != Some(MEMSTACK_LAYER_TYPE)
    {
        return Err("OCI artifact is not a MemStack plugin package".to_string());
    }
    let digest = hex_digest(Some(&Value::String(digest.to_string())), "OCI layer digest")?;
    Ok(digest)
}

fn safe_archive_name(name: &str) -> Result<String, String> {
    if name.trim() != name
        || name.starts_with('/')
        || name.contains('\\')
        || name
            .split('/')
            .any(|segment| segment.is_empty() || segment == "." || segment == "..")
    {
        return Err("plugin archive entry name is invalid".to_string());
    }
    Ok(name.to_string())
}

fn read_archive_object<'a>(
    files: &'a BTreeMap<String, Vec<u8>>,
    name: &str,
) -> Result<Value, String> {
    let bytes = files
        .get(name)
        .ok_or_else(|| format!("plugin archive is missing {name}"))?;
    serde_json::from_slice(bytes).map_err(|_| format!("plugin archive file {name} is invalid JSON"))
}

fn validate_cloud_base_url(record: &TrustedSessionRecord) -> Result<Url, String> {
    let url = Url::parse(&record.api_base_url)
        .map_err(|_| "trusted cloud API base URL is invalid".to_string())?;
    let loopback = matches!(url.host_str(), Some("127.0.0.1" | "localhost" | "::1"));
    if (url.scheme() != "https" && !loopback)
        || !username_password_empty(&url)
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err("trusted cloud API base URL is unsafe".to_string());
    }
    Ok(url)
}

fn username_password_empty(url: &Url) -> bool {
    url.username().is_empty() && url.password().is_none()
}

fn control_plane_url(base: &Url, suffix: &str) -> Result<Url, String> {
    let base_path = base.path().trim_end_matches('/');
    let prefix = if base_path.ends_with("/api/v1") {
        base_path.to_string()
    } else {
        format!("{base_path}/api/v1")
    };
    let mut url = base.clone();
    url.set_path(&format!("{prefix}/{suffix}"));
    Ok(url)
}

fn validate_snapshot(snapshot: &ControlPlaneSnapshot) -> Result<(), String> {
    if snapshot.version == 0 {
        return Err("control-plane snapshot version must be positive".to_string());
    }
    if snapshot.nonce.trim().is_empty() || snapshot.nonce.len() > 128 {
        return Err("control-plane snapshot nonce is invalid".to_string());
    }
    if snapshot.profile_id.trim().is_empty() {
        return Err("control-plane snapshot profile id is required".to_string());
    }
    if snapshot.digest.len() != 64
        || !snapshot
            .digest
            .chars()
            .all(|character| character.is_ascii_hexdigit())
    {
        return Err("control-plane snapshot digest is invalid".to_string());
    }
    let Some(payload) = snapshot.payload.as_object() else {
        return Err("control-plane snapshot payload must be an object".to_string());
    };
    if payload.get("schema_version").and_then(Value::as_u64) != Some(1)
        || !payload.get("plugins").is_some_and(Value::is_array)
        || payload.get("digest").and_then(Value::as_str) != Some(snapshot.digest.as_str())
    {
        return Err("control-plane snapshot payload contract is invalid".to_string());
    }
    if platform_plugin_payload_digest(&snapshot.payload)? != snapshot.digest {
        return Err("control-plane snapshot digest does not match canonical bytes".to_string());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::sync::{
        atomic::{AtomicU64, Ordering},
        Arc as StdArc, Mutex,
    };

    use agistack_adapters_device::SqliteCheckpointStore;
    use agistack_adapters_local_tools::LocalToolHost;
    use agistack_adapters_wasmtime::SCORE_V1_WAT;
    use axum::{
        body::Body,
        extract::State,
        http::{header::AUTHORIZATION, StatusCode},
        routing::{get, post},
        Json, Router,
    };
    use serde_json::json;
    use std::io::Write;
    use tokio::net::TcpListener;
    use tower::ServiceExt;
    use uuid::Uuid;
    use zip::ZipWriter;

    use super::super::auth_context::ContextSwitchRequest;
    use super::super::mcp_supervisor::{McpServerDefinitionInput, McpTransport};
    use super::*;
    use crate::local_runtime::LocalRuntimeState;
    use crate::trusted_session::{
        TrustedSessionBroker, TrustedSessionCredentialKind, TrustedSessionRecord,
        TrustedSessionRuntimeMode, TrustedSessionStore, TrustedSessionStoreError,
    };

    #[derive(Default)]
    struct MemoryTrustedSessionStore {
        value: Mutex<Option<String>>,
    }

    impl TrustedSessionStore for MemoryTrustedSessionStore {
        fn save_raw(&self, value: &str) -> Result<(), TrustedSessionStoreError> {
            *self.value.lock().expect("trusted session lock") = Some(value.to_string());
            Ok(())
        }
        fn load_raw(&self) -> Result<Option<String>, TrustedSessionStoreError> {
            Ok(self.value.lock().expect("trusted session lock").clone())
        }
        fn clear_raw(&self) -> Result<(), TrustedSessionStoreError> {
            *self.value.lock().expect("trusted session lock") = None;
            Ok(())
        }
    }

    #[derive(Clone)]
    struct ControlPlaneState {
        snapshot: StdArc<Mutex<Value>>,
        observations: StdArc<Mutex<Vec<(String, Value)>>>,
        calls: StdArc<AtomicU64>,
        disconnected: StdArc<std::sync::atomic::AtomicBool>,
        failures: StdArc<AtomicU64>,
        oci_manifest: StdArc<Mutex<Vec<u8>>>,
        oci_layer: StdArc<Mutex<Vec<u8>>>,
    }

    fn state() -> StdArc<LocalRuntimeState> {
        let root = std::env::temp_dir().join(format!("plugin-sync-{}", Uuid::new_v4()));
        let tool_host = LocalToolHost::new(&root).expect("tool host");
        let checkpoints = StdArc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
        let session_store = crate::local_runtime::session_store::DesktopSessionStore::in_memory()
            .expect("session store");
        StdArc::new(
            LocalRuntimeState::new(
                root,
                tool_host,
                checkpoints,
                "launch-token".to_string(),
                session_store,
            )
            .expect("runtime state"),
        )
    }

    async fn control_plane(snapshot: Value) -> (Url, TrustedSessionBroker, ControlPlaneState) {
        let store = StdArc::new(MemoryTrustedSessionStore::default());
        let broker = TrustedSessionBroker::new(store);
        let control = ControlPlaneState {
            snapshot: StdArc::new(Mutex::new(snapshot)),
            observations: StdArc::new(Mutex::new(Vec::new())),
            calls: StdArc::new(AtomicU64::new(0)),
            disconnected: StdArc::new(std::sync::atomic::AtomicBool::new(false)),
            failures: StdArc::new(AtomicU64::new(0)),
            oci_manifest: StdArc::new(Mutex::new(Vec::new())),
            oci_layer: StdArc::new(Mutex::new(Vec::new())),
        };
        let router_state = control.clone();
        async fn snapshot_endpoint(State(control): State<ControlPlaneState>) -> Json<Value> {
            if control.disconnected.load(Ordering::Acquire) {
                control.failures.fetch_add(1, Ordering::Release);
                return Json(json!({"detail": "control plane disconnected"}));
            }
            control.snapshot.lock().expect("snapshot").clone().into()
        }
        async fn receipt_endpoint(
            State(control): State<ControlPlaneState>,
            authorization: axum::http::HeaderMap,
            Json(body): Json<Value>,
        ) -> StatusCode {
            control.observations.lock().expect("observations").push((
                authorization
                    .get(AUTHORIZATION)
                    .and_then(|value| value.to_str().ok())
                    .unwrap_or_default()
                    .to_string(),
                body,
            ));
            control.calls.fetch_add(1, Ordering::Release);
            StatusCode::OK
        }
        async fn oci_manifest_endpoint(State(control): State<ControlPlaneState>) -> Vec<u8> {
            control.oci_manifest.lock().expect("OCI manifest").clone()
        }
        async fn oci_blob_endpoint(State(control): State<ControlPlaneState>) -> Vec<u8> {
            control.oci_layer.lock().expect("OCI layer").clone()
        }
        let app = Router::new()
            .route("/api/v1/platform-plugins/snapshot", get(snapshot_endpoint))
            .route(
                "/api/v1/platform-plugins/data-plane-state",
                post(receipt_endpoint),
            )
            .route("/v2/plugins/manifests/:digest", get(oci_manifest_endpoint))
            .route("/v2/plugins/blobs/:digest", get(oci_blob_endpoint))
            .with_state(router_state);
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind control plane");
        let address = listener.local_addr().expect("control-plane address");
        tokio::spawn(async move {
            axum::serve(listener, app).await.expect("control plane");
        });
        let url = Url::parse(&format!("http://{address}/api/v1")).expect("base URL");
        broker
            .save(cloud_record(url.clone()))
            .expect("save trusted cloud record");
        (url, broker, control)
    }

    async fn wait_until(deadline_ms: u64, predicate: impl Fn() -> bool) -> bool {
        let deadline = std::time::Instant::now() + Duration::from_millis(deadline_ms);
        while std::time::Instant::now() < deadline {
            if predicate() {
                return true;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
        predicate()
    }

    fn cloud_record(url: Url) -> TrustedSessionRecord {
        TrustedSessionRecord {
            version: 1,
            api_base_url: url.to_string(),
            runtime_mode: TrustedSessionRuntimeMode::Cloud,
            credential_kind: TrustedSessionCredentialKind::CloudBearer,
            credential: "cloud-session".to_string(),
            expires_at: None,
        }
    }

    #[tokio::test]
    async fn background_poller_backs_off_reconnects_and_stops_cleanly() {
        let runtime = state();
        let digest = "f".repeat(64);
        let initial = snapshot(4, &digest, "python-trusted", "vault://plugins/poller");
        let (_url, broker, control) = control_plane(initial).await;
        control.disconnected.store(true, Ordering::Release);

        let reconciler = PlatformPluginControlPlaneReconciler::start_with_intervals(
            runtime.clone(),
            broker.clone(),
            Duration::from_millis(20),
            Duration::from_millis(5),
        );
        assert!(
            wait_until(500, || control.failures.load(Ordering::Acquire) >= 1).await,
            "poller must observe the disconnected interval"
        );
        control.disconnected.store(false, Ordering::Release);
        assert!(
            wait_until(500, || control.calls.load(Ordering::Acquire) >= 1).await,
            "reconnected poller must sync"
        );
        let connection = runtime.session_store.connection().expect("connection");
        let record = plugin_snapshots::read_apply_record(&connection)
            .expect("record")
            .expect("row");
        assert_eq!(record.status, "ack");
        drop(connection);

        reconciler.shutdown().await;
        let calls_after_shutdown = control.calls.load(Ordering::Acquire);
        tokio::time::sleep(Duration::from_millis(50)).await;
        assert!(control.calls.load(Ordering::Acquire) <= calls_after_shutdown + 1);
    }

    #[tokio::test]
    async fn untrusted_wasm_artifact_is_downloaded_verified_and_activated() {
        let runtime = state();
        let (url, broker, control) = control_plane(json!({})).await;
        let registry = url.as_str().trim_end_matches("/api/v1").to_string();
        let mut plugin = json!({
            "schema_version": 1,
            "id": "third-party-tool",
            "version": "1.0.0",
            "runtime": "wasm",
            "trust": "signed",
            "provides": [{
                "kind": "tool",
                "id": "demo",
                "contract": "tool:demo",
                "permissions": ["tools.execute"]
            }],
            "activation": {"default_scope": "tenant", "restart_policy": "process-boundary"},
            "config": {}
        });
        let runtime_bytes = SCORE_V1_WAT.as_bytes().to_vec();
        let archive = wasm_package_archive(&plugin, &runtime_bytes);
        let layer_digest = sha256_hex(&archive);
        let oci_manifest = serde_json::to_vec(&json!({
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "artifactType": "application/vnd.memstack.plugin.v1",
            "layers": [{
                "mediaType": "application/vnd.memstack.plugin.bundle.v1+zip",
                "digest": format!("sha256:{layer_digest}"),
                "size": archive.len()
            }]
        }))
        .expect("OCI manifest");
        let manifest_digest = sha256_hex(&oci_manifest);
        plugin["config"]["artifact"] = json!({
            "registry": registry,
            "repository": "plugins",
            "manifest_sha256": manifest_digest,
            "layer_sha256": layer_digest
        });
        *control.oci_manifest.lock().expect("OCI manifest") = oci_manifest;
        *control.oci_layer.lock().expect("OCI layer") = archive.clone();
        let mut snapshot_payload = json!({
            "schema_version": 1,
            "profile_id": "desktop-default",
            "plugins": [plugin],
            "digest": Value::Null
        });
        let snapshot_digest =
            platform_plugin_payload_digest(&snapshot_payload).expect("snapshot digest");
        snapshot_payload["digest"] = json!(snapshot_digest);
        *control.snapshot.lock().expect("snapshot") = json!({
            "version": 7,
            "nonce": "nonce-7",
            "profile_id": "desktop-default",
            "digest": snapshot_digest,
            "payload": snapshot_payload
        });

        reconcile_once(&runtime, &broker)
            .await
            .expect("untrusted wasm reconcile");
        runtime
            .session_store
            .seed_test_session("desktop-session")
            .expect("desktop session");

        let connection = runtime.session_store.connection().expect("connection");
        let record = plugin_snapshots::read_apply_record(&connection)
            .expect("record")
            .expect("row");
        assert_eq!(record.status, "ack");
        let active = plugin_snapshots::read_active_plugins(&connection, &snapshot_digest)
            .expect("active plugins");
        assert_eq!(active[0].plugin_id, "third-party-tool");
        let artifact =
            plugin_snapshots::read_runtime_artifact(&connection, "third-party-tool", &layer_digest)
                .expect("artifact")
                .expect("stored artifact");
        assert_eq!(artifact.bytes, runtime_bytes);
        {
            let observations = control.observations.lock().expect("observations");
            assert_eq!(observations.len(), 1);
            assert_eq!(observations[0].1["status"], "ack");
        }
        drop(connection);

        let invocation =
            crate::local_runtime::workspace_core_bridge::platform_plugin_router(runtime.clone())
                .with_state(runtime.clone())
                .oneshot(
                    axum::http::Request::builder()
                        .method("POST")
                        .uri("/api/v1/platform-plugins/tools/invoke")
                        .header(AUTHORIZATION, "Bearer desktop-session")
                        .header("content-type", "application/json")
                        .body(Body::from(
                            json!({
                                "plugin_id": "third-party-tool",
                                "tool_id": "demo",
                                "input": {"text": "hello"}
                            })
                            .to_string(),
                        ))
                        .expect("tool invocation request"),
                )
                .await
                .expect("tool invocation response");
        assert_eq!(invocation.status(), StatusCode::OK);
        let invocation_body = axum::body::to_bytes(invocation.into_body(), usize::MAX)
            .await
            .expect("tool invocation body");
        let invocation: Value = serde_json::from_slice(&invocation_body).expect("tool result");
        assert_eq!(invocation["tool"], "demo");
        assert_eq!(invocation["score"], 22);

        let mut removal_payload = json!({
            "schema_version": 1,
            "profile_id": "desktop-default",
            "plugins": [],
            "digest": Value::Null
        });
        let removal_digest =
            platform_plugin_payload_digest(&removal_payload).expect("removal digest");
        removal_payload["digest"] = json!(removal_digest);
        *control.snapshot.lock().expect("snapshot") = json!({
            "version": 8,
            "nonce": "nonce-8",
            "profile_id": "desktop-default",
            "digest": removal_digest,
            "payload": removal_payload
        });
        reconcile_once(&runtime, &broker)
            .await
            .expect("untrusted wasm removal");
        let connection = runtime.session_store.connection().expect("connection");
        assert!(
            plugin_snapshots::read_active_plugins(&connection, &removal_digest)
                .expect("removed active plugins")
                .is_empty()
        );
        assert!(plugin_snapshots::read_runtime_artifact(
            &connection,
            "third-party-tool",
            &layer_digest
        )
        .expect("removed artifact")
        .is_none());
    }

    #[tokio::test]
    async fn untrusted_mcp_package_is_registered_and_uninstalled_atomically() {
        let runtime = state();
        let (url, broker, control) = control_plane(json!({})).await;
        let registry = url.as_str().trim_end_matches("/api/v1").to_string();
        let mut plugin = json!({
            "schema_version": 1,
            "id": "third-party-mcp",
            "version": "1.0.0",
            "runtime": "mcp",
            "trust": "signed",
            "provides": [{
                "kind": "tool",
                "id": "echo",
                "contract": "tool:echo",
                "permissions": ["tools.execute"]
            }],
            "activation": {"default_scope": "tenant", "restart_policy": "process-boundary"},
            "config": {}
        });
        let script = write_platform_plugin_mcp_server(&runtime);
        let python = python_executable();
        let runtime_definition = json!({
            "transport": "stdio",
            "command": [python.to_string_lossy(), script.to_string_lossy()],
            "cwd": ".",
            "enabled": true
        });
        let runtime_bytes = serde_json::to_vec(&runtime_definition).expect("MCP runtime");
        let archive = plugin_package_archive(&plugin, "runtime/plugin.json", &runtime_bytes);
        let layer_digest = sha256_hex(&archive);
        let oci_manifest = serde_json::to_vec(&json!({
            "schemaVersion": 2,
            "mediaType": OCI_MANIFEST_MEDIA_TYPE,
            "artifactType": MEMSTACK_ARTIFACT_TYPE,
            "layers": [{
                "mediaType": MEMSTACK_LAYER_TYPE,
                "digest": format!("sha256:{layer_digest}"),
                "size": archive.len()
            }]
        }))
        .expect("OCI manifest");
        let manifest_digest = sha256_hex(&oci_manifest);
        plugin["config"]["artifact"] = json!({
            "registry": registry,
            "repository": "plugins",
            "manifest_sha256": manifest_digest,
            "layer_sha256": layer_digest
        });
        *control.oci_manifest.lock().expect("OCI manifest") = oci_manifest;
        *control.oci_layer.lock().expect("OCI layer") = archive;
        let (snapshot, _) = control_snapshot_with_plugin(9, plugin.clone());
        *control.snapshot.lock().expect("snapshot") = snapshot;

        runtime
            .session_store
            .seed_test_session("desktop-session")
            .expect("desktop session");
        reconcile_once(&runtime, &broker)
            .await
            .expect("MCP activate");

        let scope = McpScope {
            tenant_id: "local".to_string(),
            project_id: "local-project".to_string(),
        };
        let server = runtime
            .mcp_supervisor
            .server_by_name(&scope, "platform-plugin-third-party-mcp")
            .expect("MCP lookup")
            .expect("MCP server registered");
        assert!(server
            .command
            .starts_with(&[python.to_string_lossy().to_string()]));

        let authenticated = runtime
            .session_store
            .validate_session_credential(
                "desktop-session",
                chrono::Utc::now().timestamp_millis() + 1_000,
            )
            .expect("validate desktop session")
            .expect("authenticated context");
        runtime
            .session_store
            .switch_workspace_context(
                &authenticated,
                &ContextSwitchRequest {
                    tenant_id: "northstar".to_string(),
                    project_id: "product-strategy".to_string(),
                    expected_revision: 0,
                    idempotency_key: "platform-plugin-scope-switch".to_string(),
                },
                1_800_000_000_001,
            )
            .expect("switch active workspace");
        reconcile_once(&runtime, &broker)
            .await
            .expect("move MCP runtime to active workspace");
        let switched_scope = McpScope {
            tenant_id: "northstar".to_string(),
            project_id: "product-strategy".to_string(),
        };
        assert!(runtime
            .mcp_supervisor
            .server_by_name(&scope, "platform-plugin-third-party-mcp")
            .expect("old MCP scope lookup")
            .is_none());
        assert!(runtime
            .mcp_supervisor
            .server_by_name(&switched_scope, "platform-plugin-third-party-mcp")
            .expect("switched MCP scope lookup")
            .is_some());
        runtime
            .mcp_supervisor
            .create_server(
                &switched_scope,
                McpServerDefinitionInput {
                    name: "platform-plugin-unmanaged".to_string(),
                    description: Some("Manually-created scope probe".to_string()),
                    transport: McpTransport::Stdio,
                    command: vec!["/bin/true".to_string()],
                    cwd: None,
                    vault_env_refs: BTreeMap::new(),
                    enabled: true,
                },
                "unmanaged-platform-plugin-scope-probe",
            )
            .expect("create unmanaged MCP server");

        let invocation =
            crate::local_runtime::workspace_core_bridge::platform_plugin_router(runtime.clone())
                .with_state(runtime.clone())
                .oneshot(
                    axum::http::Request::builder()
                        .method("POST")
                        .uri("/api/v1/platform-plugins/tools/invoke")
                        .header(AUTHORIZATION, "Bearer desktop-session")
                        .header("content-type", "application/json")
                        .body(Body::from(
                            json!({
                                "plugin_id": "third-party-mcp",
                                "tool_id": "echo",
                                "input": {"message": "hello"}
                            })
                            .to_string(),
                        ))
                        .expect("MCP invocation request"),
                )
                .await
                .expect("MCP invocation response");
        assert_eq!(invocation.status(), StatusCode::OK);
        let invocation_body = axum::body::to_bytes(invocation.into_body(), usize::MAX)
            .await
            .expect("MCP invocation body");
        let invocation: Value = serde_json::from_slice(&invocation_body).expect("MCP result");
        assert_eq!(invocation["content"][0]["type"], "text");
        assert_eq!(invocation["content"][0]["text"], r#"{"message": "hello"}"#);

        let oversized_invocation =
            crate::local_runtime::workspace_core_bridge::platform_plugin_router(runtime.clone())
                .with_state(runtime.clone())
                .oneshot(
                    axum::http::Request::builder()
                        .method("POST")
                        .uri("/api/v1/platform-plugins/tools/invoke")
                        .header(AUTHORIZATION, "Bearer desktop-session")
                        .header("content-type", "application/json")
                        .body(Body::from(
                            json!({
                                "plugin_id": "third-party-mcp",
                                "tool_id": "echo",
                                "input": {"message": "x".repeat(300 * 1024)}
                            })
                            .to_string(),
                        ))
                        .expect("oversized MCP invocation request"),
                )
                .await
                .expect("oversized MCP invocation response");
        assert_eq!(oversized_invocation.status(), StatusCode::CONFLICT);
        let oversized_body = axum::body::to_bytes(oversized_invocation.into_body(), usize::MAX)
            .await
            .expect("oversized MCP invocation body");
        let oversized: Value =
            serde_json::from_slice(&oversized_body).expect("oversized MCP result");
        assert_eq!(
            oversized["detail"],
            "platform plugin MCP request exceeds its input quota"
        );

        plugin["config"]["artifact"]["layer_sha256"] = json!("0".repeat(64));
        let (bad_snapshot, _) = control_snapshot_with_plugin(10, plugin.clone());
        *control.snapshot.lock().expect("snapshot") = bad_snapshot;
        let bad_error = reconcile_once(&runtime, &broker)
            .await
            .expect_err("MCP runtime artifact must fail closed");
        assert!(bad_error.contains("requested layer digest does not match OCI manifest"));
        assert!(runtime
            .mcp_supervisor
            .server_by_name(&switched_scope, "platform-plugin-third-party-mcp")
            .expect("last-good MCP lookup")
            .is_some());
        plugin["config"]["artifact"]["layer_sha256"] = json!(layer_digest);

        let mut removal_payload = json!({
            "schema_version": 1,
            "profile_id": "desktop-default",
            "plugins": [],
            "digest": Value::Null
        });
        let removal_digest =
            platform_plugin_payload_digest(&removal_payload).expect("removal digest");
        removal_payload["digest"] = json!(removal_digest);
        *control.snapshot.lock().expect("snapshot") = json!({
            "version": 11,
            "nonce": "nonce-11",
            "profile_id": "desktop-default",
            "digest": removal_digest,
            "payload": removal_payload
        });
        reconcile_once(&runtime, &broker).await.expect("MCP remove");
        assert!(runtime
            .mcp_supervisor
            .server_by_name(&switched_scope, "platform-plugin-third-party-mcp")
            .expect("MCP removed lookup")
            .is_none());
        assert!(runtime
            .mcp_supervisor
            .server_by_name(&switched_scope, "platform-plugin-unmanaged")
            .expect("unmanaged MCP lookup")
            .is_some());
        runtime
            .mcp_supervisor
            .remove_platform_plugin_server(&switched_scope, "unmanaged")
            .expect("remove unmanaged MCP server");
        {
            let connection = runtime.session_store.connection().expect("connection");
            assert!(plugin_snapshots::read_runtime_artifact(
                &connection,
                "third-party-mcp",
                &layer_digest
            )
            .expect("removed MCP artifact")
            .is_none());
        }
    }

    fn python_executable() -> std::path::PathBuf {
        std::env::split_paths(&std::env::var_os("PATH").expect("test PATH"))
            .map(|entry| entry.join("python3"))
            .find(|candidate| candidate.is_file())
            .and_then(|candidate| candidate.canonicalize().ok())
            .expect("python3 executable")
    }

    fn write_platform_plugin_mcp_server(runtime: &StdArc<LocalRuntimeState>) -> std::path::PathBuf {
        let root = runtime
            .workspace_root
            .lock()
            .expect("workspace root")
            .clone();
        std::fs::create_dir_all(&root).expect("MCP workspace root");
        let script = root.join("platform_plugin_mcp.py");
        std::fs::write(
            &script,
            r#"import json
import sys

for raw_line in sys.stdin:
    request = json.loads(raw_line)
    method = request.get("method")
    request_id = request.get("id")
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "platform-plugin-mcp", "version": "1.0.0"},
        }
    elif method == "tools/call":
        arguments = request.get("params", {}).get("arguments", {})
        result = {
            "content": [{"type": "text", "text": json.dumps(arguments, sort_keys=True)}],
            "isError": False,
        }
    else:
        result = None
    if result is None:
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "method not found"},
        }
    else:
        response = {"jsonrpc": "2.0", "id": request_id, "result": result}
    sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
    sys.stdout.flush()
"#,
        )
        .expect("MCP server script");
        script
    }

    #[tokio::test]
    async fn untrusted_frontend_package_is_served_and_uninstalled_atomically() {
        let runtime = state();
        let (url, broker, control) = control_plane(json!({})).await;
        let registry = url.as_str().trim_end_matches("/api/v1").to_string();
        let mut plugin = json!({
            "schema_version": 1,
            "id": "third-party-ui",
            "version": "1.0.0",
            "runtime": "frontend",
            "trust": "signed",
            "provides": [{
                "kind": "ui_renderer",
                "id": "tool_result_renderer",
                "contract": "ui_renderer:tool-result",
                "permissions": ["ui.render"]
            }],
            "activation": {"default_scope": "tenant", "restart_policy": "process-boundary"},
            "config": {}
        });
        let runtime_definition = json!({
            "html": "<main id=\"plugin-module\">signed module</main>",
            "slots": ["tool_result_renderer"]
        });
        let runtime_bytes = serde_json::to_vec(&runtime_definition).expect("frontend runtime");
        let archive = plugin_package_archive(&plugin, "runtime/plugin.json", &runtime_bytes);
        let layer_digest = sha256_hex(&archive);
        let oci_manifest = serde_json::to_vec(&json!({
            "schemaVersion": 2,
            "mediaType": OCI_MANIFEST_MEDIA_TYPE,
            "artifactType": MEMSTACK_ARTIFACT_TYPE,
            "layers": [{
                "mediaType": MEMSTACK_LAYER_TYPE,
                "digest": format!("sha256:{layer_digest}"),
                "size": archive.len()
            }]
        }))
        .expect("OCI manifest");
        let manifest_digest = sha256_hex(&oci_manifest);
        plugin["config"]["artifact"] = json!({
            "registry": registry,
            "repository": "plugins",
            "manifest_sha256": manifest_digest,
            "layer_sha256": layer_digest
        });
        *control.oci_manifest.lock().expect("OCI manifest") = oci_manifest;
        *control.oci_layer.lock().expect("OCI layer") = archive;
        let (snapshot, _) = control_snapshot_with_plugin(11, plugin);
        *control.snapshot.lock().expect("snapshot") = snapshot;

        reconcile_once(&runtime, &broker)
            .await
            .expect("frontend activate");
        runtime
            .session_store
            .seed_test_session("desktop-session")
            .expect("desktop session");
        let module_response =
            crate::local_runtime::workspace_core_bridge::platform_plugin_router(runtime.clone())
                .with_state(runtime.clone())
                .oneshot(
                    axum::http::Request::builder()
                        .method("GET")
                        .uri("/api/v1/platform-plugins/frontend/third-party-ui/module")
                        .header(AUTHORIZATION, "Bearer desktop-session")
                        .body(Body::empty())
                        .expect("frontend module request"),
                )
                .await
                .expect("frontend module response");
        assert_eq!(module_response.status(), StatusCode::OK);
        let module_body = axum::body::to_bytes(module_response.into_body(), usize::MAX)
            .await
            .expect("frontend module body");
        let module: Value = serde_json::from_slice(&module_body).expect("frontend module");
        assert_eq!(module["plugin_id"], "third-party-ui");
        assert_eq!(module["digest"], layer_digest);
        assert_eq!(module["trust"], "signed");
        assert_eq!(
            module["html"],
            "<main id=\"plugin-module\">signed module</main>"
        );

        let mut removal_payload = json!({
            "schema_version": 1,
            "profile_id": "desktop-default",
            "plugins": [],
            "digest": Value::Null
        });
        let removal_digest =
            platform_plugin_payload_digest(&removal_payload).expect("removal digest");
        removal_payload["digest"] = json!(removal_digest);
        *control.snapshot.lock().expect("snapshot") = json!({
            "version": 12,
            "nonce": "nonce-12",
            "profile_id": "desktop-default",
            "digest": removal_digest,
            "payload": removal_payload
        });
        reconcile_once(&runtime, &broker)
            .await
            .expect("frontend remove");
        let removed_response =
            crate::local_runtime::workspace_core_bridge::platform_plugin_router(runtime.clone())
                .with_state(runtime.clone())
                .oneshot(
                    axum::http::Request::builder()
                        .method("GET")
                        .uri("/api/v1/platform-plugins/frontend/third-party-ui/module")
                        .header(AUTHORIZATION, "Bearer desktop-session")
                        .body(Body::empty())
                        .expect("removed frontend module request"),
                )
                .await
                .expect("removed frontend module response");
        assert_eq!(removed_response.status(), StatusCode::NOT_FOUND);
        let connection = runtime.session_store.connection().expect("connection");
        assert!(plugin_snapshots::read_runtime_artifact(
            &connection,
            "third-party-ui",
            &layer_digest
        )
        .expect("removed frontend artifact")
        .is_none());
    }

    fn snapshot(version: u64, digest: &str, runtime: &str, credential: &str) -> Value {
        let mut payload = json!({
            "version": version,
            "nonce": format!("nonce-{version}"),
            "profile_id": "desktop-default",
            "digest": digest,
            "payload": {
                "schema_version": 1,
                "profile_id": "desktop-default",
                "plugins": [{
                    "schema_version": 1,
                    "id": "workspace-runtime",
                    "version": "1.0.0",
                    "runtime": runtime,
                    "trust": "builtin",
                    "provides": [{
                        "kind": "hook",
                        "id": "before_response",
                        "contract": "hook:before_response",
                        "permissions": []
                    }],
                    "config": {"credential_ref": credential}
                }],
                "digest": digest
            }
        });
        let canonical_digest = platform_plugin_payload_digest(&payload["payload"])
            .expect("canonical test snapshot digest");
        payload["digest"] = json!(canonical_digest);
        payload["payload"]["digest"] = json!(canonical_digest);
        payload
    }

    fn sha256_hex(bytes: &[u8]) -> String {
        let digest = Sha256::digest(bytes);
        digest.iter().map(|byte| format!("{byte:02x}")).collect()
    }

    #[test]
    fn control_plane_snapshot_digest_must_match_canonical_bytes() {
        let mut snapshot = snapshot(4, "ignored", "python-trusted", "vault://plugins/test");
        snapshot["digest"] = json!("0".repeat(64));
        snapshot["payload"]["digest"] = json!("0".repeat(64));
        let snapshot =
            serde_json::from_value::<ControlPlaneSnapshot>(snapshot).expect("test snapshot");

        let error = validate_snapshot(&snapshot).expect_err("digest must be canonical");

        assert_eq!(
            error,
            "control-plane snapshot digest does not match canonical bytes"
        );
    }

    fn plugin_package_archive(plugin: &Value, runtime_name: &str, runtime: &[u8]) -> Vec<u8> {
        let manifest = serde_json::to_vec(plugin).expect("plugin manifest JSON");
        let checksums = json!({
            "plugin.manifest.json": sha256_hex(&manifest),
            runtime_name: sha256_hex(runtime),
        });
        let checksums = serde_json::to_vec(&checksums).expect("checksum JSON");
        let mut archive = ZipWriter::new(Cursor::new(Vec::new()));
        archive
            .start_file(
                "plugin.manifest.json",
                zip::write::SimpleFileOptions::default(),
            )
            .expect("manifest entry");
        archive.write_all(&manifest).expect("manifest bytes");
        archive
            .start_file(runtime_name, zip::write::SimpleFileOptions::default())
            .expect("runtime entry");
        archive.write_all(runtime).expect("runtime bytes");
        archive
            .start_file("checksums.json", zip::write::SimpleFileOptions::default())
            .expect("checksum entry");
        archive.write_all(&checksums).expect("checksum bytes");
        archive.finish().expect("plugin archive").into_inner()
    }

    fn wasm_package_archive(plugin: &Value, wasm: &[u8]) -> Vec<u8> {
        plugin_package_archive(plugin, "runtime/plugin.wasm", wasm)
    }

    fn control_snapshot_with_plugin(version: u64, plugin: Value) -> (Value, String) {
        let mut payload = json!({
            "schema_version": 1,
            "profile_id": "desktop-default",
            "plugins": [plugin],
            "digest": Value::Null
        });
        let digest = platform_plugin_payload_digest(&payload).expect("snapshot digest");
        payload["digest"] = json!(digest);
        let snapshot = json!({
            "version": version,
            "nonce": format!("nonce-{version}"),
            "profile_id": "desktop-default",
            "digest": digest,
            "payload": payload
        });
        (snapshot, digest)
    }

    #[tokio::test]
    async fn full_resync_survives_disconnect_and_converges_to_new_snapshot() {
        let runtime = state();
        let first = snapshot(4, "ignored", "python-trusted", "vault://plugins/one");
        let first_digest = first["digest"].as_str().expect("first digest").to_string();
        let (url, broker, control) = control_plane(first.clone()).await;
        reconcile_once(&runtime, &broker).await.expect("first sync");

        control.disconnected.store(true, Ordering::Release);
        let error = reconcile_once(&runtime, &broker)
            .await
            .expect_err("disconnected");
        assert!(error.contains("control-plane"));
        {
            let connection = runtime.session_store.connection().expect("connection");
            let record = plugin_snapshots::read_apply_record(&connection)
                .expect("record")
                .expect("row");
            assert_eq!(
                record.applied_digest.as_deref(),
                Some(first_digest.as_str())
            );
        }
        broker
            .save(cloud_record(url))
            .expect("save reconnected record");
        control.disconnected.store(false, Ordering::Release);
        *control.snapshot.lock().expect("snapshot") =
            snapshot(5, "ignored", "python-trusted", "vault://plugins/two");
        let second_digest = control.snapshot.lock().expect("snapshot")["digest"]
            .as_str()
            .expect("second digest")
            .to_string();
        reconcile_once(&runtime, &broker)
            .await
            .expect("second sync");
        {
            let connection = runtime.session_store.connection().expect("connection");
            let record = plugin_snapshots::read_apply_record(&connection)
                .expect("record")
                .expect("row");
            assert_eq!(
                record.applied_digest.as_deref(),
                Some(second_digest.as_str())
            );
            let active = plugin_snapshots::read_active_plugins(&connection, &second_digest)
                .expect("active plugins");
            assert_eq!(active.len(), 1);
        }
        assert_eq!(control.calls.load(Ordering::Acquire), 2);
        assert!(control
            .observations
            .lock()
            .expect("observations")
            .iter()
            .all(|(authorization, _)| authorization == "Bearer cloud-session"));
    }

    #[tokio::test]
    async fn preparation_failure_posts_nack_and_keeps_last_good() {
        let runtime = state();
        let good = snapshot(4, "ignored", "python-trusted", "vault://plugins/good");
        let good_digest = good["digest"].as_str().expect("good digest").to_string();
        let (_url, broker, control) = control_plane(good).await;
        reconcile_once(&runtime, &broker).await.expect("good sync");

        *control.snapshot.lock().expect("snapshot") =
            snapshot(5, "ignored", "wasm", "vault://plugins/bad");
        let error = reconcile_once(&runtime, &broker)
            .await
            .expect_err("wasm artifact is unavailable");
        assert!(error.contains("runtime artifact"));
        let connection = runtime.session_store.connection().expect("connection");
        let record = plugin_snapshots::read_apply_record(&connection)
            .expect("record")
            .expect("row");
        assert_eq!(record.status, "nack");
        assert_eq!(record.applied_digest.as_deref(), Some(good_digest.as_str()));
        let observations = control.observations.lock().expect("observations");
        assert_eq!(observations[1].1["status"], "nack");
        assert_eq!(observations[1].1["applied_version"], 4);
    }
}
