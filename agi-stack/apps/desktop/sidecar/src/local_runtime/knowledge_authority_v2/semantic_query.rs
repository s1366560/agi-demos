//! Internal query: actual embedding, then current profile/source checks and ranking.
use agistack_core::knowledge::{
    index::*,
    similarity::{rank_index_vectors, ScoredIndexSource},
};
use std::num::NonZeroUsize;

use super::*;
use crate::local_runtime::LocalRuntimeState;

#[derive(Debug)]
#[cfg_attr(
    not(test),
    allow(
        dead_code,
        reason = "internal semantic result awaits joint release acceptance"
    )
)]
pub(super) struct SemanticQueryResult {
    pub(super) build: IndexBuild,
    pub(super) processing: ProcessingCoverage,
    pub(super) index: IndexCoverage,
    pub(super) hits: Vec<ScoredIndexSource>,
}

#[allow(
    dead_code,
    reason = "internal semantic entrypoints stay unpublished until joint release acceptance"
)]
impl KnowledgeOperationV2 {
    pub(super) fn index_coverage(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        build: &IndexBuild,
    ) -> Result<(ProcessingCoverage, IndexCoverage), KnowledgeAuthorityErrorV2> {
        let provider = super::indexing::resolve_build(self, state, auth, build, false)?;
        super::embedding_provider::with_current(self, state, auth, &provider, false, |clock| {
            let read = self
                .authority
                .repository()
                .map_err(|_| KnowledgeError::Conflict)?
                .read_active_index_durable(build, clock)?;
            Ok((read.processing, read.coverage))
        })
    }

    pub(super) async fn semantic_query(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        build: &IndexBuild,
        query: &str,
        limit: usize,
    ) -> Result<SemanticQueryResult, KnowledgeAuthorityErrorV2> {
        if query.trim().is_empty() || query.len() > 4096 || !(1..=100).contains(&limit) {
            return Err(KnowledgeError::InvalidInput.into());
        }
        let provider = super::indexing::resolve_build(self, state, auth, build, false)?;
        // Validate the declared active build before issuing a query. An old
        // profile is never silently substituted for a reconfigured Provider.
        super::embedding_provider::with_current(self, state, auth, &provider, false, |clock| {
            self.authority
                .repository()
                .map_err(|_| KnowledgeError::Conflict)?
                .read_active_index_durable(build, clock)
                .map(|_| ())
        })?;
        let vector = provider
            .client()
            .embed_verified(
                query,
                Some(
                    NonZeroUsize::new(build.profile.dimensions.get() as usize)
                        .ok_or(KnowledgeError::InvalidInput)?,
                ),
            )
            .await
            .map_err(|_| KnowledgeAuthorityErrorV2::TransportUnavailable)?;
        super::embedding_provider::with_current(self, state, auth, &provider, false, |clock| {
            let read = self
                .authority
                .repository()
                .map_err(|_| KnowledgeError::Conflict)?
                .read_active_index_durable(build, clock)?;
            let mut hits = rank_index_vectors(vector.vector(), &read.vectors)?;
            hits.truncate(limit);
            Ok(SemanticQueryResult {
                build: read.build,
                processing: read.processing,
                index: read.coverage,
                hits,
            })
        })
    }
}
