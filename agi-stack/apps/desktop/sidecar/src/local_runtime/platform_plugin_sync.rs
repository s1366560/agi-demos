//! Background reconciliation from the Python plugin control plane.

use std::{
    sync::{Arc, Mutex},
    time::Duration,
};

use rusqlite::Connection;
use serde::Deserialize;
use serde_json::Value;
use tokio::sync::watch;
use url::Url;

use crate::{
    plugin_snapshots::{self, RequestedPluginSnapshot},
    trusted_session::{
        TrustedSessionBroker, TrustedSessionCredentialKind, TrustedSessionRecord,
        TrustedSessionRuntimeMode,
    },
};

use super::LocalRuntimeState;

const SUCCESS_INTERVAL: Duration = Duration::from_secs(30);
const INITIAL_ERROR_INTERVAL: Duration = Duration::from_secs(2);
const MAX_ERROR_INTERVAL: Duration = Duration::from_secs(60);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_SNAPSHOT_BYTES: usize = 4 * 1024 * 1024;

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

    let receipt = prepare_local_snapshot(state, &snapshot)?;
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

type ControlPlaneReceipt = Option<(u64, u64, String, String, Option<String>)>;

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
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::sync::{
        atomic::{AtomicU64, Ordering},
        Arc as StdArc,
    };

    use agistack_adapters_device::SqliteCheckpointStore;
    use agistack_adapters_local_tools::LocalToolHost;
    use axum::{
        extract::State,
        http::{header::AUTHORIZATION, StatusCode},
        routing::{get, post},
        Json, Router,
    };
    use serde_json::json;
    use tokio::net::TcpListener;
    use uuid::Uuid;

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
        let app = Router::new()
            .route("/api/v1/platform-plugins/snapshot", get(snapshot_endpoint))
            .route(
                "/api/v1/platform-plugins/data-plane-state",
                post(receipt_endpoint),
            )
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

    fn snapshot(version: u64, digest: &str, runtime: &str, credential: &str) -> Value {
        json!({
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
        })
    }

    #[tokio::test]
    async fn full_resync_survives_disconnect_and_converges_to_new_snapshot() {
        let runtime = state();
        let first_digest = "a".repeat(64);
        let first = snapshot(4, &first_digest, "python-trusted", "vault://plugins/one");
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
        let second_digest = "b".repeat(64);
        *control.snapshot.lock().expect("snapshot") =
            snapshot(5, &second_digest, "python-trusted", "vault://plugins/two");
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
        let good_digest = "c".repeat(64);
        let good = snapshot(4, &good_digest, "python-trusted", "vault://plugins/good");
        let (_url, broker, control) = control_plane(good).await;
        reconcile_once(&runtime, &broker).await.expect("good sync");

        let bad_digest = "d".repeat(64);
        *control.snapshot.lock().expect("snapshot") =
            snapshot(5, &bad_digest, "wasm", "vault://plugins/bad");
        let error = reconcile_once(&runtime, &broker)
            .await
            .expect_err("wasm artifact is unavailable");
        assert!(error.contains("requires an installed runtime artifact"));
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
