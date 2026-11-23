use super::*;
use crate::trusted_session::{
    TrustedSessionCredentialKind, TrustedSessionRecord, TrustedSessionRuntimeMode,
};
use agistack_plugin_host::{
    parse_control_plane_distribution_v2, protocol_v2::signed_archive::TrustedEd25519KeyV2,
};
use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    routing::{get, post},
    Json, Router,
};
use sha2::{Digest, Sha256};
use std::sync::Mutex;

#[allow(dead_code)]
#[path = "../../../../../../crates/plugin-host/tests/support/signed_wasm_runtime.rs"]
mod fixture;

#[derive(Default)]
struct Remote {
    binding: Mutex<Option<Value>>,
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
    let lock = remote.binding.lock().unwrap();
    let binding = lock.as_ref().ok_or(StatusCode::FORBIDDEN)?;
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
        assert_eq!(body["grant_id"], "grant-current");
    }
    let mut response = binding.clone();
    for (key, value) in [
        ("allowed", json!(true)),
        ("grant_id", json!("grant-current")),
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

async fn exercise_device_package(
    bytes: Vec<u8>,
    key: TrustedEd25519KeyV2,
    input: Value,
    expected: Value,
    incompatible: Option<Vec<u8>>,
) {
    let mut state = native_state(key).await;
    let root = std::env::temp_dir().join(uuid::Uuid::new_v4().to_string());
    let transfers = root.join("device-plugin-transfers");
    std::fs::create_dir_all(&transfers).unwrap();
    Arc::get_mut(&mut state).unwrap().app_data_dir = Some(root.clone());
    let archive = uuid::Uuid::new_v4().to_string();
    std::fs::write(transfers.join(archive.to_string()), bytes).unwrap();
    let remote = Arc::new(Remote::default());
    *remote.user.lock().unwrap() = "owner".into();
    let app=Router::new().route("/api/v1/auth/me",get(me))
        .route("/api/v1/projects/project",get(||async{Json(json!({"id":"project","tenant_id":"tenant"}))}))
        .route("/api/v1/workspace-context",get(||async{Json(json!({"context":{"tenant_id":"tenant","project_id":"project","revision":1},"membership_role":"owner"}))}))
        .route("/api/v1/projects/project/device-plugin-grants/authority",get(|| async {Json(json!({"can_manage":true}))}))
        .route("/api/v1/projects/project/device-plugin-grants/",post(approve))
        .route("/api/v1/projects/project/device-plugin-grants/check",post(check))
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
    let call = |op: Value, token: &Value| {
        operation(
            &state,
            &broker,
            json!({"tenant_id":"tenant","project_id":"project","context_token":token,"operation":op}),
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
    let installed = call(import, token).await.unwrap();
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
    remote.binding.lock().unwrap().take();
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
