use std::{convert::Infallible, sync::Arc};

use agistack_plugin_host::{
    desktop_sidecar_host_definition_v2, desktop_sidecar_http_routes_definition_v2,
    parse_profile_snapshot_v2, DataPlaneTargetV2, LoaderV2, RuntimeV2Error, ScopeKindV2, ScopeV2,
    TargetHostDescriptorV2, DESKTOP_SIDECAR_HOST_SERVICE_V2,
};
use axum::{
    body::{to_bytes, Body, Bytes},
    extract::Extension,
    http::{header::HeaderName, HeaderValue, Request, StatusCode},
    middleware,
    response::{IntoResponse, Response},
    routing::get,
    Json, Router,
};
use futures_util::{stream, StreamExt};
use serde_json::{json, Value};
use tower::ServiceExt;

use super::{
    local_router_with_generation_required,
    platform_plugin_authority_v2::ActivePlatformPluginGenerationLeaseV2,
    platform_plugin_route_admission_v2::{require_generation_v2, PlatformPluginRouteAdmissionV2},
    tests::{seed_plan_conversation, test_state},
    LocalRuntimeState,
};

const BOOTSTRAP: &str =
    include_str!("../../../../../../shared/profiles/memstack-default-bootstrap.v2.json");
const GENERATION_DIGEST: HeaderName = HeaderName::from_static("x-test-generation-digest");

#[tokio::test]
async fn automation_capabilities_report_the_admitted_generation_revision() {
    let credential = "automation-generation-test";
    let state = test_state(credential);
    for generation in [51, 52, 9_007_199_254_740_991, 9_007_199_254_740_992] {
        publish_generation(
            &state,
            "automation-capabilities",
            generation,
            &format!("{generation:064x}"),
        )
        .await;
        let response = local_router_with_generation_required(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .uri("/api/v1/projects/local-project/cron-jobs/capabilities")
                    .header("authorization", format!("Bearer {credential}"))
                    .header("x-agistack-launch", credential)
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        if generation > 9_007_199_254_740_991 {
            assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
            continue;
        }
        assert_eq!(response.status(), StatusCode::OK);
        let payload: Value =
            serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await.unwrap())
                .unwrap();
        assert_eq!(payload["schema_version"], 3);
        assert_eq!(payload["authority_revision"], generation);
        assert_eq!(payload["read"], true);
    }
    state.platform_plugin_authority_v2.deactivate().await;
}

async fn publish_generation(
    state: &LocalRuntimeState,
    profile_id: &str,
    generation_number: u64,
    digest: &str,
) -> Arc<agistack_plugin_host::RuntimeGenerationV2> {
    let mut snapshot = parse_profile_snapshot_v2(BOOTSTRAP).expect("bootstrap profile must parse");
    snapshot.profile_id = profile_id.to_owned();
    snapshot.generation = generation_number;
    snapshot.digest = digest.to_owned();
    let generation = LoaderV2::for_target(
        DataPlaneTargetV2::DesktopSidecar,
        [
            desktop_sidecar_http_routes_definition_v2(),
            desktop_sidecar_host_definition_v2(),
            super::computer_use_v2::definition()
                .expect("the built-in computer-use contract is statically valid"),
        ],
    )
    .stage(snapshot.clone())
    .await
    .expect("desktop generation must stage");
    state
        .platform_plugin_authority_v2
        .publish_local_baseline(
            &snapshot,
            &serde_json::to_value(&snapshot).expect("test snapshot must serialize"),
            Arc::clone(&generation),
        )
        .await;
    generation
}

fn admitted_router(state: Arc<LocalRuntimeState>) -> Router {
    Router::new()
        .route("/probe", get(generation_probe))
        .route("/stream", get(streaming_generation_probe))
        .layer(middleware::from_fn_with_state(
            PlatformPluginRouteAdmissionV2::required(Arc::clone(&state)),
            require_generation_v2,
        ))
        .with_state(state)
}

async fn generation_probe(
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
) -> Json<Value> {
    Json(json!({
        "digest": lease.descriptor().digest,
        "route_contribution_id": lease.http_routes().contribution_id,
        "route_strategy": lease.http_routes().strategy,
    }))
}

async fn streaming_generation_probe(
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
) -> Response {
    let body =
        stream::once(async { Ok::<Bytes, Infallible>(Bytes::from_static(b"generation-stream")) })
            .chain(stream::pending());
    let mut response = Body::from_stream(body).into_response();
    response.headers_mut().insert(
        GENERATION_DIGEST,
        HeaderValue::from_str(&lease.descriptor().digest).expect("digest header must be valid"),
    );
    response
}

#[tokio::test]
async fn required_admission_rejects_business_requests_without_a_v2_generation() {
    let state = test_state("generation-required-secret");
    let response = admitted_router(state)
        .oneshot(
            Request::builder()
                .uri("/probe")
                .body(Body::empty())
                .expect("request must build"),
        )
        .await
        .expect("router response");

    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    let payload: Value = serde_json::from_slice(
        &to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("error body"),
    )
    .expect("error JSON");
    assert_eq!(payload["error"]["code"], "plugin_generation_v2_unavailable");
    assert_eq!(payload["error"]["target"], "desktop-sidecar");
    assert_eq!(payload["error"]["generation"], Value::Null);
}

#[tokio::test]
async fn security_kernel_routes_remain_available_without_a_business_generation() {
    let state = test_state("kernel-route-secret");
    let app = local_router_with_generation_required(state);
    let auth = app
        .oneshot(
            Request::builder()
                .uri("/api/v1/auth/me")
                .header("authorization", "Bearer kernel-route-secret")
                .header("x-agistack-launch", "kernel-route-secret")
                .body(Body::empty())
                .expect("request must build"),
        )
        .await
        .expect("kernel response");

    assert_eq!(auth.status(), StatusCode::OK);
}

#[tokio::test]
async fn response_body_and_request_extension_pin_one_generation_across_a_swap() {
    let state = test_state("generation-body-secret");
    let old_generation = publish_generation(
        &state,
        "desktop-generation-old",
        41,
        "sha256:desktop-generation-old",
    )
    .await;
    let app = admitted_router(Arc::clone(&state));
    let old_response = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/stream")
                .body(Body::empty())
                .expect("request must build"),
        )
        .await
        .expect("old response");
    assert_eq!(
        old_response
            .headers()
            .get(&GENERATION_DIGEST)
            .and_then(|value| value.to_str().ok()),
        Some("sha256:desktop-generation-old")
    );

    let _new_generation = publish_generation(
        &state,
        "desktop-generation-new",
        42,
        "sha256:desktop-generation-new",
    )
    .await;
    let root_scope = ScopeV2 {
        kind: ScopeKindV2::Root,
        tenant_id: None,
        project_id: None,
        session_id: None,
    };
    assert!(old_generation
        .resolve_versioned::<TargetHostDescriptorV2>(
            DESKTOP_SIDECAR_HOST_SERVICE_V2,
            "1.0.0",
            &root_scope,
            None,
        )
        .is_ok());

    let new_response = app
        .oneshot(
            Request::builder()
                .uri("/probe")
                .body(Body::empty())
                .expect("request must build"),
        )
        .await
        .expect("new response");
    let new_payload: Value = serde_json::from_slice(
        &to_bytes(new_response.into_body(), usize::MAX)
            .await
            .expect("new response body"),
    )
    .expect("new response JSON");
    assert_eq!(new_payload["digest"], "sha256:desktop-generation-new");

    drop(old_response);
    tokio::time::timeout(std::time::Duration::from_secs(1), async {
        loop {
            if matches!(
                old_generation.resolve_versioned::<TargetHostDescriptorV2>(
                    DESKTOP_SIDECAR_HOST_SERVICE_V2,
                    "1.0.0",
                    &root_scope,
                    None,
                ),
                Err(RuntimeV2Error::GenerationDisposed)
            ) {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("old generation must dispose after response body drop");
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn derived_agent_operation_retains_and_records_the_request_generation() {
    let state = test_state("generation-operation-secret");
    let conversation_id = "generation-operation-conversation";
    seed_plan_conversation(&state, conversation_id);
    let _generation = publish_generation(
        &state,
        "desktop-operation-generation",
        51,
        "sha256:desktop-operation-generation",
    )
    .await;
    let lease = Arc::new(
        state
            .platform_plugin_authority_v2
            .acquire_generation()
            .expect("request generation must be available"),
    );
    state.platform_plugin_authority_v2.deactivate().await;

    Arc::clone(&state)
        .run_agent_message_on_generation(
            conversation_id.to_owned(),
            "local-project".to_owned(),
            "Run on the pinned generation".to_owned(),
            "generation-operation-message".to_owned(),
            None,
            None,
            Arc::clone(&lease),
        )
        .await;

    let timeline = state
        .session_store
        .timeline(conversation_id, 100)
        .expect("operation timeline");
    let user_message = timeline
        .iter()
        .find(|item| {
            item["type"] == "user_message" && item["message_id"] == "generation-operation-message"
        })
        .expect("pinned operation user message");
    assert_eq!(
        user_message["payload"]["plugin_generation"]["digest"],
        "sha256:desktop-operation-generation"
    );
    assert_eq!(
        user_message["payload"]["plugin_generation"]["generation"],
        51
    );
    assert_eq!(lease.descriptor().generation, 51);
    drop(lease);
}

#[tokio::test]
async fn hitl_continuation_keeps_original_generation_and_message_after_publication() {
    let credential = "hitl-generation-secret";
    let state = test_state(credential);
    let conversation_id = "hitl-generation-conversation";
    seed_plan_conversation(&state, conversation_id);
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let endpoint = Router::new().route(
        "/v1/chat/completions",
        axum::routing::post({
            let calls = calls.clone();
            move |Json(body): Json<Value>| {
                let index = calls.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                async move {
                    let action = if index == 0 {
                        json!({"kind":"request_human","request":{"id":"generation-hitl","kind":"clarification","prompt":"Which input?"}})
                    } else {
                        json!({"kind":"finish","answer":"resumed on original generation"})
                    };
                    if body["stream"] == true {
                        (
                            [("content-type", "text/event-stream")],
                            format!("data: {}\n\ndata: [DONE]\n\n", json!({"choices":[{"delta":{"content":action.to_string()}}]})),
                        ).into_response()
                    } else {
                        Json(json!({"choices":[{"message":{"content":action.to_string()}}]})).into_response()
                    }
                }
            }
        }),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move { axum::serve(listener, endpoint).await.unwrap() });
    *state.test_llm_override.lock().unwrap() = Some(Arc::new(
        agistack_adapters_http_llm::HttpLlm::new(format!("http://{address}/v1"), "test-model"),
    ));
    publish_generation(&state, "hitl-old", 61, "sha256:hitl-old").await;
    let lease = Arc::new(
        state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap(),
    );
    state
        .clone()
        .run_agent_message_on_generation(
            conversation_id.into(),
            "local-project".into(),
            "Clarify then finish".into(),
            "original-message".into(),
            None,
            None,
            lease,
        )
        .await;
    let pending = state
        .session_store
        .hitl_request("generation-hitl")
        .unwrap()
        .unwrap();
    assert_eq!(state.suspended_agent_operations_v2.lock().unwrap().len(), 1);
    publish_generation(&state, "hitl-new", 62, "sha256:hitl-new").await;
    // Unrelated request/run identities cannot acquire the held operation.
    let (_, unrelated) = state.continuation_operation_v2(
        conversation_id,
        "unrelated-message".into(),
        None,
        Some("unrelated-hitl"),
        None,
    );
    assert!(unrelated.is_none());
    let response = local_router_with_generation_required(state.clone()).oneshot(
        Request::builder()
            .method("POST").uri("/api/v1/agent/hitl/respond")
            .header("authorization", format!("Bearer {credential}"))
            .header("x-agistack-launch", credential)
            .header("content-type", "application/json")
            .body(Body::from(json!({"request_id":pending.id,"hitl_type":"clarification","response_data":{"answer":"Use saved input"},"expected_revision":pending.authority_revision,"idempotency_key":"same-operation-answer"}).to_string())).unwrap(),
    ).await.unwrap();
    let status = response.status();
    let body: Value =
        serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await.unwrap()).unwrap();
    assert_eq!(status, StatusCode::OK, "{body}");
    tokio::time::timeout(std::time::Duration::from_secs(10), async {
        loop {
            if !state
                .agent_runs
                .lock()
                .unwrap()
                .contains_key(conversation_id)
            {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    let timeline = state.session_store.timeline(conversation_id, 100).unwrap();
    let attempts: Vec<_> = timeline
        .iter()
        .filter(|event| event["type"] == "model_request_prepared")
        .collect();
    assert_eq!(attempts.len(), 2, "{timeline:?}");
    for attempt in attempts {
        assert_eq!(attempt["message_id"], "original-message");
        assert_eq!(attempt["data"]["generation_digest"], "sha256:hitl-old");
    }
    assert!(state
        .suspended_agent_operations_v2
        .lock()
        .unwrap()
        .is_empty());
    server.abort();
}
