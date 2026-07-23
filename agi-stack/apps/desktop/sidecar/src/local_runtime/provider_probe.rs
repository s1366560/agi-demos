//! Bounded, credential-safe connectivity probing for local LLM providers.

use std::{
    collections::HashSet,
    net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr},
    sync::Arc,
    time::{Duration, Instant},
};

use futures_util::StreamExt;
use reqwest::{
    header::{HeaderName, HeaderValue, AUTHORIZATION, CONTENT_LENGTH, CONTENT_TYPE},
    redirect::Policy,
    Client, RequestBuilder, StatusCode,
};
use serde_json::Value;
use tokio::{net::lookup_host, sync::Semaphore, time::timeout};
use url::{Host, Url};

const DNS_TIMEOUT: Duration = Duration::from_secs(1);
const CONNECT_TIMEOUT: Duration = Duration::from_secs(2);
const TOTAL_TIMEOUT: Duration = Duration::from_secs(5);
const MAX_RESPONSE_BYTES: usize = 1024 * 1024;
const MAX_MODELS: usize = 2_000;
const MAX_MODEL_ID_BYTES: usize = 256;
const MAX_CREDENTIAL_BYTES: usize = 8 * 1024;
const MAX_CONCURRENT_PROBES: usize = 4;

const ANTHROPIC_API_KEY: HeaderName = HeaderName::from_static("x-api-key");
const ANTHROPIC_VERSION: HeaderName = HeaderName::from_static("anthropic-version");

#[derive(Clone)]
pub(super) struct ProviderProbeService {
    concurrency: Arc<Semaphore>,
    limits: ProbeLimits,
}

#[derive(Clone, Copy)]
struct ProbeLimits {
    dns_timeout: Duration,
    connect_timeout: Duration,
    total_timeout: Duration,
    max_response_bytes: usize,
}

pub(super) struct ProviderProbeRequest {
    pub(super) provider_type: String,
    pub(super) base_url: String,
    pub(super) auth_method: String,
    pub(super) credential: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct DiscoveredModel {
    pub(super) id: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct ProviderProbeOutcome {
    pub(super) status: &'static str,
    pub(super) detail: &'static str,
    pub(super) error_code: Option<&'static str>,
    pub(super) response_time_ms: u64,
    pub(super) models: Vec<DiscoveredModel>,
}

impl ProviderProbeOutcome {
    pub(super) fn healthy(&self) -> bool {
        self.status == "healthy"
    }
}

impl Default for ProviderProbeService {
    fn default() -> Self {
        Self {
            concurrency: Arc::new(Semaphore::new(MAX_CONCURRENT_PROBES)),
            limits: ProbeLimits {
                dns_timeout: DNS_TIMEOUT,
                connect_timeout: CONNECT_TIMEOUT,
                total_timeout: TOTAL_TIMEOUT,
                max_response_bytes: MAX_RESPONSE_BYTES,
            },
        }
    }
}

impl ProviderProbeService {
    pub(super) async fn probe(&self, request: ProviderProbeRequest) -> ProviderProbeOutcome {
        let started = Instant::now();
        let result = timeout(self.limits.total_timeout, async {
            let permit = self
                .concurrency
                .acquire()
                .await
                .map_err(|_| ProbeFailure::ProviderUnavailable)?;
            let result = self.probe_bounded(request).await;
            drop(permit);
            result
        })
        .await;
        match result {
            Ok(Ok(models)) => ProviderProbeOutcome {
                status: "healthy",
                detail: "Authentication succeeded and the provider returned its model catalog.",
                error_code: None,
                response_time_ms: elapsed_millis(started),
                models,
            },
            Ok(Err(failure)) => failure.to_outcome(started),
            Err(_) => failure_outcome(
                "connection_timeout",
                "The provider did not respond before the connection test timed out.",
                started,
            ),
        }
    }

    async fn probe_bounded(
        &self,
        request: ProviderProbeRequest,
    ) -> Result<Vec<DiscoveredModel>, ProbeFailure> {
        let mut endpoint = models_endpoint(&request)?;
        let host = endpoint
            .host_str()
            .ok_or(ProbeFailure::EndpointBlocked)?
            .to_string();
        let port = endpoint
            .port_or_known_default()
            .ok_or(ProbeFailure::EndpointBlocked)?;
        if port == 0 {
            return Err(ProbeFailure::EndpointBlocked);
        }
        let address = resolve_and_authorize_endpoint(
            &endpoint,
            &request.provider_type,
            &request.auth_method,
            self.limits.dns_timeout,
        )
        .await?;

        // The hostname remains in the URL for HTTP Host and TLS SNI. `resolve` pins the one
        // authorized address so reqwest cannot perform a second, attacker-controlled lookup.
        let client = Client::builder()
            .connect_timeout(self.limits.connect_timeout)
            .timeout(self.limits.total_timeout)
            .redirect(Policy::none())
            .no_proxy()
            .resolve(&host, address)
            .user_agent("MemStack-Desktop/0.1 provider-probe")
            .build()
            .map_err(|_| ProbeFailure::ProviderUnavailable)?;

        // Query parameters are intentionally fixed by the desktop runtime. No provider response
        // can supply a continuation URL or change the next network destination.
        if request.provider_type == "anthropic" {
            endpoint.query_pairs_mut().append_pair("limit", "1000");
        }
        let response = authorized_request(&client, endpoint, &request)?
            .send()
            .await
            .map_err(|error| classify_transport_error(&error))?;
        let status = response.status();
        if status.is_redirection() {
            return Err(ProbeFailure::RedirectRejected);
        }
        if matches!(status, StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN) {
            return Err(ProbeFailure::AuthFailed);
        }
        if status == StatusCode::TOO_MANY_REQUESTS {
            return Err(ProbeFailure::RateLimited);
        }
        if !status.is_success() {
            return Err(ProbeFailure::ProviderUnavailable);
        }
        if response
            .headers()
            .get(CONTENT_LENGTH)
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.parse::<usize>().ok())
            .is_some_and(|length| length > self.limits.max_response_bytes)
        {
            return Err(ProbeFailure::ResponseTooLarge);
        }
        let mut body = Vec::new();
        let mut stream = response.bytes_stream();
        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|error| classify_transport_error(&error))?;
            if body.len().saturating_add(chunk.len()) > self.limits.max_response_bytes {
                return Err(ProbeFailure::ResponseTooLarge);
            }
            body.extend_from_slice(&chunk);
        }
        parse_model_catalog(&body)
    }

    #[cfg(test)]
    fn with_test_limits(total_timeout: Duration, max_response_bytes: usize) -> Self {
        Self {
            concurrency: Arc::new(Semaphore::new(MAX_CONCURRENT_PROBES)),
            limits: ProbeLimits {
                dns_timeout: total_timeout,
                connect_timeout: total_timeout,
                total_timeout,
                max_response_bytes,
            },
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ProbeFailure {
    EndpointBlocked,
    DnsFailed,
    ConnectionTimeout,
    ProviderUnavailable,
    RedirectRejected,
    CredentialUnavailable,
    AuthFailed,
    RateLimited,
    ResponseTooLarge,
    InvalidModelCatalog,
}

impl ProbeFailure {
    fn to_outcome(self, started: Instant) -> ProviderProbeOutcome {
        let (code, detail) = match self {
            Self::EndpointBlocked => (
                "endpoint_blocked",
                "The provider endpoint is not permitted by the desktop network policy.",
            ),
            Self::DnsFailed => (
                "dns_failed",
                "The provider hostname could not be resolved safely.",
            ),
            Self::ConnectionTimeout => (
                "connection_timeout",
                "The provider did not respond before the connection test timed out.",
            ),
            Self::ProviderUnavailable => (
                "provider_unavailable",
                "The provider is unavailable or returned an unexpected status.",
            ),
            Self::RedirectRejected => (
                "redirect_rejected",
                "The provider returned a redirect, which is not followed for credential safety.",
            ),
            Self::CredentialUnavailable => (
                "credential_unavailable",
                "The provider credential is missing or could not be used safely.",
            ),
            Self::AuthFailed => (
                "auth_failed",
                "The provider rejected the configured credential.",
            ),
            Self::RateLimited => (
                "rate_limited",
                "The provider rate-limited the connection test. Try again later.",
            ),
            Self::ResponseTooLarge => (
                "response_too_large",
                "The provider model catalog exceeded the desktop safety limit.",
            ),
            Self::InvalidModelCatalog => (
                "invalid_model_catalog",
                "The provider returned an invalid model catalog.",
            ),
        };
        failure_outcome(code, detail, started)
    }
}

fn failure_outcome(
    code: &'static str,
    detail: &'static str,
    started: Instant,
) -> ProviderProbeOutcome {
    ProviderProbeOutcome {
        status: "unhealthy",
        detail,
        error_code: Some(code),
        response_time_ms: elapsed_millis(started),
        models: Vec::new(),
    }
}

fn elapsed_millis(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX)
}

fn models_endpoint(request: &ProviderProbeRequest) -> Result<Url, ProbeFailure> {
    if !matches!(
        request.provider_type.as_str(),
        "openai" | "openai_compatible" | "anthropic"
    ) {
        return Err(ProbeFailure::EndpointBlocked);
    }
    let mut endpoint =
        Url::parse(request.base_url.trim()).map_err(|_| ProbeFailure::EndpointBlocked)?;
    if !matches!(endpoint.scheme(), "http" | "https")
        || !endpoint.username().is_empty()
        || endpoint.password().is_some()
        || endpoint.host().is_none()
        || endpoint.query().is_some()
        || endpoint.fragment().is_some()
        || endpoint.port() == Some(0)
    {
        return Err(ProbeFailure::EndpointBlocked);
    }
    let path = endpoint.path().trim_end_matches('/').to_string();
    if path.ends_with("/models") {
        return Ok(endpoint);
    }
    let mut segments = endpoint
        .path_segments_mut()
        .map_err(|_| ProbeFailure::EndpointBlocked)?;
    segments.pop_if_empty();
    if request.provider_type == "anthropic" && (path.is_empty() || path == "/") {
        segments.push("v1");
    }
    segments.push("models");
    drop(segments);
    Ok(endpoint)
}

fn authorized_request(
    client: &Client,
    endpoint: Url,
    request: &ProviderProbeRequest,
) -> Result<RequestBuilder, ProbeFailure> {
    let mut builder = client.get(endpoint);
    match request.auth_method.as_str() {
        "api_key" => {
            let credential = request
                .credential
                .as_deref()
                .filter(|value| !value.trim().is_empty())
                .ok_or(ProbeFailure::CredentialUnavailable)?;
            if credential.len() > MAX_CREDENTIAL_BYTES {
                return Err(ProbeFailure::CredentialUnavailable);
            }
            if request.provider_type == "anthropic" {
                let mut value = HeaderValue::from_str(credential)
                    .map_err(|_| ProbeFailure::CredentialUnavailable)?;
                value.set_sensitive(true);
                builder = builder
                    .header(ANTHROPIC_API_KEY, value)
                    .header(ANTHROPIC_VERSION, HeaderValue::from_static("2023-06-01"))
                    .header(CONTENT_TYPE, HeaderValue::from_static("application/json"));
            } else {
                let mut value = HeaderValue::from_str(&format!("Bearer {credential}"))
                    .map_err(|_| ProbeFailure::CredentialUnavailable)?;
                value.set_sensitive(true);
                builder = builder.header(AUTHORIZATION, value);
            }
        }
        "none" => {
            if request.credential.is_some() {
                return Err(ProbeFailure::CredentialUnavailable);
            }
            if request.provider_type == "anthropic" {
                builder = builder
                    .header(ANTHROPIC_VERSION, HeaderValue::from_static("2023-06-01"))
                    .header(CONTENT_TYPE, HeaderValue::from_static("application/json"));
            }
        }
        _ => return Err(ProbeFailure::EndpointBlocked),
    }
    Ok(builder)
}

async fn resolve_and_authorize_endpoint(
    endpoint: &Url,
    provider_type: &str,
    auth_method: &str,
    dns_timeout: Duration,
) -> Result<SocketAddr, ProbeFailure> {
    let host = endpoint.host().ok_or(ProbeFailure::EndpointBlocked)?;
    let port = endpoint
        .port_or_known_default()
        .ok_or(ProbeFailure::EndpointBlocked)?;
    let addresses = match host {
        Host::Ipv4(address) => vec![SocketAddr::new(IpAddr::V4(address), port)],
        Host::Ipv6(address) => vec![SocketAddr::new(IpAddr::V6(address), port)],
        Host::Domain(domain) => timeout(dns_timeout, lookup_host((domain, port)))
            .await
            .map_err(|_| ProbeFailure::DnsFailed)?
            .map_err(|_| ProbeFailure::DnsFailed)?
            .collect::<Vec<_>>(),
    };
    if addresses.is_empty() {
        return Err(ProbeFailure::DnsFailed);
    }
    if !resolved_transport_allowed(endpoint, provider_type, auth_method, &addresses) {
        return Err(ProbeFailure::EndpointBlocked);
    }
    Ok(addresses[0])
}

fn resolved_transport_allowed(
    endpoint: &Url,
    provider_type: &str,
    auth_method: &str,
    addresses: &[SocketAddr],
) -> bool {
    if addresses.is_empty() {
        return false;
    }
    let all_loopback = addresses.iter().all(|address| address.ip().is_loopback());
    let domain_target = matches!(endpoint.host(), Some(Host::Domain(_)));
    let all_authorized_remote = addresses.iter().all(|address| {
        is_allowed_public_ip(address.ip()) || (domain_target && is_proxy_fake_ip(address.ip()))
    });
    let transport_allowed = if all_loopback {
        endpoint.scheme() == "https"
            || (endpoint.scheme() == "http"
                && provider_type == "openai_compatible"
                && auth_method == "none")
    } else {
        endpoint.scheme() == "https" && all_authorized_remote
    };
    transport_allowed && (auth_method != "api_key" || endpoint.scheme() == "https")
}

fn is_proxy_fake_ip(address: IpAddr) -> bool {
    match address {
        IpAddr::V4(address) => {
            let octets = address.octets();
            // Clash-compatible fake-IP DNS maps public hostnames into RFC 2544's benchmarking
            // range. The caller permits this range only for domain-based HTTPS endpoints, so a
            // user-supplied reserved IP literal or cleartext endpoint remains blocked.
            octets[0] == 198 && matches!(octets[1], 18 | 19)
        }
        IpAddr::V6(_) => false,
    }
}

fn is_allowed_public_ip(address: IpAddr) -> bool {
    match address {
        IpAddr::V4(address) => is_allowed_public_ipv4(address),
        IpAddr::V6(address) => is_allowed_public_ipv6(address),
    }
}

fn is_allowed_public_ipv4(address: Ipv4Addr) -> bool {
    let octets = address.octets();
    !address.is_private()
        && !address.is_loopback()
        && !address.is_link_local()
        && !address.is_broadcast()
        && !address.is_documentation()
        && !address.is_multicast()
        && !address.is_unspecified()
        && octets[0] != 0
        && (octets[0] & 0xf0) != 0xf0
        && !(octets[0] == 100 && (64..=127).contains(&octets[1]))
        && !(octets[0] == 192 && octets[1] == 0 && octets[2] == 0)
        && !(octets[0] == 198 && matches!(octets[1], 18 | 19))
    // Benchmarking range.
}

fn is_allowed_public_ipv6(address: Ipv6Addr) -> bool {
    if let Some(mapped) = address.to_ipv4_mapped() {
        return is_allowed_public_ipv4(mapped);
    }
    let segments = address.segments();
    (segments[0] & 0xe000) == 0x2000 // Global-unicast 2000::/3.
        && !(segments[0] == 0x2001 && segments[1] == 0x0db8) // Documentation.
}

fn classify_transport_error(error: &reqwest::Error) -> ProbeFailure {
    if error.is_timeout() {
        ProbeFailure::ConnectionTimeout
    } else {
        ProbeFailure::ProviderUnavailable
    }
}

fn parse_model_catalog(body: &[u8]) -> Result<Vec<DiscoveredModel>, ProbeFailure> {
    let payload: Value =
        serde_json::from_slice(body).map_err(|_| ProbeFailure::InvalidModelCatalog)?;
    if payload.get("has_more").and_then(Value::as_bool) == Some(true) {
        // Anthropic is requested with the maximum supported page size. Never present a partial
        // page as an authoritative catalog; bounded cursor pagination can be added independently.
        return Err(ProbeFailure::InvalidModelCatalog);
    }
    let data = payload
        .get("data")
        .and_then(Value::as_array)
        .ok_or(ProbeFailure::InvalidModelCatalog)?;
    if data.len() > MAX_MODELS {
        return Err(ProbeFailure::InvalidModelCatalog);
    }
    let mut seen = HashSet::new();
    let mut models = Vec::new();
    for item in data {
        let Some(id) = item.get("id").and_then(Value::as_str).map(str::trim) else {
            return Err(ProbeFailure::InvalidModelCatalog);
        };
        if id.is_empty() || id.len() > MAX_MODEL_ID_BYTES || id.chars().any(char::is_control) {
            return Err(ProbeFailure::InvalidModelCatalog);
        }
        if seen.insert(id.to_string()) {
            models.push(DiscoveredModel { id: id.to_string() });
        }
    }
    Ok(models)
}

#[cfg(test)]
mod tests {
    use std::{convert::Infallible, net::SocketAddr, time::Duration};

    use axum::{
        body::Body,
        extract::State,
        http::{HeaderMap, StatusCode},
        response::Response,
        routing::get,
        Router,
    };
    use serde_json::json;
    use tokio::{net::TcpListener, sync::oneshot};

    use super::*;

    #[test]
    fn model_endpoint_appends_only_fixed_api_segments() {
        let request = probe_request("http://127.0.0.1:11434/v1", "none");
        assert_eq!(
            models_endpoint(&request).expect("model endpoint").as_str(),
            "http://127.0.0.1:11434/v1/models"
        );
        let request = ProviderProbeRequest {
            provider_type: "anthropic".to_string(),
            base_url: "https://api.anthropic.com".to_string(),
            auth_method: "api_key".to_string(),
            credential: Some("test-key".to_string()),
        };
        assert_eq!(
            models_endpoint(&request).expect("model endpoint").as_str(),
            "https://api.anthropic.com/v1/models"
        );
    }

    #[test]
    fn https_domains_accept_proxy_fake_ips_without_allowing_reserved_ip_endpoints() {
        let fake_ip = SocketAddr::new(IpAddr::V4(Ipv4Addr::new(198, 18, 0, 91)), 443);
        let domain = Url::parse("https://provider.example/v1/models").expect("domain URL");
        assert!(resolved_transport_allowed(
            &domain,
            "openai_compatible",
            "api_key",
            &[fake_ip],
        ));

        let direct_ip = Url::parse("https://198.18.0.91/v1/models").expect("direct IP URL");
        assert!(!resolved_transport_allowed(
            &direct_ip,
            "openai_compatible",
            "api_key",
            &[fake_ip],
        ));

        let insecure_domain = Url::parse("http://provider.example/v1/models").expect("HTTP URL");
        assert!(!resolved_transport_allowed(
            &insecure_domain,
            "openai_compatible",
            "api_key",
            &[SocketAddr::new(IpAddr::V4(Ipv4Addr::new(8, 8, 8, 8)), 80)],
        ));

        assert!(!resolved_transport_allowed(
            &domain,
            "openai_compatible",
            "api_key",
            &[SocketAddr::new(
                IpAddr::V4(Ipv4Addr::new(169, 254, 169, 254)),
                443,
            )],
        ));
    }

    #[test]
    fn model_catalog_parser_is_bounded_and_rejects_control_characters() {
        assert_eq!(
            parse_model_catalog(br#"{"data":[{"id":"model-a"},{"id":"model-a"}]}"#)
                .expect("catalog"),
            vec![DiscoveredModel {
                id: "model-a".to_string()
            }]
        );
        assert_eq!(
            parse_model_catalog(br#"{"data":[{"id":"model\u0000secret"}]}"#),
            Err(ProbeFailure::InvalidModelCatalog)
        );
        assert_eq!(
            parse_model_catalog(br#"{"data":[{"id":"model-a"}],"has_more":true}"#),
            Err(ProbeFailure::InvalidModelCatalog)
        );
    }

    #[test]
    fn provider_auth_headers_are_exact_and_sensitive() {
        let client = Client::new();
        let openai = ProviderProbeRequest {
            provider_type: "openai".to_string(),
            base_url: "https://api.openai.com/v1".to_string(),
            auth_method: "api_key".to_string(),
            credential: Some("canary-openai-secret".to_string()),
        };
        let openai_request = authorized_request(
            &client,
            Url::parse("https://api.openai.com/v1/models").expect("OpenAI URL"),
            &openai,
        )
        .expect("OpenAI request")
        .build()
        .expect("built OpenAI request");
        let bearer = openai_request
            .headers()
            .get(AUTHORIZATION)
            .expect("bearer header");
        assert_eq!(
            bearer.to_str().expect("bearer value"),
            "Bearer canary-openai-secret"
        );
        assert!(bearer.is_sensitive());

        let anthropic = ProviderProbeRequest {
            provider_type: "anthropic".to_string(),
            base_url: "https://api.anthropic.com/v1".to_string(),
            auth_method: "api_key".to_string(),
            credential: Some("canary-anthropic-secret".to_string()),
        };
        let anthropic_request = authorized_request(
            &client,
            Url::parse("https://api.anthropic.com/v1/models").expect("Anthropic URL"),
            &anthropic,
        )
        .expect("Anthropic request")
        .build()
        .expect("built Anthropic request");
        let api_key = anthropic_request
            .headers()
            .get(ANTHROPIC_API_KEY)
            .expect("Anthropic API key");
        assert_eq!(
            api_key.to_str().expect("API key value"),
            "canary-anthropic-secret"
        );
        assert!(api_key.is_sensitive());
        assert_eq!(
            anthropic_request.headers().get(ANTHROPIC_VERSION),
            Some(&HeaderValue::from_static("2023-06-01"))
        );
        assert_eq!(
            anthropic_request.headers().get(CONTENT_TYPE),
            Some(&HeaderValue::from_static("application/json"))
        );
    }

    #[tokio::test]
    async fn auth_none_loopback_probe_has_no_auth_headers_and_discovers_models() {
        let (address, shutdown) = spawn_server(|headers| {
            assert!(headers.get(AUTHORIZATION).is_none());
            assert!(headers.get(ANTHROPIC_API_KEY).is_none());
            Response::builder()
                .status(StatusCode::OK)
                .header("content-type", "application/json")
                .body(Body::from(
                    json!({"data": [{"id": "local-model"}]}).to_string(),
                ))
                .expect("response")
        })
        .await;
        let outcome = ProviderProbeService::default()
            .probe(ProviderProbeRequest {
                provider_type: "openai_compatible".to_string(),
                base_url: format!("http://{address}/v1"),
                auth_method: "none".to_string(),
                credential: None,
            })
            .await;
        assert!(outcome.healthy(), "unexpected outcome: {outcome:?}");
        assert_eq!(outcome.models[0].id, "local-model");
        shutdown.send(()).ok();
    }

    #[tokio::test]
    async fn redirects_are_not_followed_and_oversized_bodies_are_rejected() {
        let (redirect_address, redirect_shutdown) = spawn_server(|_| {
            Response::builder()
                .status(StatusCode::TEMPORARY_REDIRECT)
                .header("location", "http://127.0.0.1:9/credential-sink")
                .body(Body::empty())
                .expect("redirect response")
        })
        .await;
        let service = ProviderProbeService::with_test_limits(Duration::from_secs(1), 64);
        let redirect = service
            .probe(probe_request(
                &format!("http://{redirect_address}/v1"),
                "none",
            ))
            .await;
        assert_eq!(redirect.error_code, Some("redirect_rejected"));
        redirect_shutdown.send(()).ok();

        let (large_address, large_shutdown) = spawn_server(|_| {
            Response::builder()
                .status(StatusCode::OK)
                .header("content-type", "application/json")
                .body(Body::from(vec![b'x'; 65]))
                .expect("large response")
        })
        .await;
        let large = service
            .probe(probe_request(&format!("http://{large_address}/v1"), "none"))
            .await;
        assert_eq!(large.error_code, Some("response_too_large"));
        large_shutdown.send(()).ok();
    }

    #[tokio::test]
    async fn probe_timeout_is_sanitized() {
        let (address, shutdown) = spawn_server(|_| {
            std::thread::sleep(Duration::from_millis(100));
            Response::builder()
                .status(StatusCode::OK)
                .body(Body::from(r#"{"data":[]}"#))
                .expect("response")
        })
        .await;
        let outcome = ProviderProbeService::with_test_limits(Duration::from_millis(20), 1024)
            .probe(probe_request(&format!("http://{address}/v1"), "none"))
            .await;
        assert_eq!(outcome.error_code, Some("connection_timeout"));
        assert!(!format!("{outcome:?}").contains("canary"));
        shutdown.send(()).ok();
    }

    fn probe_request(base_url: &str, auth_method: &str) -> ProviderProbeRequest {
        ProviderProbeRequest {
            provider_type: "openai_compatible".to_string(),
            base_url: base_url.to_string(),
            auth_method: auth_method.to_string(),
            credential: None,
        }
    }

    async fn spawn_server<F>(handler: F) -> (SocketAddr, oneshot::Sender<()>)
    where
        F: Fn(HeaderMap) -> Response<Body> + Clone + Send + Sync + 'static,
    {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))
            .await
            .expect("test listener");
        let address = listener.local_addr().expect("test address");
        let (shutdown_tx, shutdown_rx) = oneshot::channel();
        let app = Router::new()
            .route(
                "/v1/models",
                get(|State(handler): State<F>, headers: HeaderMap| async move {
                    Ok::<_, Infallible>(handler(headers))
                }),
            )
            .with_state(handler);
        tokio::spawn(async move {
            axum::serve(listener, app)
                .with_graceful_shutdown(async move {
                    shutdown_rx.await.ok();
                })
                .await
                .ok();
        });
        (address, shutdown_tx)
    }
}
