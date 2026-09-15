use super::*;
use crate::local_runtime::{
    self,
    authorized_tool_host::AuthorizedRunToolHost,
    knowledge_authority_v2::agent_access::{self, RunAuthorization},
    local_plugin_tool_host_v2::LocalPluginToolHostV2,
};
use agistack_core::ports::ToolHost;
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde_json::json;
use tower::ServiceExt;
#[allow(dead_code)]
#[path = "../../../../../crates/plugin-host/tests/support/signed_wasm_runtime.rs"]
mod fixture;
const MARKER: &str =
    "(module (func (export \"score\") (param i32) (result i32) i32.const 20260914))";
const TOKEN: &str = "local-plugin-runtime-test-session";
async fn request(
    state: &Arc<LocalRuntimeState>,
    method: &str,
    path: &str,
    body: Value,
) -> (StatusCode, Value) {
    let response = local_runtime::local_router_with_generation_required(state.clone())
        .oneshot(
            Request::builder()
                .method(method)
                .uri(path)
                .header("authorization", format!("Bearer {TOKEN}"))
                .header("x-agistack-launch", TOKEN)
                .header("content-type", "application/json")
                .body(Body::from(body.to_string()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 1000000).await.unwrap();
    let value = serde_json::from_slice(&bytes)
        .unwrap_or_else(|_| json!({"body":String::from_utf8_lossy(&bytes)}));
    (status, value)
}
async fn setup() -> (Arc<LocalRuntimeState>, Vec<u8>) {
    setup_wasm(MARKER).await
}
async fn setup_wasm(wasm: &str) -> (Arc<LocalRuntimeState>, Vec<u8>) {
    let (_, _, bytes, key, _) = fixture::signed_fixture_with_bytes(wasm, |_| {});
    let mut state = local_runtime::tests::test_state(TOKEN);
    Arc::get_mut(&mut state).unwrap().local_plugin_signing_keys = Ok(vec![key]);
    let mut reconciler = desktop_reconciler(&state);
    activate_authority_source(&state, &mut reconciler, &DesktopAuthoritySourceV2::Local)
        .await
        .unwrap();
    (state, bytes)
}
async fn import(state: &Arc<LocalRuntimeState>, bytes: &[u8]) -> Value {
    let payload = json!({"tenant_id":"local","project_id":"local-project","archive_base64":STANDARD.encode(bytes)});
    let (status, preview) = request(
        state,
        "POST",
        "/api/v1/local-plugins/v2/installations/inspect",
        payload.clone(),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{preview}");
    assert_eq!(preview["verified"], true);
    let mut payload = payload;
    payload["reference"] = preview["reference"].clone();
    payload["approved_permissions"] = preview["declared_permissions"].clone();
    let (status, result) = request(
        state,
        "POST",
        "/api/v1/local-plugins/v2/installations/import",
        payload,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{result}");
    let list = request(
        state,
        "GET",
        "/api/v1/local-plugins/v2/installations?tenant_id=local&project_id=local-project",
        Value::Null,
    )
    .await
    .1;
    assert_eq!(list["installations"][0]["activation_status"], "pending");
    assert!(list["installations"][0]["activation_error"].is_null());
    let mut reconciler = desktop_reconciler(state);
    activate_authority_source(state, &mut reconciler, &DesktopAuthoritySourceV2::Local)
        .await
        .unwrap();
    preview["reference"].clone()
}
async fn run(
    state: &Arc<LocalRuntimeState>,
) -> (local_runtime::LocalConversation, local_runtime::DesktopRun) {
    local_runtime::tests::seed_plan_conversation(state, "local-plugin-conversation");
    state.session_store.replace_agent_plan_tasks("local-plugin-conversation",&[json!({"id":"local-plugin-task","conversation_id":"local-plugin-conversation","content":"Call signed marker","status":"pending","priority":"high","order_index":0,"created_at":local_runtime::now_iso(),"updated_at":local_runtime::now_iso()})]).unwrap();
    let reviewed = state
        .session_store
        .latest_draft_plan("local-plugin-conversation")
        .unwrap()
        .unwrap();
    let now = local_runtime::now_iso();
    let prepared = state
        .worktree_manager()
        .prepare(
            local_runtime::DesktopExecutionEnvironmentKind::Local,
            "local-plugin-environment",
            &now,
        )
        .unwrap();
    let queued = state
        .session_store
        .approve_plan_and_start_in_environment(
            local_runtime::session_store::ApprovePlanStartInput {
                conversation_id: "local-plugin-conversation",
                project_id: "local-project",
                plan_version_id: &reviewed.id,
                expected_plan_version: reviewed.version,
                idempotency_key: "local-plugin-run",
                message_id: "local-plugin-message",
                request_message: "Call signed marker",
                environment: Some(prepared.environment),
                requested_environment_kind: local_runtime::DesktopExecutionEnvironmentKind::Local,
                permission_profile: local_runtime::DesktopPermissionProfile::ReadOnly,
                now: &now,
            },
        )
        .unwrap()
        .run;
    let run = state
        .prepare_authoritative_run_for_execution(
            &queued.id,
            &queued.conversation_id,
            &queued.project_id,
            &queued.request_message,
            &local_runtime::now_iso(),
        )
        .await
        .unwrap()
        .unwrap();
    let conversation = state
        .session_store
        .conversation("local-plugin-conversation")
        .unwrap()
        .unwrap();
    (conversation, run)
}

#[tokio::test]
async fn local_signed_install_real_toolhost_execution_and_revocation() {
    let (state, bytes) = setup().await;
    let reference = import(&state, &bytes).await;
    let (conversation, run) = run(&state).await;
    let auth = state
        .session_store
        .validate_session_credential(TOKEN, chrono::Utc::now().timestamp_millis())
        .unwrap()
        .unwrap();
    assert!(LocalPluginToolHostV2::new(&state, &conversation, &run)
        .await
        .unwrap()
        .is_none());
    let captured = RunAuthorization::capture(
        auth,
        Some(Arc::new(
            state
                .platform_plugin_authority_v2
                .acquire_generation()
                .unwrap(),
        )),
        &conversation,
        &run.message_id,
        Some(&run.id),
    )
    .unwrap();
    agent_access::scope(Some(captured), async {
        let host = Arc::new(
            LocalPluginToolHostV2::new(&state, &conversation, &run)
                .await
                .unwrap()
                .unwrap(),
        );
        let names = host.list_tools();
        assert_eq!(names.len(), 1);
        assert!(host.call(&names[0], r#"{"input":"direct"}"#).await.is_err());
        let wrapped = AuthorizedRunToolHost::with_dynamic_metadata(
            host.clone(),
            state.session_store.clone(),
            run.clone(),
            host.metadata(),
        );
        let output: Value =
            serde_json::from_str(&wrapped.call(&names[0], r#"{"input":"中"}"#).await.unwrap())
                .unwrap();
        assert_eq!(output, json!({"score":20260914,"input_bytes":15}));
        let (status, result) = request(
            &state,
            "POST",
            &format!(
                "/api/v1/local-plugins/v2/installations/{}/revoke",
                reference["bundle_id"].as_str().unwrap()
            ),
            json!({"tenant_id":"local","project_id":"local-project","reference":reference}),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{result}");
        assert!(host.list_tools().is_empty());
        assert!(wrapped
            .call(&names[0], r#"{"input":"after revoke"}"#)
            .await
            .is_err());
    })
    .await;
    let (status, list) = request(
        &state,
        "GET",
        "/api/v1/local-plugins/v2/installations?tenant_id=local&project_id=local-project",
        Value::Null,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{list}");
    assert_eq!(list["installations"][0]["authorization_status"], "revoked");
    let (status, _) = request(
        &state,
        "POST",
        &format!(
            "/api/v1/local-plugins/v2/installations/{}/enable",
            reference["bundle_id"].as_str().unwrap()
        ),
        json!({"tenant_id":"local","project_id":"local-project","reference":reference}),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn local_import_scope_permissions_signature_and_execution_preflight_fail_closed() {
    let (state, bytes) = setup().await;
    let base =
        json!({"tenant_id":"local","project_id":"other","archive_base64":STANDARD.encode(&bytes)});
    assert_eq!(
        request(
            &state,
            "POST",
            "/api/v1/local-plugins/v2/installations/inspect",
            base
        )
        .await
        .0,
        StatusCode::FORBIDDEN
    );
    let preview=request(&state,"POST","/api/v1/local-plugins/v2/installations/inspect",json!({"tenant_id":"local","project_id":"local-project","archive_base64":STANDARD.encode(&bytes)})).await.1;
    let payload = json!({"tenant_id":"local","project_id":"local-project","archive_base64":STANDARD.encode(&bytes),"reference":preview["reference"],"approved_permissions":[]});
    assert_eq!(
        request(
            &state,
            "POST",
            "/api/v1/local-plugins/v2/installations/import",
            payload.clone()
        )
        .await
        .0,
        StatusCode::UNPROCESSABLE_ENTITY
    );
    let mut forged = payload;
    forged["public_keys_pem"] = json!(["untrusted"]);
    assert_eq!(
        request(
            &state,
            "POST",
            "/api/v1/local-plugins/v2/installations/import",
            forged
        )
        .await
        .0,
        StatusCode::UNPROCESSABLE_ENTITY
    );
    let list = request(
        &state,
        "GET",
        "/api/v1/local-plugins/v2/installations?tenant_id=local&project_id=local-project",
        Value::Null,
    )
    .await
    .1;
    assert_eq!(list["installations"], json!([]));
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn local_disabled_uninstalled_and_expired_session_invalidate_retained_real_tools() {
    for action in ["disable", "uninstall", "signout"] {
        let (state, bytes) = setup().await;
        let reference = import(&state, &bytes).await;
        let (conversation, run) = run(&state).await;
        let auth = state
            .session_store
            .validate_session_credential(TOKEN, chrono::Utc::now().timestamp_millis())
            .unwrap()
            .unwrap();
        let capture = RunAuthorization::capture(
            auth,
            Some(Arc::new(
                state
                    .platform_plugin_authority_v2
                    .acquire_generation()
                    .unwrap(),
            )),
            &conversation,
            &run.message_id,
            Some(&run.id),
        )
        .unwrap();
        agent_access::scope(Some(capture), async {
            let host = Arc::new(
                LocalPluginToolHostV2::new(&state, &conversation, &run)
                    .await
                    .unwrap()
                    .unwrap(),
            );
            let names = host.list_tools();
            assert_eq!(names.len(), 1);
            let wrapped = AuthorizedRunToolHost::with_dynamic_metadata(
                host.clone(),
                state.session_store.clone(),
                run.clone(),
                host.metadata(),
            );
            assert!(wrapped
                .call(&names[0], r#"{"input":"before"}"#)
                .await
                .is_ok());
            if action == "signout" {
                state
                    .session_store
                    .revoke_session(TOKEN, chrono::Utc::now().timestamp_millis())
                    .unwrap();
            } else {
                let (status, result) = request(
                    &state,
                    "POST",
                    &format!(
                        "/api/v1/local-plugins/v2/installations/{}/{action}",
                        reference["bundle_id"].as_str().unwrap()
                    ),
                    json!({"tenant_id":"local","project_id":"local-project","reference":reference}),
                )
                .await;
                assert_eq!(status, StatusCode::OK, "{result}");
            }
            assert!(host.list_tools().is_empty());
            assert!(wrapped
                .call(&names[0], r#"{"input":"after"}"#)
                .await
                .is_err());
        })
        .await;
        if action == "disable" {
            let (status, result) = request(
                &state,
                "POST",
                &format!(
                    "/api/v1/local-plugins/v2/installations/{}/enable",
                    reference["bundle_id"].as_str().unwrap()
                ),
                json!({"tenant_id":"local","project_id":"local-project","reference":reference}),
            )
            .await;
            assert_eq!(status, StatusCode::OK, "{result}");
        }
        state.platform_plugin_authority_v2.deactivate().await;
    }
}

#[tokio::test]
async fn damaged_local_archive_cannot_replace_the_last_good_generation() {
    let (state, bytes) = setup().await;
    import(&state, &bytes).await;
    let previous = state
        .platform_plugin_authority_v2
        .acquire_generation()
        .unwrap()
        .descriptor()
        .clone();
    state
        .session_store
        .connection()
        .unwrap()
        .execute(
            "UPDATE desktop_local_plugin_installations_v2 SET archive=x'00'",
            [],
        )
        .unwrap();
    let mut reconciler = desktop_reconciler(&state);
    assert!(
        activate_authority_source(&state, &mut reconciler, &DesktopAuthoritySourceV2::Local)
            .await
            .is_err()
    );
    assert_eq!(
        state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap()
            .descriptor(),
        &previous
    );
    let (conversation, run) = run(&state).await;
    let auth = state
        .session_store
        .validate_session_credential(TOKEN, chrono::Utc::now().timestamp_millis())
        .unwrap()
        .unwrap();
    let capture = RunAuthorization::capture(
        auth,
        Some(Arc::new(
            state
                .platform_plugin_authority_v2
                .acquire_generation()
                .unwrap(),
        )),
        &conversation,
        &run.message_id,
        Some(&run.id),
    )
    .unwrap();
    agent_access::scope(Some(capture), async {
        assert!(LocalPluginToolHostV2::new(&state, &conversation, &run)
            .await
            .unwrap()
            .unwrap()
            .list_tools()
            .is_empty());
    })
    .await;
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn valid_signatures_do_not_bypass_real_wasm_preflight_or_route_body_limits() {
    for wasm in ["(module (func (export \"score\") (param i64) (result i32) i32.const 1))", "(module (import \"env\" \"host\" (func)) (func (export \"score\") (param i32) (result i32) i32.const 1))"] {
        let (state,bytes)=setup_wasm(wasm).await;
        let payload=json!({"tenant_id":"local","project_id":"local-project","archive_base64":STANDARD.encode(&bytes)});
        let (status,preview)=request(&state,"POST","/api/v1/local-plugins/v2/installations/inspect",payload.clone()).await;
        assert_eq!(status,StatusCode::OK,"{preview}");
        let mut payload=payload; payload["reference"]=preview["reference"].clone();payload["approved_permissions"]=preview["declared_permissions"].clone();
        let (status,result)=request(&state,"POST","/api/v1/local-plugins/v2/installations/import",payload).await;
        assert_eq!(status,StatusCode::UNPROCESSABLE_ENTITY,"{result}");
        assert_eq!(result["code"],"local_plugin_activation_failed");
        let connection=state.session_store.connection().unwrap();
        assert_eq!(crate::local_plugin_installations_v2::revision(&connection).unwrap(),0);
        drop(connection);
        state.platform_plugin_authority_v2.deactivate().await;
    }
    let (state, _) = setup().await;
    let large = json!({"tenant_id":"local","project_id":"local-project","archive_base64":STANDARD.encode(vec![0u8;3*1024*1024])});
    assert_eq!(
        request(
            &state,
            "POST",
            "/api/v1/local-plugins/v2/installations/inspect",
            large.clone()
        )
        .await
        .0,
        StatusCode::UNPROCESSABLE_ENTITY
    );
    assert_eq!(
        request(
            &state,
            "POST",
            "/api/v1/local-plugins/v2/installations/example/disable",
            large
        )
        .await
        .0,
        StatusCode::PAYLOAD_TOO_LARGE
    );
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
#[ignore = "explicit local QA artifact export; output directory must be supplied"]
async fn export_verified_local_wasm_qa_fixture() {
    let output = std::path::PathBuf::from(
        std::env::var_os("AGISTACK_LOCAL_WASM_FIXTURE_OUTPUT")
            .expect("explicit artifact directory"),
    );
    let (archive, _, bytes, key, pem) = fixture::signed_fixture_with_bytes(MARKER, |_| {});
    let mut state = local_runtime::tests::test_state(TOKEN);
    Arc::get_mut(&mut state).unwrap().local_plugin_signing_keys = Ok(vec![key]);
    let mut reconciler = desktop_reconciler(&state);
    activate_authority_source(&state, &mut reconciler, &DesktopAuthoritySourceV2::Local)
        .await
        .unwrap();
    let reference = import(&state, &bytes).await;
    let (conversation, run) = run(&state).await;
    let auth = state
        .session_store
        .validate_session_credential(TOKEN, chrono::Utc::now().timestamp_millis())
        .unwrap()
        .unwrap();
    let capture = RunAuthorization::capture(
        auth,
        Some(Arc::new(
            state
                .platform_plugin_authority_v2
                .acquire_generation()
                .unwrap(),
        )),
        &conversation,
        &run.message_id,
        Some(&run.id),
    )
    .unwrap();
    let (tool_name, result) = agent_access::scope(Some(capture), async {
        let host = Arc::new(
            LocalPluginToolHostV2::new(&state, &conversation, &run)
                .await
                .unwrap()
                .unwrap(),
        );
        let name = host.list_tools().into_iter().next().unwrap();
        let wrapped = AuthorizedRunToolHost::with_dynamic_metadata(
            host.clone(),
            state.session_store.clone(),
            run.clone(),
            host.metadata(),
        );
        let result: Value =
            serde_json::from_str(&wrapped.call(&name, r#"{"input":"中"}"#).await.unwrap()).unwrap();
        assert_eq!(result, json!({"score":20260914,"input_bytes":15}));
        (name, result)
    })
    .await;
    state.platform_plugin_authority_v2.deactivate().await;
    std::fs::create_dir_all(&output).unwrap();
    std::fs::write(output.join("marker.mspkg"), &bytes).unwrap();
    std::fs::write(output.join("signer-public.pem"), &pem).unwrap();
    std::fs::write(
        output.join("trust.json"),
        serde_json::to_vec_pretty(&json!({"schema_version":1,"public_keys_pem":[pem]})).unwrap(),
    )
    .unwrap();
    std::fs::write(output.join("metadata.json"),serde_json::to_vec_pretty(&json!({
        "reference":reference,"artifact_digest":archive.manifest().artifacts[0].digest,
        "target":"desktop-sidecar","entrypoint":"score","abi":"memstack.wasm.score-json-utf8.v1",
        "tool_name":"qa_marketplace_marker","model_tool_name_for_test_scope":tool_name,
        "test_scope":{"tenant_id":"local","project_id":"local-project"},"permissions":["tools.execute"],
        "verified_result":result,"archive_bytes":bytes.len(),"private_key_persisted":false,
        "validation":"Actual signed archive -> authenticated local import -> production generation -> AuthorizedRunToolHost -> Wasmtime"
    })).unwrap()).unwrap();
}

#[tokio::test]
async fn local_first_boot_external_failure_keeps_management_recoverable_without_exposure() {
    for damage in ["archive", "trust_removed", "trust_config_invalid"] {
        let (mut state, bytes) = setup().await;
        let reference = import(&state, &bytes).await;
        let list = request(
            &state,
            "GET",
            "/api/v1/local-plugins/v2/installations?tenant_id=local&project_id=local-project",
            Value::Null,
        )
        .await
        .1;
        assert_eq!(list["installations"][0]["activation_status"], "active");
        state.platform_plugin_authority_v2.deactivate().await;
        match damage {
            "archive" => {
                state
                    .session_store
                    .connection()
                    .unwrap()
                    .execute(
                        "UPDATE desktop_local_plugin_installations_v2 SET archive=x'00'",
                        [],
                    )
                    .unwrap();
            }
            "trust_removed" => {
                Arc::get_mut(&mut state).unwrap().local_plugin_signing_keys = Ok(vec![])
            }
            _ => {
                Arc::get_mut(&mut state).unwrap().local_plugin_signing_keys =
                    Err("local signing trust file unavailable".into())
            }
        }
        let mut reconciler = desktop_reconciler(&state);
        activate_authority_source(&state, &mut reconciler, &DesktopAuthoritySourceV2::Local)
            .await
            .unwrap();
        let (status, list) = request(
            &state,
            "GET",
            "/api/v1/local-plugins/v2/installations?tenant_id=local&project_id=local-project",
            Value::Null,
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{list}");
        assert_eq!(list["installations"][0]["activation_status"], "failed");
        assert!(list["installations"][0]["activation_error"]
            .as_str()
            .is_some_and(|value| !value.is_empty()));
        assert!(state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap()
            .plugin_availability("qa-marketplace-marker", "local", "local-project")
            .is_err());
        let (status, result) = request(
            &state,
            "POST",
            &format!(
                "/api/v1/local-plugins/v2/installations/{}/uninstall",
                reference["bundle_id"].as_str().unwrap()
            ),
            json!({"tenant_id":"local","project_id":"local-project","reference":reference}),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{result}");
        activate_authority_source(&state, &mut reconciler, &DesktopAuthoritySourceV2::Local)
            .await
            .unwrap();
        assert!(state
            .local_plugin_activation_error
            .lock()
            .unwrap()
            .is_none());
        let list = request(
            &state,
            "GET",
            "/api/v1/local-plugins/v2/installations?tenant_id=local&project_id=local-project",
            Value::Null,
        )
        .await
        .1;
        assert_eq!(list["installations"], json!([]));
        state.platform_plugin_authority_v2.deactivate().await;
    }
}

#[tokio::test]
async fn aborted_operation_releases_its_real_signed_generation_lease() {
    use agistack_plugin_host::protocol_v2::{
        wasm_runtime::{
            WasmOperationAuthorityV2, WasmOperationV2, WasmToolAttributionV2, WasmToolSetV2,
            WASM_TOOL_SET_SERVICE_V2,
        },
        GenerationManagerV2, ScopeKindV2, ScopeV2,
    };
    use local_runtime::local_plugin_tool_host_v2::OperationReleaseGuardV2;
    struct PendingAuthority(Arc<tokio::sync::Notify>);
    #[async_trait::async_trait]
    impl WasmOperationAuthorityV2 for PendingAuthority {
        async fn authorize(
            &self,
            _operation: &WasmOperationV2,
            _tool: &WasmToolAttributionV2,
        ) -> bool {
            self.0.notify_one();
            std::future::pending().await
        }
    }
    let (archive, snapshot) = fixture::signed_fixture(MARKER, |_| {});
    let generation = LoaderV2::for_target(DataPlaneTargetV2::DesktopSidecar, [])
        .with_verified_archives(vec![archive])
        .stage(snapshot)
        .await
        .unwrap();
    let manager = GenerationManagerV2::new();
    manager.publish(generation.clone()).await;
    let scope = ScopeV2 {
        kind: ScopeKindV2::Root,
        tenant_id: None,
        project_id: None,
        session_id: None,
    };
    let set = generation
        .resolve::<WasmToolSetV2>(WASM_TOOL_SET_SERVICE_V2, &scope, None)
        .unwrap();
    let entered = Arc::new(tokio::sync::Notify::new());
    let authority = Arc::new(PendingAuthority(entered.clone()));
    let lease = manager.acquire().unwrap();
    let (sender, receiver) = tokio::sync::oneshot::channel();
    let operation_set = set.clone();
    let operation_scope = scope.clone();
    let worker = tokio::spawn(async move {
        let operation = OperationReleaseGuardV2::new(WasmOperationV2::new(
            lease,
            operation_scope,
            "aborted-operation".into(),
            Some(authority),
        ));
        sender.send(Arc::clone(&operation)).ok().unwrap();
        // A real staged ToolSet is waiting for permission; cancellation must not leak its lease.
        operation_set.prepare(&operation).await
    });
    let escaped = receiver.await.unwrap();
    entered.notified().await;
    manager.close().await;
    assert!(generation
        .resolve::<WasmToolSetV2>(WASM_TOOL_SET_SERVICE_V2, &scope, None)
        .is_ok());
    worker.abort();
    assert!(worker.await.err().unwrap().is_cancelled());
    tokio::time::timeout(Duration::from_secs(2), async {
        while generation
            .resolve::<WasmToolSetV2>(WASM_TOOL_SET_SERVICE_V2, &scope, None)
            .is_ok()
        {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("abort must release the lease and dispose the retired generation");
    assert!(set.prepare(&escaped).await.is_empty());
}

#[path = "local_plugin_operation_v2_tests.rs"]
mod operation_authority_tests;
#[path = "local_plugin_continuation_v2_tests.rs"]
mod continuation_authority_tests;
#[path = "local_plugin_timeline_v2_tests.rs"]
mod timeline_metadata_tests;
#[path = "local_skill_discovery_v2_tests.rs"]
mod skill_discovery_tests;
#[path = "local_execution_selection_patch_tests.rs"]
mod selection_patch_tests;
