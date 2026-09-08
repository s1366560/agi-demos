//! Every enrollment observation is the server's actual request-pinned generation.
//! A later data operation sends the observed descriptor as a conditional header.
use super::*;
use crate::local_runtime::knowledge_authority_v2::contracts::SyncCloudEnrollment;

impl SyncCloudGeneration {
    pub(in crate::local_runtime::knowledge_authority_v2) fn validate(
        &self,
    ) -> Result<(), KnowledgeAuthorityErrorV2> {
        let descriptor = &self.descriptor;
        if self.contract_version != "1.0.0"
            || !valid_identifier(&descriptor.profile_id)
            || !(1..=9_007_199_254_740_991).contains(&descriptor.generation)
            || descriptor.digest.len() != 64
            || !descriptor
                .digest
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(KnowledgeAuthorityErrorV2::RemoteRejected);
        }
        Ok(())
    }
    pub(in crate::local_runtime::knowledge_authority_v2) fn matches(&self, other: &Self) -> bool {
        self.contract_version == other.contract_version
            && self.descriptor.profile_id == other.descriptor.profile_id
            && self.descriptor.generation == other.descriptor.generation
            && self.descriptor.digest == other.descriptor.digest
    }
    pub(in crate::local_runtime::knowledge_authority_v2) fn header(
        &self,
    ) -> Result<String, KnowledgeAuthorityErrorV2> {
        self.validate()?;
        let header =
            serde_json::to_string(self).map_err(|_| KnowledgeAuthorityErrorV2::RemoteRejected)?;
        if header.len() > 2048 {
            return Err(KnowledgeAuthorityErrorV2::RemoteRejected);
        }
        Ok(header)
    }
}

impl TrustedCloudConnection {
    pub(in crate::local_runtime::knowledge_authority_v2) async fn enrollment(
        &self,
        tenant: &str,
        project: &str,
        expected: Option<&SyncCloudGeneration>,
    ) -> Result<SyncCloudEnrollment, KnowledgeAuthorityErrorV2> {
        let response = self
            .get(
                self.project_url(project, &["knowledge-sync", "enrollment"])?,
                expected,
            )
            .await?;
        self.parse_enrollment(response, tenant, project, expected)
    }

    pub(in crate::local_runtime::knowledge_authority_v2) async fn enroll(
        &self,
        tenant: &str,
        project: &str,
        expected: &SyncCloudGeneration,
    ) -> Result<SyncCloudEnrollment, KnowledgeAuthorityErrorV2> {
        let request = self
            .request(
                Method::POST,
                self.project_url(project, &["knowledge-sync", "enrollment"])?,
                Some(expected),
            )?
            .json(&serde_json::json!({"contract_version":"1.0.0","operation":"enroll"}));
        // A failed/lost response remains uncertain. Callers may GET enrollment
        // again; this method never automatically retries an external mutation.
        let (_, response) = self.send(request, &[StatusCode::OK]).await?;
        let result = self.parse_enrollment(response, tenant, project, Some(expected))?;
        if !result.enabled {
            return Err(KnowledgeAuthorityErrorV2::SyncNotEnrolled);
        }
        Ok(result)
    }

    fn parse_enrollment(
        &self,
        response: Value,
        tenant: &str,
        project: &str,
        expected: Option<&SyncCloudGeneration>,
    ) -> Result<SyncCloudEnrollment, KnowledgeAuthorityErrorV2> {
        let result: SyncCloudEnrollment = serde_json::from_value(response)
            .map_err(|_| KnowledgeAuthorityErrorV2::RemoteRejected)?;
        result.generation.validate()?;
        if result.contract_version != "1.0.0"
            || result.tenant_id != tenant
            || result.project_id != project
            || result.actor_id != self.actor_id
            || result.bootstrap_count > 9_007_199_254_740_991
            || result.next_cursor > 9_007_199_254_740_991
        {
            return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
        }
        if expected.is_some_and(|expected| !expected.matches(&result.generation)) {
            return Err(KnowledgeAuthorityErrorV2::CloudGenerationMismatch);
        }
        Ok(result)
    }
}
