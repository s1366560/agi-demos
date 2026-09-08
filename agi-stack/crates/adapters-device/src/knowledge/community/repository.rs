use std::time::Instant;

use agistack_core::knowledge::community::build::*;

use super::*;

// Preserve the trusted host clock's epoch while measuring time spent waiting
// for SQLite/repository locks and executing the transaction. Reading the wall
// clock here would mix epochs with callers using an injected logical clock.
fn advancing_clock(now_ms: i64) -> KnowledgeResult<impl Fn() -> KnowledgeResult<i64>> {
    if now_ms < 0 {
        return Err(KnowledgeError::InvalidInput);
    }
    let started = Instant::now();
    Ok(move || {
        let elapsed = i64::try_from(started.elapsed().as_millis())
            .map_err(|_| KnowledgeError::InvalidInput)?;
        now_ms
            .checked_add(elapsed)
            .ok_or(KnowledgeError::InvalidInput)
    })
}

#[async_trait]
impl CommunityBuildRepository for SqliteKnowledgeRepository {
    async fn create_community_build(
        &self,
        scope: &KnowledgeScope,
        request: &CommunityBuildRequest,
        now_ms: i64,
    ) -> KnowledgeResult<CommunityBuildReceipt> {
        self.create_community_build_durable(scope, request, &advancing_clock(now_ms)?)
    }

    async fn community_build(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
    ) -> KnowledgeResult<Option<CommunityBuildInput>> {
        self.community_build_durable(scope, build_id)
    }

    async fn claim_community_job(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
        worker_id: &str,
        now_ms: i64,
        lease_ms: u64,
    ) -> KnowledgeResult<Option<CommunityJobLease>> {
        self.claim_community_job_durable(
            scope,
            build_id,
            worker_id,
            lease_ms,
            &advancing_clock(now_ms)?,
        )
    }

    async fn renew_community_job(
        &self,
        scope: &KnowledgeScope,
        lease: &CommunityJobLease,
        now_ms: i64,
        lease_ms: u64,
    ) -> KnowledgeResult<CommunityJobLease> {
        self.renew_community_job_durable(scope, lease, lease_ms, &advancing_clock(now_ms)?)
    }

    async fn fail_community_job(
        &self,
        scope: &KnowledgeScope,
        lease: &CommunityJobLease,
        failure: CommunityJobFailure,
        now_ms: i64,
    ) -> KnowledgeResult<()> {
        self.fail_community_job_durable(scope, lease, failure, &advancing_clock(now_ms)?)
    }

    async fn retry_community_job(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
        candidate_id: &str,
        expected_attempt: u32,
    ) -> KnowledgeResult<()> {
        self.retry_community_job_durable(scope, build_id, candidate_id, expected_attempt, &|| Ok(0))
    }

    async fn community_job_status(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
        candidate_id: &str,
    ) -> KnowledgeResult<Option<CommunityJobStatus>> {
        self.community_job_status_durable(scope, build_id, candidate_id)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn advancing_clock_rejects_negative_origin_and_elapsed_overflow() {
        assert!(advancing_clock(-1).is_err());
        let clock = advancing_clock(i64::MAX).unwrap();
        std::thread::sleep(std::time::Duration::from_millis(2));
        assert!(matches!(clock(), Err(KnowledgeError::InvalidInput)));
    }
}
