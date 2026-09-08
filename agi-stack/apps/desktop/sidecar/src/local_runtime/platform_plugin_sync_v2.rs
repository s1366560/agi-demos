//! Protocol-v2 background reconciliation from the Python control plane.

use std::{
    sync::{Arc, Mutex},
    time::Duration,
};

use agistack_plugin_host::protocol_v2::ProfileSnapshotV2;
use agistack_plugin_host::{
    desktop_sidecar_host_definition_v2, desktop_sidecar_http_routes_definition_v2,
    parse_control_plane_distribution_v2, parse_profile_snapshot_v2, ControlPlaneDistributionV2,
    DataPlaneTargetV2, GenerationRetirementV2, LoaderV2, PluginSnapshotReconcilerV2,
    SnapshotApplyReceiptV2, SnapshotPreparationV2,
};
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use tokio::sync::{mpsc, oneshot, watch};
use url::Url;
use zeroize::{Zeroize, Zeroizing};

use crate::{
    plugin_data_plane_credential_v2::{
        validate_base_url_v2, PluginDataPlaneCredentialBrokerV2, PluginDataPlaneCredentialRecordV2,
        DESKTOP_PLUGIN_DATA_PLANE_ID_V2,
    },
    plugin_snapshots_v2,
    trusted_session::{
        TrustedSessionBroker, TrustedSessionCredentialKind, TrustedSessionRecord,
        TrustedSessionRuntimeMode,
    },
};

use super::LocalRuntimeState;

const DATA_PLANE_ID: &str = DESKTOP_PLUGIN_DATA_PLANE_ID_V2;
const SUCCESS_INTERVAL: Duration = Duration::from_secs(30);
const INITIAL_ERROR_INTERVAL: Duration = Duration::from_secs(2);
const MAX_ERROR_INTERVAL: Duration = Duration::from_secs(60);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_DISTRIBUTION_BYTES: usize = 4 * 1024 * 1024;
const SELECTION_COMMAND_CAPACITY: usize = 8;
const LOCAL_BOOTSTRAP_PROFILE_V2: &str =
    include_str!("../../../../../../shared/profiles/memstack-default-bootstrap.v2.json");

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub(crate) enum PlatformPluginAuthorityModeV2 {
    Local,
    Cloud,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct PlatformPluginAuthoritySelectionV2 {
    mode: PlatformPluginAuthorityModeV2,
    epoch: u64,
}

impl Default for PlatformPluginAuthoritySelectionV2 {
    fn default() -> Self {
        Self {
            mode: PlatformPluginAuthorityModeV2::Local,
            epoch: 0,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum SelectionReconcileOutcomeV2 {
    Applied,
    Superseded,
}

struct SelectionReconcileCommandV2 {
    selection: PlatformPluginAuthoritySelectionV2,
    response: oneshot::Sender<Result<SelectionReconcileOutcomeV2, String>>,
}

struct ReconcileLoopControlV2 {
    shutdown_rx: watch::Receiver<bool>,
    selection: Arc<Mutex<PlatformPluginAuthoritySelectionV2>>,
    selection_rx: mpsc::Receiver<SelectionReconcileCommandV2>,
}

#[derive(Clone, Copy)]
struct ReconcileIntervalsV2 {
    success: Duration,
    initial_error: Duration,
}

pub(super) struct CloudAuthorityV2 {
    pub(super) base_url: Url,
    pub(super) credential: String,
    fingerprint: String,
    configuration_fingerprint: String,
    ack_participation: bool,
}

impl Drop for CloudAuthorityV2 {
    fn drop(&mut self) {
        self.credential.zeroize();
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum DesktopAuthoritySourceV2 {
    Local,
    Cloud(String),
}

/// Owns the protocol-v2 desktop-sidecar polling task and its shutdown signal.
#[derive(Debug)]
pub(crate) struct PlatformPluginControlPlaneReconcilerV2 {
    shutdown: watch::Sender<bool>,
    selection: Arc<Mutex<PlatformPluginAuthoritySelectionV2>>,
    selection_tx: mpsc::Sender<SelectionReconcileCommandV2>,
    task: tokio::task::JoinHandle<()>,
}

impl PlatformPluginControlPlaneReconcilerV2 {
    pub(super) async fn start(
        state: Arc<LocalRuntimeState>,
        plugin_data_plane_credentials_v2: PluginDataPlaneCredentialBrokerV2,
    ) -> Result<Self, String> {
        Self::start_with_intervals(
            state,
            plugin_data_plane_credentials_v2,
            SUCCESS_INTERVAL,
            INITIAL_ERROR_INTERVAL,
        )
        .await
    }

    async fn start_with_intervals(
        state: Arc<LocalRuntimeState>,
        plugin_data_plane_credentials_v2: PluginDataPlaneCredentialBrokerV2,
        success_interval: Duration,
        initial_error_interval: Duration,
    ) -> Result<Self, String> {
        let selection = Arc::new(Mutex::new(PlatformPluginAuthoritySelectionV2::default()));
        let mut reconciler = desktop_reconciler(&state);
        activate_authority_source(&state, &mut reconciler, &DesktopAuthoritySourceV2::Local)
            .await?;
        let (shutdown, shutdown_rx) = watch::channel(false);
        let (selection_tx, selection_rx) = mpsc::channel(SELECTION_COMMAND_CAPACITY);
        let task = tokio::spawn(reconcile_loop(
            state,
            plugin_data_plane_credentials_v2,
            ReconcileLoopControlV2 {
                shutdown_rx,
                selection: Arc::clone(&selection),
                selection_rx,
            },
            reconciler,
            Some(DesktopAuthoritySourceV2::Local),
            ReconcileIntervalsV2 {
                success: success_interval,
                initial_error: initial_error_interval,
            },
        ));
        Ok(Self {
            shutdown,
            selection,
            selection_tx,
            task,
        })
    }

    pub(crate) fn selection_snapshot(
        &self,
    ) -> Result<(PlatformPluginAuthorityModeV2, u64), String> {
        let selected = lock_selection(&self.selection)?;
        Ok((selected.mode, selected.epoch))
    }

    pub(crate) async fn select(&self, mode: PlatformPluginAuthorityModeV2) -> Result<(), String> {
        let selection = self.advance_selection(mode)?;
        match self.reconcile_selection(selection).await? {
            SelectionReconcileOutcomeV2::Applied => Ok(()),
            SelectionReconcileOutcomeV2::Superseded => {
                Err("platform plugin authority selection was superseded".to_string())
            }
        }
    }

    pub(crate) async fn refresh(&self) -> Result<(), String> {
        let mode = lock_selection(&self.selection)?.mode;
        let selection = self.advance_selection(mode)?;
        let _ = self.reconcile_selection(selection).await?;
        Ok(())
    }

    fn advance_selection(
        &self,
        mode: PlatformPluginAuthorityModeV2,
    ) -> Result<PlatformPluginAuthoritySelectionV2, String> {
        let mut current = lock_selection(&self.selection)?;
        let epoch = current
            .epoch
            .checked_add(1)
            .ok_or_else(|| "platform plugin authority selection epoch is exhausted".to_string())?;
        let selection = PlatformPluginAuthoritySelectionV2 { mode, epoch };
        *current = selection;
        Ok(selection)
    }

    async fn reconcile_selection(
        &self,
        selection: PlatformPluginAuthoritySelectionV2,
    ) -> Result<SelectionReconcileOutcomeV2, String> {
        let (response_tx, response_rx) = oneshot::channel();
        self.selection_tx
            .send(SelectionReconcileCommandV2 {
                selection,
                response: response_tx,
            })
            .await
            .map_err(|_| "platform plugin authority reconciler is unavailable".to_string())?;
        response_rx.await.map_err(|_| {
            "platform plugin authority reconciler stopped before selection".to_string()
        })?
    }

    pub(crate) async fn shutdown(self) {
        let _ = self.shutdown.send(true);
        let _ = self.task.await;
    }
}

async fn reconcile_loop(
    state: Arc<LocalRuntimeState>,
    plugin_data_plane_credentials_v2: PluginDataPlaneCredentialBrokerV2,
    mut control: ReconcileLoopControlV2,
    mut reconciler: PluginSnapshotReconcilerV2,
    mut active_authority: Option<DesktopAuthoritySourceV2>,
    intervals: ReconcileIntervalsV2,
) {
    let mut error_interval = intervals.initial_error;
    let mut next_interval = intervals.success;

    loop {
        let requested_selection = tokio::select! {
            biased;
            _ = control.shutdown_rx.changed() => break,
            command = control.selection_rx.recv() => {
                let Some(command) = command else { break };
                Some(command)
            }
            _ = tokio::time::sleep(next_interval) => None,
        };

        let (expected_selection, response) = match requested_selection {
            Some(command) => (command.selection, Some(command.response)),
            None => match lock_selection(&control.selection) {
                Ok(current) => (*current, None),
                Err(error) => {
                    log_reconcile_failure(&error);
                    next_interval = error_interval;
                    error_interval =
                        std::cmp::min(error_interval.saturating_mul(2), MAX_ERROR_INTERVAL);
                    continue;
                }
            },
        };

        let transition = reconcile_selected_authority(
            &state,
            &plugin_data_plane_credentials_v2,
            &control.selection,
            expected_selection,
            &mut reconciler,
            &mut active_authority,
        )
        .await;
        let transition = match transition {
            Ok(SelectionReconcileOutcomeV2::Applied)
                if !selection_is_current(&control.selection, expected_selection)
                    .unwrap_or(false) =>
            {
                Ok(SelectionReconcileOutcomeV2::Superseded)
            }
            other => other,
        };
        if let Some(response) = response {
            let _ = response.send(transition.clone());
        }

        let result = match transition {
            Ok(SelectionReconcileOutcomeV2::Applied) => {
                poll_selected_authority(
                    &state,
                    &plugin_data_plane_credentials_v2,
                    &control.selection,
                    expected_selection,
                    &mut reconciler,
                )
                .await
            }
            Ok(SelectionReconcileOutcomeV2::Superseded) => {
                next_interval = Duration::ZERO;
                continue;
            }
            Err(error) => Err(error),
        };
        match result {
            Ok(()) => {
                error_interval = intervals.initial_error;
                next_interval = intervals.success;
            }
            Err(error) => {
                log_reconcile_failure(&error);
                next_interval = error_interval;
                error_interval =
                    std::cmp::min(error_interval.saturating_mul(2), MAX_ERROR_INTERVAL);
            }
        }
    }
    state.platform_plugin_authority_v2.deactivate().await;
}

fn log_reconcile_failure(error: &str) {
    tracing::warn!(
        error,
        data_plane_id = DATA_PLANE_ID,
        "protocol-v2 platform plugin control-plane poll failed"
    );
}

fn desktop_reconciler(state: &LocalRuntimeState) -> PluginSnapshotReconcilerV2 {
    PluginSnapshotReconcilerV2::new_with_manager(
        desktop_loader(
            state.app_data_dir.clone(),
            state.local_knowledge_acceptance.clone(),
        ),
        state.platform_plugin_authority_v2.manager(),
    )
}

fn desktop_loader(
    app_data_dir: Option<std::path::PathBuf>,
    local_acceptance: Option<crate::local_knowledge_acceptance::LocalKnowledgeAcceptance>,
) -> LoaderV2 {
    LoaderV2::for_target(
        DataPlaneTargetV2::DesktopSidecar,
        [
            desktop_sidecar_http_routes_definition_v2(),
            desktop_sidecar_host_definition_v2(),
            super::knowledge_authority_v2::definition(app_data_dir, local_acceptance)
                .expect("the built-in knowledge contract is statically valid"),
        ],
    )
}

struct LocalBootstrapSnapshotV2 {
    snapshot: ProfileSnapshotV2,
    snapshot_wire: Value,
}

fn local_bootstrap_snapshot(state: &LocalRuntimeState) -> Result<LocalBootstrapSnapshotV2, String> {
    let source = if let Some(qualification) = &state.local_knowledge_acceptance {
        qualification.require_current(
            state
                .app_data_dir
                .as_deref()
                .ok_or("local acceptance data root missing")?,
            &state
                .workspace_root
                .lock()
                .map_err(|_| "local acceptance workspace unavailable")?,
        )?;
        qualification.snapshot()
    } else {
        LOCAL_BOOTSTRAP_PROFILE_V2
    };
    let snapshot = parse_profile_snapshot_v2(source).map_err(|error| error.to_string())?;
    let snapshot_wire = serde_json::from_str(source).map_err(|error| error.to_string())?;
    Ok(LocalBootstrapSnapshotV2 {
        snapshot,
        snapshot_wire,
    })
}

async fn activate_authority_source(
    state: &LocalRuntimeState,
    reconciler: &mut PluginSnapshotReconcilerV2,
    source: &DesktopAuthoritySourceV2,
) -> Result<(), String> {
    match source {
        DesktopAuthoritySourceV2::Cloud(fingerprint) => {
            let Some(distribution) = restore_last_good(state, fingerprint)? else {
                state.platform_plugin_authority_v2.deactivate().await;
                reconciler.reset_publication_ordering();
                return Ok(());
            };
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
        DesktopAuthoritySourceV2::Local => {
            let baseline = local_bootstrap_snapshot(state)?;
            let generation = reconciler
                .stage_snapshot(baseline.snapshot.clone())
                .await
                .map_err(|error| error.to_string())?;
            state
                .platform_plugin_authority_v2
                .publish_local_baseline(&baseline.snapshot, &baseline.snapshot_wire, generation)
                .await;
            reconciler.reset_publication_ordering();
        }
    }
    Ok(())
}

async fn reconcile_selected_authority(
    state: &LocalRuntimeState,
    plugin_data_plane_credentials_v2: &PluginDataPlaneCredentialBrokerV2,
    selection: &Mutex<PlatformPluginAuthoritySelectionV2>,
    expected_selection: PlatformPluginAuthoritySelectionV2,
    reconciler: &mut PluginSnapshotReconcilerV2,
    active_authority: &mut Option<DesktopAuthoritySourceV2>,
) -> Result<SelectionReconcileOutcomeV2, String> {
    if !selection_is_current(selection, expected_selection)? {
        return Ok(SelectionReconcileOutcomeV2::Superseded);
    }
    let desired_authority = match expected_selection.mode {
        PlatformPluginAuthorityModeV2::Local => Some(DesktopAuthoritySourceV2::Local),
        PlatformPluginAuthorityModeV2::Cloud => {
            match load_plugin_data_plane_authority_v2(plugin_data_plane_credentials_v2) {
                Ok(Some(authority)) => Some(DesktopAuthoritySourceV2::Cloud(
                    authority.fingerprint.clone(),
                )),
                Ok(None) => None,
                Err(error) => {
                    let outcome =
                        deactivate_for_selection(state, selection, expected_selection).await?;
                    if outcome == SelectionReconcileOutcomeV2::Applied {
                        *active_authority = None;
                        reconciler.reset_publication_ordering();
                        return Err(error);
                    }
                    return Ok(outcome);
                }
            }
        }
    };
    if *active_authority == desired_authority {
        return Ok(SelectionReconcileOutcomeV2::Applied);
    }

    let outcome = match desired_authority.as_ref() {
        Some(source) => {
            match activate_authority_source_for_selection(
                state,
                reconciler,
                source,
                selection,
                expected_selection,
            )
            .await
            {
                Ok(outcome) => outcome,
                Err(error) => {
                    let outcome =
                        deactivate_for_selection(state, selection, expected_selection).await?;
                    if outcome == SelectionReconcileOutcomeV2::Applied {
                        *active_authority = None;
                        reconciler.reset_publication_ordering();
                        return Err(error);
                    }
                    return Ok(outcome);
                }
            }
        }
        None => deactivate_for_selection(state, selection, expected_selection).await?,
    };
    if outcome == SelectionReconcileOutcomeV2::Applied {
        *active_authority = desired_authority;
        if active_authority.is_none() {
            reconciler.reset_publication_ordering();
        }
    }
    Ok(outcome)
}

async fn activate_authority_source_for_selection(
    state: &LocalRuntimeState,
    reconciler: &mut PluginSnapshotReconcilerV2,
    source: &DesktopAuthoritySourceV2,
    selection: &Mutex<PlatformPluginAuthoritySelectionV2>,
    expected_selection: PlatformPluginAuthoritySelectionV2,
) -> Result<SelectionReconcileOutcomeV2, String> {
    match source {
        DesktopAuthoritySourceV2::Cloud(fingerprint) => {
            let Some(distribution) = restore_last_good(state, fingerprint)? else {
                let outcome =
                    deactivate_for_selection(state, selection, expected_selection).await?;
                if outcome == SelectionReconcileOutcomeV2::Applied {
                    reconciler.reset_publication_ordering();
                }
                return Ok(outcome);
            };
            let generation = reconciler
                .stage_snapshot(distribution.snapshot.clone())
                .await
                .map_err(|error| error.to_string())?;
            let retirement = begin_selected_publication(selection, expected_selection, || {
                state
                    .platform_plugin_authority_v2
                    .replace_distribution(&distribution, Arc::clone(&generation))
            });
            let retirement = match retirement {
                Ok(retirement) => retirement,
                Err(error) => {
                    reconciler.discard_staged_snapshot(generation).await;
                    return Err(error);
                }
            };
            let Some(retirement) = retirement else {
                reconciler.discard_staged_snapshot(generation).await;
                return Ok(SelectionReconcileOutcomeV2::Superseded);
            };
            drop(generation);
            retirement.dispose().await;
            reconciler.restore_publication_ordering(
                distribution.envelope.version,
                distribution.snapshot.digest,
            );
        }
        DesktopAuthoritySourceV2::Local => {
            let baseline = local_bootstrap_snapshot(state)?;
            let generation = reconciler
                .stage_snapshot(baseline.snapshot.clone())
                .await
                .map_err(|error| error.to_string())?;
            let retirement = begin_selected_publication(selection, expected_selection, || {
                state.platform_plugin_authority_v2.replace_local_baseline(
                    &baseline.snapshot,
                    &baseline.snapshot_wire,
                    Arc::clone(&generation),
                )
            });
            let retirement = match retirement {
                Ok(retirement) => retirement,
                Err(error) => {
                    reconciler.discard_staged_snapshot(generation).await;
                    return Err(error);
                }
            };
            let Some(retirement) = retirement else {
                reconciler.discard_staged_snapshot(generation).await;
                return Ok(SelectionReconcileOutcomeV2::Superseded);
            };
            drop(generation);
            retirement.dispose().await;
            reconciler.reset_publication_ordering();
        }
    }
    Ok(SelectionReconcileOutcomeV2::Applied)
}

async fn deactivate_for_selection(
    state: &LocalRuntimeState,
    selection: &Mutex<PlatformPluginAuthoritySelectionV2>,
    expected_selection: PlatformPluginAuthoritySelectionV2,
) -> Result<SelectionReconcileOutcomeV2, String> {
    let retirement = match selection.lock() {
        Ok(current) if *current == expected_selection => {
            Some(state.platform_plugin_authority_v2.retire_current())
        }
        Ok(_) => None,
        Err(_) => {
            return Err("platform plugin authority selection state is unavailable".into());
        }
    };
    let Some(retirement) = retirement else {
        return Ok(SelectionReconcileOutcomeV2::Superseded);
    };
    retirement.dispose().await;
    Ok(SelectionReconcileOutcomeV2::Applied)
}

async fn poll_selected_authority(
    state: &LocalRuntimeState,
    plugin_data_plane_credentials_v2: &PluginDataPlaneCredentialBrokerV2,
    selection: &Mutex<PlatformPluginAuthoritySelectionV2>,
    expected_selection: PlatformPluginAuthoritySelectionV2,
    reconciler: &mut PluginSnapshotReconcilerV2,
) -> Result<(), String> {
    if expected_selection.mode == PlatformPluginAuthorityModeV2::Local
        || !selection_is_current(selection, expected_selection)?
    {
        return Ok(());
    }
    let Some(authority) = load_plugin_data_plane_authority_v2(plugin_data_plane_credentials_v2)?
    else {
        return Ok(());
    };
    reconcile_once(
        state,
        plugin_data_plane_credentials_v2,
        &authority,
        selection,
        expected_selection,
        reconciler,
    )
    .await
}

fn selection_is_current(
    selection: &Mutex<PlatformPluginAuthoritySelectionV2>,
    expected_selection: PlatformPluginAuthoritySelectionV2,
) -> Result<bool, String> {
    lock_selection(selection).map(|current| *current == expected_selection)
}

fn begin_selected_publication<F>(
    selection: &Mutex<PlatformPluginAuthoritySelectionV2>,
    expected_selection: PlatformPluginAuthoritySelectionV2,
    publish: F,
) -> Result<Option<GenerationRetirementV2>, String>
where
    F: FnOnce() -> GenerationRetirementV2,
{
    let current = lock_selection(selection)?;
    if *current != expected_selection {
        return Ok(None);
    }
    Ok(Some(publish()))
}

#[allow(clippy::too_many_arguments)]
fn begin_selected_cloud_publication(
    state: &LocalRuntimeState,
    plugin_data_plane_credentials_v2: &PluginDataPlaneCredentialBrokerV2,
    authority: &CloudAuthorityV2,
    selection: &Mutex<PlatformPluginAuthoritySelectionV2>,
    expected_selection: PlatformPluginAuthoritySelectionV2,
    distribution: &ControlPlaneDistributionV2,
    receipt: &SnapshotApplyReceiptV2,
    generation: Arc<agistack_plugin_host::RuntimeGenerationV2>,
) -> Result<Option<GenerationRetirementV2>, String> {
    let current = lock_selection(selection)?;
    if *current != expected_selection
        || !plugin_data_plane_authority_is_current_v2(
            plugin_data_plane_credentials_v2,
            &authority.configuration_fingerprint,
        )?
    {
        return Ok(None);
    }
    persist_receipt(state, authority, distribution, receipt)?;
    Ok(Some(
        state
            .platform_plugin_authority_v2
            .replace_distribution(distribution, generation),
    ))
}

fn lock_selection(
    selection: &Mutex<PlatformPluginAuthoritySelectionV2>,
) -> Result<std::sync::MutexGuard<'_, PlatformPluginAuthoritySelectionV2>, String> {
    selection
        .lock()
        .map_err(|_| "platform plugin authority selection state is unavailable".to_string())
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
        configuration_fingerprint: fingerprint.clone(),
        fingerprint,
        ack_participation: false,
    }))
}

fn load_plugin_data_plane_authority_v2(
    plugin_data_plane_credentials_v2: &PluginDataPlaneCredentialBrokerV2,
) -> Result<Option<CloudAuthorityV2>, String> {
    let Some(mut record) = plugin_data_plane_credentials_v2
        .load()
        .map_err(|error| error.to_string())?
    else {
        return Ok(None);
    };
    let base_url = validate_base_url_v2(&record.api_base_url)
        .map_err(|()| "plugin data-plane API base URL is invalid".to_string())?;
    let fingerprint =
        data_plane_authority_fingerprint_v2(&base_url, record.data_plane_id.as_str())?;
    let configuration_fingerprint = data_plane_configuration_fingerprint_v2(&fingerprint, &record)?;
    let credential = std::mem::take(&mut record.credential);
    Ok(Some(CloudAuthorityV2 {
        base_url,
        credential,
        fingerprint,
        configuration_fingerprint,
        ack_participation: record.ack_participation,
    }))
}

fn authority_fingerprint(base_url: &Url, credential: &str) -> Result<String, String> {
    let normalized_base_url = normalized_cloud_base_url(base_url);
    let identity = Zeroizing::new(
        serde_json::to_vec(&(
            "memstack-platform-plugin-authority-v2",
            normalized_base_url,
            credential,
        ))
        .map_err(|_| "plugin v2 authority identity could not be encoded".to_string())?,
    );
    Ok(format!("sha256:{:x}", Sha256::digest(identity.as_slice())))
}

fn data_plane_authority_fingerprint_v2(
    base_url: &Url,
    data_plane_id: &str,
) -> Result<String, String> {
    let identity = serde_json::to_vec(&(
        "memstack-platform-plugin-data-plane-authority-v2",
        normalized_cloud_base_url(base_url),
        data_plane_id,
    ))
    .map_err(|_| "plugin v2 data-plane authority identity could not be encoded".to_string())?;
    Ok(format!("sha256:{:x}", Sha256::digest(identity)))
}

fn data_plane_configuration_fingerprint_v2(
    authority_fingerprint: &str,
    record: &PluginDataPlaneCredentialRecordV2,
) -> Result<String, String> {
    let identity = Zeroizing::new(
        serde_json::to_vec(&(
            "memstack-platform-plugin-data-plane-configuration-v2",
            authority_fingerprint,
            record.credential.as_str(),
            record.ack_participation,
        ))
        .map_err(|_| "plugin v2 data-plane configuration could not be encoded".to_string())?,
    );
    Ok(format!("sha256:{:x}", Sha256::digest(identity.as_slice())))
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
    plugin_data_plane_credentials_v2: &PluginDataPlaneCredentialBrokerV2,
    authority: &CloudAuthorityV2,
    selection: &Mutex<PlatformPluginAuthoritySelectionV2>,
    expected_selection: PlatformPluginAuthoritySelectionV2,
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
    if !selected_cloud_authority_is_current(
        plugin_data_plane_credentials_v2,
        &authority.configuration_fingerprint,
        selection,
        expected_selection,
    )? {
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
            if !selected_cloud_authority_is_current(
                plugin_data_plane_credentials_v2,
                &authority.configuration_fingerprint,
                selection,
                expected_selection,
            )? {
                return Ok(());
            }
            persist_receipt(state, authority, &distribution, &receipt)?;
            receipt
        }
        SnapshotPreparationV2::Ready(prepared) => {
            if !selected_cloud_authority_is_current(
                plugin_data_plane_credentials_v2,
                &authority.configuration_fingerprint,
                selection,
                expected_selection,
            )? {
                prepared.discard().await;
                return Ok(());
            }
            let durable_receipt = prepared.receipt();
            let expected_manager = state.platform_plugin_authority_v2.manager();
            let distribution_for_publish = distribution.clone();
            let durable_receipt_for_publish = durable_receipt.clone();
            let receipt = prepared
                .commit_try_if_with(|manager, generation| async move {
                    debug_assert!(Arc::ptr_eq(&manager, &expected_manager));
                    let retirement = begin_selected_cloud_publication(
                        state,
                        plugin_data_plane_credentials_v2,
                        authority,
                        selection,
                        expected_selection,
                        &distribution_for_publish,
                        &durable_receipt_for_publish,
                        generation,
                    )?;
                    let Some(retirement) = retirement else {
                        return Ok::<bool, String>(false);
                    };
                    retirement.dispose().await;
                    Ok::<bool, String>(true)
                })
                .await?;
            let Some(receipt) = receipt else {
                selection_is_current(selection, expected_selection)?;
                return Ok(());
            };
            debug_assert_eq!(receipt, durable_receipt);
            receipt
        }
    };
    if authority.ack_participation {
        post_receipt(
            &client,
            &authority.base_url,
            authority.credential.as_str(),
            &distribution,
            &receipt,
        )
        .await?;
    }
    Ok(())
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

fn plugin_data_plane_authority_is_current_v2(
    plugin_data_plane_credentials_v2: &PluginDataPlaneCredentialBrokerV2,
    expected_configuration_fingerprint: &str,
) -> Result<bool, String> {
    load_plugin_data_plane_authority_v2(plugin_data_plane_credentials_v2).map(|authority| {
        authority.as_ref().is_some_and(|authority| {
            authority.configuration_fingerprint == expected_configuration_fingerprint
        })
    })
}

fn selected_cloud_authority_is_current(
    plugin_data_plane_credentials_v2: &PluginDataPlaneCredentialBrokerV2,
    expected_configuration_fingerprint: &str,
    selection: &Mutex<PlatformPluginAuthoritySelectionV2>,
    expected_selection: PlatformPluginAuthoritySelectionV2,
) -> Result<bool, String> {
    Ok(selection_is_current(selection, expected_selection)?
        && plugin_data_plane_authority_is_current_v2(
            plugin_data_plane_credentials_v2,
            expected_configuration_fingerprint,
        )?)
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
    use axum::{
        extract::State,
        http::{header::AUTHORIZATION, HeaderMap, Method, StatusCode},
        routing::{get, post},
        Json, Router,
    };
    use serde_json::{json, Value};
    use tokio::{
        io::{AsyncReadExt, AsyncWriteExt},
        net::TcpListener,
        sync::oneshot,
        task::JoinHandle,
    };
    use uuid::Uuid;

    use crate::plugin_data_plane_credential_v2::{
        PluginDataPlaneCredentialStoreErrorV2, PluginDataPlaneCredentialStoreV2,
    };

    use super::super::session_store::DesktopSessionStore;
    use super::*;

    const BOOTSTRAP: &str =
        include_str!("../../../../../../shared/profiles/memstack-default-bootstrap.v2.json");
    const CLOUD_AUTHORITY: &str =
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    #[derive(Default)]
    struct InMemoryPluginDataPlaneCredentialStoreV2 {
        raw: Mutex<Option<String>>,
    }

    impl PluginDataPlaneCredentialStoreV2 for InMemoryPluginDataPlaneCredentialStoreV2 {
        fn save_raw(&self, value: &str) -> Result<(), PluginDataPlaneCredentialStoreErrorV2> {
            *self
                .raw
                .lock()
                .map_err(|_| PluginDataPlaneCredentialStoreErrorV2::Unavailable)? =
                Some(value.to_owned());
            Ok(())
        }

        fn load_raw(&self) -> Result<Option<String>, PluginDataPlaneCredentialStoreErrorV2> {
            self.raw
                .lock()
                .map(|raw| raw.clone())
                .map_err(|_| PluginDataPlaneCredentialStoreErrorV2::Unavailable)
        }

        fn clear_raw(&self) -> Result<(), PluginDataPlaneCredentialStoreErrorV2> {
            self.raw
                .lock()
                .map(|mut raw| raw.take())
                .map(|_| ())
                .map_err(|_| PluginDataPlaneCredentialStoreErrorV2::Unavailable)
        }
    }

    #[derive(Clone, Debug, Eq, PartialEq)]
    struct DataPlaneRequestV2 {
        method: Method,
        authorization: Option<String>,
        body: Option<Value>,
    }

    #[derive(Clone)]
    struct MockDataPlaneV2 {
        distribution: Value,
        requests: Arc<Mutex<Vec<DataPlaneRequestV2>>>,
    }

    impl MockDataPlaneV2 {
        fn requests(&self) -> Vec<DataPlaneRequestV2> {
            self.requests
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .clone()
        }

        fn record(&self, request: DataPlaneRequestV2) {
            self.requests
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .push(request);
        }
    }

    async fn serve_distribution_v2(
        State(data_plane): State<MockDataPlaneV2>,
        headers: HeaderMap,
    ) -> (StatusCode, Json<Value>) {
        data_plane.record(DataPlaneRequestV2 {
            method: Method::GET,
            authorization: authorization_v2(&headers),
            body: None,
        });
        (StatusCode::OK, Json(data_plane.distribution.clone()))
    }

    async fn receive_receipt_v2(
        State(data_plane): State<MockDataPlaneV2>,
        headers: HeaderMap,
        Json(body): Json<Value>,
    ) -> StatusCode {
        data_plane.record(DataPlaneRequestV2 {
            method: Method::POST,
            authorization: authorization_v2(&headers),
            body: Some(body),
        });
        StatusCode::NO_CONTENT
    }

    fn authorization_v2(headers: &HeaderMap) -> Option<String> {
        headers
            .get(AUTHORIZATION)
            .and_then(|value| value.to_str().ok())
            .map(str::to_owned)
    }

    async fn spawn_data_plane_v2(
        distribution: &ControlPlaneDistributionV2,
    ) -> (String, MockDataPlaneV2, oneshot::Sender<()>, JoinHandle<()>) {
        let data_plane = MockDataPlaneV2 {
            distribution: serde_json::to_value(distribution).expect("distribution JSON"),
            requests: Arc::new(Mutex::new(Vec::new())),
        };
        let app = Router::new()
            .route(
                "/control/api/v1/platform-plugins/v2/distribution",
                get(serve_distribution_v2),
            )
            .route(
                "/control/api/v1/platform-plugins/v2/data-plane-state",
                post(receive_receipt_v2),
            )
            .with_state(data_plane.clone());
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("mock data-plane listener");
        let address = listener.local_addr().expect("mock data-plane address");
        let (shutdown, shutdown_rx) = oneshot::channel();
        let task = tokio::spawn(async move {
            axum::serve(listener, app)
                .with_graceful_shutdown(async {
                    let _ = shutdown_rx.await;
                })
                .await
                .expect("mock data-plane server");
        });
        (
            format!("http://{address}/control"),
            data_plane,
            shutdown,
            task,
        )
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

    fn plugin_data_plane_credentials_v2() -> PluginDataPlaneCredentialBrokerV2 {
        PluginDataPlaneCredentialBrokerV2::new(Arc::new(
            InMemoryPluginDataPlaneCredentialStoreV2::default(),
        ))
    }

    fn plugin_data_plane_record_v2(
        api_base_url: &str,
        credential_fill: char,
        ack_participation: bool,
    ) -> PluginDataPlaneCredentialRecordV2 {
        PluginDataPlaneCredentialRecordV2 {
            version: 2,
            api_base_url: api_base_url.to_owned(),
            data_plane_id: DATA_PLANE_ID.to_owned(),
            credential: format!("ms_dp_{}", credential_fill.to_string().repeat(64)),
            ack_participation,
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
    async fn workload_credential_rotation_preserves_last_good_and_uses_the_new_bearer() {
        let distribution = bootstrap_distribution(23, "workload-credential-rotation");
        let (api_base_url, data_plane, shutdown, task) = spawn_data_plane_v2(&distribution).await;
        let state = test_state();
        let plugin_data_plane_credentials_v2 = plugin_data_plane_credentials_v2();
        let first_secret = format!("ms_dp_{}", "d".repeat(64));
        let second_secret = format!("ms_dp_{}", "e".repeat(64));
        let first_record = plugin_data_plane_record_v2(&api_base_url, 'd', false);
        assert_eq!(first_record.credential, first_secret);
        plugin_data_plane_credentials_v2
            .save(&first_record)
            .expect("first data-plane credential");
        let first = load_plugin_data_plane_authority_v2(&plugin_data_plane_credentials_v2)
            .expect("first data-plane authority")
            .expect("first data-plane authority record");
        let stable_fingerprint = first.fingerprint.clone();
        let first_configuration = first.configuration_fingerprint.clone();
        drop(first);
        let receipt = SnapshotApplyReceiptV2 {
            status: ApplyStatusV2::Ack,
            requested_version: distribution.envelope.version,
            requested_digest: distribution.snapshot.digest.clone(),
            applied_version: Some(distribution.envelope.version),
            applied_digest: Some(distribution.snapshot.digest.clone()),
            error_code: None,
            error_message: None,
        };
        {
            let mut connection = state.session_store.connection().expect("session store");
            plugin_snapshots_v2::initialize_schema(&connection).expect("plugin snapshot schema");
            plugin_snapshots_v2::record_requested(&connection, &stable_fingerprint, &distribution)
                .expect("requested distribution");
            plugin_snapshots_v2::record_receipt(
                &mut connection,
                &stable_fingerprint,
                &distribution.envelope.nonce,
                &receipt,
            )
            .expect("last-good receipt");
        }
        let mut reconciler = desktop_reconciler(&state);
        activate_authority_source(
            &state,
            &mut reconciler,
            &DesktopAuthoritySourceV2::Cloud(stable_fingerprint.clone()),
        )
        .await
        .expect("persisted last-good activation");

        drop(first_record);
        let rotated_record = plugin_data_plane_record_v2(&api_base_url, 'e', false);
        assert_eq!(rotated_record.credential, second_secret);
        plugin_data_plane_credentials_v2
            .save(&rotated_record)
            .expect("rotated data-plane credential");
        let rotated = load_plugin_data_plane_authority_v2(&plugin_data_plane_credentials_v2)
            .expect("rotated data-plane authority")
            .expect("rotated data-plane authority record");

        assert_eq!(rotated.fingerprint, stable_fingerprint);
        assert_ne!(rotated.configuration_fingerprint, first_configuration);
        assert!(!rotated.fingerprint.contains(&first_secret));
        assert!(!rotated.fingerprint.contains(&second_secret));
        assert_eq!(
            restore_last_good(&state, &rotated.fingerprint).expect("rotated last-good read"),
            Some(distribution.clone())
        );
        assert!(!plugin_data_plane_authority_is_current_v2(
            &plugin_data_plane_credentials_v2,
            &first_configuration,
        )
        .expect("configuration currency"));
        let expected_selection = PlatformPluginAuthoritySelectionV2 {
            mode: PlatformPluginAuthorityModeV2::Cloud,
            epoch: 1,
        };
        let selection = Mutex::new(expected_selection);

        reconcile_once(
            &state,
            &plugin_data_plane_credentials_v2,
            &rotated,
            &selection,
            expected_selection,
            &mut reconciler,
        )
        .await
        .expect("rotated workload reconcile");

        assert_eq!(
            data_plane.requests(),
            vec![DataPlaneRequestV2 {
                method: Method::GET,
                authorization: Some(format!("Bearer {second_secret}")),
                body: None,
            }]
        );
        assert_eq!(
            state
                .platform_plugin_authority_v2
                .acquire_generation()
                .expect("last-good generation after rotation")
                .descriptor()
                .publication_version,
            Some(23)
        );

        let _ = shutdown.send(());
        task.await.expect("mock data-plane task");
        reconciler.close().await;
        state.platform_plugin_authority_v2.deactivate().await;
    }

    #[tokio::test]
    async fn workload_poll_uses_dedicated_bearer_and_skips_receipt_by_default() {
        let distribution = bootstrap_distribution(21, "workload-default-no-ack");
        let (api_base_url, data_plane, shutdown, task) = spawn_data_plane_v2(&distribution).await;
        let state = test_state();
        let plugin_data_plane_credentials_v2 = plugin_data_plane_credentials_v2();
        let record = plugin_data_plane_record_v2(&api_base_url, 'f', false);
        let credential = record.credential.clone();
        plugin_data_plane_credentials_v2
            .save(&record)
            .expect("data-plane credential");
        let authority = load_plugin_data_plane_authority_v2(&plugin_data_plane_credentials_v2)
            .expect("data-plane authority")
            .expect("data-plane authority record");
        let expected_selection = PlatformPluginAuthoritySelectionV2 {
            mode: PlatformPluginAuthorityModeV2::Cloud,
            epoch: 1,
        };
        let selection = Mutex::new(expected_selection);
        let mut reconciler = desktop_reconciler(&state);

        reconcile_once(
            &state,
            &plugin_data_plane_credentials_v2,
            &authority,
            &selection,
            expected_selection,
            &mut reconciler,
        )
        .await
        .expect("workload distribution reconcile");

        assert_eq!(
            data_plane.requests(),
            vec![DataPlaneRequestV2 {
                method: Method::GET,
                authorization: Some(format!("Bearer {credential}")),
                body: None,
            }]
        );
        assert_eq!(
            state
                .platform_plugin_authority_v2
                .acquire_generation()
                .expect("published data-plane generation")
                .descriptor()
                .publication_version,
            Some(21)
        );

        let _ = shutdown.send(());
        task.await.expect("mock data-plane task");
        reconciler.close().await;
        state.platform_plugin_authority_v2.deactivate().await;
    }

    #[tokio::test]
    async fn explicit_ack_participation_posts_the_exact_workload_receipt() {
        let distribution = bootstrap_distribution(22, "workload-explicit-ack");
        let expected_digest = distribution.snapshot.digest.clone();
        let (api_base_url, data_plane, shutdown, task) = spawn_data_plane_v2(&distribution).await;
        let state = test_state();
        let plugin_data_plane_credentials_v2 = plugin_data_plane_credentials_v2();
        let record = plugin_data_plane_record_v2(&api_base_url, 'a', true);
        let credential = record.credential.clone();
        plugin_data_plane_credentials_v2
            .save(&record)
            .expect("data-plane credential");
        let authority = load_plugin_data_plane_authority_v2(&plugin_data_plane_credentials_v2)
            .expect("data-plane authority")
            .expect("data-plane authority record");
        let expected_selection = PlatformPluginAuthoritySelectionV2 {
            mode: PlatformPluginAuthorityModeV2::Cloud,
            epoch: 1,
        };
        let selection = Mutex::new(expected_selection);
        let mut reconciler = desktop_reconciler(&state);

        reconcile_once(
            &state,
            &plugin_data_plane_credentials_v2,
            &authority,
            &selection,
            expected_selection,
            &mut reconciler,
        )
        .await
        .expect("workload distribution reconcile");

        let requests = data_plane.requests();
        assert_eq!(requests.len(), 2);
        assert_eq!(requests[0].method, Method::GET);
        assert_eq!(
            requests[0].authorization,
            Some(format!("Bearer {credential}"))
        );
        assert_eq!(requests[1].method, Method::POST);
        assert_eq!(
            requests[1].authorization,
            Some(format!("Bearer {credential}"))
        );
        assert_eq!(
            requests[1].body,
            Some(json!({
                "schema_version": 2,
                "data_plane_id": "desktop-sidecar-v2",
                "nonce": "workload-explicit-ack",
                "receipt": {
                    "status": "ack",
                    "requested_version": 22,
                    "requested_digest": expected_digest,
                    "applied_version": 22,
                    "applied_digest": expected_digest,
                    "error_code": null,
                    "error_message": null,
                },
            }))
        );

        let _ = shutdown.send(());
        task.await.expect("mock data-plane task");
        reconciler.close().await;
        state.platform_plugin_authority_v2.deactivate().await;
    }

    #[tokio::test]
    async fn local_bootstrap_is_active_before_control_plane_start_returns() {
        let state = test_state();
        let plugin_data_plane_credentials_v2 = plugin_data_plane_credentials_v2();

        let control_plane = PlatformPluginControlPlaneReconcilerV2::start_with_intervals(
            Arc::clone(&state),
            plugin_data_plane_credentials_v2,
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
    async fn explicit_local_selection_ignores_an_existing_data_plane_credential() {
        let state = test_state();
        let plugin_data_plane_credentials_v2 = plugin_data_plane_credentials_v2();
        plugin_data_plane_credentials_v2
            .save(&plugin_data_plane_record_v2(
                "https://example.com",
                'a',
                false,
            ))
            .expect("data-plane credential");
        let control_plane = PlatformPluginControlPlaneReconcilerV2::start_with_intervals(
            Arc::clone(&state),
            plugin_data_plane_credentials_v2,
            Duration::from_secs(3600),
            Duration::from_secs(3600),
        )
        .await
        .expect("control plane must start");

        control_plane
            .select(PlatformPluginAuthorityModeV2::Local)
            .await
            .expect("local authority must select");

        let lease = state
            .platform_plugin_authority_v2
            .acquire_generation()
            .expect("local generation must remain active");
        assert_eq!(lease.descriptor().publication_version, None);
        drop(lease);
        control_plane.shutdown().await;
    }

    #[tokio::test]
    async fn selected_cloud_without_a_record_never_falls_back_to_local() {
        let state = test_state();
        let plugin_data_plane_credentials_v2 = plugin_data_plane_credentials_v2();
        let control_plane = PlatformPluginControlPlaneReconcilerV2::start_with_intervals(
            Arc::clone(&state),
            plugin_data_plane_credentials_v2,
            Duration::from_secs(3600),
            Duration::from_secs(3600),
        )
        .await
        .expect("control plane must start");

        control_plane
            .select(PlatformPluginAuthorityModeV2::Cloud)
            .await
            .expect("cloud mode selection must be accepted");

        assert!(state
            .platform_plugin_authority_v2
            .acquire_generation()
            .is_err());
        control_plane.shutdown().await;
    }

    #[tokio::test]
    async fn queued_selection_commands_supersede_old_epochs_and_apply_the_latest_mode() {
        let state = test_state();
        let plugin_data_plane_credentials_v2 = plugin_data_plane_credentials_v2();
        let control_plane = PlatformPluginControlPlaneReconcilerV2::start_with_intervals(
            Arc::clone(&state),
            plugin_data_plane_credentials_v2,
            Duration::from_secs(3600),
            Duration::from_secs(3600),
        )
        .await
        .expect("control plane must start");

        let old = control_plane
            .advance_selection(PlatformPluginAuthorityModeV2::Cloud)
            .expect("cloud selection must advance");
        let latest = control_plane
            .advance_selection(PlatformPluginAuthorityModeV2::Local)
            .expect("local selection must advance");
        let (old_outcome, latest_outcome) = tokio::join!(
            control_plane.reconcile_selection(old),
            control_plane.reconcile_selection(latest),
        );

        assert_eq!(
            old_outcome.expect("old command must receive a response"),
            SelectionReconcileOutcomeV2::Superseded
        );
        assert_eq!(
            latest_outcome.expect("latest command must receive a response"),
            SelectionReconcileOutcomeV2::Applied
        );
        let lease = state
            .platform_plugin_authority_v2
            .acquire_generation()
            .expect("latest local selection must remain active");
        assert_eq!(lease.descriptor().publication_version, None);
        drop(lease);
        control_plane.shutdown().await;
    }

    #[tokio::test]
    async fn cloud_refresh_activates_its_scoped_last_good_after_the_credential_appears() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("test control plane must bind");
        let api_base_url = format!(
            "http://{}",
            listener.local_addr().expect("test listener address")
        );
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.expect("distribution request");
            let mut request = [0_u8; 2048];
            let _ = stream.read(&mut request).await.expect("request bytes");
            stream
                .write_all(
                    b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                )
                .await
                .expect("404 response");
        });
        let state = test_state();
        let plugin_data_plane_credentials_v2 = plugin_data_plane_credentials_v2();
        let record = plugin_data_plane_record_v2(&api_base_url, 'b', false);
        let base_url = validate_base_url_v2(&record.api_base_url).expect("cloud base URL");
        let fingerprint = data_plane_authority_fingerprint_v2(&base_url, &record.data_plane_id)
            .expect("authority fingerprint");
        let distribution = bootstrap_distribution(8, "cloud-session-appeared");
        let mut seed = PluginSnapshotReconcilerV2::new(desktop_loader(None, None));
        let receipt = seed.apply(&distribution).await;
        assert_eq!(receipt.status, ApplyStatusV2::Ack);
        {
            let mut connection = state.session_store.connection().expect("session store");
            plugin_snapshots_v2::initialize_schema(&connection).expect("plugin snapshot schema");
            plugin_snapshots_v2::record_requested(&connection, &fingerprint, &distribution)
                .expect("requested distribution");
            plugin_snapshots_v2::record_receipt(
                &mut connection,
                &fingerprint,
                &distribution.envelope.nonce,
                &receipt,
            )
            .expect("last-good receipt");
        }
        seed.close().await;
        let control_plane = PlatformPluginControlPlaneReconcilerV2::start_with_intervals(
            Arc::clone(&state),
            plugin_data_plane_credentials_v2.clone(),
            Duration::from_secs(3600),
            Duration::from_secs(3600),
        )
        .await
        .expect("control plane must start");
        control_plane
            .select(PlatformPluginAuthorityModeV2::Cloud)
            .await
            .expect("empty cloud selection must fail closed");
        assert!(state
            .platform_plugin_authority_v2
            .acquire_generation()
            .is_err());

        plugin_data_plane_credentials_v2
            .save(&record)
            .expect("data-plane credential");
        control_plane
            .refresh()
            .await
            .expect("cloud authority refresh");
        let lease = state
            .platform_plugin_authority_v2
            .acquire_generation()
            .expect("cloud last-good generation must activate");
        assert_eq!(lease.descriptor().publication_version, Some(8));
        drop(lease);
        server.await.expect("test control plane task");
        control_plane.shutdown().await;
    }

    #[tokio::test]
    async fn superseded_cloud_candidate_cannot_advance_durable_last_good() {
        let state = test_state();
        let plugin_data_plane_credentials_v2 = plugin_data_plane_credentials_v2();
        plugin_data_plane_credentials_v2
            .save(&plugin_data_plane_record_v2(
                "https://example.com",
                'c',
                false,
            ))
            .expect("data-plane credential");
        let authority = load_plugin_data_plane_authority_v2(&plugin_data_plane_credentials_v2)
            .expect("cloud authority")
            .expect("cloud authority record");
        let accepted = bootstrap_distribution(1, "accepted-before-supersede");
        let candidate = bootstrap_distribution(2, "superseded-before-publication");
        let accepted_receipt = SnapshotApplyReceiptV2 {
            status: ApplyStatusV2::Ack,
            requested_version: accepted.envelope.version,
            requested_digest: accepted.snapshot.digest.clone(),
            applied_version: Some(accepted.envelope.version),
            applied_digest: Some(accepted.snapshot.digest.clone()),
            error_code: None,
            error_message: None,
        };
        let candidate_receipt = SnapshotApplyReceiptV2 {
            status: ApplyStatusV2::Ack,
            requested_version: candidate.envelope.version,
            requested_digest: candidate.snapshot.digest.clone(),
            applied_version: Some(candidate.envelope.version),
            applied_digest: Some(candidate.snapshot.digest.clone()),
            error_code: None,
            error_message: None,
        };
        {
            let mut connection = state.session_store.connection().expect("session store");
            plugin_snapshots_v2::initialize_schema(&connection).expect("plugin snapshot schema");
            plugin_snapshots_v2::record_requested(&connection, &authority.fingerprint, &accepted)
                .expect("accepted distribution");
            plugin_snapshots_v2::record_receipt(
                &mut connection,
                &authority.fingerprint,
                &accepted.envelope.nonce,
                &accepted_receipt,
            )
            .expect("accepted receipt");
            plugin_snapshots_v2::record_requested(&connection, &authority.fingerprint, &candidate)
                .expect("candidate distribution");
        }
        let reconciler = desktop_reconciler(&state);
        let generation = reconciler
            .stage_snapshot(candidate.snapshot.clone())
            .await
            .expect("candidate generation");
        let expected_selection = PlatformPluginAuthoritySelectionV2 {
            mode: PlatformPluginAuthorityModeV2::Cloud,
            epoch: 1,
        };
        let selection = Mutex::new(PlatformPluginAuthoritySelectionV2 {
            mode: PlatformPluginAuthorityModeV2::Local,
            epoch: 2,
        });

        let retirement = begin_selected_cloud_publication(
            &state,
            &plugin_data_plane_credentials_v2,
            &authority,
            &selection,
            expected_selection,
            &candidate,
            &candidate_receipt,
            Arc::clone(&generation),
        )
        .expect("superseded publication check");

        assert!(retirement.is_none());
        {
            let connection = state.session_store.connection().expect("session store");
            assert_eq!(
                plugin_snapshots_v2::read_last_good(&connection, &authority.fingerprint)
                    .expect("last-good read"),
                Some(accepted)
            );
        }
        assert!(state
            .platform_plugin_authority_v2
            .acquire_generation()
            .is_err());
        reconciler.discard_staged_snapshot(generation).await;
    }

    #[tokio::test]
    async fn cloud_to_local_switch_is_atomic_and_keeps_the_old_lease_pinned() {
        let state = test_state();
        let cloud_distribution = bootstrap_distribution(7, "cloud-last-good");
        let mut seed = PluginSnapshotReconcilerV2::new(desktop_loader(None, None));
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
        state.platform_plugin_authority_v2.deactivate().await;
    }

    #[tokio::test]
    async fn desktop_reconciler_activates_the_generated_local_capability_module() {
        let mut reconciler = PluginSnapshotReconcilerV2::new(desktop_loader(None, None));
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
        let mut reconciler = PluginSnapshotReconcilerV2::new(desktop_loader(None, None));
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
