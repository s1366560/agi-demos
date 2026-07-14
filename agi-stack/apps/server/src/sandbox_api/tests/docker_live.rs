use std::collections::BTreeSet;
use std::sync::Arc;
use std::time::{Duration, Instant};

use agistack_adapters_docker::{DockerContainerRuntime, ImagePullPolicy};
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::{
    connect_async,
    tungstenite::{client::IntoClientRequest, Message as TungsteniteMessage},
};

use super::super::*;
use super::*;

const LIVE_GATE_ENV: &str = "AGISTACK_RUN_SANDBOX_LIVE_TESTS";
const LIVE_IMAGE_ENV: &str = "AGISTACK_SANDBOX_LIVE_IMAGE";
const LIVE_PROJECT_ENV: &str = "AGISTACK_SANDBOX_LIVE_PROJECT_ID";
const LIVE_READY_TIMEOUT: Duration = Duration::from_secs(90);

type LiveResult<T> = Result<T, String>;

fn configured_live_image() -> Option<String> {
    if std::env::var(LIVE_GATE_ENV).ok().as_deref() != Some("1") {
        return None;
    }
    Some(
        std::env::var(LIVE_IMAGE_ENV)
            .ok()
            .filter(|image| !image.trim().is_empty())
            .unwrap_or_else(|| crate::DEFAULT_SANDBOX_IMAGE.to_string()),
    )
}

fn http_url_from_websocket(raw: &str) -> LiveResult<String> {
    let mut url = url::Url::parse(raw).map_err(|error| error.to_string())?;
    let scheme = match url.scheme() {
        "wss" => "https",
        "ws" => "http",
        scheme => return Err(format!("unsupported interactive service scheme: {scheme}")),
    };
    url.set_scheme(scheme)
        .map_err(|_| "failed to normalize interactive service scheme".to_string())?;
    url.set_path("/");
    url.set_query(None);
    Ok(url.to_string())
}

async fn wait_for_authenticated_http(
    client: &reqwest::Client,
    url: &str,
    basic_auth: &str,
) -> LiveResult<()> {
    let deadline = Instant::now() + LIVE_READY_TIMEOUT;
    let mut last_error = "service did not answer".to_string();
    while Instant::now() < deadline {
        match client
            .get(url)
            .header("authorization", basic_auth)
            .send()
            .await
        {
            Ok(response) if response.status().as_u16() < 400 => {
                for credential in [None, Some("Basic c2FuZGJveDp3cm9uZw==")] {
                    let mut request = client.get(url);
                    if let Some(credential) = credential {
                        request = request.header("authorization", credential);
                    }
                    let response = request.send().await.map_err(|error| error.to_string())?;
                    if !matches!(response.status().as_u16(), 401 | 403) {
                        return Err(
                            "interactive service accepted a missing or incorrect credential"
                                .to_string(),
                        );
                    }
                }
                return Ok(());
            }
            Ok(response) => {
                last_error = format!("service returned HTTP {}", response.status().as_u16());
            }
            Err(error) => last_error = error.to_string(),
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
    Err(format!("interactive service was not ready: {last_error}"))
}

async fn connect_mcp(
    url: &str,
    authorization: Option<&str>,
) -> LiveResult<
    tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>,
> {
    let mut request = url
        .into_client_request()
        .map_err(|error| error.to_string())?;
    if let Some(authorization) = authorization {
        request.headers_mut().insert(
            "authorization",
            authorization
                .parse()
                .map_err(|_| "invalid test authorization header".to_string())?,
        );
    }
    connect_async(request)
        .await
        .map(|(socket, _response)| socket)
        .map_err(|error| error.to_string())
}

async fn expect_mcp_rejected(url: &str, authorization: Option<&str>) -> LiveResult<()> {
    let mut socket = connect_mcp(url, authorization).await?;
    let message = tokio::time::timeout(Duration::from_secs(10), socket.next())
        .await
        .map_err(|_| "MCP rejection timed out".to_string())?
        .ok_or_else(|| "MCP rejection closed without a close frame".to_string())?
        .map_err(|error| error.to_string())?;
    match message {
        TungsteniteMessage::Close(Some(frame)) if u16::from(frame.code) == 4001 => Ok(()),
        _ => Err("MCP accepted an invalid runtime capability".to_string()),
    }
}

async fn verify_authorized_mcp(url: &str, bearer_auth: &str) -> LiveResult<()> {
    let deadline = Instant::now() + LIVE_READY_TIMEOUT;
    let mut last_error = "service did not answer".to_string();
    while Instant::now() < deadline {
        match connect_mcp(url, Some(bearer_auth)).await {
            Ok(mut socket) => {
                let request = json!({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "agistack-live-gate", "version": "1.0"}
                    }
                });
                if socket
                    .send(TungsteniteMessage::Text(request.to_string()))
                    .await
                    .is_ok()
                {
                    match tokio::time::timeout(Duration::from_secs(10), socket.next()).await {
                        Ok(Some(Ok(TungsteniteMessage::Text(response)))) => {
                            let response: Value = serde_json::from_str(&response)
                                .map_err(|error| error.to_string())?;
                            if response["result"]["serverInfo"].is_object() {
                                return Ok(());
                            }
                            last_error = "MCP initialize result was incomplete".to_string();
                        }
                        Ok(Some(Ok(_))) => {
                            last_error = "MCP initialize returned a non-text frame".to_string();
                        }
                        Ok(Some(Err(error))) => last_error = error.to_string(),
                        Ok(None) => last_error = "MCP disconnected during initialize".to_string(),
                        Err(_) => last_error = "MCP initialize timed out".to_string(),
                    }
                }
            }
            Err(error) => last_error = error,
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
    Err(format!("MCP service was not ready: {last_error}"))
}

async fn remove_project_containers(
    docker: &DockerContainerRuntime,
    project_id: &str,
) -> LiveResult<()> {
    let ids = docker
        .list(Some((PROJECT_LABEL, project_id)))
        .await
        .map_err(|error| error.to_string())?;
    for id in ids {
        docker.stop(&id).await.map_err(|error| error.to_string())?;
        docker
            .remove(&id)
            .await
            .map_err(|error| error.to_string())?;
    }
    Ok(())
}

async fn verify_rust_created_sandbox(
    service: &ProjectSandboxService,
    docker: &DockerContainerRuntime,
    project_id: &str,
) -> LiveResult<()> {
    let info = service
        .ensure(
            project_id,
            "live-gate-tenant",
            Some(SandboxProfile::Standard),
        )
        .await
        .map_err(|error| error.detail)?;
    if !info.healthy() || info.profile != SandboxProfile::Standard {
        return Err("Rust-created sandbox did not reach the running state".to_string());
    }
    let status = docker
        .status(&info.sandbox_id)
        .await
        .map_err(|error| error.to_string())?
        .ok_or_else(|| "Rust-created sandbox disappeared before verification".to_string())?;
    let published_ports = status
        .ports
        .iter()
        .map(|binding| binding.container_port)
        .collect::<BTreeSet<_>>();
    if published_ports
        != BTreeSet::from([
            MCP_CONTAINER_PORT,
            DESKTOP_CONTAINER_PORT,
            TERMINAL_CONTAINER_PORT,
        ])
        || status
            .ports
            .iter()
            .any(|binding| binding.host_ip.as_deref() != Some("127.0.0.1"))
    {
        return Err("Rust-created sandbox published an unexpected host port".to_string());
    }
    let runtime_token = info.runtime_auth_token.as_ref().ok_or_else(|| {
        "Rust-created sandbox omitted its internal runtime capability".to_string()
    })?;
    if format!("{info:?}").contains(runtime_token.expose()) {
        return Err("Rust-created sandbox leaked its runtime capability through Debug".to_string());
    }

    let mcp_url = info
        .endpoint
        .as_deref()
        .ok_or_else(|| "Rust-created sandbox omitted its MCP URL".to_string())?;
    let desktop_url = info
        .desktop_url
        .as_deref()
        .ok_or_else(|| "Rust-created sandbox omitted its desktop URL".to_string())?;
    let terminal_url = info
        .terminal_url
        .as_deref()
        .ok_or_else(|| "Rust-created sandbox omitted its terminal URL".to_string())?;
    let basic_auth = sandbox_basic_auth_header(runtime_token)
        .map_err(|error| error.detail)?
        .to_str()
        .map_err(|error| error.to_string())?
        .to_string();
    let bearer_auth = sandbox_bearer_auth_header(runtime_token)
        .map_err(|error| error.detail)?
        .to_str()
        .map_err(|error| error.to_string())?
        .to_string();

    verify_authorized_mcp(mcp_url, &bearer_auth)
        .await
        .map_err(|error| format!("authorized MCP: {error}"))?;
    expect_mcp_rejected(mcp_url, None)
        .await
        .map_err(|error| format!("unauthenticated MCP: {error}"))?;
    expect_mcp_rejected(mcp_url, Some("Bearer wrong-capability"))
        .await
        .map_err(|error| format!("wrong-capability MCP: {error}"))?;
    let mut query_url = url::Url::parse(mcp_url).map_err(|error| error.to_string())?;
    query_url
        .query_pairs_mut()
        .append_pair("token", "query-only-capability");
    expect_mcp_rejected(query_url.as_str(), None)
        .await
        .map_err(|error| format!("query-capability MCP: {error}"))?;

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .danger_accept_invalid_certs(true)
        .no_proxy()
        .build()
        .map_err(|error| error.to_string())?;
    wait_for_authenticated_http(&client, desktop_url, &basic_auth).await?;
    wait_for_authenticated_http(
        &client,
        &http_url_from_websocket(terminal_url)?,
        &basic_auth,
    )
    .await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn rust_docker_creation_enforces_full_runtime_authentication() {
    let Some(image) = configured_live_image() else {
        println!("[skip] {LIVE_GATE_ENV}=1 not set; skipping Rust full Sandbox live gate");
        return;
    };
    let docker = Arc::new(
        DockerContainerRuntime::connect_with_image_pull_policy(ImagePullPolicy::Never)
            .await
            .expect("live gate requires Docker"),
    );
    assert!(
        docker.has_image(&image).await.expect("inspect live image"),
        "live gate image is missing: {image}"
    );

    let project_id = std::env::var(LIVE_PROJECT_ENV)
        .ok()
        .filter(|project_id| project_id.starts_with("rust-live-"))
        .unwrap_or_else(|| format!("rust-live-{}", uuid::Uuid::new_v4().simple()));
    let service = ProjectSandboxService::new(docker.clone(), image)
        .with_runtime_auth_secret(TEST_RUNTIME_AUTH_SECRET)
        .expect("test runtime secret is valid");
    let result = verify_rust_created_sandbox(&service, &docker, &project_id).await;
    let _ = service.terminate(&project_id).await;
    let cleanup = remove_project_containers(&docker, &project_id).await;

    cleanup.expect("live gate must remove every Rust-owned test container");
    result.expect("Rust-created full Sandbox contract");
}
