//! Loopback validation is repeated after discovery and before every connection.
use std::net::{IpAddr, SocketAddr};
use std::time::Duration;
use url::{Host, Url};

pub(super) fn validate(value: &str) -> Result<Url, String> {
    let url = Url::parse(value).map_err(|_| "cdp_endpoint_invalid")?;
    if !matches!(url.scheme(), "http" | "https" | "ws" | "wss")
        || !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
        || !matches!(url.host(), Some(Host::Ipv4(ip)) if ip.is_loopback())
            && !matches!(url.host(), Some(Host::Ipv6(ip)) if ip.is_loopback())
            && !matches!(url.host(), Some(Host::Domain("localhost")))
    {
        return Err("cdp_endpoint_must_be_loopback".into());
    }
    Ok(url)
}

pub(super) async fn addresses(url: &Url) -> Result<Vec<SocketAddr>, String> {
    validate(url.as_str())?;
    let port = url
        .port_or_known_default()
        .ok_or("cdp_endpoint_port_invalid")?;
    let values = match url.host().ok_or("cdp_endpoint_host_invalid")? {
        Host::Ipv4(ip) => vec![SocketAddr::new(IpAddr::V4(ip), port)],
        Host::Ipv6(ip) => vec![SocketAddr::new(IpAddr::V6(ip), port)],
        Host::Domain(host) => tokio::net::lookup_host((host, port))
            .await
            .map_err(|_| "cdp_localhost_resolution_failed")?
            .collect(),
    };
    if values.is_empty() || values.iter().any(|value| !value.ip().is_loopback()) {
        return Err("cdp_endpoint_must_be_loopback".into());
    }
    Ok(values)
}

pub(super) async fn discover(value: &str) -> Result<Url, String> {
    let mut url = validate(value)?;
    if matches!(url.scheme(), "ws" | "wss") {
        return Ok(url);
    }
    if url.path() == "/" {
        url.set_path("/json/version");
    }
    for _ in 0..4 {
        let pinned = addresses(&url).await?;
        let mut builder = reqwest::Client::builder()
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(5));
        if url.host_str() == Some("localhost") {
            builder = builder.resolve_to_addrs("localhost", &pinned);
        }
        let client = builder.build().map_err(|_| "cdp_discovery_client_failed")?;
        let mut response = client
            .get(url.clone())
            .send()
            .await
            .map_err(|_| "cdp_discovery_failed")?;
        if response
            .remote_addr()
            .is_some_and(|peer| !peer.ip().is_loopback())
        {
            return Err("cdp_endpoint_must_be_loopback".into());
        }
        if response.status().is_redirection() {
            let location = response
                .headers()
                .get(reqwest::header::LOCATION)
                .and_then(|header| header.to_str().ok())
                .ok_or("cdp_discovery_redirect_invalid")?;
            let next = url
                .join(location)
                .map_err(|_| "cdp_discovery_redirect_invalid")?;
            url = validate(next.as_str())?;
            if !matches!(url.scheme(), "http" | "https") {
                return Err("cdp_discovery_redirect_invalid".into());
            }
            continue;
        }
        if !response.status().is_success() {
            return Err("cdp_discovery_failed".into());
        }
        let mut bytes = Vec::new();
        while let Some(chunk) = response.chunk().await.map_err(|_| "cdp_discovery_failed")? {
            if bytes.len().saturating_add(chunk.len()) > 1024 * 1024 {
                return Err("cdp_discovery_response_too_large".into());
            }
            bytes.extend_from_slice(&chunk);
        }
        let body: serde_json::Value =
            serde_json::from_slice(&bytes).map_err(|_| "cdp_discovery_invalid")?;
        let websocket = validate(
            body["webSocketDebuggerUrl"]
                .as_str()
                .ok_or("cdp_discovery_missing_websocket")?,
        )?;
        if !matches!(websocket.scheme(), "ws" | "wss") {
            return Err("cdp_discovery_missing_websocket".into());
        }
        return Ok(websocket);
    }
    Err("cdp_discovery_redirect_limit".into())
}
