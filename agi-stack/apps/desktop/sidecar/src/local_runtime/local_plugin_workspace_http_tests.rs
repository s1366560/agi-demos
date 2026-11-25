use std::{
    fs,
    path::{Path, PathBuf},
    sync::Arc,
};

use axum::{
    body::Body,
    http::{Method, Request, StatusCode},
    response::Response,
};
use serde_json::Value;
use tower::ServiceExt;
use uuid::Uuid;

use super::*;
use crate::local_runtime::{local_router, LocalRuntimeState};

struct TestWorkspace {
    root: PathBuf,
    outside: PathBuf,
    state: Arc<LocalRuntimeState>,
}

impl Drop for TestWorkspace {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
        let _ = fs::remove_dir_all(&self.outside);
    }
}

async fn test_workspace(credential: &str) -> TestWorkspace {
    let unique = Uuid::new_v4();
    let root = std::env::temp_dir().join(format!("agistack-sandbox-files-{unique}"));
    let outside = std::env::temp_dir().join(format!("agistack-sandbox-files-outside-{unique}"));
    fs::create_dir_all(&root).expect("create workspace root");
    fs::create_dir_all(&outside).expect("create outside root");
    let dir = PathBuf::from(std::env::var_os("MEMSTACK_ENVIRONMENTS_HTTP_RELEASE").unwrap());
    let key =
        agistack_plugin_host::protocol_v2::signed_archive::TrustedEd25519KeyV2::from_spki_pem(
            &fs::read_to_string(dir.join("public.pem")).unwrap(),
        )
        .unwrap();
    let mut state = local_runtime::tests::test_state(credential);
    let inner = Arc::get_mut(&mut state).unwrap();
    inner.profile = crate::sidecar_profile::SidecarProfile::Full;
    inner.local_plugin_signing_keys = Ok(vec![key]);
    *inner.workspace_root.lock().unwrap() = root.clone();
    let mut reconciler = desktop_reconciler(&state);
    activate_authority_source(&state, &mut reconciler, &DesktopAuthoritySourceV2::Local)
        .await
        .unwrap();
    import(&state, &fs::read(dir.join("environments.mspkg")).unwrap()).await;
    TestWorkspace {
        root,
        outside,
        state,
    }
}

fn request(method: Method, uri: &str, credential: &str) -> Request<Body> {
    Request::builder()
        .method(method)
        .uri(uri)
        .header("authorization", format!("Bearer {credential}"))
        .header("x-agistack-launch", credential)
        .body(Body::empty())
        .expect("sandbox files request")
}

async fn response_json(response: Response) -> Value {
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("response body");
    serde_json::from_slice(&body).expect("response JSON")
}

#[tokio::test]
#[ignore = "requires a signed Environments workspace-read release"]
async fn native_runtime_capabilities_declare_only_supported_sandbox_authorities() {
    let credential = TOKEN;
    let workspace = test_workspace(credential).await;
    let app = local_router(Arc::clone(&workspace.state));

    let response = app
        .oneshot(request(
            Method::GET,
            "/api/v1/projects/local-project/sandbox/capabilities",
            credential,
        ))
        .await
        .expect("sandbox capability response");
    assert_eq!(response.status(), StatusCode::OK);
    let payload = response_json(response).await;
    assert_eq!(payload["contract_version"], 2);
    assert_eq!(payload["service_version"], env!("CARGO_PKG_VERSION"));
    assert_eq!(
        payload["terminal_interactive"],
        serde_json::json!({
            "availability": "available",
            "contract_version": 1,
            "reason_code": null,
        })
    );
    assert_eq!(
        payload["terminal_resume"],
        serde_json::json!({
            "availability": "unavailable",
            "contract_version": 2,
            "reason_code": "local_terminal_resume_unavailable",
        })
    );
    assert_eq!(
        payload["files"],
        serde_json::json!({
            "availability": "available",
            "contract_version": 1,
            "reason_code": null,
        })
    );
    assert_eq!(
        payload["kasm_vnc"],
        serde_json::json!({
            "availability": "not_applicable",
            "contract_version": 1,
            "reason_code": "local_kasm_vnc_not_applicable",
        })
    );
}

#[tokio::test]
#[ignore = "requires a signed Environments workspace-read release"]
async fn native_workspace_files_list_read_and_download_use_structured_authority() {
    let credential = TOKEN;
    let workspace = test_workspace(credential).await;
    fs::create_dir_all(workspace.root.join("docs")).expect("create docs");
    fs::write(workspace.root.join("docs/readme.md"), "# Local\n").expect("write markdown");
    fs::write(workspace.root.join("data.bin"), [0_u8, 1, 2, 3]).expect("write binary");
    let app = local_router(Arc::clone(&workspace.state));

    let list = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/projects/local-project/sandbox/files?path=%2Fworkspace&limit=20",
            credential,
        ))
        .await
        .expect("list response");
    assert_eq!(list.status(), StatusCode::OK);
    let payload = response_json(list).await;
    assert_eq!(payload["contract_version"], 1);
    assert_eq!(payload["authority"], "native_workspace");
    assert_eq!(payload["isolation"], "not_applicable");
    assert_eq!(payload["path"], "/workspace");
    assert!(payload["revision"]
        .as_str()
        .is_some_and(|revision| revision.starts_with("sha256:")));
    assert_eq!(
        payload["entries"]
            .as_array()
            .expect("list entries")
            .iter()
            .map(|entry| entry["name"].as_str().expect("entry name"))
            .collect::<Vec<_>>(),
        vec!["data.bin", "docs"]
    );

    let read = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/projects/local-project/sandbox/files/content?path=%2Fworkspace%2Fdocs%2Freadme.md&max_bytes=1024",
            credential,
        ))
        .await
        .expect("read response");
    assert_eq!(read.status(), StatusCode::OK);
    let payload = response_json(read).await;
    assert_eq!(payload["authority"], "native_workspace");
    assert_eq!(payload["isolation"], "not_applicable");
    assert_eq!(payload["path"], "/workspace/docs/readme.md");
    assert_eq!(payload["encoding"], "utf-8");
    assert_eq!(payload["content"], "# Local\n");
    assert_eq!(payload["mime_type"], "text/markdown");
    assert_eq!(payload["size_bytes"], 8);
    assert_eq!(payload["truncated"], false);

    let download = app
        .oneshot(request(
            Method::GET,
            "/api/v1/projects/local-project/sandbox/files/download?path=%2Fworkspace%2Fdata.bin",
            credential,
        ))
        .await
        .expect("download response");
    assert_eq!(download.status(), StatusCode::OK);
    assert_eq!(
        download
            .headers()
            .get("content-type")
            .and_then(|value| value.to_str().ok()),
        Some("application/octet-stream")
    );
    assert_eq!(
        download
            .headers()
            .get("content-disposition")
            .and_then(|value| value.to_str().ok()),
        Some("attachment; filename=\"data.bin\"")
    );
    assert_eq!(
        download
            .headers()
            .get("x-memstack-file-contract-version")
            .and_then(|value| value.to_str().ok()),
        Some("1")
    );
    assert_eq!(
        download
            .headers()
            .get("x-memstack-file-authority")
            .and_then(|value| value.to_str().ok()),
        Some("native_workspace")
    );
    assert_eq!(
        download
            .headers()
            .get("x-memstack-file-isolation")
            .and_then(|value| value.to_str().ok()),
        Some("not_applicable")
    );
    assert!(download
        .headers()
        .get("access-control-expose-headers")
        .and_then(|value| value.to_str().ok())
        .is_some_and(|value| value.contains("X-MemStack-File-Authority")));
    let body = axum::body::to_bytes(download.into_body(), usize::MAX)
        .await
        .expect("download body");
    assert_eq!(body.as_ref(), &[0, 1, 2, 3]);
}

#[tokio::test]
#[ignore = "requires a signed Environments workspace-read release"]
async fn native_workspace_files_reject_traversal_and_out_of_scope_projects() {
    let credential = TOKEN;
    let workspace = test_workspace(credential).await;
    let app = local_router(Arc::clone(&workspace.state));

    let traversal = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/projects/local-project/sandbox/files/content?path=%2Fworkspace%2F..%2Fsecret",
            credential,
        ))
        .await
        .expect("traversal response");
    assert_eq!(traversal.status(), StatusCode::UNPROCESSABLE_ENTITY);
    let payload = response_json(traversal).await;
    assert_eq!(payload["reason_code"], "sandbox_file_path_invalid");
    assert!(!payload
        .to_string()
        .contains(&workspace.root.to_string_lossy().to_string()));

    let runtime_state = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/projects/local-project/sandbox/files/content?path=%2Fworkspace%2F.agistack%2Fsessions.sqlite",
            credential,
        ))
        .await
        .expect("reserved runtime state response");
    assert_eq!(runtime_state.status(), StatusCode::FORBIDDEN);
    assert_eq!(
        response_json(runtime_state).await["reason_code"],
        "sandbox_file_reserved_path"
    );

    let runtime_state_alias = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/projects/local-project/sandbox/files/content?path=%2Fworkspace%2F.AGISTACK%2Fsessions.sqlite",
            credential,
        ))
        .await
        .expect("case-insensitive reserved runtime state response");
    assert_eq!(runtime_state_alias.status(), StatusCode::FORBIDDEN);
    assert_eq!(
        response_json(runtime_state_alias).await["reason_code"],
        "sandbox_file_reserved_path"
    );

    let malformed = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/projects/local-project/sandbox/files?path=%2Fworkspace&unexpected=true",
            credential,
        ))
        .await
        .expect("malformed query response");
    assert_eq!(malformed.status(), StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        response_json(malformed).await["reason_code"],
        "sandbox_file_query_invalid"
    );

    let wrong_project = app
        .oneshot(request(
            Method::GET,
            "/api/v1/projects/other-project/sandbox/files?path=%2Fworkspace",
            credential,
        ))
        .await
        .expect("scope response");
    assert_eq!(wrong_project.status(), StatusCode::FORBIDDEN);
    let payload = response_json(wrong_project).await;
    assert!(!payload
        .to_string()
        .contains(&workspace.root.to_string_lossy().to_string()));
}

#[tokio::test]
#[ignore = "requires a signed Environments workspace-read release"]
async fn native_workspace_files_reject_symlinks_instead_of_following_them() {
    let credential = TOKEN;
    let workspace = test_workspace(credential).await;
    let outside_file = workspace.outside.join("secret.txt");
    fs::write(&outside_file, "outside").expect("write outside file");
    let link = workspace.root.join("escape.txt");
    if create_file_symlink(&outside_file, &link).is_err() {
        return;
    }
    let app = local_router(Arc::clone(&workspace.state));

    let read = app
        .oneshot(request(
            Method::GET,
            "/api/v1/projects/local-project/sandbox/files/content?path=%2Fworkspace%2Fescape.txt",
            credential,
        ))
        .await
        .expect("symlink response");
    assert_eq!(read.status(), StatusCode::FORBIDDEN);
    let payload = response_json(read).await;
    assert_eq!(payload["reason_code"], "sandbox_file_symlink_not_allowed");
    assert!(!payload.to_string().contains("outside"));
}

#[tokio::test]
#[ignore = "requires a signed Environments workspace-read release"]
async fn native_workspace_files_enforce_text_mime_and_byte_limits() {
    let credential = TOKEN;
    let workspace = test_workspace(credential).await;
    fs::write(workspace.root.join("binary.bin"), [0_u8, 159, 146, 150]).expect("write binary");
    fs::write(workspace.root.join("large.txt"), "oversized").expect("write text");
    let app = local_router(Arc::clone(&workspace.state));

    let binary = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/projects/local-project/sandbox/files/content?path=%2Fworkspace%2Fbinary.bin&max_bytes=1024",
            credential,
        ))
        .await
        .expect("binary response");
    assert_eq!(binary.status(), StatusCode::UNSUPPORTED_MEDIA_TYPE);
    assert_eq!(
        response_json(binary).await["reason_code"],
        "sandbox_file_text_read_unsupported"
    );

    let oversized = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/projects/local-project/sandbox/files/content?path=%2Fworkspace%2Flarge.txt&max_bytes=4",
            credential,
        ))
        .await
        .expect("oversized response");
    assert_eq!(oversized.status(), StatusCode::PAYLOAD_TOO_LARGE);
    assert_eq!(
        response_json(oversized).await["reason_code"],
        "sandbox_file_too_large"
    );

    let download = app
        .oneshot(request(
            Method::GET,
            "/api/v1/projects/local-project/sandbox/files/download?path=%2Fworkspace%2Flarge.txt&max_bytes=4",
            credential,
        ))
        .await
        .expect("download limit response");
    assert_eq!(download.status(), StatusCode::PAYLOAD_TOO_LARGE);
    assert_eq!(
        response_json(download).await["reason_code"],
        "sandbox_file_too_large"
    );
}

#[cfg(unix)]
fn create_file_symlink(source: &Path, target: &Path) -> std::io::Result<()> {
    std::os::unix::fs::symlink(source, target)
}

#[cfg(windows)]
fn create_file_symlink(source: &Path, target: &Path) -> std::io::Result<()> {
    std::os::windows::fs::symlink_file(source, target)
}

#[cfg(not(any(unix, windows)))]
fn create_file_symlink(_source: &Path, _target: &Path) -> std::io::Result<()> {
    Err(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "symlinks are unsupported on this platform",
    ))
}
