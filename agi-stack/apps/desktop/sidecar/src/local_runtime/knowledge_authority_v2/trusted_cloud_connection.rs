//! Cloud credentials stay inside the application vault. This connection never
//! reads or changes the selected local platform/session authority.
use std::time::Duration;

use futures_util::StreamExt;
use reqwest::{Client, Method, RequestBuilder, Response, StatusCode, Url};
use serde_json::Value;
use sha2::{Digest, Sha256};

use super::contracts::{SyncCloudConnectionProjection, SyncCloudGeneration};
use super::KnowledgeAuthorityErrorV2;
use crate::local_runtime::platform_plugin_sync_v2::{
    control_plane_url, load_cloud_authority, CloudAuthorityV2,
};
use crate::trusted_session::{
    TrustedSessionBroker, TrustedSessionCredentialKind, TrustedSessionRuntimeMode,
    TrustedSessionSnapshot,
};

#[path = "sync_discovery.rs"]
mod discovery;
#[path = "sync_enrollment.rs"]
mod enrollment;

pub(super) const GENERATION_HEADER: &str = "x-memstack-knowledge-sync-generation";
const MAX_RESPONSE_BYTES: usize = 8 * 1024 * 1024;

pub(super) struct TrustedCloudConnection {
    client: Client,
    authority: CloudAuthorityV2,
    broker: TrustedSessionBroker,
    epoch: u64,
    expires_at: Option<String>,
    pub(super) canonical_authority: String,
    pub(super) actor_id: String,
}

impl TrustedCloudConnection {
    pub(super) async fn open(
        broker: &TrustedSessionBroker,
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
        let mut connection = Self {
            client,
            broker: broker.clone(),
            epoch: snapshot.epoch,
            expires_at: snapshot.record.and_then(|record| record.expires_at),
            canonical_authority: control_plane_url(&authority.base_url, "")
                .as_str()
                .trim_end_matches('/')
                .to_owned(),
            authority,
            actor_id: String::new(),
        };
        if !valid_identifier(&connection.canonical_authority) {
            return Err(KnowledgeAuthorityErrorV2::TransportUnavailable);
        }
        let user = connection.get(connection.url("auth/me"), None).await?;
        // The production auth.User response has no id alias.
        let actor = user["user_id"]
            .as_str()
            .filter(|actor| valid_identifier(actor))
            .ok_or(KnowledgeAuthorityErrorV2::ScopeMismatch)?;
        if user["is_active"].as_bool() != Some(true) {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        connection.actor_id = actor.to_owned();
        Ok(connection)
    }

    pub(super) fn projection(&self, nonce: &uuid::Uuid) -> SyncCloudConnectionProjection {
        // No credential or credential-derived fingerprint enters this projection.
        // A generation-local random nonce prevents reuse after restart/recreation.
        let mut digest = Sha256::new();
        digest.update(nonce.as_bytes());
        digest.update(self.epoch.to_be_bytes());
        for value in [&self.canonical_authority, &self.actor_id] {
            digest.update((value.len() as u64).to_be_bytes());
            digest.update(value.as_bytes());
        }
        SyncCloudConnectionProjection {
            connection_revision: format!("{:x}", digest.finalize()),
            authority: self.canonical_authority.clone(),
            actor_id: self.actor_id.clone(),
        }
    }

    pub(super) fn require_observation(
        &self,
        nonce: &uuid::Uuid,
        expected: &str,
    ) -> Result<(), KnowledgeAuthorityErrorV2> {
        if self.projection(nonce).connection_revision != expected {
            return Err(KnowledgeAuthorityErrorV2::CloudConnectionMismatch);
        }
        self.ensure_current()
    }

    pub(super) fn url(&self, path: &str) -> Url {
        control_plane_url(&self.authority.base_url, path)
    }

    pub(super) fn project_url(
        &self,
        project: &str,
        suffix: &[&str],
    ) -> Result<Url, KnowledgeAuthorityErrorV2> {
        if !valid_identifier(project) {
            return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
        }
        let mut url = self.url("projects");
        {
            let mut path = url
                .path_segments_mut()
                .map_err(|_| KnowledgeAuthorityErrorV2::TransportUnavailable)?;
            path.push(project);
            for segment in suffix {
                path.push(segment);
            }
        }
        Ok(url)
    }

    pub(super) fn request(
        &self,
        method: Method,
        url: Url,
        generation: Option<&SyncCloudGeneration>,
    ) -> Result<RequestBuilder, KnowledgeAuthorityErrorV2> {
        let request = self
            .client
            .request(method, url)
            .bearer_auth(&self.authority.credential);
        match generation {
            Some(generation) => Ok(request.header(GENERATION_HEADER, generation.header()?)),
            None => Ok(request),
        }
    }

    pub(super) async fn get(
        &self,
        url: Url,
        generation: Option<&SyncCloudGeneration>,
    ) -> Result<Value, KnowledgeAuthorityErrorV2> {
        let (_, body) = self
            .send(
                self.request(Method::GET, url, generation)?,
                &[StatusCode::OK],
            )
            .await?;
        Ok(body)
    }

    pub(super) async fn send(
        &self,
        request: RequestBuilder,
        accepted: &[StatusCode],
    ) -> Result<(StatusCode, Value), KnowledgeAuthorityErrorV2> {
        self.ensure_current()?;
        let response = request
            .send()
            .await
            .map_err(|_| KnowledgeAuthorityErrorV2::RemoteRejected)?;
        self.ensure_current()?;
        let status = response.status();
        if matches!(status, StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN) {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        if status == StatusCode::PRECONDITION_FAILED {
            return Err(KnowledgeAuthorityErrorV2::CloudGenerationMismatch);
        }
        if !accepted.contains(&status) {
            return Err(KnowledgeAuthorityErrorV2::RemoteRejected);
        }
        let body = self.bounded_json(response).await?;
        self.ensure_current()?;
        Ok((status, body))
    }

    async fn bounded_json(&self, response: Response) -> Result<Value, KnowledgeAuthorityErrorV2> {
        if response
            .content_length()
            .is_some_and(|length| length > MAX_RESPONSE_BYTES as u64)
        {
            return Err(KnowledgeAuthorityErrorV2::RemoteRejected);
        }
        let mut stream = response.bytes_stream();
        let mut bytes = Vec::new();
        while let Some(chunk) = stream.next().await {
            self.ensure_current()?;
            let chunk = chunk.map_err(|_| KnowledgeAuthorityErrorV2::RemoteRejected)?;
            if bytes.len().saturating_add(chunk.len()) > MAX_RESPONSE_BYTES {
                return Err(KnowledgeAuthorityErrorV2::RemoteRejected);
            }
            bytes.extend_from_slice(&chunk);
        }
        self.ensure_current()?;
        serde_json::from_slice(&bytes).map_err(|_| KnowledgeAuthorityErrorV2::RemoteRejected)
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
            || record.expires_at != self.expires_at
        {
            return Err(KnowledgeAuthorityErrorV2::TransportUnavailable);
        }
        let base = Url::parse(&record.api_base_url)
            .map_err(|_| KnowledgeAuthorityErrorV2::TransportUnavailable)?;
        if control_plane_url(&base, "").as_str().trim_end_matches('/') != self.canonical_authority {
            return Err(KnowledgeAuthorityErrorV2::TransportUnavailable);
        }
        self.ensure_deadline()
    }

    /// Does not reacquire the vault lock. Safe inside a guarded storage commit.
    pub(super) fn ensure_deadline(&self) -> Result<(), KnowledgeAuthorityErrorV2> {
        if let Some(expires_at) = &self.expires_at {
            let expiry = chrono::DateTime::parse_from_rfc3339(expires_at)
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

pub(super) fn valid_identifier(value: &str) -> bool {
    !value.is_empty() && value.trim() == value && value.chars().count() <= 512
}
