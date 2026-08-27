//! Protocol-v2 background reconciliation from the Python control plane.

use std::{sync::Arc, time::Duration};

use agistack_plugin_host::{
    desktop_sidecar_host_definition_v2, parse_control_plane_distribution_v2,
    ControlPlaneDistributionV2, DataPlaneTargetV2, LoaderV2, PluginSnapshotReconcilerV2,
    SnapshotApplyReceiptV2,
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

pub(super) struct CloudAuthorityV2 {
    pub(super) base_url: Url,
    pub(super) credential: String,
    fingerprint: String,
}

/// Owns the protocol-v2 desktop-sidecar polling task and its shutdown signal.
#[derive(Debug)]
pub(crate) struct PlatformPluginControlPlaneReconcilerV2 {
    shutdown: watch::Sender<bool>,
    task: tokio::task::JoinHandle<()>,
}

impl PlatformPluginControlPlaneReconcilerV2 {
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
    let mut reconciler = desktop_reconciler();
    let mut active_authority = None;

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
                error_interval = INITIAL_ERROR_INTERVAL;
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

fn desktop_reconciler() -> PluginSnapshotReconcilerV2 {
    let loader = LoaderV2::for_target(
        DataPlaneTargetV2::DesktopSidecar,
        [desktop_sidecar_host_definition_v2()],
    );
    PluginSnapshotReconcilerV2::new(loader)
}

async fn reconcile_iteration(
    state: &LocalRuntimeState,
    trusted_sessions: &TrustedSessionBroker,
    reconciler: &mut PluginSnapshotReconcilerV2,
    active_authority: &mut Option<String>,
) -> Result<(), String> {
    let authority = match load_cloud_authority(trusted_sessions) {
        Ok(authority) => authority,
        Err(error) => {
            state.platform_plugin_authority_v2.clear();
            if active_authority.take().is_some() {
                replace_reconciler(reconciler).await;
            }
            return Err(error);
        }
    };
    let next_fingerprint = authority
        .as_ref()
        .map(|authority| authority.fingerprint.as_str());
    if active_authority.as_deref() != next_fingerprint {
        state.platform_plugin_authority_v2.clear();
        replace_reconciler(reconciler).await;
        active_authority.take();
        if let Some(authority) = authority.as_ref() {
            restore_last_good(state, &authority.fingerprint, reconciler).await?;
            *active_authority = Some(authority.fingerprint.clone());
        }
    }
    match authority {
        Some(authority) => reconcile_once(state, &authority, reconciler).await,
        None => Ok(()),
    }
}

async fn replace_reconciler(reconciler: &mut PluginSnapshotReconcilerV2) {
    let previous = std::mem::replace(reconciler, desktop_reconciler());
    previous.close().await;
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

async fn restore_last_good(
    state: &LocalRuntimeState,
    authority_fingerprint: &str,
    reconciler: &mut PluginSnapshotReconcilerV2,
) -> Result<(), String> {
    let last_good = {
        let connection = state.session_store.connection()?;
        plugin_snapshots_v2::initialize_schema(&connection).map_err(|error| error.to_string())?;
        plugin_snapshots_v2::read_last_good(&connection, authority_fingerprint)
            .map_err(|error| error.to_string())?
    };
    let Some(distribution) = last_good else {
        return Ok(());
    };
    let receipt = reconciler.apply(&distribution).await;
    if receipt.status == agistack_plugin_host::ApplyStatusV2::Nack {
        return Err(receipt
            .error_code
            .unwrap_or_else(|| "last_good_restore_failed".into()));
    }
    state
        .platform_plugin_authority_v2
        .publish(&distribution, reconciler.manager());
    Ok(())
}

async fn reconcile_once(
    state: &LocalRuntimeState,
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
    {
        let connection = state.session_store.connection()?;
        plugin_snapshots_v2::initialize_schema(&connection).map_err(|error| error.to_string())?;
        plugin_snapshots_v2::record_requested(&connection, &authority.fingerprint, &distribution)
            .map_err(|error| error.to_string())?;
    }
    let receipt = reconciler.apply(&distribution).await;
    if receipt.status == agistack_plugin_host::ApplyStatusV2::Ack {
        state
            .platform_plugin_authority_v2
            .publish(&distribution, reconciler.manager());
    }
    {
        let mut connection = state.session_store.connection()?;
        plugin_snapshots_v2::record_receipt(
            &mut connection,
            &authority.fingerprint,
            &distribution.envelope.nonce,
            &receipt,
        )
        .map_err(|error| error.to_string())?;
    }
    post_receipt(
        &client,
        &authority.base_url,
        authority.credential.as_str(),
        &distribution,
        &receipt,
    )
    .await
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
    use agistack_plugin_host::{
        ApplyStatusV2, ScopeKindV2, ScopeV2, TargetHostDescriptorV2,
        DESKTOP_SIDECAR_HOST_SERVICE_V2,
    };
    use serde_json::{json, Value};

    use super::*;

    const SNAPSHOT: &str =
        include_str!("../../../../../../shared/fixtures/platform-plugin-profile.v2.json");
    const BOOTSTRAP: &str =
        include_str!("../../../../../../shared/profiles/memstack-default-bootstrap.v2.json");

    fn distribution(version: u64, nonce: &str) -> ControlPlaneDistributionV2 {
        let snapshot: Value = serde_json::from_str(SNAPSHOT).expect("fixture must parse");
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
    async fn replacing_reconciler_clears_the_active_generation() {
        let mut reconciler = desktop_reconciler();
        let requested = distribution(17, "nonce-17");
        assert_eq!(
            reconciler.apply(&requested).await.status,
            ApplyStatusV2::Ack
        );
        let lease = reconciler
            .manager()
            .acquire()
            .expect("generation must be active before replacement");
        lease.release().await.expect("lease must release");

        replace_reconciler(&mut reconciler).await;

        assert!(reconciler.manager().acquire().is_err());
        reconciler.close().await;
    }

    #[tokio::test]
    async fn desktop_reconciler_activates_the_generated_local_capability_module() {
        let mut reconciler = desktop_reconciler();
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
        lease.release().await.expect("lease must release");
        reconciler.close().await;
    }
}
