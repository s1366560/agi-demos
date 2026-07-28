use std::sync::{Arc, Mutex};

use agistack_adapters_mem::InMemoryContainerRuntime;
use agistack_core::ports::{CoreResult, ToolHost};
use axum::{
    body::{to_bytes, Body},
    http::{header::CONTENT_TYPE, Request, StatusCode},
    Extension, Router,
};
use base64::{engine::general_purpose::STANDARD as BASE64_STANDARD, Engine as _};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tower::ServiceExt;

use super::super::sandbox_files;
use super::super::*;
use super::TEST_RUNTIME_AUTH_SECRET;
use crate::auth::{DevAuthenticator, Identity};
use crate::identity::DevIdentityService;

#[derive(Default)]
struct FileAuthorityToolHost {
    calls: Mutex<Vec<(String, Value)>>,
}

impl FileAuthorityToolHost {
    fn calls(&self) -> Vec<(String, Value)> {
        self.calls
            .lock()
            .expect("test call recorder mutex must remain available")
            .clone()
    }
}

#[async_trait]
impl ToolHost for FileAuthorityToolHost {
    fn list_tools(&self) -> Vec<String> {
        vec![
            "platform_list_workspace_files".to_string(),
            "platform_read_workspace_file".to_string(),
            "platform_download_workspace_file".to_string(),
        ]
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        let input: Value =
            serde_json::from_str(input_json).expect("file route must send structured JSON");
        self.calls
            .lock()
            .expect("test call recorder mutex must remain available")
            .push((tool.to_string(), input.clone()));

        let path = input
            .get("path")
            .and_then(Value::as_str)
            .expect("file route must provide a path");
        let result = match (tool, path) {
            ("platform_list_workspace_files", "/") => json!({
                "content": [{"type": "text", "text": "listed"}],
                "isError": false,
                "listing": {
                    "contract_version": 1,
                    "authority": "sandbox",
                    "isolation": "isolated",
                    "root": "/",
                    "path": "/",
                    "entries": [
                        {
                            "path": "/notes.txt",
                            "name": "notes.txt",
                            "kind": "file",
                            "size_bytes": 5,
                            "mime_type": "text/plain"
                        }
                    ],
                    "cursor": null,
                    "revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                }
            }),
            ("platform_read_workspace_file", "/notes.txt") => json!({
                "content": [{"type": "text", "text": "read"}],
                "isError": false,
                "file": {
                    "contract_version": 1,
                    "authority": "sandbox",
                    "isolation": "isolated",
                    "path": "/notes.txt",
                    "encoding": "utf-8",
                    "content": "hello",
                    "mime_type": "text/plain",
                    "size_bytes": 5,
                    "revision": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "truncated": false
                }
            }),
            ("platform_read_workspace_file", "/escape") => json!({
                "content": [{"type": "text", "text": "symbolic link rejected"}],
                "isError": true,
                "reason_code": "sandbox_file_symlink_rejected"
            }),
            ("platform_download_workspace_file", "/payload.bin") => {
                let raw = [0_u8, 1, 2, 255];
                json!({
                    "content": [{"type": "text", "text": "download"}],
                    "isError": false,
                    "download": {
                        "contract_version": 1,
                        "authority": "sandbox",
                        "isolation": "isolated",
                        "path": "/payload.bin",
                        "filename": "payload.bin",
                        "mime_type": "application/octet-stream",
                        "size_bytes": raw.len(),
                        "sha256": format!("{:x}", Sha256::digest(raw)),
                        "base64": BASE64_STANDARD.encode(raw)
                    }
                })
            }
            ("platform_download_workspace_file", "/large.bin") => json!({
                "content": [{"type": "text", "text": "file exceeds limit"}],
                "isError": true,
                "reason_code": "sandbox_file_too_large"
            }),
            ("platform_download_workspace_file", "/oversized-success.bin") => {
                let raw = vec![0_u8; 1_025];
                json!({
                    "content": [{"type": "text", "text": "malformed download"}],
                    "isError": false,
                    "download": {
                        "contract_version": 1,
                        "authority": "sandbox",
                        "isolation": "isolated",
                        "path": "/oversized-success.bin",
                        "filename": "oversized-success.bin",
                        "mime_type": "application/octet-stream",
                        "size_bytes": raw.len(),
                        "sha256": format!("{:x}", Sha256::digest(&raw)),
                        "base64": BASE64_STANDARD.encode(&raw)
                    }
                })
            }
            ("platform_download_workspace_file", "/bad-mime.bin") => {
                let raw = [7_u8];
                json!({
                    "content": [{"type": "text", "text": "malformed download"}],
                    "isError": false,
                    "download": {
                        "contract_version": 1,
                        "authority": "sandbox",
                        "isolation": "isolated",
                        "path": "/bad-mime.bin",
                        "filename": "bad-mime.bin",
                        "mime_type": "application/octet-stream\r\nx-injected: true",
                        "size_bytes": raw.len(),
                        "sha256": format!("{:x}", Sha256::digest(raw)),
                        "base64": BASE64_STANDARD.encode(raw)
                    }
                })
            }
            _ => json!({
                "content": [{"type": "text", "text": "not found"}],
                "isError": true,
                "reason_code": "sandbox_file_not_found"
            }),
        };
        Ok(result.to_string())
    }
}

async fn file_test_router() -> (Router, Arc<FileAuthorityToolHost>) {
    file_test_router_with_sandbox_tenant("dev-tenant").await
}

async fn file_test_router_with_sandbox_tenant(
    sandbox_tenant_id: &str,
) -> (Router, Arc<FileAuthorityToolHost>) {
    let host = Arc::new(FileAuthorityToolHost::default());
    let service = ProjectSandboxService::new(
        Arc::new(InMemoryContainerRuntime::new()),
        "sandbox-mcp-server:test",
    )
    .with_runtime_auth_secret(TEST_RUNTIME_AUTH_SECRET)
    .expect("test runtime auth secret is valid")
    .with_tool_host(host.clone());
    service
        .ensure("dev-project", sandbox_tenant_id, Some(SandboxProfile::Lite))
        .await
        .expect("test sandbox starts");

    let state = sandbox_files::SandboxFilesState::new(
        Arc::new(DevAuthenticator::new("dev-user")),
        Arc::new(DevIdentityService::new("dev-user")),
        Arc::new(service),
    );
    let identity = Identity {
        user_id: "dev-user".to_string(),
        _api_key_id: "dev-key".to_string(),
    };
    let app = sandbox_files::router::<sandbox_files::SandboxFilesState>()
        .layer(Extension(identity))
        .with_state(state);
    (app, host)
}

async fn get(app: &Router, uri: &str) -> axum::response::Response {
    app.clone()
        .oneshot(
            Request::builder()
                .uri(uri)
                .body(Body::empty())
                .expect("test request is valid"),
        )
        .await
        .expect("sandbox file route responds")
}

async fn json_body(response: axum::response::Response) -> Value {
    let bytes = to_bytes(response.into_body(), 2 * 1_048_576)
        .await
        .expect("response body is bounded");
    serde_json::from_slice(&bytes).expect("response body is JSON")
}

#[tokio::test]
async fn sandbox_file_routes_list_read_and_download_through_isolated_authority() {
    let (app, host) = file_test_router().await;

    let listing = get(
        &app,
        "/api/v1/projects/dev-project/sandbox/files?path=%2F&limit=20",
    )
    .await;
    assert_eq!(listing.status(), StatusCode::OK);
    let listing_body = json_body(listing).await;
    assert_eq!(listing_body["authority"], "sandbox");
    assert_eq!(listing_body["isolation"], "isolated");
    assert_eq!(listing_body["entries"][0]["path"], "/notes.txt");

    let text = get(
        &app,
        "/api/v1/projects/dev-project/sandbox/files/content?path=%2Fnotes.txt&max_bytes=1024",
    )
    .await;
    assert_eq!(text.status(), StatusCode::OK);
    assert_eq!(json_body(text).await["content"], "hello");

    let download = get(
        &app,
        "/api/v1/projects/dev-project/sandbox/files/download?path=%2Fpayload.bin&max_bytes=1024",
    )
    .await;
    assert_eq!(download.status(), StatusCode::OK);
    assert_eq!(
        download
            .headers()
            .get(CONTENT_TYPE)
            .and_then(|v| v.to_str().ok()),
        Some("application/octet-stream")
    );
    assert_eq!(
        download
            .headers()
            .get("x-memstack-file-authority")
            .and_then(|v| v.to_str().ok()),
        Some("sandbox")
    );
    assert_eq!(
        download
            .headers()
            .get("x-memstack-file-isolation")
            .and_then(|v| v.to_str().ok()),
        Some("isolated")
    );
    let bytes = to_bytes(download.into_body(), 1024)
        .await
        .expect("download body is bounded");
    assert_eq!(bytes.as_ref(), &[0, 1, 2, 255]);

    let calls = host.calls();
    assert_eq!(calls.len(), 3);
    assert_eq!(calls[0].0, "platform_list_workspace_files");
    assert_eq!(calls[1].0, "platform_read_workspace_file");
    assert_eq!(calls[2].0, "platform_download_workspace_file");
}

#[tokio::test]
async fn sandbox_file_routes_reject_traversal_before_tool_dispatch() {
    let (app, host) = file_test_router().await;

    let response = get(
        &app,
        "/api/v1/projects/dev-project/sandbox/files/content?path=%2F..%2Fsecret",
    )
    .await;

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    assert_eq!(
        json_body(response).await["detail"]["reason_code"],
        "sandbox_file_path_invalid"
    );
    assert!(host.calls().is_empty());
}

#[tokio::test]
async fn sandbox_file_routes_preserve_symlink_and_oversize_reason_codes() {
    let (app, _host) = file_test_router().await;

    let symlink = get(
        &app,
        "/api/v1/projects/dev-project/sandbox/files/content?path=%2Fescape",
    )
    .await;
    assert_eq!(symlink.status(), StatusCode::BAD_REQUEST);
    assert_eq!(
        json_body(symlink).await["detail"]["reason_code"],
        "sandbox_file_symlink_rejected"
    );

    let oversized = get(
        &app,
        "/api/v1/projects/dev-project/sandbox/files/download?path=%2Flarge.bin&max_bytes=1024",
    )
    .await;
    assert_eq!(oversized.status(), StatusCode::PAYLOAD_TOO_LARGE);
    assert_eq!(
        json_body(oversized).await["detail"]["reason_code"],
        "sandbox_file_too_large"
    );
}

#[tokio::test]
async fn sandbox_file_routes_reject_oversized_or_invalid_mime_success_payloads() {
    let (app, _host) = file_test_router().await;

    let oversized = get(
        &app,
        "/api/v1/projects/dev-project/sandbox/files/download?path=%2Foversized-success.bin&max_bytes=1024",
    )
    .await;
    assert_eq!(oversized.status(), StatusCode::BAD_GATEWAY);
    assert_eq!(
        json_body(oversized).await["detail"]["reason_code"],
        "sandbox_file_contract_invalid"
    );

    let invalid_mime = get(
        &app,
        "/api/v1/projects/dev-project/sandbox/files/download?path=%2Fbad-mime.bin&max_bytes=1024",
    )
    .await;
    assert_eq!(invalid_mime.status(), StatusCode::BAD_GATEWAY);
    assert_eq!(
        json_body(invalid_mime).await["detail"]["reason_code"],
        "sandbox_file_contract_invalid"
    );
}

#[tokio::test]
async fn sandbox_file_routes_fail_closed_for_the_wrong_project_scope() {
    let (app, host) = file_test_router().await;

    let response = get(
        &app,
        "/api/v1/projects/other-project/sandbox/files?path=%2F",
    )
    .await;

    assert_eq!(response.status(), StatusCode::FORBIDDEN);
    assert_eq!(
        json_body(response).await["detail"]["reason_code"],
        "sandbox_file_scope_forbidden"
    );
    assert!(host.calls().is_empty());
}

#[tokio::test]
async fn sandbox_file_routes_fail_closed_for_a_registry_tenant_mismatch() {
    let (app, host) = file_test_router_with_sandbox_tenant("other-tenant").await;

    let response = get(&app, "/api/v1/projects/dev-project/sandbox/files?path=%2F").await;

    assert_eq!(response.status(), StatusCode::FORBIDDEN);
    assert_eq!(
        json_body(response).await["detail"]["reason_code"],
        "sandbox_file_scope_forbidden"
    );
    assert!(host.calls().is_empty());
}

#[tokio::test]
async fn sandbox_file_capability_requires_a_real_tool_authority() {
    let unavailable = ProjectSandboxService::new(
        Arc::new(InMemoryContainerRuntime::new()),
        "sandbox-mcp-server:test",
    );
    assert!(!unavailable.file_authority_available());

    let host = Arc::new(FileAuthorityToolHost::default());
    let available = ProjectSandboxService::new(
        Arc::new(InMemoryContainerRuntime::new()),
        "sandbox-mcp-server:test",
    )
    .with_tool_host(host);
    assert!(available.file_authority_available());
}
