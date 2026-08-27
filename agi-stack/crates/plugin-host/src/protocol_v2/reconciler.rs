//! Transactional protocol-v2 reconciliation for Rust data planes.

use std::{future::Future, sync::Arc};

use super::{
    ApplyStatusV2, ControlPlaneDistributionV2, GenerationManagerV2, LoaderV2, ProfileSnapshotV2,
    RuntimeGenerationV2, RuntimeV2Error, SnapshotApplyReceiptV2,
};

pub enum SnapshotPreparationV2<'a> {
    Ready(PreparedSnapshotApplyV2<'a>),
    Receipt(SnapshotApplyReceiptV2),
}

#[must_use]
pub struct PreparedSnapshotApplyV2<'a> {
    reconciler: &'a mut PluginSnapshotReconcilerV2,
    distribution: &'a ControlPlaneDistributionV2,
    generation: Arc<RuntimeGenerationV2>,
}

impl PreparedSnapshotApplyV2<'_> {
    #[must_use]
    pub fn receipt(&self) -> SnapshotApplyReceiptV2 {
        SnapshotApplyReceiptV2 {
            status: ApplyStatusV2::Ack,
            requested_version: self.distribution.envelope.version,
            requested_digest: self.distribution.snapshot.digest.clone(),
            applied_version: Some(self.distribution.envelope.version),
            applied_digest: Some(self.distribution.snapshot.digest.clone()),
            error_code: None,
            error_message: None,
        }
    }

    pub async fn commit(self) -> SnapshotApplyReceiptV2 {
        self.commit_with(|manager, generation| async move {
            manager.publish(generation).await;
        })
        .await
    }

    pub async fn commit_with<F, Fut>(self, publish: F) -> SnapshotApplyReceiptV2
    where
        F: FnOnce(Arc<GenerationManagerV2>, Arc<RuntimeGenerationV2>) -> Fut,
        Fut: Future<Output = ()>,
    {
        let receipt = self.receipt();
        publish(self.reconciler.manager(), self.generation).await;
        self.reconciler.applied_version = Some(self.distribution.envelope.version);
        self.reconciler.applied_digest = Some(self.distribution.snapshot.digest.clone());
        receipt
    }

    /// Publish a prepared generation only when the caller's external authority is still current.
    ///
    /// A `false` result disposes the staged generation without advancing publication ordering.
    /// This lets data planes invalidate an in-flight candidate without cancelling its activation
    /// future or briefly exposing it through the shared generation manager.
    pub async fn commit_if_with<F, Fut>(self, publish: F) -> Option<SnapshotApplyReceiptV2>
    where
        F: FnOnce(Arc<GenerationManagerV2>, Arc<RuntimeGenerationV2>) -> Fut,
        Fut: Future<Output = bool>,
    {
        let receipt = self.receipt();
        if publish(self.reconciler.manager(), Arc::clone(&self.generation)).await {
            self.reconciler.applied_version = Some(self.distribution.envelope.version);
            self.reconciler.applied_digest = Some(self.distribution.snapshot.digest.clone());
            return Some(receipt);
        }
        self.generation.dispose().await;
        None
    }

    /// Publish a prepared generation only when a fallible external durability boundary succeeds.
    ///
    /// Both a superseded (`Ok(false)`) candidate and a failed (`Err`) publication dispose the
    /// staged generation without advancing publication ordering. The callback must return an error
    /// before publishing the generation.
    ///
    /// # Errors
    ///
    /// Returns the callback error after disposing the staged generation.
    pub async fn commit_try_if_with<F, Fut, E>(
        self,
        publish: F,
    ) -> Result<Option<SnapshotApplyReceiptV2>, E>
    where
        F: FnOnce(Arc<GenerationManagerV2>, Arc<RuntimeGenerationV2>) -> Fut,
        Fut: Future<Output = Result<bool, E>>,
    {
        let receipt = self.receipt();
        match publish(self.reconciler.manager(), Arc::clone(&self.generation)).await {
            Ok(true) => {
                self.reconciler.applied_version = Some(self.distribution.envelope.version);
                self.reconciler.applied_digest = Some(self.distribution.snapshot.digest.clone());
                Ok(Some(receipt))
            }
            Ok(false) => {
                self.generation.dispose().await;
                Ok(None)
            }
            Err(error) => {
                self.generation.dispose().await;
                Err(error)
            }
        }
    }

    pub async fn discard(self) {
        self.generation.dispose().await;
    }
}

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
        Self::new_with_manager(loader, Arc::new(GenerationManagerV2::new()))
    }

    /// Create a reconciler that shares an externally owned generation manager.
    #[must_use]
    pub fn new_with_manager(loader: LoaderV2, manager: Arc<GenerationManagerV2>) -> Self {
        Self {
            loader,
            manager,
            applied_version: None,
            applied_digest: None,
        }
    }

    /// Stage a local baseline without claiming a control-plane publication version.
    ///
    /// The first subsequent distribution is still compared against an empty publication history,
    /// so a control plane may start at version one while the baseline remains available on NACK.
    pub async fn new_with_baseline(
        loader: LoaderV2,
        baseline: ProfileSnapshotV2,
    ) -> Result<Self, RuntimeV2Error> {
        let reconciler = Self::new(loader);
        let generation = reconciler.stage_snapshot(baseline).await?;
        reconciler.manager.publish(generation).await;
        Ok(reconciler)
    }

    /// Stage a complete snapshot without changing the published generation.
    pub async fn stage_snapshot(
        &self,
        snapshot: ProfileSnapshotV2,
    ) -> Result<Arc<RuntimeGenerationV2>, RuntimeV2Error> {
        self.loader.stage(snapshot).await
    }

    /// Dispose a generation returned by [`Self::stage_snapshot`] before it is published.
    pub async fn discard_staged_snapshot(&self, generation: Arc<RuntimeGenerationV2>) {
        generation.dispose().await;
    }

    /// Start a new authority epoch while retaining the shared manager and its current generation.
    pub fn reset_publication_ordering(&mut self) {
        self.applied_version = None;
        self.applied_digest = None;
    }

    /// Adopt the durable last-good ordering for a newly selected authority.
    pub fn restore_publication_ordering(&mut self, version: u64, digest: String) {
        self.applied_version = Some(version);
        self.applied_digest = Some(digest);
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
        match self.prepare(distribution).await {
            SnapshotPreparationV2::Ready(prepared) => prepared.commit().await,
            SnapshotPreparationV2::Receipt(receipt) => receipt,
        }
    }

    /// Validate ordering and stage a candidate without making it visible.
    pub async fn prepare<'a>(
        &'a mut self,
        distribution: &'a ControlPlaneDistributionV2,
    ) -> SnapshotPreparationV2<'a> {
        if let Some(applied_version) = self.applied_version {
            if distribution.envelope.version < applied_version {
                return SnapshotPreparationV2::Receipt(self.nack(
                    distribution,
                    "stale_version",
                    "snapshot version is stale",
                ));
            }
            if distribution.envelope.version == applied_version {
                if self.applied_digest.as_deref() == Some(distribution.snapshot.digest.as_str()) {
                    return SnapshotPreparationV2::Receipt(self.ack(distribution));
                }
                return SnapshotPreparationV2::Receipt(self.nack(
                    distribution,
                    "version_conflict",
                    "snapshot version already belongs to another digest",
                ));
            }
        }

        match self.loader.stage(distribution.snapshot.clone()).await {
            Ok(generation) => SnapshotPreparationV2::Ready(PreparedSnapshotApplyV2 {
                reconciler: self,
                distribution,
                generation,
            }),
            Err(error) => SnapshotPreparationV2::Receipt(self.nack(
                distribution,
                "generation_apply_failed",
                &error.to_string(),
            )),
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
