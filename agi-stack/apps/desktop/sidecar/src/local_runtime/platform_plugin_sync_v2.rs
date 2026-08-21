//! Protocol-v2 background reconciliation from the Python control plane.

use std::{sync::Arc, time::Duration};

use agistack_plugin_host::{
    parse_control_plane_distribution_v2, ControlPlaneDistributionV2, DataPlaneTargetV2, LoaderV2,
    PluginDefinitionV2, PluginSnapshotReconcilerV2, SnapshotApplyReceiptV2,
};
use futures_util::StreamExt;
use serde::Serialize;
use tokio::sync::watch;
use url::Url;

use crate::{
    plugin_snapshots_v2,
    trusted_session::{
        TrustedSessionBroker, TrustedSessionCredentialKind, TrustedSessionRuntimeMode,
    },
};

use super::{platform_plugin_sync, LocalRuntimeState};

const DATA_PLANE_ID: &str = "desktop-sidecar-v2";
const SUCCESS_INTERVAL: Duration = Duration::from_secs(30);
const INITIAL_ERROR_INTERVAL: Duration = Duration::from_secs(2);
const MAX_ERROR_INTERVAL: Duration = Duration::from_secs(60);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_DISTRIBUTION_BYTES: usize = 4 * 1024 * 1024;

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
    let loader = LoaderV2::for_target(
        DataPlaneTargetV2::DesktopSidecar,
        std::iter::empty::<PluginDefinitionV2>(),
    );
    let mut reconciler = PluginSnapshotReconcilerV2::new(loader);
    if let Err(error) = restore_last_good(&state, &mut reconciler).await {
        tracing::error!(
            error_code = %error,
            "protocol-v2 platform plugin state could not be restored"
        );
        return;
    }

    loop {
        match reconcile_once(&state, &trusted_sessions, &mut reconciler).await {
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
}

async fn restore_last_good(
    state: &LocalRuntimeState,
    reconciler: &mut PluginSnapshotReconcilerV2,
) -> Result<(), String> {
    let last_good = {
        let connection = state.session_store.connection()?;
        plugin_snapshots_v2::initialize_schema(&connection).map_err(|error| error.to_string())?;
        plugin_snapshots_v2::read_last_good(&connection).map_err(|error| error.to_string())?
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
    Ok(())
}

async fn reconcile_once(
    state: &LocalRuntimeState,
    trusted_sessions: &TrustedSessionBroker,
    reconciler: &mut PluginSnapshotReconcilerV2,
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
    let base_url = platform_plugin_sync::validate_cloud_base_url(&record)?;
    let client = reqwest::Client::builder()
        .timeout(REQUEST_TIMEOUT)
        .build()
        .map_err(|error| format!("plugin v2 control-plane client unavailable: {error}"))?;
    let Some(distribution) =
        fetch_distribution(&client, &base_url, record.credential.as_str()).await?
    else {
        return Ok(());
    };
    {
        let connection = state.session_store.connection()?;
        plugin_snapshots_v2::initialize_schema(&connection).map_err(|error| error.to_string())?;
        plugin_snapshots_v2::record_requested(&connection, &distribution)
            .map_err(|error| error.to_string())?;
    }
    let receipt = reconciler.apply(&distribution).await;
    {
        let mut connection = state.session_store.connection()?;
        plugin_snapshots_v2::record_receipt(
            &mut connection,
            &distribution.envelope.nonce,
            &receipt,
        )
        .map_err(|error| error.to_string())?;
    }
    post_receipt(
        &client,
        &base_url,
        record.credential.as_str(),
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
    let url =
        platform_plugin_sync::control_plane_url(base_url, "platform-plugins/v2/distribution")?;
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
    let url =
        platform_plugin_sync::control_plane_url(base_url, "platform-plugins/v2/data-plane-state")?;
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

#[cfg(test)]
mod tests {
    use agistack_plugin_host::ApplyStatusV2;
    use serde_json::json;

    use super::*;

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
}
