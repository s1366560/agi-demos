use agistack_core::knowledge::community::build::*;

use super::*;

#[async_trait]
impl CommunityBuildRepository for SqliteKnowledgeRepository {
    async fn create_community_build(
        &self,
        scope: &KnowledgeScope,
        request: &CommunityBuildRequest,
        now_ms: i64,
    ) -> KnowledgeResult<CommunityBuildReceipt> {
        self.create_community_build_durable(scope, request, &|| Ok(now_ms))
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
        self.claim_community_job_durable(scope, build_id, worker_id, lease_ms, &|| Ok(now_ms))
    }

    async fn renew_community_job(
        &self,
        scope: &KnowledgeScope,
        lease: &CommunityJobLease,
        now_ms: i64,
        lease_ms: u64,
    ) -> KnowledgeResult<CommunityJobLease> {
        self.renew_community_job_durable(scope, lease, lease_ms, &|| Ok(now_ms))
    }

    async fn fail_community_job(
        &self,
        scope: &KnowledgeScope,
        lease: &CommunityJobLease,
        failure: CommunityJobFailure,
        now_ms: i64,
    ) -> KnowledgeResult<()> {
        self.fail_community_job_durable(scope, lease, failure, &|| Ok(now_ms))
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
