use std::time::{Duration, Instant};

use reqwest::{
    header::{self, HeaderValue},
    Client,
};
use tokio::time::timeout;

use crate::application_vault::ApplicationCredentialVault;

use super::{
    http::HttpRuntime,
    remote_common::{remote_headers, retry_delay, ResolvedEndpoint},
    McpServerDefinition, SupervisorLimits,
};

impl HttpRuntime {
    pub(super) async fn fail(
        &mut self,
        server: &McpServerDefinition,
        credential_vault: Option<&ApplicationCredentialVault>,
        limits: SupervisorLimits,
    ) {
        self.reset(server, credential_vault, limits).await;
        self.consecutive_failures = self.consecutive_failures.saturating_add(1);
        self.retry_after = Some(Instant::now() + retry_delay(self.consecutive_failures, limits));
    }

    pub(super) async fn reset(
        &mut self,
        server: &McpServerDefinition,
        credential_vault: Option<&ApplicationCredentialVault>,
        limits: SupervisorLimits,
    ) {
        best_effort_delete(
            server,
            credential_vault,
            self.client.as_ref(),
            self.endpoint.as_ref(),
            self.session_id.as_ref(),
            self.protocol_version.as_ref(),
            limits.request_timeout,
        )
        .await;
        self.stop();
    }

    fn stop(&mut self) {
        self.client = None;
        self.endpoint = None;
        self.session_id = None;
        self.protocol_version = None;
        self.initialized_revision = None;
        self.server_info = None;
    }
}

pub(super) async fn best_effort_delete(
    server: &McpServerDefinition,
    credential_vault: Option<&ApplicationCredentialVault>,
    client: Option<&Client>,
    endpoint: Option<&ResolvedEndpoint>,
    session_id: Option<&HeaderValue>,
    protocol_version: Option<&HeaderValue>,
    request_timeout: Duration,
) {
    let (Some(client), Some(endpoint), Some(session_id)) = (client, endpoint, session_id) else {
        return;
    };
    let Ok(mut headers) = remote_headers(server, credential_vault) else {
        return;
    };
    headers.insert("mcp-session-id", session_id.clone());
    if let Some(protocol_version) = protocol_version {
        headers.insert("mcp-protocol-version", protocol_version.clone());
    }
    headers.insert(header::ACCEPT, HeaderValue::from_static("application/json"));
    let delete_timeout = request_timeout.min(Duration::from_secs(1));
    let _ = timeout(
        delete_timeout,
        client.delete(endpoint.url.clone()).headers(headers).send(),
    )
    .await;
}
