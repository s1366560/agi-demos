use std::time::Duration;

use futures_util::{stream, StreamExt};

async fn configure_provider(
    app: &Router,
    provider: &str,
    base: &str,
    model: &str,
    timeout: Option<u64>,
    revision: u64,
) -> Value {
    let mut body = json!({
        "provider_type":"openai_compatible", "base_url":base, "auth_method":"none",
        "llm_model":model, "allowed_models":[model], "is_active":true,
        "expected_revision":revision,
    });
    if let Some(timeout) = timeout {
        body["request_timeout_ms"] = json!(timeout);
    }
    let response = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            &format!("/api/v1/llm-providers/{provider}"),
            "request-timeout",
            body,
        ))
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    response_json(response).await
}

fn policy(model: &str, fallbacks: Value) -> Value {
    json!({
        "roles": {"default":{"provider_id":"local-runtime","model_id":model},
            "fast":null,"coding":null,"vision":null},
        "fallbacks":fallbacks,
    })
}

async fn delayed_http() -> (String, Arc<Mutex<Vec<String>>>, tokio::task::JoinHandle<()>) {
    let calls = Arc::new(Mutex::new(Vec::new()));
    let app = Router::new().route(
        "/v1/chat/completions",
        post({
            let calls = calls.clone();
            move |Json(body): Json<Value>| {
                let calls = calls.clone();
                async move {
                    let model = body["model"].as_str().unwrap().to_string();
                    calls.lock().unwrap().push(model.clone());
                    let delay = if model == "fast" { 1 } else { 200 };
                    let sse = body["stream"] == true;
                    let partial = model == "partial" && sse;
                    let first = partial.then(|| {
                        format!("data: {}\n\n", json!({"choices":[{"delta":{"content":"{\"kind\":\"finish\",\"answer\":\"visible prefix"}}]}))
                    });
                    let response = if sse {
                        let content = if partial {
                            " continued\"}".to_string()
                        } else {
                            json!({"kind":"finish","answer":model}).to_string()
                        };
                        format!("data: {}\n\ndata: [DONE]\n\n", json!({"choices":[{"delta":{"content":content}}]}))
                    } else {
                        json!({"choices":[{"message":{"content":json!({"kind":"finish","answer":model}).to_string()}}]}).to_string()
                    };
                    let chunks = stream::iter(first.into_iter().map(Ok::<_, std::io::Error>))
                        .chain(stream::once(async move {
                            tokio::time::sleep(Duration::from_millis(delay)).await;
                            Ok::<_, std::io::Error>(response)
                        }));
                    axum::response::Response::builder()
                        .header("content-type", if sse { "text/event-stream" } else { "application/json" })
                        .body(Body::from_stream(chunks))
                        .unwrap()
                }
            }
        }),
    );
    let listener = TcpListener::bind(("127.0.0.1", 0)).await.unwrap();
    let base = format!("http://{}/v1", listener.local_addr().unwrap());
    let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    (base, calls, server)
}

#[tokio::test]
async fn provider_create_applies_default_and_explicit_timeout_before_persistence() {
    let state = test_state("request-timeout");
    let app = local_router(state.clone());
    for timeout in [None, Some(120_000), Some(300_001)] {
        let mut body = json!({
            "name":"Timeout connection", "provider_type":"openai_compatible",
            "base_url":"http://127.0.0.1:9/v1", "auth_method":"none",
            "llm_model":"slow", "allowed_models":["slow"], "is_active":true,
        });
        if let Some(timeout) = timeout {
            body["request_timeout_ms"] = json!(timeout);
        }
        let response = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/api/v1/llm-providers/",
                "request-timeout",
                body,
            ))
            .await
            .unwrap();
        if timeout == Some(300_001) {
            assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
            continue;
        }
        assert_eq!(response.status(), StatusCode::OK);
        let created = response_json(response).await;
        let expected = timeout.unwrap_or(45_000);
        assert_eq!(created["request_timeout_ms"], expected);
        let stored = state
            .session_store
            .managed_resource(
                ManagedResourceKind::Provider,
                "tenant",
                "local",
                created["id"].as_str().unwrap(),
            )
            .unwrap()
            .unwrap();
        assert_eq!(stored["request_timeout_ms"], expected);
    }
}

#[tokio::test]
async fn provider_timeout_crud_preserves_default_revision_and_rejects_invalid_boundaries() {
    let state = test_state("request-timeout");
    let app = local_router(state.clone());
    let initial = configure_provider(
        &app,
        "local-runtime",
        "http://127.0.0.1:9/v1",
        "slow",
        None,
        0,
    )
    .await;
    assert_eq!(initial["request_timeout_ms"], 45_000);
    assert_eq!(
        llm_request_timeout::duration(&json!({})).unwrap(),
        Duration::from_secs(45)
    );
    let changed = configure_provider(
        &app,
        "local-runtime",
        "http://127.0.0.1:9/v1",
        "slow",
        Some(120_000),
        1,
    )
    .await;
    assert_eq!(changed["request_timeout_ms"], 120_000);
    let omitted = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/local-runtime",
            "request-timeout",
            json!({"name":"Updated name","expected_revision":2}),
        ))
        .await
        .unwrap();
    assert_eq!(omitted.status(), StatusCode::OK);
    assert_eq!(response_json(omitted).await["request_timeout_ms"], 120_000);
    for invalid in [
        json!(0),
        json!(300_001),
        json!(-1),
        json!(1.5),
        json!("120000"),
        Value::Null,
    ] {
        let response = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "request-timeout",
                json!({"request_timeout_ms":invalid,"expected_revision":3}),
            ))
            .await
            .unwrap();
        assert_eq!(
            response.status(),
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid value {invalid}"
        );
    }
    let stale = app
        .clone()
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/local-runtime",
            "request-timeout",
            json!({"request_timeout_ms":1,"expected_revision":2}),
        ))
        .await
        .unwrap();
    assert_eq!(stale.status(), StatusCode::CONFLICT);
    let stored = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            "local",
            "local-runtime",
        )
        .unwrap()
        .unwrap();
    assert_eq!(stored["revision"], 3);
    assert_eq!(stored["request_timeout_ms"], 120_000);
    assert_eq!(
        runtime_binding_from_provider(&stored)
            .unwrap()
            .request_timeout,
        Duration::from_secs(120)
    );
    for (revision, timeout) in [(3, 1), (4, 300_000)] {
        let changed = configure_provider(
            &app,
            "local-runtime",
            "http://127.0.0.1:9/v1",
            "slow",
            Some(timeout),
            revision,
        )
        .await;
        assert_eq!(changed["request_timeout_ms"], timeout);
    }
    let listed = app
        .oneshot(
            Request::builder()
                .uri("/api/v1/llm-providers/?include_inactive=true")
                .header("authorization", "Bearer request-timeout")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(listed.status(), StatusCode::OK);
    assert!(response_json(listed)
        .await
        .as_array()
        .unwrap()
        .iter()
        .any(|p| p["id"] == "local-runtime" && p["request_timeout_ms"] == 300_000));
}

#[tokio::test]
async fn configured_deadline_bounds_both_workspace_and_explicit_routes_over_real_http() {
    let (base, calls, server) = delayed_http().await;
    let state = test_state("request-timeout");
    state.mock_llm_enabled.store(0, Ordering::Release);
    let app = local_router(state.clone());
    configure_provider(&app, "local-runtime", &base, "slow", Some(40), 0).await;
    seed_plan_conversation(&state, "timeout-conversation");
    state
        .session_store
        .update_conversation_llm_route(
            "timeout-conversation",
            Some(&LlmRouteTarget {
                provider_id: "local-runtime".into(),
                model_id: "slow".into(),
            }),
            &now_iso(),
        )
        .unwrap();
    let conversation = state
        .session_store
        .conversation("timeout-conversation")
        .unwrap()
        .unwrap();
    for explicit in [false, true] {
        let llm = if explicit {
            state
                .llm_for_role(&conversation, LlmWorkloadRole::Default)
                .await
                .unwrap()
        } else {
            state.llm_for_policy(
                "local",
                &policy("slow", json!([])),
                LlmWorkloadRole::Default,
            )
        };
        let result =
            tokio::time::timeout(Duration::from_secs(2), llm.decide("finish", 0, &[], &[]))
                .await
                .unwrap();
        assert!(result.unwrap_err().to_string().contains("model_timeout"));
    }
    configure_provider(&app, "local-runtime", &base, "slow", Some(120_000), 1).await;
    for explicit in [false, true] {
        let llm = if explicit {
            state
                .llm_for_role(&conversation, LlmWorkloadRole::Default)
                .await
                .unwrap()
        } else {
            state.llm_for_policy(
                "local",
                &policy("slow", json!([])),
                LlmWorkloadRole::Default,
            )
        };
        let result = tokio::time::timeout(
            Duration::from_secs(2),
            llm.decide_with_tools_stream("finish", 0, &[], &[], &|_| {}),
        )
        .await
        .unwrap()
        .unwrap();
        assert!(matches!(result, AgentAction::Finish { answer } if answer=="slow"));
    }
    assert_eq!(calls.lock().unwrap().len(), 4);
    let provider = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            "local",
            "local-runtime",
        )
        .unwrap()
        .unwrap();
    assert_eq!(provider["health_status"], "not_checked");
    server.abort();
}

#[tokio::test]
async fn provider_deadlines_preserve_fallback_order_without_joining_partial_streams() {
    let (base, calls, server) = delayed_http().await;
    let state = test_state("request-timeout");
    let app = local_router(state.clone());
    configure_provider(&app, "local-runtime", &base, "slow", Some(40), 0).await;
    let created = app.clone().oneshot(authenticated_json_request(
        "POST", "/api/v1/llm-providers/", "request-timeout",
        json!({"name":"Fallback","provider_type":"openai_compatible","base_url":base,"auth_method":"none",
            "llm_model":"fast","allowed_models":["fast"],"is_active":true,"request_timeout_ms":500}),
    )).await.unwrap();
    assert_eq!(created.status(), StatusCode::OK);
    let fallback = response_json(created).await["id"]
        .as_str()
        .unwrap()
        .to_string();
    let fallbacks = json!([{"provider_id":fallback,"model_id":"fast"}]);
    let llm = state.llm_for_policy(
        "local",
        &policy("slow", fallbacks.clone()),
        LlmWorkloadRole::Default,
    );
    let answer = llm
        .decide_with_tools_stream("finish", 0, &[], &[], &|_| {})
        .await
        .unwrap();
    assert!(matches!(answer, AgentAction::Finish { answer } if answer=="fast"));
    assert_eq!(*calls.lock().unwrap(), ["slow", "fast"]);
    calls.lock().unwrap().clear();
    configure_provider(&app, "local-runtime", &base, "partial", Some(40), 1).await;
    let text = Mutex::new(String::new());
    let llm = state.llm_for_policy(
        "local",
        &policy("partial", fallbacks),
        LlmWorkloadRole::Default,
    );
    let result = llm
        .decide_with_tools_stream("finish", 0, &[], &[], &|delta| {
            text.lock().unwrap().push_str(delta)
        })
        .await;
    assert!(result.unwrap_err().to_string().contains("model_timeout"));
    assert_eq!(*text.lock().unwrap(), "visible prefix");
    assert_eq!(*calls.lock().unwrap(), ["partial"]);
    server.abort();
}
