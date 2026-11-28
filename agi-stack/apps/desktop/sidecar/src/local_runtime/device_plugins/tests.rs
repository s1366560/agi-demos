use super::*;
use crate::local_runtime::signed_wasm_fixture as fixture;
use crate::trusted_session::{
    TrustedSessionCredentialKind, TrustedSessionRecord, TrustedSessionRuntimeMode,
};
use agistack_plugin_host::{
    parse_control_plane_distribution_v2, protocol_v2::signed_archive::TrustedEd25519KeyV2,
};
use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    routing::{delete, get, post},
    Json, Router,
};
use sha2::{Digest, Sha256};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Mutex,
};
use tokio::sync::Notify;

const GRANT_ID: &str = "6b28ce7b-d3c4-43cc-a618-a5c625002358";

#[derive(Default)]
struct Remote {
    binding: Mutex<Option<Value>>,
    hold_next_check: AtomicBool,
    checking: Notify,
    resume: Notify,
    user: Mutex<String>,
}
async fn me(State(remote): State<Arc<Remote>>) -> Json<Value> {
    Json(json!({"user_id":*remote.user.lock().unwrap()}))
}
async fn approve(
    State(remote): State<Arc<Remote>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> StatusCode {
    assert_eq!(headers["authorization"], "Bearer fixture-session");
    assert!(body.get("device_proof").is_none());
    assert_eq!(body["bundle_digest"].as_str().unwrap().len(), 64);
    *remote.binding.lock().unwrap() = Some(body);
    StatusCode::CREATED
}
async fn check(
    State(remote): State<Arc<Remote>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Result<Json<Value>, StatusCode> {
    assert_eq!(headers["authorization"], "Bearer fixture-session");
    let binding = remote
        .binding
        .lock()
        .unwrap()
        .clone()
        .ok_or(StatusCode::FORBIDDEN)?;
    if body["permission"] == "invoke" && remote.hold_next_check.swap(false, Ordering::SeqCst) {
        remote.checking.notify_one();
        remote.resume.notified().await;
    }
    assert_eq!(
        binding["device_fingerprint"],
        format!(
            "sha256:{:x}",
            Sha256::digest(body["device_proof"].as_str().unwrap().as_bytes())
        )
    );
    assert_eq!(binding["machine_id"], body["machine_id"]);
    assert_eq!(binding["generation_id"], body["generation_id"]);
    assert_eq!(binding["bundle_digest"], body["bundle_digest"]);
    if body["permission"] == "invoke" {
        assert_eq!(body["grant_id"], GRANT_ID);
    }
    let mut response = binding;
    for (key, value) in [
        ("allowed", json!(true)),
        ("grant_id", json!(GRANT_ID)),
        ("permission", body["permission"].clone()),
        ("tenant_id", json!("tenant")),
        ("project_id", json!("project")),
    ] {
        response[key] = value;
    }
    Ok(Json(response))
}
async fn native_state(key: TrustedEd25519KeyV2) -> Arc<LocalRuntimeState> {
    use super::super::platform_plugin_sync_v2::desktop_loader;
    let mut state = super::super::tests::test_state("device-plugin");
    Arc::get_mut(&mut state).unwrap().local_plugin_signing_keys = Ok(vec![key]);
    let snapshot: Value = serde_json::from_str(include_str!(
        "../../../../../../../shared/profiles/memstack-default-bootstrap.v2.json"
    ))
    .unwrap();
    let wire = json!({"schema_version":2,"descriptor":{"profile_id":snapshot["profile_id"],"generation":snapshot["generation"],"digest":snapshot["digest"]},"snapshot":snapshot,
        "envelope":{"version":1,"nonce":"device-package-test","snapshot_digest":snapshot["digest"],"type_url":"types.memstack.ai/plugin.profile.v2"}});
    let publication = parse_control_plane_distribution_v2(&wire.to_string()).unwrap();
    let runtime = desktop_loader(None, None)
        .stage(publication.snapshot.clone())
        .await
        .unwrap();
    state
        .platform_plugin_authority_v2
        .publish(&publication, runtime)
        .await;
    state
}
#[tokio::test]
async fn install_invoke_reject_revoked_grant_and_switched_principal() {
    let (_, _, bytes, key, _) = fixture::signed_fixture_with_bytes(
        r#"(module (func (export "score") (param i32) (result i32) i32.const 42))"#,
        |_| {},
    );
    exercise_device_package(
        bytes,
        key,
        json!({"input":"abc"}),
        json!({"score":42}),
        None,
    )
    .await;
}

#[tokio::test]
#[ignore = "use plugins/business/knowledge/workers/device_search/verify_sidecar.py to build and sign the Wasm guest"]
async fn publisher_signed_knowledge_guest_at_abi_boundary() {
    let root = std::path::PathBuf::from(
        std::env::var_os("MEMSTACK_KNOWLEDGE_QA_RELEASES").expect("publisher release directory"),
    );
    let key = TrustedEd25519KeyV2::from_spki_pem(
        &std::fs::read_to_string(root.join("public.pem")).unwrap(),
    )
    .unwrap();
    let mut input = json!({"query":"needle", "documents":[{"id":"test", "text":"needle\n"}]});
    let extra = 65536 - serde_json::to_vec(&input).unwrap().len();
    input["documents"][0]["text"] = format!("needle\n{}", "x".repeat(extra)).into();
    assert_eq!(serde_json::to_vec(&input).unwrap().len(), 65536);
    exercise_device_package(
        std::fs::read(root.join("current.mspkg")).unwrap(),
        key,
        input,
        json!({"hits":[{"id":"test","line":1,"excerpt":"needle"}]}),
        Some(std::fs::read(root.join("future.mspkg")).unwrap()),
    )
    .await;
}

#[tokio::test]
#[ignore = "requires the published Environments archive and public key"]
async fn published_environments_cloud_http_routes_require_approved_device_grant() {
    let root =
        std::path::PathBuf::from(std::env::var_os("MEMSTACK_ENVIRONMENTS_HTTP_RELEASE").unwrap());
    let key = TrustedEd25519KeyV2::from_spki_pem(
        &std::fs::read_to_string(root.join("public.pem")).unwrap(),
    )
    .unwrap();
    exercise_device_package(
        std::fs::read(root.join("environments.mspkg")).unwrap(),
        key,
        json!({"project_id":"project","method":"POST","path":"sandbox/proxy-auth-cookie"}),
        json!({"status":200,"body":{"ok":true}}),
        None,
    )
    .await;
}

async fn exercise_device_package(
    bytes: Vec<u8>,
    key: TrustedEd25519KeyV2,
    input: Value,
    expected: Value,
    incompatible: Option<Vec<u8>>,
) {
    let advertised = packages::inspect(&bytes, std::slice::from_ref(&key)).unwrap();
    let project_selection = (advertised.reference().bundle_id == "memstack-environments")
        .then(|| advertised.reference().clone());
    let project_plugin = project_selection.as_ref().map(|s| s.bundle_id.clone());
    let mut state = native_state(key).await;
    Arc::get_mut(&mut state).unwrap().profile = crate::sidecar_profile::SidecarProfile::Full;
    let root = std::env::temp_dir().join(uuid::Uuid::new_v4().to_string());
    let workspace = root.join("workspace");
    std::fs::create_dir_all(&workspace).unwrap();
    *state.workspace_root.lock().unwrap() = workspace.clone();
    let transfers = root.join("device-plugin-transfers");
    std::fs::create_dir_all(&transfers).unwrap();
    Arc::get_mut(&mut state).unwrap().app_data_dir = Some(root.clone());
    // A trusted publisher can still ship a guest with a wrong executable ABI.
    let (_, _, broken, candidate_key, _) = fixture::signed_fixture_with_bytes(
        r#"(module (func (export "unexpected") (param i32) (result i32) i32.const 0))"#,
        |_| {},
    );
    Arc::get_mut(&mut state)
        .unwrap()
        .local_plugin_signing_keys
        .as_mut()
        .unwrap()
        .push(candidate_key);
    let broken_id = uuid::Uuid::new_v4().to_string();
    std::fs::write(transfers.join(&broken_id), broken).unwrap();
    let archive = uuid::Uuid::new_v4().to_string();
    std::fs::write(transfers.join(&archive), bytes).unwrap();
    let remote = Arc::new(Remote::default());
    *remote.user.lock().unwrap() = "owner".into();
    let app=Router::new().route("/api/v1/auth/me",get(me))
        .route("/api/v1/projects/project",get(||async{Json(json!({"id":"project","tenant_id":"tenant"}))}))
        .route("/api/v1/workspace-context",get(||async{Json(json!({"context":{"tenant_id":"tenant","project_id":"project","revision":1},"membership_role":"owner"}))}))
        .route("/api/v1/projects/project/device-plugin-grants/selection",get(move || {
            let reference = project_selection.clone();
            async move { Json(reference.map(|r|json!({"plugin_id":r.bundle_id,"generation_id":format!("p{}", "1".repeat(63)),"digest":r.digest}))) }
        }))
        .route("/api/v1/projects/project/device-plugin-grants/authority",get(|| async {Json(json!({"can_manage":true}))}))
        .route("/api/v1/projects/project/device-plugin-grants/",post(approve))
        .route("/api/v1/projects/project/device-plugin-grants/check",post(check))
        .route(&format!("/api/v1/projects/project/device-plugin-grants/{GRANT_ID}"), delete(|State(remote): State<Arc<Remote>>| async move {
            remote.binding.lock().unwrap().take();
            StatusCode::NO_CONTENT
        }))
        .with_state(remote.clone());
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    let broker = TrustedSessionBroker::native(
        crate::application_vault::ApplicationCredentialVault::open(&root).unwrap(),
    );
    broker
        .save(TrustedSessionRecord {
            version: 1,
            api_base_url: base,
            runtime_mode: TrustedSessionRuntimeMode::Cloud,
            credential_kind: TrustedSessionCredentialKind::CloudBearer,
            credential: "fixture-session".into(),
            expires_at: None,
            refresh_token: None,
            access_expires_at: None,
            persist_across_restart: true,
        })
        .unwrap();
    state
        .platform_plugin_authority_v2
        .install_trusted_sessions(broker.clone());
    let http = |bearer: &str, method: &str, path: &str| {
        use tower::ServiceExt;
        super::super::local_router(state.clone()).oneshot(
            axum::http::Request::builder()
                .method(method)
                .uri(path)
                .header("x-agistack-launch", &state.api_token)
                .header("authorization", format!("Bearer {bearer}"))
                .body(axum::body::Body::empty())
                .unwrap(),
        )
    };
    let call = |op: Value, token: &Value| {
        operation(
            &state,
            &broker,
            json!({"tenant_id":"tenant","project_id":"project","plugin_id":project_plugin,"context_token":token,"operation":op}),
        )
    };
    let catalog = call(json!({"action":"list"}), &Value::Null).await.unwrap();
    let token = &catalog["context_token"];

    if let Some(bytes) = incompatible.as_ref() {
        let id = uuid::Uuid::new_v4().to_string();
        std::fs::write(transfers.join(&id), bytes).unwrap();
        let result = call(json!({"action":"inspect","archive_id":id}), token).await;
        assert!(result.unwrap_err().contains("incompatible_host_abi"));
        assert!(remote.binding.lock().unwrap().is_none());
    }
    let preview = call(json!({"action":"inspect","archive_id":archive}), token)
        .await
        .unwrap();
    let import = json!({"action":"install","approve_for_day":false,"archive_id":archive,"reference":preview["reference"],"approved_permissions":preview["declared_permissions"]});
    assert!(call(import.clone(), token).await.is_err());
    let mut import = import;
    import["approve_for_day"] = true.into();
    if preview["workspace"].is_object() {
        assert!(call(import.clone(), token).await.is_err());
        import["workspace_token"] = preview["workspace"]["token"].clone();
    }
    let installed = call(import.clone(), token).await.unwrap();
    import["archive_id"] = json!(broken_id);
    let error = call(import, token).await.unwrap_err();
    if project_plugin.is_some() {
        assert_eq!(error, "device_plugin_selection_changed");
        assert_eq!(
            http(
                "wrong",
                "POST",
                "/api/v1/projects/project/sandbox/proxy-auth-cookie"
            )
            .await
            .unwrap()
            .status(),
            StatusCode::UNAUTHORIZED
        );
        let response = http(
            "fixture-session",
            "POST",
            "/api/v1/projects/project/sandbox/proxy-auth-cookie",
        )
        .await
        .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let bytes = axum::body::to_bytes(response.into_body(), 1024)
            .await
            .unwrap();
        assert_eq!(
            serde_json::from_slice::<Value>(&bytes).unwrap(),
            json!({"ok":true})
        );
    } else {
        assert!(error.contains("signed WASM ABI"), "{error}");
    }
    if preview["workspace"].is_object() {
        let bytes = vec![33_u8; 128 * 1024];
        std::fs::write(workspace.join("download.txt"), &bytes).unwrap();
        let path =
            "/api/v1/projects/project/sandbox/files/download?path=%2Fworkspace%2Fdownload.txt";
        let reply = http("fixture-session", "GET", path).await.unwrap();
        assert_eq!(reply.status(), StatusCode::OK);
        assert_eq!(
            axum::body::to_bytes(reply.into_body(), 256 * 1024)
                .await
                .unwrap()
                .as_ref(),
            bytes
        );
        let mut file = json!({"action":"invoke","grant_id":installed["grant_id"],"reference":preview["reference"],"tool":installed["tools"][0],"input":{"project_id":"project","method":"GET","path":"sandbox/files/download","query":"path=%2Fworkspace%2Fdownload.txt"}});
        let file_result = call(file.clone(), token).await.unwrap();
        assert_eq!(file_result["status"], 200);
        assert_eq!(
            file_result["body_base64"],
            base64::Engine::encode(&base64::engine::general_purpose::STANDARD, &bytes)
        );
        file["input"]["project_id"] = json!("other");
        assert!(call(file, token).await.is_err());
        *state.workspace_root.lock().unwrap() = root.clone();
        assert_eq!(
            http("fixture-session", "GET", path).await.unwrap().status(),
            StatusCode::FORBIDDEN
        );
        *state.workspace_root.lock().unwrap() = workspace.clone();
    }
    let invoke = json!({"action":"invoke","reference":preview["reference"],"grant_id":installed["grant_id"],"tool":installed["tools"][0],"input":input});
    let output = call(invoke.clone(), token).await.unwrap();
    // The legacy score ABI also includes package attribution in its result metadata.
    for (field, value) in expected.as_object().unwrap() {
        assert_eq!(&output[field], value);
    }
    if incompatible.is_some() {
        let mut oversized = invoke.clone();
        let text = oversized["input"]["documents"][0]["text"]
            .as_str()
            .unwrap()
            .to_owned()
            + "x";
        oversized["input"]["documents"][0]["text"] = text.into();
        assert!(call(oversized, token)
            .await
            .unwrap_err()
            .contains("byte budget"));
    }
    let live = call(json!({"action":"list"}), &Value::Null).await.unwrap();
    assert_eq!(
        live["installations"][0]["reference"],
        installed["reference"]
    );
    assert_eq!(live["installations"][0]["grant_status"], "approved");
    assert!(live["installations"][0]["last_invoked_at"].is_string());
    remote.hold_next_check.store(true, Ordering::SeqCst);
    let revoke_during_call = async {
        remote.checking.notified().await;
        let revoked = call(
            json!({"action":"revoke","reference":installed["reference"],"grant_id":GRANT_ID}),
            token,
        )
        .await
        .unwrap();
        assert_eq!(revoked["revoked"], true);
        remote.resume.notify_one();
    };
    let (result, ()) = tokio::time::timeout(std::time::Duration::from_secs(10), async {
        tokio::join!(call(invoke.clone(), token), revoke_during_call)
    })
    .await
    .expect("revocation must not wait for a running guest");
    assert!(result.is_err());
    if project_plugin.is_some() {
        assert_eq!(
            http(
                "fixture-session",
                "POST",
                "/api/v1/projects/project/sandbox/proxy-auth-cookie"
            )
            .await
            .unwrap()
            .status(),
            StatusCode::FORBIDDEN
        );
    }
    assert!(call(invoke.clone(), token).await.is_err());
    *remote.user.lock().unwrap() = "switched".into();
    let other = call(json!({"action":"list"}), &Value::Null).await.unwrap();
    assert_ne!(other["context_token"], *token);
    assert_eq!(other["installations"], json!([]));
    assert!(call(invoke.clone(), token).await.is_err());
    assert!(call(invoke, &other["context_token"]).await.is_err());
    server.abort();
    std::fs::remove_dir_all(root).unwrap();
}
