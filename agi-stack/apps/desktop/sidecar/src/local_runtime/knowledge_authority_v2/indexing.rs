//! Native embedding attempts over the provenance-bound durable index.
use agistack_adapters_http_llm::VerifiedEmbeddingError;
use agistack_core::knowledge::index::*;
use std::{
    num::{NonZeroU32, NonZeroUsize},
    time::Duration,
};

use super::{
    embedding_provider::{self, EmbeddingProvider, EmbeddingRoute},
    *,
};
use crate::local_runtime::LocalRuntimeState;

#[derive(Clone, Copy)]
pub(super) struct IndexRunOptions {
    pub(super) lease_ms: u64,
    pub(super) renew_every_ms: u64,
}
impl Default for IndexRunOptions {
    fn default() -> Self {
        Self {
            lease_ms: 30_000,
            renew_every_ms: 10_000,
        }
    }
}

#[derive(Debug, PartialEq)]
pub(super) enum IndexRunOutcome {
    Indexed,
    Failed(IndexFailure),
}
#[derive(Debug)]
#[cfg_attr(
    not(test),
    allow(
        dead_code,
        reason = "internal index receipts await the closed entrypoint consumer"
    )
)]
pub(super) struct IndexRunReceipt {
    pub(super) input: IndexSource,
    pub(super) attempt: u32,
    pub(super) outcome: IndexRunOutcome,
}

#[allow(
    dead_code,
    reason = "internal embedding entrypoints stay unpublished until joint release acceptance"
)]
impl KnowledgeOperationV2 {
    /// Probe through the real configured adapter. Dimensions are observed from
    /// this response before creating an immutable build; no catalogue inference.
    pub(super) async fn prepare_index_build(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        route: &EmbeddingRoute,
        build_id: &str,
    ) -> Result<IndexBuild, KnowledgeAuthorityErrorV2> {
        if build_id.trim().is_empty() {
            return Err(KnowledgeError::InvalidInput.into());
        }
        let provider = embedding_provider::resolve(self, state, auth, route, true)?;
        let observed = provider
            .client()
            .embed_verified("Knowledge embedding dimension verification", None)
            .await
            .map_err(|_| KnowledgeAuthorityErrorV2::TransportUnavailable)?;
        let dimensions = NonZeroU32::new(
            u32::try_from(observed.dimensions().get()).map_err(|_| KnowledgeError::InvalidInput)?,
        )
        .ok_or(KnowledgeError::InvalidInput)?;
        let build = IndexBuild {
            scope: self.scope.clone(),
            build_id: build_id.into(),
            profile: provider.profile(dimensions),
        };
        embedding_provider::with_current(self, state, auth, &provider, true, |clock| {
            self.authority
                .repository()
                .map_err(|_| KnowledgeError::Conflict)?
                .begin_index_build_durable(&build, clock)
        })?;
        Ok(build)
    }

    pub(super) async fn index_one(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        build: &IndexBuild,
        options: IndexRunOptions,
    ) -> Result<Option<IndexRunReceipt>, KnowledgeAuthorityErrorV2> {
        if options.renew_every_ms == 0 || options.renew_every_ms >= options.lease_ms {
            return Err(KnowledgeError::InvalidInput.into());
        }
        let provider = resolve_build(self, state, auth, build, true)?;
        let repository = self.authority.repository()?;
        let Some(lease) =
            embedding_provider::with_current(self, state, auth, &provider, true, |clock| {
                repository.claim_index_durable(
                    build,
                    "knowledge-embedding-v1",
                    options.lease_ms,
                    clock,
                )
            })?
        else {
            return Ok(None);
        };
        let mut attempt = IndexAttempt {
            operation: self,
            state,
            auth,
            provider: &provider,
            repository,
            lease,
            armed: true,
        };
        let client = provider.client();
        let input = attempt.lease.input_text.clone();
        let response = client.embed_verified(
            &input,
            Some(
                NonZeroUsize::new(build.profile.dimensions.get() as usize)
                    .ok_or(KnowledgeError::InvalidInput)?,
            ),
        );
        tokio::pin!(response);
        let mut interval = tokio::time::interval(Duration::from_millis(options.renew_every_ms));
        interval.tick().await;
        let response = loop {
            tokio::select! {
                response=&mut response=>break response,
                _=interval.tick()=>{
                    attempt.lease=embedding_provider::with_current(self,state,auth,&provider,true,|clock| {
                        attempt.repository.renew_index_durable(&attempt.lease,options.lease_ms,clock)
                    })?;
                }
            }
        };
        match response {
            Ok(vector) => {
                embedding_provider::with_current(self, state, auth, &provider, true, |clock| {
                    attempt.repository.complete_index_durable(
                        &attempt.lease,
                        vector.vector(),
                        clock,
                    )
                })?;
                attempt.armed = false;
                Ok(Some(attempt.receipt(IndexRunOutcome::Indexed)))
            }
            Err(error) => {
                let failure = match error {
                    VerifiedEmbeddingError::InvalidResponse
                    | VerifiedEmbeddingError::ModelMismatch
                    | VerifiedEmbeddingError::DimensionMismatch
                    | VerifiedEmbeddingError::InvalidVector
                    | VerifiedEmbeddingError::InvalidInput => IndexFailure::InvalidEmbedding,
                    _ => IndexFailure::ProviderUnavailable,
                };
                attempt.fail(failure)?;
                Ok(Some(attempt.receipt(IndexRunOutcome::Failed(failure))))
            }
        }
    }

    pub(super) fn promote_index_build(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        build: &IndexBuild,
        expected_active: Option<&str>,
    ) -> Result<(), KnowledgeAuthorityErrorV2> {
        let provider = resolve_build(self, state, auth, build, true)?;
        embedding_provider::with_current(self, state, auth, &provider, true, |clock| {
            self.authority
                .repository()
                .map_err(|_| KnowledgeError::Conflict)?
                .promote_index_build_durable(build, expected_active, clock)
        })
    }
    pub(super) fn retry_index(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        build: &IndexBuild,
        input: &IndexSource,
        expected_attempt: u32,
    ) -> Result<(), KnowledgeAuthorityErrorV2> {
        let provider = resolve_build(self, state, auth, build, true)?;
        embedding_provider::with_current(self, state, auth, &provider, true, |clock| {
            self.authority
                .repository()
                .map_err(|_| KnowledgeError::Conflict)?
                .retry_index_durable(build, input, expected_attempt, clock)
        })
    }
}

pub(super) fn resolve_build(
    operation: &KnowledgeOperationV2,
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    build: &IndexBuild,
    write: bool,
) -> Result<EmbeddingProvider, KnowledgeAuthorityErrorV2> {
    if build.scope != operation.scope {
        return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
    }
    let route = EmbeddingRoute {
        provider_id: build.profile.provider_id.clone(),
        model_id: build.profile.model_id.clone(),
        provider_revision: build.profile.provider_revision,
    };
    let provider = embedding_provider::resolve(operation, state, auth, &route, write)?;
    if provider.profile(build.profile.dimensions) != build.profile {
        return Err(KnowledgeError::Conflict.into());
    }
    Ok(provider)
}

struct IndexAttempt<'a> {
    operation: &'a KnowledgeOperationV2,
    state: &'a LocalRuntimeState,
    auth: &'a AuthenticatedContext,
    provider: &'a EmbeddingProvider,
    repository: Arc<SqliteKnowledgeRepository>,
    lease: IndexLease,
    armed: bool,
}
impl IndexAttempt<'_> {
    fn receipt(&self, outcome: IndexRunOutcome) -> IndexRunReceipt {
        IndexRunReceipt {
            input: self.lease.input.clone(),
            attempt: self.lease.attempt,
            outcome,
        }
    }
    fn fail(&mut self, failure: IndexFailure) -> Result<(), KnowledgeAuthorityErrorV2> {
        embedding_provider::with_current(
            self.operation,
            self.state,
            self.auth,
            self.provider,
            true,
            |clock| {
                self.repository
                    .fail_index_durable(&self.lease, failure, clock)
            },
        )?;
        self.armed = false;
        Ok(())
    }
}
impl Drop for IndexAttempt<'_> {
    fn drop(&mut self) {
        // No lock is retained by this attempt or across await. Cancellation can
        // fail its own current lease, but revoked/reconfigured/retired admission
        // leaves it to expire for recovery; Drop never bypasses live permission.
        if self.armed && tokio::runtime::Handle::try_current().is_ok() {
            let _ = self.fail(IndexFailure::Cancelled);
        }
    }
}
