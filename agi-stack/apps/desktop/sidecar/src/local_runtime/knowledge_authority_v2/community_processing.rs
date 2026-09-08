//! One generation-fenced, audited semantic attempt over frozen graph input.

use agistack_core::knowledge::community::{build::CommunityJobLease, result::*, worker::*};
use sha2::{Digest, Sha256};
use std::time::{Duration, Instant};

use super::{processing::ProcessingRunOptions, processing_provider::ProcessingProvider, *};
use crate::local_runtime::LocalRuntimeState;

const WORKER: &str = "knowledge-community-v1";

impl KnowledgeOperationV2 {
    #[allow(
        dead_code,
        reason = "internal worker awaits the community RPC consumer"
    )]
    pub(super) async fn process_community_one(
        &self,
        state: Arc<LocalRuntimeState>,
        authenticated: AuthenticatedContext,
        workspace_id: &str,
        build_id: &str,
        options: ProcessingRunOptions,
    ) -> Result<Option<CommunityAuditRecord>, KnowledgeAuthorityErrorV2> {
        let provider =
            super::processing_provider::resolve(self, &state, &authenticated, workspace_id).await?;
        self.process_community_with_provider(state, authenticated, provider, build_id, options)
            .await
    }

    pub(super) async fn process_community_with_provider(
        &self,
        state: Arc<LocalRuntimeState>,
        authenticated: AuthenticatedContext,
        provider: ProcessingProvider,
        build_id: &str,
        options: ProcessingRunOptions,
    ) -> Result<Option<CommunityAuditRecord>, KnowledgeAuthorityErrorV2> {
        if options.renew_every_ms == 0 || options.renew_every_ms >= options.lease_ms {
            return Err(KnowledgeError::InvalidInput.into());
        }
        let repository = self.authority.repository()?;
        let Some(lease) = current(self, &state, &authenticated, |clock| {
            repository.claim_community_job_durable(
                &self.scope,
                build_id,
                WORKER,
                options.lease_ms,
                clock,
            )
        })?
        else {
            return Ok(None);
        };
        // Construct the guard immediately: pre-audit errors must release this
        // attempt too, without pretending that a model was called.
        let mut attempt = CommunityAttempt {
            repository,
            scope: self.scope.clone(),
            lease,
            started: Instant::now(),
            audited: false,
            armed: true,
        };
        let input = attempt
            .repository
            .community_candidate_input_durable(
                &attempt.scope,
                build_id,
                &attempt.lease.candidate_id,
            )?
            .ok_or(KnowledgeError::Conflict)?;
        current(self, &state, &authenticated, |clock| {
            attempt.repository.begin_community_audit_durable(
                &attempt.scope,
                &attempt.lease,
                CommunityInvocation {
                    agent_id: WORKER.into(),
                    provider_id: provider.provider_id,
                    model_id: provider.model_id,
                    tool_name: SUBMIT_COMMUNITY_TOOL.into(),
                    contract_version: 1,
                    input: input.clone(),
                },
                clock,
            )
        })?;
        attempt.audited = true;
        if let Err(error) = current(self, &state, &authenticated, |_| Ok(())) {
            return attempt.fail(failure_for(&error), None).map(Some);
        }
        let call = request_community(provider.llm.as_ref(), &input);
        tokio::pin!(call);
        let mut renewal = tokio::time::interval(Duration::from_millis(options.renew_every_ms));
        renewal.tick().await;
        let action = loop {
            tokio::select! {
                result = &mut call => break result,
                _ = renewal.tick() => {
                    match current(self, &state, &authenticated, |clock| {
                        attempt.repository.renew_community_job_durable(
                            &attempt.scope, &attempt.lease, options.lease_ms, clock,
                        )
                    }) {
                        Ok(lease) => attempt.lease = lease,
                        Err(error) => return attempt.fail(failure_for(&error), None).map(Some),
                    }
                }
            }
        };
        let action = match action {
            Ok(action) => action,
            Err(_) => {
                return attempt
                    .fail(CommunityAuditFailure::ProviderUnavailable, None)
                    .map(Some)
            }
        };
        let Some(submission) = parse_submission(&action, &input) else {
            let digest = rejected_digest(&action);
            return attempt
                .fail(CommunityAuditFailure::InvalidSubmission, digest)
                .map(Some);
        };
        let result = current(self, &state, &authenticated, |clock| {
            attempt.repository.finish_community_audit_durable(
                &attempt.scope,
                &attempt.lease,
                CommunityAuditOutcome::Applied { submission },
                attempt.elapsed(),
                clock,
            )
        });
        match result {
            Ok(record) => {
                attempt.armed = false;
                // Storage can reject a valid submission after graph/lease CAS.
                // Return its actual outcome, never the requested outcome.
                Ok(Some(record))
            }
            Err(error) => attempt.fail(failure_for(&error), None).map(Some),
        }
    }
}

fn current<T>(
    operation: &KnowledgeOperationV2,
    state: &LocalRuntimeState,
    authenticated: &AuthenticatedContext,
    action: impl FnOnce(
        &dyn Fn() -> agistack_core::knowledge::KnowledgeResult<i64>,
    ) -> agistack_core::knowledge::KnowledgeResult<T>,
) -> Result<T, KnowledgeAuthorityErrorV2> {
    super::processing_context::with_read_current_checked(
        operation,
        state,
        authenticated,
        true,
        |_| Ok(()),
        action,
    )
}

fn failure_for(error: &KnowledgeAuthorityErrorV2) -> CommunityAuditFailure {
    match error {
        KnowledgeAuthorityErrorV2::Knowledge(KnowledgeError::Conflict) => {
            CommunityAuditFailure::LeaseLost
        }
        KnowledgeAuthorityErrorV2::Forbidden
        | KnowledgeAuthorityErrorV2::Disposed
        | KnowledgeAuthorityErrorV2::ScopeMismatch
        | KnowledgeAuthorityErrorV2::GenerationMismatch => CommunityAuditFailure::AdmissionChanged,
        _ => CommunityAuditFailure::InternalFailure,
    }
}

/// Hash rejected responses without allocating a second copy or processing
/// unbounded output. Oversized responses retain only the typed failure code.
fn rejected_digest(action: &agistack_core::agent::AgentAction) -> Option<String> {
    struct BoundedHash {
        hash: Sha256,
        remaining: usize,
    }
    impl std::io::Write for BoundedHash {
        fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
            if bytes.len() > self.remaining {
                return Err(std::io::Error::other("response exceeds audit byte budget"));
            }
            self.hash.update(bytes);
            self.remaining -= bytes.len();
            Ok(bytes.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    let mut writer = BoundedHash {
        hash: Sha256::new(),
        remaining: 2 * 1024 * 1024,
    };
    serde_json::to_writer(&mut writer, action).ok()?;
    Some(format!("{:x}", writer.hash.finalize()))
}

struct CommunityAttempt {
    repository: Arc<SqliteKnowledgeRepository>,
    scope: KnowledgeScope,
    lease: CommunityJobLease,
    started: Instant,
    audited: bool,
    armed: bool,
}

impl CommunityAttempt {
    fn elapsed(&self) -> u64 {
        u64::try_from(self.started.elapsed().as_millis()).unwrap_or(u64::MAX)
    }
    fn fail(
        &mut self,
        code: CommunityAuditFailure,
        response_digest: Option<String>,
    ) -> Result<CommunityAuditRecord, KnowledgeAuthorityErrorV2> {
        let record = self.repository.finish_community_audit_durable(
            &self.scope,
            &self.lease,
            CommunityAuditOutcome::Failed {
                code,
                response_digest,
            },
            self.elapsed(),
            &|| Ok(chrono::Utc::now().timestamp_millis()),
        )?;
        self.armed = false;
        Ok(record)
    }
}

impl Drop for CommunityAttempt {
    fn drop(&mut self) {
        if !self.armed {
            return;
        }
        if self.audited {
            let _ = self.fail(CommunityAuditFailure::Cancelled, None);
        } else {
            let _ = self.repository.fail_community_job_durable(
                &self.scope,
                &self.lease,
                agistack_core::knowledge::community::build::CommunityJobFailure::Cancelled,
                &|| Ok(chrono::Utc::now().timestamp_millis()),
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use agistack_core::agent::AgentAction;

    #[test]
    fn rejected_digest_is_exact_for_bounded_output_and_absent_for_oversized_output() {
        let action = AgentAction::Finish {
            answer: "rejected text".into(),
        };
        let expected = format!("{:x}", Sha256::digest(serde_json::to_vec(&action).unwrap()));
        assert_eq!(rejected_digest(&action), Some(expected));
        assert!(rejected_digest(&AgentAction::Finish {
            answer: "x".repeat(2 * 1024 * 1024)
        })
        .is_none());
    }
}
