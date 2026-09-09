//! Schema document view over the verified cloud connection. Exact receipt bytes
//! are retained end to end; protocol validation belongs to the core envelopes.
//! A lost or failed mutation response stays uncertain: callers recover through
//! an explicit receipt lookup, never through an automatic retry or rebase.

use agistack_core::project_schema::cloud_rpc::{
    CloudSchemaHistoryPage, CloudSchemaHistoryQuery, CloudSchemaProtocolError, CloudSchemaReceipt,
    CloudSchemaReceiptQuery, CloudSchemaReplaceRequest, MAX_CLOUD_SCHEMA_BYTES,
};
use agistack_core::project_schema::ProjectSchemaDocument;
use serde::Deserialize;
use serde_json::value::RawValue;

use super::*;

/// Local durable-state fence re-checked around every remote await point. It runs
/// synchronously and must never reenter storage while its connection lock is held.
pub(in crate::local_runtime::knowledge_authority_v2) type LocalFence<'a> =
    &'a (dyn Fn() -> Result<(), KnowledgeAuthorityErrorV2> + Sync);

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReadBody<'a> {
    #[serde(borrow)]
    document: Option<&'a RawValue>,
    generation: SyncCloudGeneration,
}

pub(in crate::local_runtime::knowledge_authority_v2) struct SchemaCloudView {
    connection: TrustedCloudConnection,
    remote_tenant_id: String,
    remote_project_id: String,
    generation: SyncCloudGeneration,
    document: Option<ProjectSchemaDocument>,
}

fn protocol(error: CloudSchemaProtocolError) -> KnowledgeAuthorityErrorV2 {
    match error {
        CloudSchemaProtocolError::ScopeMismatch => KnowledgeAuthorityErrorV2::ScopeMismatch,
        _ => KnowledgeAuthorityErrorV2::RemoteRejected,
    }
}

impl SchemaCloudView {
    /// Open only the pinned durable authority, bind the authenticated actor and
    /// remote scope, then observe the current document and server generation.
    pub(in crate::local_runtime::knowledge_authority_v2) async fn connect(
        broker: &TrustedSessionBroker,
        authority: &str,
        remote_tenant_id: &str,
        remote_project_id: &str,
        remote_actor_id: &str,
    ) -> Result<Self, KnowledgeAuthorityErrorV2> {
        let connection = TrustedCloudConnection::open_for_authority(broker, authority).await?;
        if connection.actor_id != remote_actor_id {
            return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
        }
        connection
            .verify_project(remote_tenant_id, remote_project_id)
            .await?;
        let (document, generation) = Self::read_document(
            &connection,
            remote_tenant_id,
            remote_project_id,
            None,
            &|| Ok(()),
        )
        .await?;
        Ok(Self {
            connection,
            remote_tenant_id: remote_tenant_id.into(),
            remote_project_id: remote_project_id.into(),
            generation,
            document,
        })
    }

    pub(in crate::local_runtime::knowledge_authority_v2) fn generation(
        &self,
    ) -> &SyncCloudGeneration {
        &self.generation
    }

    pub(in crate::local_runtime::knowledge_authority_v2) fn document(
        &self,
    ) -> Option<&ProjectSchemaDocument> {
        self.document.as_ref()
    }

    /// Refresh the observed document under the pinned generation condition.
    pub(in crate::local_runtime::knowledge_authority_v2) async fn read(
        &self,
        local: LocalFence<'_>,
    ) -> Result<Option<ProjectSchemaDocument>, KnowledgeAuthorityErrorV2> {
        let (document, generation) = Self::read_document(
            &self.connection,
            &self.remote_tenant_id,
            &self.remote_project_id,
            Some(&self.generation),
            local,
        )
        .await?;
        if !generation.matches(&self.generation) {
            return Err(KnowledgeAuthorityErrorV2::CloudGenerationMismatch);
        }
        Ok(document)
    }

    /// One bounded page of contiguous accepted history after an exact cursor.
    pub(in crate::local_runtime::knowledge_authority_v2) async fn history(
        &self,
        query: &CloudSchemaHistoryQuery,
        previous: Option<&CloudSchemaReceipt>,
        local: LocalFence<'_>,
    ) -> Result<CloudSchemaHistoryPage, KnowledgeAuthorityErrorV2> {
        CloudSchemaHistoryPage::require_previous(
            &self.remote_tenant_id,
            &self.remote_project_id,
            query,
            previous,
        )
        .map_err(protocol)?;
        let body =
            serde_json::to_string(query).map_err(|_| KnowledgeAuthorityErrorV2::RemoteRejected)?;
        let (_, text) = self.post("history", body, &[StatusCode::OK], local).await?;
        CloudSchemaHistoryPage::from_json(
            &text,
            &self.remote_tenant_id,
            &self.remote_project_id,
            query,
            previous,
        )
        .map_err(protocol)
    }

    /// Send the exact prepared bytes once and accept only their actual receipt.
    pub(in crate::local_runtime::knowledge_authority_v2) async fn replace(
        &self,
        request: &CloudSchemaReplaceRequest,
        local: LocalFence<'_>,
    ) -> Result<CloudSchemaReceipt, KnowledgeAuthorityErrorV2> {
        let (_, text) = self
            .post(
                "replace",
                request.as_json().to_owned(),
                &[StatusCode::OK],
                local,
            )
            .await?;
        let receipt =
            CloudSchemaReceipt::from_json(&text, &self.remote_tenant_id, &self.remote_project_id)
                .map_err(protocol)?;
        request.require_receipt(&receipt).map_err(protocol)?;
        Ok(receipt)
    }

    /// Actor-scoped receipt lookup. A missing receipt is an explicit absence.
    pub(in crate::local_runtime::knowledge_authority_v2) async fn receipt(
        &self,
        query: &CloudSchemaReceiptQuery,
        local: LocalFence<'_>,
    ) -> Result<Option<CloudSchemaReceipt>, KnowledgeAuthorityErrorV2> {
        let body =
            serde_json::to_string(query).map_err(|_| KnowledgeAuthorityErrorV2::RemoteRejected)?;
        let (status, text) = self
            .post(
                "receipt",
                body,
                &[StatusCode::OK, StatusCode::NOT_FOUND],
                local,
            )
            .await?;
        if status == StatusCode::NOT_FOUND {
            return Ok(None);
        }
        CloudSchemaReceipt::from_json(&text, &self.remote_tenant_id, &self.remote_project_id)
            .map(Some)
            .map_err(protocol)
    }

    async fn read_document(
        connection: &TrustedCloudConnection,
        tenant: &str,
        project: &str,
        expected: Option<&SyncCloudGeneration>,
        local: LocalFence<'_>,
    ) -> Result<(Option<ProjectSchemaDocument>, SyncCloudGeneration), KnowledgeAuthorityErrorV2>
    {
        let request = connection
            .request(
                Method::POST,
                connection.project_url(project, &["schema", "document", "read"])?,
                expected,
            )?
            .header("content-type", "application/json")
            .body("{}");
        let (_, bytes) = connection
            .send_bounded_bytes(request, &[StatusCode::OK], MAX_CLOUD_SCHEMA_BYTES, local)
            .await?;
        let text =
            String::from_utf8(bytes).map_err(|_| KnowledgeAuthorityErrorV2::RemoteRejected)?;
        let body: ReadBody<'_> =
            serde_json::from_str(&text).map_err(|_| KnowledgeAuthorityErrorV2::RemoteRejected)?;
        body.generation.validate()?;
        let document = body
            .document
            .map(|raw| ProjectSchemaDocument::from_json(raw.get()))
            .transpose()
            .map_err(|_| KnowledgeAuthorityErrorV2::RemoteRejected)?;
        if let Some(document) = &document {
            if document.tenant_id() != tenant || document.project_id() != project {
                return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
            }
        }
        if expected.is_some_and(|expected| !expected.matches(&body.generation)) {
            return Err(KnowledgeAuthorityErrorV2::CloudGenerationMismatch);
        }
        Ok((document, body.generation))
    }

    async fn post(
        &self,
        suffix: &str,
        body: String,
        accepted: &[StatusCode],
        local: LocalFence<'_>,
    ) -> Result<(StatusCode, String), KnowledgeAuthorityErrorV2> {
        let request = self
            .connection
            .request(
                Method::POST,
                self.connection
                    .project_url(&self.remote_project_id, &["schema", "document", suffix])?,
                Some(&self.generation),
            )?
            .header("content-type", "application/json")
            .body(body);
        let (status, bytes) = self
            .connection
            .send_bounded_bytes(request, accepted, MAX_CLOUD_SCHEMA_BYTES, local)
            .await?;
        let text =
            String::from_utf8(bytes).map_err(|_| KnowledgeAuthorityErrorV2::RemoteRejected)?;
        Ok((status, text))
    }
}
