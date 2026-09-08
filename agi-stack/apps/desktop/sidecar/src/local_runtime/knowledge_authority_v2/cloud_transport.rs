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
        let request = self
            .connection
            .request(
                Method::POST,
                self.project_url(&[
                    "knowledge-sync",
                    "conflicts",
                    &record.command.conflict_id,
                    "resolve",
                ])?,
                Some(&self.generation),
            )?
            .header("content-type", "application/json")
            .body(record.request_json.clone());
        let (status, response) = self
            .connection
            .send(request, &[StatusCode::OK, StatusCode::CONFLICT])
            .await?;
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
