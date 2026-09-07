//! One internal audited extraction attempt; no public route or release gate.

use agistack_core::knowledge::processing::{
    audit::*, worker::*, ProcessingLease, ProcessingSource,
};
use sha2::{Digest, Sha256};
use std::time::{Duration, Instant};

use super::processing_provider::ProcessingProvider;
use super::*;
use crate::local_runtime::LocalRuntimeState;

#[derive(Clone, Copy)]
pub(super) struct ProcessingRunOptions {
    pub(super) lease_ms: u64,
    pub(super) renew_every_ms: u64,
}

impl Default for ProcessingRunOptions {
    fn default() -> Self {
        Self {
            lease_ms: 30_000,
            renew_every_ms: 10_000,
        }
    }
}

#[derive(Debug)]
#[cfg_attr(
    not(test),
    allow(
        dead_code,
        reason = "receipt fields await the closed internal processing entrypoint consumer"
    )
)]
pub(super) struct ProcessingRunReceipt {
    pub(super) source: ProcessingSource,
    pub(super) attempt: u32,
    pub(super) outcome: ProcessingAuditOutcome,
}

impl KnowledgeOperationV2 {
    #[allow(
        dead_code,
        reason = "internal extraction entry stays unpublished until joint release acceptance"
    )]
    pub(super) async fn process_one(
        &self,
        state: Arc<LocalRuntimeState>,
        authenticated: AuthenticatedContext,
        workspace_id: &str,
        options: ProcessingRunOptions,
    ) -> Result<Option<ProcessingRunReceipt>, KnowledgeAuthorityErrorV2> {
        let provider =
            super::processing_provider::resolve(self, &state, &authenticated, workspace_id).await?;
        self.process_one_with_provider(state, authenticated, provider, options)
            .await
    }

    pub(super) async fn process_one_with_provider(
        &self,
        state: Arc<LocalRuntimeState>,
        authenticated: AuthenticatedContext,
        provider: ProcessingProvider,
        options: ProcessingRunOptions,
    ) -> Result<Option<ProcessingRunReceipt>, KnowledgeAuthorityErrorV2> {
        if options.renew_every_ms == 0 || options.renew_every_ms >= options.lease_ms {
            return Err(KnowledgeError::InvalidInput.into());
        }
        let repository = self.authority.repository()?;
        let Some(lease) =
            super::processing_context::with_current(self, &state, &authenticated, |clock| {
                repository.claim_processing_durable_with_clock(
                    &self.scope,
                    "knowledge-extractor-v1",
                    options.lease_ms,
                    clock,
                )
            })?
        else {
            return Ok(None);
        };
        let change = self
            .change(lease.source.change_sequence)
            .await?
            .ok_or(KnowledgeError::Conflict)?;
        if change.deleted
            || change.memory.id != lease.source.memory_id
            || change.memory.version != lease.source.revision
        {
            return Err(KnowledgeError::Conflict.into());
        }
        let input = ProcessingInput {
            source: lease.source.clone(),
            title: change.memory.title,
            content: change.memory.content,
        };
        let invocation = ProcessingInvocation {
            agent_id: "knowledge-extractor-v1".into(),
            provider_id: provider.provider_id,
            model_id: provider.model_id,
            tool_name: SUBMIT_PROJECTION_TOOL.into(),
            contract_version: 1,
            input: input.clone(),
        };
        super::processing_context::with_current(self, &state, &authenticated, |clock| {
            repository.begin_processing_audit_durable_with_clock(
                &self.scope,
                &lease,
                invocation,
                clock,
            )
        })?;
        let mut attempt = AuditAttempt {
            repository,
            scope: self.scope.clone(),
            lease,
            started: Instant::now(),
            armed: true,
        };
        if super::processing_context::with_current(self, &state, &authenticated, |_| Ok(()))
            .is_err()
        {
            return attempt
                .fail(ProcessingAuditFailure::AdmissionChanged, None)
                .map(Some);
        }
        let call = request_projection(provider.llm.as_ref(), &input);
        tokio::pin!(call);
        let mut renewal = tokio::time::interval(Duration::from_millis(options.renew_every_ms));
        renewal.tick().await;
        let action = loop {
            tokio::select! {
                result = &mut call => break result,
                _ = renewal.tick() => {
                    let renewed = super::processing_context::with_current(self,&state,&authenticated,|clock| {
                        attempt.repository.renew_processing_durable_with_clock(&attempt.scope,&attempt.lease,options.lease_ms,clock)
                    });
                    match renewed {
                        Ok(lease) => attempt.lease=lease,
                        Err(error) => return attempt.fail(failure_for(&error),None).map(Some),
                    }
                }
            }
        };
        let action = match action {
            Ok(action) => action,
            Err(_) => {
                return attempt
                    .fail(ProcessingAuditFailure::ProviderUnavailable, None)
                    .map(Some)
            }
        };
        let Some(submission) = parse_submission(&action, &attempt.lease.source) else {
            let digest = serde_json::to_vec(&action)
                .ok()
                .map(|bytes| format!("{:x}", Sha256::digest(bytes)));
            return attempt
                .fail(ProcessingAuditFailure::InvalidExtraction, digest)
                .map(Some);
        };
        let outcome = ProcessingAuditOutcome::Applied { submission };
        let result =
            super::processing_context::with_current(self, &state, &authenticated, |clock| {
                attempt
                    .repository
                    .finish_processing_audit_durable_with_clock(
                        &attempt.scope,
                        &attempt.lease,
                        outcome.clone(),
                        attempt.elapsed(),
                        clock,
                    )
            });
        match result {
            Ok(()) => {
                attempt.armed = false;
                Ok(Some(attempt.receipt(outcome)))
            }
            Err(error) => attempt.fail(failure_for(&error), None).map(Some),
        }
    }
}

fn now() -> i64 {
    chrono::Utc::now().timestamp_millis()
}
fn failure_for(error: &KnowledgeAuthorityErrorV2) -> ProcessingAuditFailure {
    match error {
        KnowledgeAuthorityErrorV2::Knowledge(KnowledgeError::Conflict) => {
            ProcessingAuditFailure::LeaseLost
        }
        KnowledgeAuthorityErrorV2::Forbidden
        | KnowledgeAuthorityErrorV2::Disposed
        | KnowledgeAuthorityErrorV2::ScopeMismatch
        | KnowledgeAuthorityErrorV2::GenerationMismatch => ProcessingAuditFailure::AdmissionChanged,
        _ => ProcessingAuditFailure::InternalFailure,
    }
}

struct AuditAttempt {
    repository: Arc<SqliteKnowledgeRepository>,
    scope: KnowledgeScope,
    lease: ProcessingLease,
    started: Instant,
    armed: bool,
}
impl AuditAttempt {
    fn elapsed(&self) -> u64 {
        u64::try_from(self.started.elapsed().as_millis()).unwrap_or(u64::MAX)
    }
    fn receipt(&self, outcome: ProcessingAuditOutcome) -> ProcessingRunReceipt {
        ProcessingRunReceipt {
            source: self.lease.source.clone(),
            attempt: self.lease.attempt,
            outcome,
        }
    }
    fn fail(
        &mut self,
        code: ProcessingAuditFailure,
        response_digest: Option<String>,
    ) -> Result<ProcessingRunReceipt, KnowledgeAuthorityErrorV2> {
        let outcome = ProcessingAuditOutcome::Failed {
            code,
            response_digest,
        };
        self.repository.finish_processing_audit_durable_with_clock(
            &self.scope,
            &self.lease,
            outcome.clone(),
            self.elapsed(),
            &|| Ok(now()),
        )?;
        self.armed = false;
        Ok(self.receipt(outcome))
    }
}
impl Drop for AuditAttempt {
    fn drop(&mut self) {
        if self.armed {
            // A dropped/aborted async task still records a typed terminal result.
            // If storage is unavailable, the durable start remains incomplete;
            // no projection was published and lease expiry allows recovery.
            let _ = self.repository.finish_processing_audit_durable_with_clock(
                &self.scope,
                &self.lease,
                ProcessingAuditOutcome::Failed {
                    code: ProcessingAuditFailure::Cancelled,
                    response_digest: None,
                },
                self.elapsed(),
                &|| Ok(now()),
            );
        }
    }
}
