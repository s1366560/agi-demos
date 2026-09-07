use super::*;
use agistack_core::knowledge::sync::cloud_resolution::KnowledgeCloudResolutionRecord;

pub(in crate::local_runtime::knowledge_authority_v2) enum CloudResolutionResponse {
    Success(Value),
    Stale(Value),
}
impl VerifiedCloudTransport {
    pub(in crate::local_runtime::knowledge_authority_v2) async fn conflict_snapshot(
        &self,
        id: &str,
    ) -> Result<Value, KnowledgeAuthorityErrorV2> {
        self.get(self.project_url(&["knowledge-sync", "conflicts", id])?)
            .await
    }
    pub(in crate::local_runtime::knowledge_authority_v2) async fn resolve_cloud(
        &self,
        record: &KnowledgeCloudResolutionRecord,
    ) -> Result<CloudResolutionResponse, KnowledgeAuthorityErrorV2> {
        self.ensure_current()?;
        let response = self
            .client
            .post(self.project_url(&[
                "knowledge-sync",
                "conflicts",
                &record.command.conflict_id,
                "resolve",
            ])?)
            .bearer_auth(&self.authority.credential)
            .header("content-type", "application/json")
            .body(record.request_json.clone())
            .send()
            .await
            .map_err(|_| KnowledgeAuthorityErrorV2::RemoteRejected)?;
        self.ensure_current()?;
        let status = response.status();
        if matches!(status, StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN) {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        if !matches!(status, StatusCode::OK | StatusCode::CONFLICT) {
            return Err(KnowledgeAuthorityErrorV2::RemoteRejected);
        }
        let response = bounded_json(response).await?;
        self.ensure_current()?;
        match status {
            StatusCode::OK => Ok(CloudResolutionResponse::Success(response)),
            StatusCode::CONFLICT
                if response["detail"]["code"] == "knowledge_sync_resolution_stale" =>
            {
                Ok(CloudResolutionResponse::Stale(response))
            }
            _ => Err(KnowledgeAuthorityErrorV2::RemoteRejected),
        }
    }
}
