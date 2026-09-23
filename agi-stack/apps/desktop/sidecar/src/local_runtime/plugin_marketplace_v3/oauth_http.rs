//! Bounded, DNS-pinned OAuth requests. Redirects and ambient proxy credentials are never followed.
use super::{sources, PackageResult};
use futures_util::StreamExt;
use serde_json::{json, Value};
use std::time::Duration;

pub(super) async fn client(raw: &str) -> PackageResult<(reqwest::Client, url::Url)> {
    let parsed = url::Url::parse(raw).map_err(|_| "oauth_url_invalid")?;
    if !parsed.username().is_empty() || parsed.password().is_some() || parsed.fragment().is_some() {
        return Err("oauth_url_invalid".into());
    }
    let test_origin = cfg!(debug_assertions)
        && std::env::var("PLUGIN_MARKETPLACE_OAUTH_TEST_ORIGIN")
            .ok()
            .is_some_and(|origin| {
                origin == parsed.origin().ascii_serialization()
                    && parsed.scheme() == "http"
                    && parsed
                        .host_str()
                        .is_some_and(|host| host == "127.0.0.1" || host == "[::1]")
            });
    let mut builder = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(20));
    if !test_origin {
        let (url, addresses) = sources::resolved(raw).await?;
        builder = builder.resolve_to_addrs(url.host_str().ok_or("oauth_url_invalid")?, &addresses);
    }
    Ok((
        builder.build().map_err(|_| "oauth_client_unavailable")?,
        parsed,
    ))
}
async fn body(response: reqwest::Response) -> PackageResult<Value> {
    let status = response.status();
    let mut chunks = response.bytes_stream();
    let mut bytes = Vec::new();
    while let Some(chunk) = chunks.next().await {
        let chunk = chunk.map_err(|_| "oauth_response_interrupted")?;
        if bytes.len() + chunk.len() > 256 * 1024 {
            return Err("oauth_response_too_large".into());
        }
        bytes.extend_from_slice(&chunk);
    }
    if !status.is_success() {
        if serde_json::from_slice::<Value>(&bytes)
            .ok()
            .is_some_and(|value| value["error"] == "invalid_grant")
        {
            return Err("oauth_invalid_grant".into());
        }
        return Err(format!("oauth_http_{}", status.as_u16()));
    }
    serde_json::from_slice(&bytes).map_err(|_| "oauth_response_invalid".into())
}
pub(super) async fn get(raw: &str) -> PackageResult<Value> {
    let (client, url) = client(raw).await?;
    body(
        client
            .get(url)
            .send()
            .await
            .map_err(|_| "oauth_request_failed")?,
    )
    .await
}
pub(in crate::local_runtime) async fn post(
    raw: &str,
    fields: &[(String, String)],
) -> PackageResult<Value> {
    let (client, url) = client(raw).await?;
    body(
        client
            .post(url)
            .form(fields)
            .send()
            .await
            .map_err(|_| "oauth_request_failed")?,
    )
    .await
}
pub(in crate::local_runtime) async fn revoke(
    raw: &str,
    fields: &[(String, String)],
) -> PackageResult<()> {
    let (client, url) = client(raw).await?;
    let result = client
        .post(url)
        .form(fields)
        .send()
        .await
        .map_err(|_| "oauth_revocation_failed")?;
    if !result.status().is_success() {
        return Err("oauth_revocation_failed".into());
    }
    Ok(())
}
fn challenge(headers: &reqwest::header::HeaderMap, name: &str) -> Option<String> {
    headers
        .get_all(reqwest::header::WWW_AUTHENTICATE)
        .iter()
        .filter_map(|h| h.to_str().ok())
        .find_map(|header| {
            // Parameter names and quoted values are protocol syntax, not semantic classification.
            header.split(',').find_map(|part| {
                let part = part.trim().strip_prefix("Bearer ").unwrap_or(part.trim());
                let (key, value) = part.split_once('=')?;
                (key.trim() == name).then(|| value.trim().trim_matches('"').to_owned())
            })
        })
}
pub(super) async fn discover(resource: &str, declared: &Value) -> PackageResult<Value> {
    let (resource_client, url) = client(resource).await?;
    let response = resource_client
        .get(url.clone())
        .send()
        .await
        .map_err(|_| "oauth_resource_unavailable")?;
    let challenged_scope = challenge(response.headers(), "scope");
    let mut candidates = challenge(response.headers(), "resource_metadata")
        .into_iter()
        .collect::<Vec<_>>();
    if candidates.is_empty() {
        candidates.push(format!(
            "{}/.well-known/oauth-protected-resource{}",
            url.origin().ascii_serialization(),
            url.path().trim_end_matches('/')
        ));
        candidates.push(format!(
            "{}/.well-known/oauth-protected-resource",
            url.origin().ascii_serialization()
        ));
    }
    let mut protected = None;
    for candidate in candidates {
        if let Ok(value) = get(&candidate).await {
            protected = Some(value);
            break;
        }
    }
    let protected = protected.ok_or("oauth_resource_metadata_unavailable")?;
    if protected["resource"].as_str() != Some(resource) {
        return Err("oauth_resource_mismatch".into());
    }
    let issuers = protected["authorization_servers"]
        .as_array()
        .ok_or("oauth_issuer_missing")?;
    let issuer = if let Some(selected) = declared["issuer"].as_str() {
        if !issuers.iter().any(|i| i.as_str() == Some(selected)) {
            return Err("oauth_issuer_mismatch".into());
        }
        selected
    } else if issuers.len() == 1 {
        issuers[0].as_str().ok_or("oauth_issuer_invalid")?
    } else {
        return Err("oauth_issuer_selection_required".into());
    };
    let (_, issuer_url) = client(issuer).await?;
    if issuer_url.query().is_some() {
        return Err("oauth_issuer_invalid".into());
    }
    let origin = issuer_url.origin().ascii_serialization();
    let path = issuer_url.path().trim_end_matches('/');
    let mut metadata = None;
    for endpoint in [
        format!("{origin}/.well-known/oauth-authorization-server{path}"),
        format!("{origin}/.well-known/openid-configuration{path}"),
        format!("{}{}/.well-known/openid-configuration", origin, path),
    ] {
        if let Ok(value) = get(&endpoint).await {
            metadata = Some(value);
            break;
        }
    }
    let mut metadata = metadata.ok_or("oauth_authorization_metadata_unavailable")?;
    if metadata["issuer"].as_str() != Some(issuer) {
        return Err("oauth_issuer_mismatch".into());
    }
    if !metadata["code_challenge_methods_supported"]
        .as_array()
        .is_some_and(|methods| methods.iter().any(|m| m == "S256"))
    {
        return Err("oauth_pkce_s256_required".into());
    }
    for key in ["authorization_endpoint", "token_endpoint"] {
        client(metadata[key].as_str().ok_or("oauth_endpoint_missing")?).await?;
    }
    let scopes = challenged_scope.unwrap_or_else(|| {
        declared["scopes"]
            .as_array()
            .or_else(|| protected["scopes_supported"].as_array())
            .map(|items| {
                items
                    .iter()
                    .filter_map(Value::as_str)
                    .collect::<Vec<_>>()
                    .join(" ")
            })
            .unwrap_or_default()
    });
    metadata["scope"] = json!(scopes);
    Ok(metadata)
}
pub(super) async fn registration(
    metadata: &Value,
    declared: &Value,
    redirect: &str,
) -> PackageResult<String> {
    if let Some(id) = declared["client_id"].as_str().filter(|id| !id.is_empty()) {
        return Ok(id.into());
    }
    if metadata["client_id_metadata_document_supported"] == true {
        if let Some(raw) = declared["client_metadata_url"].as_str() {
            let url = url::Url::parse(raw).map_err(|_| "oauth_client_metadata_invalid")?;
            if url.scheme() != "https" || url.path() == "/" {
                return Err("oauth_client_metadata_invalid".into());
            }
            let value = get(raw).await?;
            if value["client_id"] != raw
                || !value["redirect_uris"].as_array().is_some_and(|items| {
                    items.iter().any(|r| {
                        r == redirect
                            || r.as_str()
                                .is_some_and(|raw| native_redirect_matches(raw, redirect))
                    })
                })
            {
                return Err("oauth_client_metadata_redirect_mismatch".into());
            }
            return Ok(raw.into());
        }
    }
    let endpoint = metadata["registration_endpoint"]
        .as_str()
        .ok_or("oauth_client_configuration_required")?;
    let (client, url) = client(endpoint).await?;
    let value=body(client.post(url).json(&json!({"client_name":"AGIStack Desktop","redirect_uris":[redirect],"grant_types":["authorization_code","refresh_token"],"response_types":["code"],"token_endpoint_auth_method":"none"})).send().await.map_err(|_|"oauth_registration_failed")?).await?;
    if value.get("client_secret").is_some()
        || value["token_endpoint_auth_method"]
            .as_str()
            .is_some_and(|m| m != "none")
    {
        return Err("oauth_public_client_required".into());
    }
    value["client_id"]
        .as_str()
        .map(str::to_owned)
        .ok_or("oauth_client_id_missing".into())
}

// RFC 8252 native loopback redirects vary only the dynamically assigned port.
fn native_redirect_matches(registered: &str, actual: &str) -> bool {
    let (Ok(left), Ok(right)) = (url::Url::parse(registered), url::Url::parse(actual)) else {
        return false;
    };
    left.scheme() == "http"
        && right.scheme() == "http"
        && left.host_str() == Some("127.0.0.1")
        && right.host_str() == Some("127.0.0.1")
        && left.path() == right.path()
        && left.query() == right.query()
        && left.fragment().is_none()
        && left.username().is_empty()
        && left.password().is_none()
}
