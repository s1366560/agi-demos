use agistack_core::agent::types::MediaAttachment;

#[tokio::test]
async fn audio_declaration_is_revision_bound_model_specific_and_reaches_real_http() {
    let captured = Arc::new(tokio::sync::Mutex::new(Vec::new()));
    let app = Router::new().route("/v1/chat/completions", post({
        let captured = captured.clone();
        move |Json(body): Json<Value>| { let captured = captured.clone(); async move {
            captured.lock().await.push(body);
            Json(json!({"choices":[{"message":{"content":r#"{"kind":"finish","answer":"audio accepted"}"#}}]}))
        }}
    }));
    let listener = TcpListener::bind(("127.0.0.1", 0)).await.unwrap();
    let base = format!("http://{}/v1", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    let state = test_state("audio-declaration");
    let app = local_router(state.clone());
    let response = app.clone().oneshot(authenticated_json_request("PUT","/api/v1/llm-providers/local-runtime","audio-declaration",json!({
        "provider_type":"openai_compatible","base_url":base,"auth_method":"none","is_active":true,
        "llm_model":"opaque-text","allowed_models":["opaque-text","opaque-audio"],"audio_input_models":["opaque-audio"],"expected_revision":0
    }))).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let provider = response_json(response).await;
    assert_eq!(provider["audio_input_models"], json!(["opaque-audio"]));
    assert_eq!(provider["revision"], 1);
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
    assert_eq!(stored["audio_input_models"], json!(["opaque-audio"]));
    let path = std::env::temp_dir().join(format!("memstack-audio-provider-{}.wav", Uuid::new_v4()));
    let mut wav = b"RIFF".to_vec();
    wav.extend_from_slice(&38u32.to_le_bytes());
    wav.extend_from_slice(b"WAVEfmt ");
    wav.extend_from_slice(&16u32.to_le_bytes());
    wav.extend_from_slice(&1u16.to_le_bytes());
    wav.extend_from_slice(&1u16.to_le_bytes());
    wav.extend_from_slice(&24000u32.to_le_bytes());
    wav.extend_from_slice(&48000u32.to_le_bytes());
    wav.extend_from_slice(&2u16.to_le_bytes());
    wav.extend_from_slice(&16u16.to_le_bytes());
    wav.extend_from_slice(b"data");
    wav.extend_from_slice(&2u32.to_le_bytes());
    wav.extend_from_slice(&[0, 0]);
    std::fs::write(&path, &wav).unwrap();
    let transcript = vec![
        TranscriptEntry::new(0, Role::Human, "listen").with_media(vec![MediaAttachment {
            artifact_path: path.to_string_lossy().into(),
            mime_type: "audio/wav".into(),
        }]),
    ];
    let mut binding = runtime_binding_from_provider(&stored).unwrap();
    assert!(llm_from_runtime_binding(binding.clone(), None)
        .unwrap()
        .decide("listen", 1, &transcript, &[])
        .await
        .unwrap_err()
        .to_string()
        .contains("audio_input_unsupported"));
    assert!(captured.lock().await.is_empty());
    binding.model = "opaque-audio".into();
    let result = llm_from_runtime_binding(binding, None)
        .unwrap()
        .decide("listen", 1, &transcript, &[])
        .await
        .unwrap();
    assert!(matches!(result,AgentAction::Finish{answer} if answer=="audio accepted"));
    let wire = captured.lock().await;
    assert_eq!(wire.len(), 1);
    assert_eq!(wire[0]["model"], "opaque-audio");
    assert_eq!(wire[0]["messages"][1]["content"][1]["type"], "input_audio");
    assert_eq!(
        wire[0]["messages"][1]["content"][1]["input_audio"]["format"],
        "wav"
    );
    drop(wire);
    for (payload, status) in [
        (
            json!({"audio_input_models":[],"expected_revision":0}),
            StatusCode::CONFLICT,
        ),
        (
            json!({"allowed_models":["opaque-text"],"expected_revision":1}),
            StatusCode::UNPROCESSABLE_ENTITY,
        ),
        (
            json!({"provider_type":"anthropic","expected_revision":1}),
            StatusCode::UNPROCESSABLE_ENTITY,
        ),
    ] {
        let response = app
            .clone()
            .oneshot(authenticated_json_request(
                "PUT",
                "/api/v1/llm-providers/local-runtime",
                "audio-declaration",
                payload,
            ))
            .await
            .unwrap();
        assert_eq!(response.status(), status);
    }
    let cleared = app
        .oneshot(authenticated_json_request(
            "PUT",
            "/api/v1/llm-providers/local-runtime",
            "audio-declaration",
            json!({"audio_input_models":[],"allowed_models":["opaque-text"],"expected_revision":1}),
        ))
        .await
        .unwrap();
    assert_eq!(cleared.status(), StatusCode::OK);
    assert_eq!(
        response_json(cleared).await["audio_input_models"],
        json!([])
    );
    std::fs::remove_file(path).unwrap();
    server.abort();
}

#[test]
fn audio_declaration_never_infers_support_from_model_name_and_catalog_stays_explicit() {
    let provider = json!({"provider_type":"openai_compatible","llm_model":"gpt-audio","allowed_models":["opaque-audio"]});
    assert!(provider_audio_declaration::models(&provider).is_empty());
    let mut declared = provider.clone();
    provider_audio_declaration::apply(&mut declared, Some(vec!["opaque-audio".into()])).unwrap();
    let outcome = ProviderProbeOutcome {
        status: "healthy",
        detail: "fixture",
        error_code: None,
        response_time_ms: 0,
        models: vec![provider_probe::DiscoveredModel {
            id: "gpt-audio".into(),
        }],
    };
    assert_eq!(
        provider_probe_catalog(
            "openai_compatible",
            Some("p"),
            &outcome,
            "fixture",
            Some(&provider)
        )["models"]["audio_input"],
        json!([])
    );
    let catalog = provider_probe_catalog(
        "openai_compatible",
        Some("p"),
        &outcome,
        "fixture",
        Some(&declared),
    );
    assert_eq!(catalog["models"]["audio_input"], json!(["opaque-audio"]));
    assert_eq!(catalog["source"], "provider-api+explicit-configuration");
    assert!(
        provider_audio_declaration::apply(&mut declared, Some(vec!["not-rostered".into()]))
            .is_err()
    );
}
