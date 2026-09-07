//! The renderer can request a push, but cannot supply URLs, credentials or
//! remote receipts. Those come exclusively from the trusted application session
//! and a verified cloud HTTP response held for this operation.

use std::time::Duration;

use agistack_core::knowledge::sync::push::{KnowledgeSyncTarget, PreparedKnowledgePush};
use agistack_core::knowledge::sync::KnowledgeSyncLink;
use futures_util::StreamExt;
use reqwest::{Client, Response, StatusCode, Url};
use serde_json::Value;

use super::KnowledgeAuthorityErrorV2;
use crate::local_runtime::platform_plugin_sync_v2::{
    control_plane_url, load_cloud_authority, CloudAuthorityV2,
};
use crate::trusted_session::{
    TrustedSessionBroker, TrustedSessionCredentialKind, TrustedSessionRuntimeMode,
    TrustedSessionSnapshot,
};

pub(super) struct VerifiedCloudTransport {
    client: Client,
    authority: CloudAuthorityV2,
    broker: TrustedSessionBroker,
    epoch: u64,
    pub(super) target: KnowledgeSyncTarget,
}

impl VerifiedCloudTransport {
    pub(super) async fn connect(
        broker: &TrustedSessionBroker,
        link: KnowledgeSyncLink,
    ) -> Result<Self, KnowledgeAuthorityErrorV2> {
        let snapshot = broker
            .snapshot()
            .map_err(|_| KnowledgeAuthorityErrorV2::TransportUnavailable)?;
        let authority = load_cloud_authority(broker)
            .map_err(|_| KnowledgeAuthorityErrorV2::TransportUnavailable)?
            .ok_or(KnowledgeAuthorityErrorV2::TransportUnavailable)?;
        let client = Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs(30))
            .build()
            .map_err(|_| KnowledgeAuthorityErrorV2::TransportUnavailable)?;
        let transport = Self {
            client,
            broker: broker.clone(),
            epoch: snapshot.epoch,
            target: KnowledgeSyncTarget {
                authority: control_plane_url(&authority.base_url, "")
                    .as_str()
                    .trim_end_matches('/')
                    .to_owned(),
                link,
            },
            authority,
        };
        transport.ensure_current()?;
        let user = transport
            .get(control_plane_url(&transport.authority.base_url, "auth/me"))
            .await?;
        if user["id"] != transport.target.link.remote_actor_id {
            return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
        }
        let mut project_url = transport.project_url(&[])?;
        project_url
            .query_pairs_mut()
            .append_pair("tenant_id", &transport.target.link.remote_tenant_id);
        let project = transport.get(project_url).await?;
        if project["id"] != transport.target.link.remote_project_id
            || project["tenant_id"] != transport.target.link.remote_tenant_id
        {
            return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
        }
        Ok(transport)
    }

    fn project_url(&self, suffix: &[&str]) -> Result<Url, KnowledgeAuthorityErrorV2> {
        let mut url = control_plane_url(&self.authority.base_url, "projects");
        {
            let mut path = url
                .path_segments_mut()
                .map_err(|_| KnowledgeAuthorityErrorV2::TransportUnavailable)?;
            path.push(&self.target.link.remote_project_id);
            for segment in suffix {
                path.push(segment);
            }
        }
        Ok(url)
    }

    async fn get(&self, url: Url) -> Result<Value, KnowledgeAuthorityErrorV2> {
        self.ensure_current()?;
        let response = self
            .client
            .get(url)
            .bearer_auth(&self.authority.credential)
            .send()
            .await
            .map_err(|_| KnowledgeAuthorityErrorV2::RemoteRejected)?;
        self.ensure_current()?;
        if response.status() != StatusCode::OK {
            return Err(KnowledgeAuthorityErrorV2::RemoteRejected);
        }
        let result = bounded_json(response).await?;
        self.ensure_current()?;
        Ok(result)
    }

    pub(super) async fn pull(&self, after: u64) -> Result<Value, KnowledgeAuthorityErrorV2> {
        let mut url = self.project_url(&["knowledge-sync", "changes"])?;
        // One maximum-size memory, including JSON escaping and metadata, fits
        // within bounded_json. The receipt's has_more drives subsequent calls.
        url.query_pairs_mut()
            .append_pair("after", &after.to_string())
            .append_pair("limit", "1");
        self.get(url).await
    }

    pub(super) async fn push(
        &self,
        prepared: &PreparedKnowledgePush,
    ) -> Result<(Value, Option<Value>), KnowledgeAuthorityErrorV2> {
        self.ensure_current()?;
        let response = self
            .client
            .post(self.project_url(&["knowledge-sync", "mutations"])?)
            .bearer_auth(&self.authority.credential)
            .header("content-type", "application/json")
            .body(prepared.request_json.clone())
            .send()
            .await
            .map_err(|_| KnowledgeAuthorityErrorV2::RemoteRejected)?;
        self.ensure_current()?;
        let status = response.status();
        if !matches!(status, StatusCode::OK | StatusCode::CONFLICT) {
            return Err(KnowledgeAuthorityErrorV2::RemoteRejected);
        }
        let response = bounded_json(response).await?;
        self.ensure_current()?;
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

    fn check_snapshot(
        &self,
        snapshot: TrustedSessionSnapshot,
    ) -> Result<(), KnowledgeAuthorityErrorV2> {
        let record = snapshot
            .record
            .ok_or(KnowledgeAuthorityErrorV2::TransportUnavailable)?;
        if snapshot.epoch != self.epoch
            || record.runtime_mode != TrustedSessionRuntimeMode::Cloud
            || record.credential_kind != TrustedSessionCredentialKind::CloudBearer
            || record.credential != self.authority.credential
        {
            return Err(KnowledgeAuthorityErrorV2::TransportUnavailable);
        }
        let base = Url::parse(&record.api_base_url)
            .map_err(|_| KnowledgeAuthorityErrorV2::TransportUnavailable)?;
        if control_plane_url(&base, "").as_str().trim_end_matches('/') != self.target.authority {
            return Err(KnowledgeAuthorityErrorV2::TransportUnavailable);
        }
        if let Some(expires_at) = record.expires_at {
            let expiry = chrono::DateTime::parse_from_rfc3339(&expires_at)
                .map_err(|_| KnowledgeAuthorityErrorV2::TransportUnavailable)?;
            if expiry <= chrono::Utc::now() {
                return Err(KnowledgeAuthorityErrorV2::TransportUnavailable);
            }
        }
        Ok(())
    }

    pub(super) fn ensure_current(&self) -> Result<(), KnowledgeAuthorityErrorV2> {
        self.with_current_session(|| Ok(()))
    }

    pub(super) fn with_current_session<T>(
        &self,
        action: impl FnOnce() -> Result<T, KnowledgeAuthorityErrorV2>,
    ) -> Result<T, KnowledgeAuthorityErrorV2> {
        self.broker
            .with_snapshot(|snapshot| {
                self.check_snapshot(snapshot)?;
                action()
            })
            .map_err(|_| KnowledgeAuthorityErrorV2::TransportUnavailable)?
    }
}

async fn bounded_json(response: Response) -> Result<Value, KnowledgeAuthorityErrorV2> {
    const MAX_RESPONSE_BYTES: usize = 8 * 1024 * 1024;
    if response
        .content_length()
        .is_some_and(|length| length > MAX_RESPONSE_BYTES as u64)
    {
        return Err(KnowledgeAuthorityErrorV2::RemoteRejected);
    }
    let mut stream = response.bytes_stream();
    let mut bytes = Vec::new();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|_| KnowledgeAuthorityErrorV2::RemoteRejected)?;
        if bytes.len().saturating_add(chunk.len()) > MAX_RESPONSE_BYTES {
            return Err(KnowledgeAuthorityErrorV2::RemoteRejected);
        }
        bytes.extend_from_slice(&chunk);
    }
    serde_json::from_slice(&bytes).map_err(|_| KnowledgeAuthorityErrorV2::RemoteRejected)
}
