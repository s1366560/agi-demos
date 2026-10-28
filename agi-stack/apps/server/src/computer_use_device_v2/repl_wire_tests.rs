use super::*;
use crate::auth::DevAuthenticator;
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
    middleware,
};
use tower::ServiceExt;

fn declared_definition(declared: bool) -> ToolDefinition {
    let mut schema = json!({"type":"object"});
    if declared {
        schema["x-agistack-display-kind"] = json!("repl_output");
    }
    ToolDefinition::new("cua_repl_js", "Fixture", schema)
}
fn media_output(mime: &str, size: usize) -> String {
    json!({"outputs":[{"type":"text","text":"before"},{"type":"text","text":"after"}],"artifacts":[{"kind":if mime.starts_with("image/") {"image"} else {"audio"},"artifact_id":"native_media","mime_type":mime,"size_bytes":size}],"output_order":[{"source":"text","index":0},{"source":"media","index":0},{"source":"text","index":1}]}).to_string()
}
fn payload(mime: &str, size: usize) -> Vec<u8> {
    let mut bytes = vec![0; size];
    match mime {
        "image/png" => bytes[..8].copy_from_slice(b"\x89PNG\r\n\x1a\n"),
        "audio/mpeg" => bytes[..3].copy_from_slice(b"ID3"),
        _ => {
            bytes[..4].copy_from_slice(b"RIFF");
            bytes[8..12].copy_from_slice(b"WAVE");
        }
    }
    bytes
}
async fn http_get(app: AppState, path: &str, authenticated: bool) -> axum::response::Response {
    let router = crate::computer_use_device_v2::router()
        .layer(middleware::from_fn_with_state(
            app.clone(),
            crate::auth::require_api_key,
        ))
        .with_state(app);
    let mut request = Request::builder().uri(path);
    if authenticated {
        request = request.header("Authorization", "Bearer ms_sk_fixture_owned_media");
    }
    router
        .oneshot(request.body(Body::empty()).unwrap())
        .await
        .unwrap()
}

#[tokio::test]
async fn registered_repl_wire_complete_display_and_authenticated_get_round_trip() {
    for (mime, size) in [
        ("image/png", 9 * 1024 * 1024),
        ("audio/mpeg", 32),
        ("audio/x-wav", 44),
    ] {
        let (broker, _, mut receive) = fixture();
        let own = Owner {
            user_id: "user".into(),
            tenant_id: "dev-tenant".into(),
            project_id: "dev-project".into(),
        };
        {
            let mut devices = broker.devices.lock().unwrap();
            let device = devices.get_mut("connection").unwrap();
            device.owner = own.clone();
            device.tools = vec![declared_definition(true)];
        }
        let mut app = crate::prod_api::unit::test_state();
        app.computer_use_devices = broker.clone();
        app.auth = Arc::new(DevAuthenticator::new("user"));
        let conversation = app
            .agent_conversations
            .create_conversation(
                "user",
                serde_json::from_value(json!({"project_id":"dev-project"})).unwrap(),
            )
            .await
            .unwrap();
        let cloned = broker.clone();
        let call_owner = own.clone();
        let conversation_id = serde_json::to_value(conversation).unwrap()["id"]
            .as_str()
            .unwrap()
            .to_owned();
        let call_conversation_id = conversation_id.clone();
        let call = tokio::spawn(async move {
            cloned
                .request(
                    &call_owner,
                    &call_conversation_id,
                    &run(),
                    &context(1, "cua_repl_js"),
                    "{}",
                )
                .await
        });
        let request = receive.recv().await.unwrap();
        let id = request["request_id"].as_str().unwrap();
        broker.claim(id, "user", "device").unwrap();
        let bytes = payload(mime, size);
        let output = media_output(mime, size);
        broker
            .receive_result(
                "connection",
                id,
                output.clone(),
                false,
                vec![broker::Descriptor {
                    artifact_id: "native_media".into(),
                    mime_type: mime.into(),
                    size_bytes: size as u64,
                }],
            )
            .unwrap();
        for (index, chunk) in bytes.chunks(128 * 1024).enumerate() {
            let offset = index * 128 * 1024;
            broker
                .receive_media(
                    "connection",
                    id,
                    "native_media",
                    mime,
                    offset as u64,
                    &STANDARD.encode(chunk),
                    offset + chunk.len() == bytes.len(),
                )
                .unwrap();
        }
        broker.complete(id).await.unwrap();
        let result = call.await.unwrap().unwrap();
        assert_eq!(result.media.len(), 1);
        let display = broker
            .current_tool_display(
                &own,
                &conversation_id,
                "engine-session",
                1,
                "cua_repl_js",
                "{}",
                &output,
            )
            .unwrap();
        let cloud_id = display["entries"][1]["artifactId"].as_str().unwrap();
        assert_ne!(cloud_id, "native_media");
        let path=format!("/api/v1/agent/conversations/{}/tool-media/{}?tenant_id=dev-tenant&project_id=dev-project",conversation_id,cloud_id);
        let response = http_get(app.clone(), &path, true).await;
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response.headers()["content-type"], mime);
        assert_eq!(response.headers()["content-length"], size.to_string());
        assert_eq!(response.headers()["cache-control"], "private, no-store");
        assert_eq!(response.headers()["x-content-type-options"], "nosniff");
        assert_eq!(
            to_bytes(response.into_body(), 10 * 1024 * 1024)
                .await
                .unwrap()
                .as_ref(),
            bytes.as_slice()
        );
        assert_eq!(
            http_get(app.clone(), &path, false).await.status(),
            StatusCode::UNAUTHORIZED
        );
        for (invalid, status) in [
            (
                path.replace("tenant_id=dev-tenant", "tenant_id=other"),
                StatusCode::FORBIDDEN,
            ),
            (
                path.replace("project_id=dev-project", "project_id=other"),
                StatusCode::FORBIDDEN,
            ),
            (
                path.replace(&conversation_id, "other"),
                StatusCode::NOT_FOUND,
            ),
            (
                path.replace(cloud_id, "native_media"),
                StatusCode::NOT_FOUND,
            ),
        ] {
            assert_eq!(http_get(app.clone(), &invalid, true).await.status(), status);
        }
        app.auth = Arc::new(DevAuthenticator::new("other-user"));
        assert_eq!(
            http_get(app, &path, true).await.status(),
            StatusCode::NOT_FOUND
        );
        let cache = broker.cache.lock().unwrap().take();
        if let Some(cache) = cache {
            std::fs::remove_dir_all(cache).unwrap();
        }
    }
}

#[tokio::test]
async fn fresh_wire_limits_and_media_count_are_scoped_to_declared_repl() {
    for declared in [false, true] {
        for (mime, size, count, allowed) in [
            ("image/png", 9 * 1024 * 1024, 1, declared),
            ("audio/mpeg", 32, 1, declared),
            ("audio/x-wav", 44, 1, declared),
            ("audio/wav", 10 * 1024 * 1024 + 1, 1, !declared),
            ("audio/wav", 8 * 1024 * 1024, 5, !declared),
            ("image/png", 32, 21, declared),
        ] {
            let (broker, _, mut receive) = fixture();
            broker
                .devices
                .lock()
                .unwrap()
                .get_mut("connection")
                .unwrap()
                .tools = vec![declared_definition(declared)];
            let call = dispatch(&broker, 1, "cua_repl_js", "{}");
            let frame = receive.recv().await.unwrap();
            let id = frame["request_id"].as_str().unwrap();
            broker.claim(id, "user", "device").unwrap();
            let descriptors = (0..count)
                .map(|index| broker::Descriptor {
                    artifact_id: format!("media_{index}"),
                    mime_type: mime.into(),
                    size_bytes: size,
                })
                .collect();
            assert_eq!(
                broker
                    .receive_result("connection", id, "{}".into(), false, descriptors)
                    .is_ok(),
                allowed,
                "{declared} {mime} {size} {count}"
            );
            assert!(broker
                .objects
                .as_ref()
                .unwrap()
                .list("")
                .await
                .unwrap()
                .is_empty());
            assert!(broker.cache.lock().unwrap().is_none());
            assert!(broker.requests.lock().unwrap()[id]
                .result
                .as_ref()
                .is_none_or(|result| result.media.is_empty()));
            call.abort();
        }
    }
}

#[tokio::test]
async fn legacy_received_oversized_repl_media_never_reaches_generic_store_cache_or_model() {
    let (broker, _, mut receive) = fixture();
    broker
        .devices
        .lock()
        .unwrap()
        .get_mut("connection")
        .unwrap()
        .tools = vec![declared_definition(true)];
    let call = dispatch(&broker, 1, "cua_repl_js", "{}");
    let frame = receive.recv().await.unwrap();
    let id = frame["request_id"].as_str().unwrap();
    broker.claim(id, "user", "device").unwrap();
    let size = 10 * 1024 * 1024 + 1;
    let output = media_output("audio/wav", size);
    // Model a receipt accepted by the former WAV transport limit before completion.
    {
        let mut requests = broker.requests.lock().unwrap();
        let request = requests.get_mut(id).unwrap();
        request.output = Some(output.clone());
        request.status = "saving";
        request.media = vec![broker::Artifact {
            descriptor: broker::Descriptor {
                artifact_id: "native_media".into(),
                mime_type: "audio/wav".into(),
                size_bytes: size as u64,
            },
            bytes: payload("audio/wav", size),
            complete: true,
        }];
    }
    broker.complete(id).await.unwrap();
    let result = call.await.unwrap().unwrap();
    assert!(result.media.is_empty());
    assert!(broker
        .objects
        .as_ref()
        .unwrap()
        .list("")
        .await
        .unwrap()
        .is_empty());
    assert!(broker.cache.lock().unwrap().is_none());
    let display = broker
        .current_tool_display(
            &owner(),
            "conversation",
            "engine-session",
            1,
            "cua_repl_js",
            "{}",
            &output,
        )
        .unwrap();
    assert_eq!(
        display["entries"][1],
        json!({"kind":"unavailable","reason":"media_size_limit"})
    );
    assert_eq!(display["entries"][2]["text"], "after");
}
