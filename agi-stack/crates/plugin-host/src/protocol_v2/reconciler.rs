//! Transactional protocol-v2 reconciliation for Rust data planes.

use std::sync::Arc;

use super::{
    ApplyStatusV2, ControlPlaneDistributionV2, GenerationManagerV2, LoaderV2,
    SnapshotApplyReceiptV2,
};

/// Stages complete target-specific generations and retains the last-good publication.
pub struct PluginSnapshotReconcilerV2 {
    loader: LoaderV2,
    manager: Arc<GenerationManagerV2>,
    applied_version: Option<u64>,
    applied_digest: Option<String>,
}

impl PluginSnapshotReconcilerV2 {
    /// Create a reconciler for a loader whose target is fixed at construction.
    #[must_use]
    pub fn new(loader: LoaderV2) -> Self {
        Self {
            loader,
            manager: Arc::new(GenerationManagerV2::new()),
            applied_version: None,
            applied_digest: None,
        }
    }

    /// Return the shared generation manager used to lease the currently applied generation.
    #[must_use]
    pub fn manager(&self) -> Arc<GenerationManagerV2> {
        Arc::clone(&self.manager)
    }

    /// Validate transition ordering, stage target entries, and atomically publish on ACK.
    pub async fn apply(
        &mut self,
        distribution: &ControlPlaneDistributionV2,
    ) -> SnapshotApplyReceiptV2 {
        if let Some(applied_version) = self.applied_version {
            if distribution.envelope.version < applied_version {
                return self.nack(distribution, "stale_version", "snapshot version is stale");
            }
            if distribution.envelope.version == applied_version {
                if self.applied_digest.as_deref() == Some(distribution.snapshot.digest.as_str()) {
                    return self.ack(distribution);
                }
                return self.nack(
                    distribution,
                    "version_conflict",
                    "snapshot version already belongs to another digest",
                );
            }
        }

        match self.loader.stage(distribution.snapshot.clone()).await {
            Ok(generation) => {
                self.manager.publish(generation).await;
                self.applied_version = Some(distribution.envelope.version);
                self.applied_digest = Some(distribution.snapshot.digest.clone());
                self.ack(distribution)
            }
            Err(error) => self.nack(distribution, "generation_apply_failed", &error.to_string()),
        }
    }

    /// Dispose the active generation after outstanding leases drain.
    pub async fn close(&self) {
        self.manager.close().await;
    }

    fn ack(&self, distribution: &ControlPlaneDistributionV2) -> SnapshotApplyReceiptV2 {
        SnapshotApplyReceiptV2 {
            status: ApplyStatusV2::Ack,
            requested_version: distribution.envelope.version,
            requested_digest: distribution.snapshot.digest.clone(),
            applied_version: self.applied_version,
            applied_digest: self.applied_digest.clone(),
            error_code: None,
            error_message: None,
        }
    }

    fn nack(
        &self,
        distribution: &ControlPlaneDistributionV2,
        error_code: &str,
        error_message: &str,
    ) -> SnapshotApplyReceiptV2 {
        SnapshotApplyReceiptV2 {
            status: ApplyStatusV2::Nack,
            requested_version: distribution.envelope.version,
            requested_digest: distribution.snapshot.digest.clone(),
            applied_version: self.applied_version,
            applied_digest: self.applied_digest.clone(),
            error_code: Some(error_code.to_owned()),
            error_message: Some(error_message.to_owned()),
        }
    }
}

impl Default for PluginSnapshotReconcilerV2 {
    fn default() -> Self {
        Self::new(LoaderV2::new(std::iter::empty()))
    }
}
