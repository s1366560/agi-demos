//! Protocol-v2 background reconciliation from the Python control plane.

use std::{sync::Arc, time::Duration};

use agistack_plugin_host::protocol_v2::ProfileSnapshotV2;
use agistack_plugin_host::{
    desktop_sidecar_host_definition_v2, desktop_sidecar_http_routes_definition_v2,
    parse_control_plane_distribution_v2, parse_profile_snapshot_v2, ControlPlaneDistributionV2,
    DataPlaneTargetV2, LoaderV2, PluginSnapshotReconcilerV2, SnapshotApplyReceiptV2,
    SnapshotPreparationV2,
};
use futures_util::StreamExt;
use serde::Serialize;
use sha2::{Digest, Sha256};
use tokio::sync::watch;
use url::Url;

use crate::{
    plugin_snapshots_v2,
    trusted_session::{
        TrustedSessionBroker, TrustedSessionCredentialKind, TrustedSessionRecord,
        TrustedSessionRuntimeMode,
    },
};

use super::LocalRuntimeState;

const DATA_PLANE_ID: &str = "desktop-sidecar-v2";
const SUCCESS_INTERVAL: Duration = Duration::from_secs(30);
const INITIAL_ERROR_INTERVAL: Duration = Duration::from_secs(2);
const MAX_ERROR_INTERVAL: Duration = Duration::from_secs(60);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_DISTRIBUTION_BYTES: usize = 4 * 1024 * 1024;
const LOCAL_BOOTSTRAP_PROFILE_V2: &str =
    include_str!("../../../../../../shared/profiles/memstack-default-bootstrap.v2.json");

pub(super) struct CloudAuthorityV2 {
    pub(super) base_url: Url,
    pub(super) credential: String,
    fingerprint: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum DesktopAuthoritySourceV2 {
    Local,
    Cloud(String),
}

impl DesktopAuthoritySourceV2 {
    fn fingerprint(&self) -> Option<&str> {
        match self {
            Self::Local => None,
            Self::Cloud(fingerprint) => Some(fingerprint),
        }
    }
}

/// Owns the protocol-v2 desktop-sidecar polling task and its shutdown signal.
#[derive(Debug)]
pub(crate) struct PlatformPluginControlPlaneReconcilerV2 {
    shutdown: watch::Sender<bool>,
    task: tokio::task::JoinHandle<()>,
}

impl PlatformPluginControlPlaneReconcilerV2 {
    pub(super) async fn start(
        state: Arc<LocalRuntimeState>,
        trusted_sessions: TrustedSessionBroker,
    ) -> Result<Self, String> {
        Self::start_with_intervals(
            state,
            trusted_sessions,
            SUCCESS_INTERVAL,
            INITIAL_ERROR_INTERVAL,
        )
        .await
    }

    async fn start_with_intervals(
        state: Arc<LocalRuntimeState>,
        trusted_sessions: TrustedSessionBroker,
        success_interval: Duration,
        initial_error_interval: Duration,
    ) -> Result<Self, String> {
        let mut reconciler = desktop_reconciler(&state);
        activate_authority_source(&state, &mut reconciler, &DesktopAuthoritySourceV2::Local)
            .await?;
        let (shutdown, shutdown_rx) = watch::channel(false);
        let task = tokio::spawn(reconcile_loop(
            state,
            trusted_sessions,
            shutdown_rx,
            reconciler,
            DesktopAuthoritySourceV2::Local,
            success_interval,
            initial_error_interval,
        ));
        Ok(Self { shutdown, task })
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
    mut reconciler: PluginSnapshotReconcilerV2,
    mut active_authority: DesktopAuthoritySourceV2,
    success_interval: Duration,
    initial_error_interval: Duration,
) {
    let mut error_interval = initial_error_interval;

    loop {
        match reconcile_iteration(
            &state,
            &trusted_sessions,
            &mut reconciler,
            &mut active_authority,
        )
        .await
        {
            Ok(()) => {
                error_interval = initial_error_interval;
                tokio::select! {
                    _ = shutdown_rx.changed() => break,
                    _ = tokio::time::sleep(success_interval) => {}
                }
            }
            Err(error) => {
                tracing::warn!(
                    error = %error,
                    data_plane_id = DATA_PLANE_ID,
                    "protocol-v2 platform plugin control-plane poll failed"
                );
                tokio::select! {
                    _ = shutdown_rx.changed() => break,
                    _ = tokio::time::sleep(error_interval) => {}
                }
                error_interval =
                    std::cmp::min(error_interval.saturating_mul(2), MAX_ERROR_INTERVAL);
            }
        }
    }
    reconciler.close().await;
    state.platform_plugin_authority_v2.clear();
}

fn desktop_reconciler(state: &LocalRuntimeState) -> PluginSnapshotReconcilerV2 {
    PluginSnapshotReconcilerV2::new_with_manager(
        desktop_loader(),
        state.platform_plugin_authority_v2.manager(),
    )
}

fn desktop_loader() -> LoaderV2 {
    LoaderV2::for_target(
        DataPlaneTargetV2::DesktopSidecar,
        [
            desktop_sidecar_http_routes_definition_v2(),
            desktop_sidecar_host_definition_v2(),
        ],
    )
}

fn local_bootstrap_snapshot() -> Result<ProfileSnapshotV2, String> {
    parse_profile_snapshot_v2(LOCAL_BOOTSTRAP_PROFILE_V2).map_err(|error| error.to_string())
}

async fn activate_authority_source(
    state: &LocalRuntimeState,
    reconciler: &mut PluginSnapshotReconcilerV2,
    source: &DesktopAuthoritySourceV2,
) -> Result<(), String> {
    let last_good = match source.fingerprint() {
        Some(fingerprint) => restore_last_good(state, fingerprint)?,
        None => None,
    };
    match last_good {
        Some(distribution) => {
            let generation = reconciler
                .stage_snapshot(distribution.snapshot.clone())
                .await
                .map_err(|error| error.to_string())?;
            state
                .platform_plugin_authority_v2
                .publish(&distribution, generation)
                .await;
            reconciler.restore_publication_ordering(
                distribution.envelope.version,
                distribution.snapshot.digest,
            );
        }
        None => {
            let baseline = local_bootstrap_snapshot()?;
            let generation = reconciler
                .stage_snapshot(baseline.clone())
                .await
                .map_err(|error| error.to_string())?;
            state
                .platform_plugin_authority_v2
                .publish_local_baseline(&baseline, generation)
                .await;
            reconciler.reset_publication_ordering();
        }
    }
    Ok(())
}

async fn reconcile_iteration(
    state: &LocalRuntimeState,
    trusted_sessions: &TrustedSessionBroker,
    reconciler: &mut PluginSnapshotReconcilerV2,
    active_authority: &mut DesktopAuthoritySourceV2,
) -> Result<(), String> {
    let authority = match load_cloud_authority(trusted_sessions) {
        Ok(authority) => authority,
        Err(error) => {
            if *active_authority != DesktopAuthoritySourceV2::Local {
                activate_authority_source(state, reconciler, &DesktopAuthoritySourceV2::Local)
                    .await?;
                *active_authority = DesktopAuthoritySourceV2::Local;
            }
            return Err(error);
        }
    };
    let next_authority = authority
        .as_ref()
        .map(|authority| DesktopAuthoritySourceV2::Cloud(authority.fingerprint.clone()))
        .unwrap_or(DesktopAuthoritySourceV2::Local);
    if *active_authority != next_authority {
        activate_authority_source(state, reconciler, &next_authority).await?;
        *active_authority = next_authority;
    }
    match authority {
        Some(authority) => reconcile_once(state, trusted_sessions, &authority, reconciler).await,
        None => Ok(()),
    }
}

pub(super) fn load_cloud_authority(
    trusted_sessions: &TrustedSessionBroker,
) -> Result<Option<CloudAuthorityV2>, String> {
    let Some(record) = trusted_sessions.load().map_err(|error| error.to_string())? else {
        return Ok(None);
    };
    if !matches!(
        (record.runtime_mode, record.credential_kind),
        (
            TrustedSessionRuntimeMode::Cloud,
            TrustedSessionCredentialKind::CloudBearer
        )
    ) {
        return Ok(None);
    }
    let base_url = validate_cloud_base_url(&record)?;
    let fingerprint = authority_fingerprint(&base_url, &record.credential)?;
    Ok(Some(CloudAuthorityV2 {
        base_url,
        credential: record.credential,
        fingerprint,
    }))
}

fn authority_fingerprint(base_url: &Url, credential: &str) -> Result<String, String> {
    let normalized_base_url = normalized_cloud_base_url(base_url);
    let identity = serde_json::to_vec(&(
        "memstack-platform-plugin-authority-v2",
        normalized_base_url,
        credential,
    ))
    .map_err(|_| "plugin v2 authority identity could not be encoded".to_string())?;
    Ok(format!("sha256:{:x}", Sha256::digest(identity)))
}

fn normalized_cloud_base_url(base_url: &Url) -> String {
    let base_path = base_url.path().trim_end_matches('/');
    let control_plane_root = if base_path.ends_with("/api/v1") {
        base_path.to_owned()
    } else {
        format!("{base_path}/api/v1")
    };
    let mut normalized = base_url.clone();
    normalized.set_path(&control_plane_root);
    normalized.set_query(None);
    normalized.set_fragment(None);
    normalized.to_string()
}

fn restore_last_good(
    state: &LocalRuntimeState,
    authority_fingerprint: &str,
) -> Result<Option<ControlPlaneDistributionV2>, String> {
    let connection = state.session_store.connection()?;
    plugin_snapshots_v2::initialize_schema(&connection).map_err(|error| error.to_string())?;
    plugin_snapshots_v2::read_last_good(&connection, authority_fingerprint)
        .map_err(|error| error.to_string())
}

async fn reconcile_once(
    state: &LocalRuntimeState,
    trusted_sessions: &TrustedSessionBroker,
    authority: &CloudAuthorityV2,
    reconciler: &mut PluginSnapshotReconcilerV2,
) -> Result<(), String> {
    let client = reqwest::Client::builder()
        .timeout(REQUEST_TIMEOUT)
        .build()
        .map_err(|error| format!("plugin v2 control-plane client unavailable: {error}"))?;
    let Some(distribution) =
        fetch_distribution(&client, &authority.base_url, authority.credential.as_str()).await?
    else {
        return Ok(());
    };
    if !cloud_authority_is_current(trusted_sessions, &authority.fingerprint)? {
        return Ok(());
    }
    {
        let connection = state.session_store.connection()?;
        plugin_snapshots_v2::initialize_schema(&connection).map_err(|error| error.to_string())?;
        plugin_snapshots_v2::record_requested(&connection, &authority.fingerprint, &distribution)
            .map_err(|error| error.to_string())?;
    }
    let receipt = match reconciler.prepare(&distribution).await {
        SnapshotPreparationV2::Receipt(receipt) => {
            persist_receipt(state, authority, &distribution, &receipt)?;
            receipt
        }
        SnapshotPreparationV2::Ready(prepared) => {
            if !cloud_authority_is_current(trusted_sessions, &authority.fingerprint)? {
                prepared.discard().await;
                return Ok(());
            }
            let durable_receipt = prepared.receipt();
            if let Err(error) = persist_receipt(state, authority, &distribution, &durable_receipt) {
                prepared.discard().await;
                return Err(error);
            }
            if !cloud_authority_is_current(trusted_sessions, &authority.fingerprint)? {
                prepared.discard().await;
                return Ok(());
            }
            let expected_manager = state.platform_plugin_authority_v2.manager();
            let distribution_for_publish = distribution.clone();
            let receipt = prepared
                .commit_with(|manager, generation| async move {
                    debug_assert!(Arc::ptr_eq(&manager, &expected_manager));
                    state
                        .platform_plugin_authority_v2
                        .publish(&distribution_for_publish, generation)
                        .await;
                })
                .await;
            debug_assert_eq!(receipt, durable_receipt);
            receipt
        }
    };
    post_receipt(
        &client,
        &authority.base_url,
        authority.credential.as_str(),
        &distribution,
        &receipt,
    )
    .await
}

fn persist_receipt(
    state: &LocalRuntimeState,
    authority: &CloudAuthorityV2,
    distribution: &ControlPlaneDistributionV2,
    receipt: &SnapshotApplyReceiptV2,
) -> Result<(), String> {
    let mut connection = state.session_store.connection()?;
    plugin_snapshots_v2::record_receipt(
        &mut connection,
        &authority.fingerprint,
        &distribution.envelope.nonce,
        receipt,
    )
    .map_err(|error| error.to_string())
}

fn cloud_authority_is_current(
    trusted_sessions: &TrustedSessionBroker,
    expected_fingerprint: &str,
) -> Result<bool, String> {
    load_cloud_authority(trusted_sessions).map(|authority| {
        authority
            .as_ref()
            .is_some_and(|authority| authority.fingerprint == expected_fingerprint)
    })
}

async fn fetch_distribution(
    client: &reqwest::Client,
    base_url: &Url,
    credential: &str,
) -> Result<Option<ControlPlaneDistributionV2>, String> {
    let url = control_plane_url(base_url, "platform-plugins/v2/distribution");
    let response = client
        .get(url)
        .bearer_auth(credential)
        .send()
        .await
        .map_err(|error| format!("plugin v2 distribution fetch failed: {error}"))?;
    if response.status().as_u16() == 404 {
        return Ok(None);
    }
    if response.status().as_u16() == 409 {
        return Err("incompatible_schema_version".into());
    }
    if !response.status().is_success() {
        return Err(format!(
            "plugin v2 distribution fetch returned {}",
            response.status()
        ));
    }
    let bytes = bounded_response_bytes(response, MAX_DISTRIBUTION_BYTES).await?;
    let raw = std::str::from_utf8(&bytes)
        .map_err(|_| "plugin v2 distribution body is not UTF-8".to_string())?;
    parse_control_plane_distribution_v2(raw)
        .map(Some)
        .map_err(|error| error.to_string())
}

async fn bounded_response_bytes(
    response: reqwest::Response,
    limit: usize,
) -> Result<Vec<u8>, String> {
    if response
        .content_length()
        .is_some_and(|length| length > limit as u64)
    {
        return Err("plugin v2 distribution exceeds its size limit".into());
    }
    let mut stream = response.bytes_stream();
    let mut bytes = Vec::new();
    while let Some(chunk) = stream.next().await {
        let chunk =
            chunk.map_err(|error| format!("plugin v2 distribution body failed: {error}"))?;
        if bytes.len().saturating_add(chunk.len()) > limit {
            return Err("plugin v2 distribution exceeds its size limit".into());
        }
        bytes.extend_from_slice(&chunk);
    }
    Ok(bytes)
}

async fn post_receipt(
    client: &reqwest::Client,
    base_url: &Url,
    credential: &str,
    distribution: &ControlPlaneDistributionV2,
    receipt: &SnapshotApplyReceiptV2,
) -> Result<(), String> {
    let url = control_plane_url(base_url, "platform-plugins/v2/data-plane-state");
    let body = DataPlaneReceiptRequestV2 {
        schema_version: 2,
        data_plane_id: DATA_PLANE_ID,
        nonce: &distribution.envelope.nonce,
        receipt,
    };
    let response = client
        .post(url)
        .bearer_auth(credential)
        .json(&body)
        .send()
        .await
        .map_err(|error| format!("plugin v2 receipt post failed: {error}"))?;
    if !response.status().is_success() {
        return Err(format!(
            "plugin v2 receipt post returned {}",
            response.status()
        ));
    }
    Ok(())
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct DataPlaneReceiptRequestV2<'a> {
    schema_version: u64,
    data_plane_id: &'a str,
    nonce: &'a str,
    receipt: &'a SnapshotApplyReceiptV2,
}

fn validate_cloud_base_url(record: &TrustedSessionRecord) -> Result<Url, String> {
    let url = Url::parse(&record.api_base_url)
        .map_err(|_| "trusted cloud API base URL is invalid".to_string())?;
    let loopback = matches!(url.host_str(), Some("127.0.0.1" | "localhost" | "::1"));
    if (url.scheme() != "https" && !loopback)
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err("trusted cloud API base URL is unsafe".to_string());
    }
    Ok(url)
}

pub(super) fn control_plane_url(base: &Url, suffix: &str) -> Url {
    let base_path = base.path().trim_end_matches('/');
    let prefix = if base_path.ends_with("/api/v1") {
        base_path.to_string()
    } else {
        format!("{base_path}/api/v1")
    };
    let mut url = base.clone();
    url.set_path(&format!("{prefix}/{suffix}"));
    url
}

#[cfg(test)]
mod tests {
    use std::{
        path::PathBuf,
        sync::{Arc, Mutex},
    };

    use agistack_adapters_device::SqliteCheckpointStore;
    use agistack_adapters_local_tools::LocalToolHost;
    use agistack_plugin_host::{
        ApplyStatusV2, DesktopSidecarHttpRouteContributionV2, ScopeKindV2, ScopeV2,
        TargetHostDescriptorV2, DESKTOP_SIDECAR_HOST_SERVICE_V2,
        DESKTOP_SIDECAR_HTTP_ROUTES_SERVICE_V2,
    };
    use serde_json::{json, Value};
    use uuid::Uuid;

    use crate::trusted_session::{TrustedSessionStore, TrustedSessionStoreError};

    use super::super::session_store::DesktopSessionStore;
    use super::*;

    const BOOTSTRAP: &str =
        include_str!("../../../../../../shared/profiles/memstack-default-bootstrap.v2.json");
    const CLOUD_AUTHORITY: &str =
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    #[derive(Default)]
    struct InMemoryTrustedSessionStore {
        raw: Mutex<Option<String>>,
    }

    impl TrustedSessionStore for InMemoryTrustedSessionStore {
        fn save_raw(&self, value: &str) -> Result<(), TrustedSessionStoreError> {
            *self
                .raw
                .lock()
                .map_err(|_| TrustedSessionStoreError::Unavailable)? = Some(value.to_owned());
            Ok(())
        }

        fn load_raw(&self) -> Result<Option<String>, TrustedSessionStoreError> {
            self.raw
                .lock()
                .map(|raw| raw.clone())
                .map_err(|_| TrustedSessionStoreError::Unavailable)
        }

        fn clear_raw(&self) -> Result<(), TrustedSessionStoreError> {
            self.raw
                .lock()
                .map(|mut raw| raw.take())
                .map(|_| ())
                .map_err(|_| TrustedSessionStoreError::Unavailable)
        }
    }

    fn test_state() -> Arc<LocalRuntimeState> {
        let root: PathBuf = std::env::temp_dir().join(format!(
            "agistack-platform-plugin-sync-v2-{}",
            Uuid::new_v4()
        ));
        let tool_host = LocalToolHost::new(&root).expect("tool host");
        let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
        let session_store = DesktopSessionStore::in_memory().expect("session store");
        Arc::new(
            LocalRuntimeState::new(
                root,
                tool_host,
                checkpoints,
                "platform-plugin-sync-v2-secret".to_owned(),
                session_store,
            )
            .expect("local runtime state"),
        )
    }

    fn bootstrap_distribution(version: u64, nonce: &str) -> ControlPlaneDistributionV2 {
        let snapshot: Value = serde_json::from_str(BOOTSTRAP).expect("bootstrap must parse");
        let digest = snapshot["digest"].as_str().expect("snapshot digest");
        let raw = json!({
            "schema_version": 2,
            "descriptor": {
                "profile_id": snapshot["profile_id"],
                "generation": snapshot["generation"],
                "digest": digest,
            },
            "snapshot": snapshot,
            "envelope": {
                "version": version,
                "nonce": nonce,
                "snapshot_digest": digest,
                "type_url": "types.memstack.ai/plugin.profile.v2",
            },
        });
        parse_control_plane_distribution_v2(&raw.to_string()).expect("distribution must parse")
    }

    fn bootstrap_distribution_without_route_provider(
        version: u64,
        nonce: &str,
    ) -> ControlPlaneDistributionV2 {
        let mut snapshot: Value = serde_json::from_str(BOOTSTRAP).expect("bootstrap must parse");
        let entries = snapshot["entries"].as_array_mut().expect("profile entries");
        let provider_index = entries
            .iter()
            .position(|entry| entry["entry_id"] == "builtin-desktop-sidecar-http-routes")
            .expect("desktop sidecar route provider entry");
        entries.remove(provider_index);
        entries
            .iter_mut()
            .find(|entry| entry["entry_id"] == "builtin-desktop-sidecar-local-capability")
            .expect("desktop sidecar host entry")["parent_entry_id"] = Value::Null;

        let mut digest_payload = snapshot.clone();
        digest_payload
            .as_object_mut()
            .expect("snapshot object")
            .remove("digest");
        let canonical = serde_jcs::to_vec(&digest_payload).expect("snapshot must canonicalize");
        let digest = format!("{:x}", <sha2::Sha256 as sha2::Digest>::digest(canonical));
        snapshot["digest"] = Value::String(digest.clone());
        let raw = json!({
            "schema_version": 2,
            "descriptor": {
                "profile_id": snapshot["profile_id"],
                "generation": snapshot["generation"],
                "digest": digest,
            },
            "snapshot": snapshot,
            "envelope": {
                "version": version,
                "nonce": nonce,
                "snapshot_digest": digest,
                "type_url": "types.memstack.ai/plugin.profile.v2",
            },
        });
        parse_control_plane_distribution_v2(&raw.to_string()).expect("distribution must parse")
    }

    fn trusted_record(api_base_url: &str) -> TrustedSessionRecord {
        TrustedSessionRecord {
            version: 1,
            api_base_url: api_base_url.to_string(),
            runtime_mode: TrustedSessionRuntimeMode::Cloud,
            credential_kind: TrustedSessionCredentialKind::CloudBearer,
            credential: "test-credential".to_string(),
            expires_at: None,
        }
    }

    #[test]
    fn cloud_authority_url_accepts_https_and_loopback_only() {
        assert!(validate_cloud_base_url(&trusted_record("https://example.com/control")).is_ok());
        assert!(validate_cloud_base_url(&trusted_record("http://127.0.0.1:8000")).is_ok());
        assert!(validate_cloud_base_url(&trusted_record("http://example.com")).is_err());
        assert!(validate_cloud_base_url(&trusted_record("https://user@example.com")).is_err());
        assert!(validate_cloud_base_url(&trusted_record("https://example.com?token=x")).is_err());
    }

    #[test]
    fn control_plane_url_preserves_one_api_v1_prefix() {
        let root = Url::parse("https://example.com/control").expect("root URL");
        let prefixed = Url::parse("https://example.com/control/api/v1").expect("prefixed URL");

        assert_eq!(
            control_plane_url(&root, "platform-plugins/v2/distribution").as_str(),
            "https://example.com/control/api/v1/platform-plugins/v2/distribution"
        );
        assert_eq!(
            control_plane_url(&prefixed, "platform-plugins/v2/data-plane-state").as_str(),
            "https://example.com/control/api/v1/platform-plugins/v2/data-plane-state"
        );
    }

    #[test]
    fn receipt_request_uses_the_exact_v2_transport_shape() {
        let receipt = SnapshotApplyReceiptV2 {
            status: ApplyStatusV2::Nack,
            requested_version: 7,
            requested_digest: "a".repeat(64),
            applied_version: None,
            applied_digest: None,
            error_code: Some("generation_apply_failed".into()),
            error_message: Some("module unavailable".into()),
        };
        let body = serde_json::to_value(DataPlaneReceiptRequestV2 {
            schema_version: 2,
            data_plane_id: DATA_PLANE_ID,
            nonce: "nonce-7",
            receipt: &receipt,
        })
        .expect("receipt must serialize");

        assert_eq!(
            body,
            json!({
                "schema_version": 2,
                "data_plane_id": "desktop-sidecar-v2",
                "nonce": "nonce-7",
                "receipt": {
                    "status": "nack",
                    "requested_version": 7,
                    "requested_digest": "a".repeat(64),
                    "applied_version": null,
                    "applied_digest": null,
                    "error_code": "generation_apply_failed",
                    "error_message": "module unavailable",
                },
            })
        );
    }

    #[test]
    fn authority_fingerprint_normalizes_base_url_and_hides_the_credential() {
        let base = Url::parse("https://EXAMPLE.com:443/control").expect("base URL");
        let equivalent = Url::parse("https://example.com/control/api/v1/").expect("equivalent URL");
        let credential = "cloud-bearer-that-must-never-be-persisted";

        let first = authority_fingerprint(&base, credential).expect("fingerprint");
        let second = authority_fingerprint(&equivalent, credential).expect("fingerprint");
        let other = authority_fingerprint(&base, "different-bearer").expect("fingerprint");

        assert_eq!(first, second);
        assert_ne!(first, other);
        assert!(first.starts_with("sha256:"));
        assert!(!first.contains(credential));
    }

    #[tokio::test]
    async fn local_bootstrap_is_active_before_control_plane_start_returns() {
        let state = test_state();
        let trusted_sessions =
            TrustedSessionBroker::new(Arc::new(InMemoryTrustedSessionStore::default()));

        let control_plane = PlatformPluginControlPlaneReconcilerV2::start_with_intervals(
            Arc::clone(&state),
            trusted_sessions,
            Duration::from_secs(3600),
            Duration::from_secs(3600),
        )
        .await
        .expect("local bootstrap must activate");

        let lease = state
            .platform_plugin_authority_v2
            .acquire_generation()
            .expect("local bootstrap generation must be available");
        assert_eq!(lease.descriptor().publication_version, None);
        assert_eq!(
            lease.http_routes().contribution_id,
            "memstack-desktop-local-api.v1"
        );
        drop(lease);
        control_plane.shutdown().await;
        assert!(state
            .platform_plugin_authority_v2
            .acquire_generation()
            .is_err());
    }

    #[tokio::test]
    async fn cloud_to_local_switch_is_atomic_and_keeps_the_old_lease_pinned() {
        let state = test_state();
        let cloud_distribution = bootstrap_distribution(7, "cloud-last-good");
        let mut seed = PluginSnapshotReconcilerV2::new(desktop_loader());
        let receipt = seed.apply(&cloud_distribution).await;
        assert_eq!(receipt.status, ApplyStatusV2::Ack);
        {
            let mut connection = state.session_store.connection().expect("session store");
            plugin_snapshots_v2::initialize_schema(&connection).expect("plugin snapshot schema");
            plugin_snapshots_v2::record_requested(
                &connection,
                CLOUD_AUTHORITY,
                &cloud_distribution,
            )
            .expect("requested cloud distribution");
            plugin_snapshots_v2::record_receipt(
                &mut connection,
                CLOUD_AUTHORITY,
                &cloud_distribution.envelope.nonce,
                &receipt,
            )
            .expect("cloud last-good receipt");
        }
        seed.close().await;

        let mut reconciler = desktop_reconciler(&state);
        let lifecycle_manager = reconciler.manager();
        activate_authority_source(
            &state,
            &mut reconciler,
            &DesktopAuthoritySourceV2::Cloud(CLOUD_AUTHORITY.to_owned()),
        )
        .await
        .expect("cloud authority generation must activate");
        let cloud_lease = state
            .platform_plugin_authority_v2
            .acquire_generation()
            .expect("cloud last-good generation must publish");
        assert_eq!(cloud_lease.descriptor().publication_version, Some(7));

        activate_authority_source(&state, &mut reconciler, &DesktopAuthoritySourceV2::Local)
            .await
            .expect("local authority generation must replace cloud");
        assert!(Arc::ptr_eq(&lifecycle_manager, &reconciler.manager()));
        let local_lease = state
            .platform_plugin_authority_v2
            .acquire_generation()
            .expect("local bootstrap generation must publish");
        assert_eq!(local_lease.descriptor().publication_version, None);
        assert_eq!(
            local_lease.http_routes().contribution_id,
            "memstack-desktop-local-api.v1"
        );
        assert_eq!(cloud_lease.descriptor().publication_version, Some(7));
        assert_eq!(
            cloud_lease.http_routes().contribution_id,
            "memstack-desktop-local-api.v1"
        );

        drop(local_lease);
        drop(cloud_lease);
        reconciler.close().await;
        state.platform_plugin_authority_v2.clear();
    }

    #[tokio::test]
    async fn desktop_reconciler_activates_the_generated_local_capability_module() {
        let mut reconciler = PluginSnapshotReconcilerV2::new(desktop_loader());
        let requested = bootstrap_distribution(18, "nonce-18");

        assert_eq!(
            reconciler.apply(&requested).await.status,
            ApplyStatusV2::Ack
        );
        let lease = reconciler
            .manager()
            .acquire()
            .expect("desktop-sidecar generation must be active");
        let descriptor = lease
            .generation()
            .expect("generation must remain leased")
            .resolve::<TargetHostDescriptorV2>(
                DESKTOP_SIDECAR_HOST_SERVICE_V2,
                &ScopeV2 {
                    kind: ScopeKindV2::Root,
                    tenant_id: None,
                    project_id: None,
                    session_id: None,
                },
                None,
            )
            .expect("local capability descriptor must resolve");
        assert_eq!(descriptor.target, "desktop-sidecar");
        assert_eq!(descriptor.strategy, "native-local-capability");
        let routes = lease
            .generation()
            .expect("generation must remain leased")
            .resolve::<DesktopSidecarHttpRouteContributionV2>(
                DESKTOP_SIDECAR_HTTP_ROUTES_SERVICE_V2,
                &ScopeV2 {
                    kind: ScopeKindV2::Root,
                    tenant_id: None,
                    project_id: None,
                    session_id: None,
                },
                None,
            )
            .expect("local HTTP route contribution must resolve");
        assert_eq!(routes.contribution_id, "memstack-desktop-local-api.v1");
        assert_eq!(routes.strategy, "axum-host-router");
        lease.release().await.expect("lease must release");
        reconciler.close().await;
    }

    #[tokio::test]
    async fn rejected_route_candidate_preserves_the_last_good_desktop_generation() {
        let mut reconciler = PluginSnapshotReconcilerV2::new(desktop_loader());
        let accepted = bootstrap_distribution(18, "nonce-last-good");
        assert_eq!(reconciler.apply(&accepted).await.status, ApplyStatusV2::Ack);
        let accepted_digest = accepted.snapshot.digest.clone();
        let pinned = reconciler
            .manager()
            .acquire()
            .expect("accepted generation must be available");

        let rejected = bootstrap_distribution_without_route_provider(19, "nonce-rejected");
        assert_ne!(rejected.snapshot.digest, accepted_digest);
        let receipt = reconciler.apply(&rejected).await;

        assert_eq!(receipt.status, ApplyStatusV2::Nack);
        assert_eq!(
            receipt.error_code.as_deref(),
            Some("generation_apply_failed")
        );
        assert!(receipt
            .error_message
            .as_deref()
            .is_some_and(|message| message.contains("injects missing service")));
        assert_eq!(receipt.applied_version, Some(18));
        assert_eq!(
            receipt.applied_digest.as_deref(),
            Some(accepted_digest.as_str())
        );

        let active = reconciler
            .manager()
            .acquire()
            .expect("last-good generation must remain active");
        assert_eq!(
            active
                .generation()
                .expect("active generation must remain leased")
                .snapshot
                .digest,
            accepted_digest
        );
        let routes = pinned
            .generation()
            .expect("pinned generation must survive the rejected candidate")
            .resolve::<DesktopSidecarHttpRouteContributionV2>(
                DESKTOP_SIDECAR_HTTP_ROUTES_SERVICE_V2,
                &ScopeV2 {
                    kind: ScopeKindV2::Root,
                    tenant_id: None,
                    project_id: None,
                    session_id: None,
                },
                None,
            )
            .expect("last-good route contribution must still resolve");
        assert_eq!(routes.contribution_id, "memstack-desktop-local-api.v1");
        assert_eq!(routes.strategy, "axum-host-router");

        active.release().await.expect("active lease must release");
        pinned.release().await.expect("pinned lease must release");
        reconciler.close().await;
    }
}
