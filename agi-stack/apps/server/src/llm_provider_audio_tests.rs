use super::*;

#[test]
fn audio_input_provider_crud_is_exact_default_closed_and_revision_bound() {
    let create = || {
        serde_json::from_value::<ProviderCreateRequest>(json!({
            "name":"fixture", "provider_type":"openai", "base_url":"https://api.openai.com/v1",
            "api_key":"fixture-key", "llm_model":"opaque-model"
        }))
        .unwrap()
    };
    let record = provider_record_from_create_for_dev(create()).unwrap();
    assert!(provider_response_from_record(record.clone(), None)
        .audio_input_models
        .is_empty());
    let mut request = create();
    request.audio_input_models = Some(vec!["opaque-model".into()]);
    let mut record = provider_record_from_create_for_dev(request).unwrap();
    let response = provider_response_from_record(record.clone(), None);
    assert_eq!(response.audio_input_models, vec!["opaque-model"]);
    let revision = response.revision;
    let update = |value: Value| serde_json::from_value::<ProviderUpdateRequest>(value).unwrap();
    let stale = provider_update_record_with_auth(
        &record,
        update(json!({
            "expected_revision": revision - 1, "audio_input_models": []
        })),
    )
    .unwrap_err();
    assert_eq!(stale.status, StatusCode::CONFLICT);
    for invalid in [
        json!({"expected_revision":revision,"llm_model":"other"}),
        json!({"expected_revision":revision,"blocked_models":["opaque-model"]}),
        json!({"expected_revision":revision,"audio_input_models":["gpt-4o-audio-preview"]}),
        json!({"expected_revision":revision,"audio_input_models":["*"]}),
    ] {
        assert!(provider_update_record_with_auth(&record, update(invalid)).is_err());
    }
    let updated = provider_update_record_with_auth(
        &record,
        update(json!({
            "expected_revision":revision, "llm_model":"other", "allowed_models":["opaque-model"],
            "config":{"temperature":0.3}
        })),
    )
    .unwrap();
    apply_update_to_dev_record(&mut record, updated);
    let response = provider_response_from_record(record.clone(), None);
    assert_eq!(response.audio_input_models, vec!["opaque-model"]);
    assert!(response.revision > revision);
    let updated = provider_update_record_with_auth(
        &record,
        update(json!({
            "expected_revision":response.revision, "audio_input_models":[]
        })),
    )
    .unwrap();
    apply_update_to_dev_record(&mut record, updated);
    assert!(provider_response_from_record(record, None)
        .audio_input_models
        .is_empty());
}

#[test]
fn audio_input_provider_protocol_and_nested_declaration_cannot_bypass_validation() {
    for input in [
        json!({"provider_type":"anthropic","llm_model":"audio","audio_input_models":["audio"]}),
        json!({"provider_type":"openai","llm_model":"audio","audio_input_models":["other"]}),
        json!({"provider_type":"openai","llm_model":"audio","config":{"audio_input_models":["audio"]}}),
    ] {
        let mut input = input;
        input["name"] = json!("fixture");
        input["api_key"] = json!("fixture-key");
        let request = serde_json::from_value::<ProviderCreateRequest>(input).unwrap();
        assert!(provider_create_record_with_auth(request).is_err());
    }
    let request = serde_json::from_value::<ProviderProbeRequest>(json!({
        "name":"fixture", "provider_type":"openai", "api_key":"fixture-key",
        "llm_model":"audio", "audio_input_models":["other"]
    }))
    .unwrap();
    assert!(ProviderProbeConfig::from_probe_request_with(request, &|_| None).is_err());
}
