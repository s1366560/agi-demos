//! Internal read surface only; no HTTP contribution until joint release acceptance.

use super::*;
use crate::local_runtime::LocalRuntimeState;
use agistack_core::knowledge::retrieval::*;

impl KnowledgeOperationV2 {
    #[allow(
        dead_code,
        reason = "internal retrieval remains unpublished until joint release acceptance"
    )]
    pub(super) fn entities(
        &self,
        state: &LocalRuntimeState,
        authenticated: &AuthenticatedContext,
        request: &RetrievalRequest,
    ) -> Result<RetrievalPage<RetrievedEntity>, KnowledgeAuthorityErrorV2> {
        super::processing_context::with_read_current(self, state, authenticated, |clock| {
            self.authority
                .repository()
                .map_err(|_| KnowledgeError::Conflict)?
                .entities_durable(&self.scope, request, clock)
        })
    }
    #[allow(
        dead_code,
        reason = "internal retrieval remains unpublished until joint release acceptance"
    )]
    pub(super) fn relationships(
        &self,
        state: &LocalRuntimeState,
        authenticated: &AuthenticatedContext,
        request: &RetrievalRequest,
    ) -> Result<RetrievalPage<RetrievedRelationship>, KnowledgeAuthorityErrorV2> {
        super::processing_context::with_read_current(self, state, authenticated, |clock| {
            self.authority
                .repository()
                .map_err(|_| KnowledgeError::Conflict)?
                .relationships_durable(&self.scope, request, clock)
        })
    }
    #[allow(
        dead_code,
        reason = "internal retrieval remains unpublished until joint release acceptance"
    )]
    pub(super) fn search_text(
        &self,
        state: &LocalRuntimeState,
        authenticated: &AuthenticatedContext,
        literal: &str,
        request: &RetrievalRequest,
    ) -> Result<RetrievalPage<LiteralTextHit>, KnowledgeAuthorityErrorV2> {
        super::processing_context::with_read_current(self, state, authenticated, |clock| {
            self.authority
                .repository()
                .map_err(|_| KnowledgeError::Conflict)?
                .search_text_durable(&self.scope, literal, request, clock)
        })
    }
}
