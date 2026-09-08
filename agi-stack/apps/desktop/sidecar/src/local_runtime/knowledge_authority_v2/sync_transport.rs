//! Renderer input cannot supply cloud credentials, origins or remote receipts.
//! Every data operation authenticates its actor/project and observes enrollment
//! before sending the server's request-pinned generation as a condition.
use agistack_core::knowledge::sync::push::{KnowledgeSyncTarget, PreparedKnowledgePush};
use agistack_core::knowledge::sync::KnowledgeSyncLink;
use reqwest::{Method, StatusCode, Url};
use serde_json::Value;

use super::contracts::SyncCloudGeneration;
use super::trusted_cloud_connection::TrustedCloudConnection;
use super::KnowledgeAuthorityErrorV2;
use crate::trusted_session::TrustedSessionBroker;

#[path = "cloud_transport.rs"]
mod cloud_transport;
pub(super) use cloud_transport::CloudResolutionResponse;

pub(super) struct VerifiedCloudTransport {
    connection: TrustedCloudConnection,
    pub(super) generation: SyncCloudGeneration,
    pub(super) target: KnowledgeSyncTarget,
}

impl VerifiedCloudTransport {
    pub(super) async fn connect(
        broker: &TrustedSessionBroker,
        link: KnowledgeSyncLink,
    ) -> Result<Self, KnowledgeAuthorityErrorV2> {
        let connection = TrustedCloudConnection::open(broker).await?;
        if connection.actor_id != link.remote_actor_id {
            return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
        }
        connection
            .verify_project(&link.remote_tenant_id, &link.remote_project_id)
            .await?;
        let enrollment = connection
            .enrollment(&link.remote_tenant_id, &link.remote_project_id, None)
            .await?;
        if !enrollment.enabled {
            return Err(KnowledgeAuthorityErrorV2::SyncNotEnrolled);
        }
        Ok(Self {
            target: KnowledgeSyncTarget {
                authority: connection.canonical_authority.clone(),
                link,
            },
            generation: enrollment.generation,
            connection,
        })
    }

    fn project_url(&self, suffix: &[&str]) -> Result<Url, KnowledgeAuthorityErrorV2> {
        self.connection
            .project_url(&self.target.link.remote_project_id, suffix)
    }

    async fn get(&self, url: Url) -> Result<Value, KnowledgeAuthorityErrorV2> {
        self.connection.get(url, Some(&self.generation)).await
    }

    pub(super) async fn pull(&self, after: u64) -> Result<Value, KnowledgeAuthorityErrorV2> {
        let mut url = self.project_url(&["knowledge-sync", "changes"])?;
        url.query_pairs_mut()
            .append_pair("after", &after.to_string())
            .append_pair("limit", "1");
        self.get(url).await
    }

    pub(super) async fn push(
        &self,
        prepared: &PreparedKnowledgePush,
    ) -> Result<(Value, Option<Value>), KnowledgeAuthorityErrorV2> {
        let request = self
            .connection
            .request(
                Method::POST,
                self.project_url(&["knowledge-sync", "mutations"])?,
                Some(&self.generation),
            )?
            .header("content-type", "application/json")
            .body(prepared.request_json.clone());
        let (status, response) = self
            .connection
            .send(request, &[StatusCode::OK, StatusCode::CONFLICT])
            .await?;
        let conflict = if status == StatusCode::CONFLICT {
            if response["receipt"]["status"] != "conflict" {
                return Err(KnowledgeAuthorityErrorV2::RemoteRejected);
            }
            let id = response["receipt"]["conflict_id"]
                .as_str()
                .ok_or(KnowledgeAuthorityErrorV2::RemoteRejected)?;
            Some(
                self.get(self.project_url(&["knowledge-sync", "conflicts", id])?)
                    .await?,
            )
        } else {
            if response["receipt"]["status"] != "applied" {
                return Err(KnowledgeAuthorityErrorV2::RemoteRejected);
            }
            None
        };
        self.ensure_current()?;
        Ok((response, conflict))
    }

    pub(super) fn ensure_current(&self) -> Result<(), KnowledgeAuthorityErrorV2> {
        self.connection.ensure_current()
    }

    pub(super) fn with_current_session<T>(
        &self,
        action: impl FnOnce() -> Result<T, KnowledgeAuthorityErrorV2>,
    ) -> Result<T, KnowledgeAuthorityErrorV2> {
        self.connection.with_current_session(action)
    }
}
