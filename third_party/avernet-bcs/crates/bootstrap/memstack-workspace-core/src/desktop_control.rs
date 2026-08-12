//! Authenticated private control protocol for the Desktop Local helper.

use std::path::PathBuf;
use std::time::{Duration, Instant};

use anyhow::{Context, Result, bail};
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use futures::{SinkExt as _, StreamExt as _};
use hmac::{Hmac, Mac as _};
use reqwest::Url;
use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};
use tokio::io::{Stdin, Stdout};
use tokio::time::sleep;
use tokio_util::codec::{FramedRead, FramedWrite, LinesCodec};
use zeroize::Zeroizing;

const PROTOCOL_VERSION: u16 = 1;
const MAX_CONTROL_LINE_BYTES: usize = 64 * 1024;
const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);
const HEALTH_RETRY_DELAY: Duration = Duration::from_millis(100);

type HmacSha256 = Hmac<Sha256>;

fn ready_proof(secret: &[u8], nonce: &str, pid: u32, api_base_url: &str) -> Result<String> {
    let canonical = format!("{PROTOCOL_VERSION}\n{nonce}\n{pid}\n{api_base_url}");
    let mut mac = HmacSha256::new_from_slice(secret)
        .context("failed to initialize Desktop readiness proof")?;
    mac.update(canonical.as_bytes());
    Ok(hex::encode(mac.finalize().into_bytes()))
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct DesktopInitialize {
    #[serde(rename = "type")]
    message_type: String,
    protocol_version: u16,
    nonce: String,
    secret: String,
    config_path: PathBuf,
    mode: String,
    service_token: String,
    agent_registry_url: String,
    agent_registry_token: String,
    provider_webhook_url: String,
    provider_webhook_token: String,
    provider_event_token: String,
    plan_dispatch_url: String,
    instance_id: String,
}

impl DesktopInitialize {
    pub(crate) fn config_path(&self) -> &PathBuf {
        &self.config_path
    }

    pub(crate) fn service_token(&self) -> &str {
        &self.service_token
    }

    pub(crate) fn agent_registry_url(&self) -> &str {
        &self.agent_registry_url
    }

    pub(crate) fn agent_registry_token(&self) -> &str {
        &self.agent_registry_token
    }

    pub(crate) fn provider_webhook_url(&self) -> &str {
        &self.provider_webhook_url
    }

    pub(crate) fn provider_webhook_token(&self) -> &str {
        &self.provider_webhook_token
    }

    pub(crate) fn provider_event_token(&self) -> &str {
        &self.provider_event_token
    }

    pub(crate) fn plan_dispatch_url(&self) -> &str {
        &self.plan_dispatch_url
    }

    pub(crate) fn instance_id(&self) -> &str {
        &self.instance_id
    }

    fn validate(&self) -> Result<Zeroizing<Vec<u8>>> {
        if self.message_type != "desktop_initialize" {
            bail!("first Desktop control frame must be desktop_initialize");
        }
        if self.protocol_version != PROTOCOL_VERSION {
            bail!("unsupported Desktop control protocol version");
        }
        if self.mode != "desktop-local" {
            bail!("Desktop control mode must be desktop-local");
        }
        if !self.config_path.is_absolute() {
            bail!("Desktop control configPath must be absolute");
        }
        validate_identifier("nonce", &self.nonce, 16, 256)?;
        validate_identifier("instanceId", &self.instance_id, 1, 256)?;
        let secret = Zeroizing::new(
            URL_SAFE_NO_PAD
                .decode(self.secret.as_bytes())
                .context("Desktop control secret must be URL-safe base64")?,
        );
        if secret.len() != 32 {
            bail!("Desktop control secret must decode to 32 bytes");
        }
        let credentials = [
            ("serviceToken", self.service_token.as_str()),
            ("agentRegistryToken", self.agent_registry_token.as_str()),
            ("providerWebhookToken", self.provider_webhook_token.as_str()),
            ("providerEventToken", self.provider_event_token.as_str()),
        ];
        for (name, value) in credentials {
            validate_identifier(name, value, 32, 512)?;
        }
        for left in 0..credentials.len() {
            for right in (left + 1)..credentials.len() {
                if credentials[left].1 == credentials[right].1 {
                    bail!("Desktop control credentials must be distinct");
                }
            }
        }
        for (name, value) in [
            ("agentRegistryUrl", self.agent_registry_url.as_str()),
            ("providerWebhookUrl", self.provider_webhook_url.as_str()),
            ("planDispatchUrl", self.plan_dispatch_url.as_str()),
        ] {
            validate_loopback_url(name, value)?;
        }
        Ok(secret)
    }
}

fn validate_identifier(name: &str, value: &str, minimum: usize, maximum: usize) -> Result<()> {
    if !(minimum..=maximum).contains(&value.len())
        || value
            .bytes()
            .any(|byte| byte.is_ascii_control() || byte.is_ascii_whitespace())
    {
        bail!("Desktop control {name} is invalid");
    }
    Ok(())
}

fn validate_loopback_url(name: &str, value: &str) -> Result<()> {
    let url = Url::parse(value).with_context(|| format!("Desktop control {name} is invalid"))?;
    let loopback = url
        .host_str()
        .and_then(|host| host.parse::<std::net::IpAddr>().ok())
        .is_some_and(|address| address.is_loopback());
    if url.scheme() != "http"
        || !loopback
        || url.port().is_none()
        || url.username() != ""
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        bail!("Desktop control {name} must be an explicit loopback HTTP URL");
    }
    Ok(())
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopReady<'a> {
    #[serde(rename = "type")]
    message_type: &'static str,
    protocol_version: u16,
    nonce: &'a str,
    pid: u32,
    api_base_url: &'a str,
    proof: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct DesktopShutdown {
    #[serde(rename = "type")]
    message_type: String,
    protocol_version: u16,
    nonce: String,
}

fn validate_shutdown_frame(frame: &str, expected_nonce: &str) -> Result<()> {
    let shutdown: DesktopShutdown =
        serde_json::from_str(frame).context("invalid Desktop shutdown frame")?;
    if shutdown.message_type != "desktop_shutdown"
        || shutdown.protocol_version != PROTOCOL_VERSION
        || shutdown.nonce != expected_nonce
    {
        bail!("Desktop shutdown frame does not match the authenticated session");
    }
    Ok(())
}

pub(crate) struct DesktopControl {
    input: FramedRead<Stdin, LinesCodec>,
    output: FramedWrite<Stdout, LinesCodec>,
    nonce: String,
    secret: Zeroizing<Vec<u8>>,
}

impl DesktopControl {
    pub(crate) async fn read_initialize() -> Result<(Self, DesktopInitialize)> {
        let mut input = FramedRead::new(
            tokio::io::stdin(),
            LinesCodec::new_with_max_length(MAX_CONTROL_LINE_BYTES),
        );
        let line = input
            .next()
            .await
            .context("Desktop control pipe closed before initialization")?
            .context("Desktop initialization frame exceeds the protocol limit")?;
        let initialize: DesktopInitialize =
            serde_json::from_str(&line).context("invalid Desktop initialization frame")?;
        let secret = initialize.validate()?;
        Ok((
            Self {
                input,
                output: FramedWrite::new(
                    tokio::io::stdout(),
                    LinesCodec::new_with_max_length(MAX_CONTROL_LINE_BYTES),
                ),
                nonce: initialize.nonce.clone(),
                secret,
            },
            initialize,
        ))
    }

    pub(crate) fn principal_signing_key(&self) -> Zeroizing<String> {
        let mut digest = Sha256::new();
        digest.update(b"memstack-workspace-desktop-principal-v1\0");
        digest.update(self.secret.as_slice());
        Zeroizing::new(URL_SAFE_NO_PAD.encode(digest.finalize()))
    }

    pub(crate) fn group_session_ws_signing_key(&self) -> Zeroizing<String> {
        let mut digest = Sha256::new();
        digest.update(b"memstack-workspace-desktop-group-session-v1\0");
        digest.update(self.secret.as_slice());
        Zeroizing::new(URL_SAFE_NO_PAD.encode(digest.finalize()))
    }

    pub(crate) async fn wait_until_healthy(&self, api_base_url: &str) -> Result<()> {
        validate_loopback_url("apiBaseUrl", api_base_url)?;
        let client = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(1))
            .timeout(Duration::from_secs(2))
            .build()
            .context("failed to initialize Desktop readiness client")?;
        let health_url = format!("{}/health", api_base_url.trim_end_matches('/'));
        let deadline = Instant::now() + HEALTH_TIMEOUT;
        loop {
            if let Ok(response) = client.get(&health_url).send().await
                && response.status().is_success()
            {
                return Ok(());
            }
            if Instant::now() >= deadline {
                bail!("Workspace Core did not bind and become healthy before the deadline");
            }
            sleep(HEALTH_RETRY_DELAY).await;
        }
    }

    pub(crate) async fn emit_ready(&mut self, api_base_url: &str) -> Result<()> {
        let pid = std::process::id();
        let ready = DesktopReady {
            message_type: "desktop_ready",
            protocol_version: PROTOCOL_VERSION,
            nonce: &self.nonce,
            pid,
            api_base_url,
            proof: ready_proof(self.secret.as_slice(), &self.nonce, pid, api_base_url)?,
        };
        let encoded =
            serde_json::to_string(&ready).context("failed to encode Desktop readiness")?;
        self.output
            .send(encoded)
            .await
            .context("failed to write Desktop readiness frame")
    }

    pub(crate) async fn wait_for_shutdown(&mut self) -> Result<()> {
        let Some(frame) = self.input.next().await else {
            return Ok(());
        };
        let frame = frame.context("Desktop shutdown frame exceeds the protocol limit")?;
        validate_shutdown_frame(&frame, &self.nonce)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn initialize() -> DesktopInitialize {
        DesktopInitialize {
            message_type: "desktop_initialize".to_string(),
            protocol_version: PROTOCOL_VERSION,
            nonce: "nonce-0123456789abcdef".to_string(),
            secret: URL_SAFE_NO_PAD.encode([7_u8; 32]),
            config_path: PathBuf::from("/tmp/workspace-core/config.toml"),
            mode: "desktop-local".to_string(),
            service_token: "service-token-0123456789abcdef0123456789".to_string(),
            agent_registry_url: "http://127.0.0.1:31000/internal/registry".to_string(),
            agent_registry_token: "registry-token-0123456789abcdef012345678".to_string(),
            provider_webhook_url: "http://127.0.0.1:31000/internal/provider".to_string(),
            provider_webhook_token: "webhook-token-0123456789abcdef0123456789".to_string(),
            provider_event_token: "event-token-0123456789abcdef012345678901".to_string(),
            plan_dispatch_url: "http://127.0.0.1:31000/internal/plan-dispatch".to_string(),
            instance_id: "desktop-sidecar-1".to_string(),
        }
    }

    #[test]
    fn initialize_requires_distinct_credentials_and_loopback_urls() {
        assert!(initialize().validate().is_ok());
        let mut duplicate = initialize();
        duplicate.provider_event_token = duplicate.provider_webhook_token.clone();
        let duplicate_error = duplicate.validate().err().map(|error| error.to_string());
        assert!(
            duplicate_error
                .as_deref()
                .is_some_and(|error| error.contains("distinct"))
        );
        let mut external = initialize();
        external.agent_registry_url = "https://registry.example.com".to_string();
        let external_error = external.validate().err().map(|error| error.to_string());
        assert!(
            external_error
                .as_deref()
                .is_some_and(|error| error.contains("loopback"))
        );
    }

    #[test]
    fn ready_proof_uses_the_frozen_canonical_field_order() {
        let proof = ready_proof(
            &[7_u8; 32],
            "nonce-0123456789abcdef",
            42,
            "http://127.0.0.1:21000",
        )
        .ok();
        assert_eq!(
            proof.as_deref(),
            Some("98b9a162b1f8bbc10854bf6d531a81b2690dc74079d589e94f938fc244b46e20"),
        );
    }

    #[test]
    fn shutdown_frame_completes_without_requiring_control_pipe_eof() {
        let frame = serde_json::json!({
            "type": "desktop_shutdown",
            "protocolVersion": PROTOCOL_VERSION,
            "nonce": "nonce-0123456789abcdef",
        })
        .to_string();

        assert!(validate_shutdown_frame(&frame, "nonce-0123456789abcdef").is_ok());
    }

    #[test]
    fn shutdown_frame_rejects_a_different_session() {
        let frame = serde_json::json!({
            "type": "desktop_shutdown",
            "protocolVersion": PROTOCOL_VERSION,
            "nonce": "nonce-from-another-session",
        })
        .to_string();

        let error = validate_shutdown_frame(&frame, "nonce-0123456789abcdef")
            .err()
            .map(|error| error.to_string());
        assert!(
            error
                .as_deref()
                .is_some_and(|error| error.contains("authenticated session"))
        );
    }

    #[test]
    fn initialize_parse_errors_do_not_echo_credentials() {
        let raw = serde_json::json!({
            "type": "desktop_initialize",
            "protocolVersion": PROTOCOL_VERSION,
            "nonce": "nonce-0123456789abcdef",
            "secret": URL_SAFE_NO_PAD.encode([7_u8; 32]),
            "configPath": "/tmp/workspace-core/config.toml",
            "mode": "desktop-local",
            "serviceToken": "service-token-0123456789abcdef0123456789",
            "agentRegistryUrl": "http://127.0.0.1:31000/internal/registry",
            "agentRegistryToken": "registry-token-0123456789abcdef012345678",
            "providerWebhookUrl": "http://127.0.0.1:31000/internal/provider",
            "providerWebhookToken": "webhook-token-0123456789abcdef0123456789",
            "providerEventToken": "event-token-0123456789abcdef012345678901",
            "planDispatchUrl": "http://127.0.0.1:31000/internal/plan-dispatch",
            "instanceId": "desktop-sidecar-1",
            "unexpected": true,
        });
        let error = match serde_json::from_value::<DesktopInitialize>(raw) {
            Ok(_) => panic!("unknown fields must fail"),
            Err(error) => error.to_string(),
        };
        assert!(!error.contains("service-token"));
        assert!(!error.contains("registry-token"));
        assert!(!error.contains("webhook-token"));
        assert!(!error.contains("event-token"));
    }
}
