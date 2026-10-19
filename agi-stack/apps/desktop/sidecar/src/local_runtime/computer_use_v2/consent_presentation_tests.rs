//! Granted retry records remain internal; presentation exposes only unanswered consent.
use super::*;

async fn pending_fixture() -> (
    Fixture,
    super::super::management_lifecycle_tests::Helper,
    Value,
) {
    let fixture = Fixture::new().await;
    let helper = super::super::management_lifecycle_tests::Helper::new(false);
    assert!(fixture
        .state
        .computer_use
        .client
        .set(helper.client.clone())
        .is_ok());
    fixture.publish_factory(true).await;
    store::update(
        &fixture.state.session_store.connection().unwrap(),
        &fixture.owner(),
        0,
        "enable",
        None,
    )
    .unwrap();
    fixture.operation("describe").await.unwrap();
    let output = call(&fixture, 4, json!({"app":"fixture"})).await;
    assert_eq!(output["error"], "cua_permission_required");
    assert_eq!(
        api::snapshot(&fixture.state, &fixture.owner()).unwrap()["pending"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    (fixture, helper, output["request"].clone())
}

async fn call(fixture: &Fixture, round: u64, input: Value) -> Value {
    {
        let mut claim = fixture.authority.claim.lock().unwrap();
        claim["round"] = json!(round);
        claim["input_json"] = json!(input.to_string());
    }
    fixture.authority.release.add_permits(1);
    let result = fixture.operation("call").await.unwrap();
    serde_json::from_str(result["output_json"].as_str().unwrap()).unwrap()
}

async fn grant(fixture: &Fixture, request: &Value, scope: &str) -> Value {
    api::operation(
        &fixture.state,
        &fixture.owner(),
        serde_json::from_value(json!({
            "action":"grant", "request_id":request["request_id"], "scope":scope
        }))
        .unwrap(),
    )
    .await
    .unwrap()
}

#[tokio::test]
async fn broad_grant_hides_pending_after_changed_arguments_and_while_paused() {
    for scope in ["session", "always"] {
        let (fixture, helper, request) = pending_fixture().await;
        assert_eq!(grant(&fixture, &request, scope).await["pending"], json!([]));
        let output = call(
            &fixture,
            5,
            json!({"app":"fixture", "window_id":"window-1"}),
        )
        .await;
        assert!(output.get("error").is_none());
        assert_eq!(
            fixture
                .state
                .computer_use
                .pending_for(&fixture.owner())
                .len(),
            1
        );
        let status = api::snapshot(&fixture.state, &fixture.owner()).unwrap();
        assert_eq!(status["pending"], json!([]));
        assert_eq!(status["sessions"][0]["presentation"]["phase"], "idle");
        presentation::pause_resume(
            &fixture.state,
            &fixture.owner(),
            request["session_id"].as_str().unwrap(),
            false,
        )
        .await
        .unwrap();
        let status = api::snapshot(&fixture.state, &fixture.owner()).unwrap();
        assert_eq!(status["pending"], json!([]));
        assert_eq!(status["sessions"][0]["presentation"]["phase"], "paused");
        fixture.operation("cancel").await.unwrap();
        helper.client.shutdown().await;
    }
}

#[tokio::test]
async fn pending_projection_neither_spends_once_nor_hides_a_different_request() {
    let (fixture, helper, request) = pending_fixture().await;
    assert_eq!(
        grant(&fixture, &request, "once").await["pending"],
        json!([])
    );
    for _ in 0..2 {
        let status = api::snapshot(&fixture.state, &fixture.owner()).unwrap();
        assert_eq!(status["pending"], json!([]));
        assert_eq!(status["grants"].as_array().unwrap().len(), 1);
    }
    let changed = call(
        &fixture,
        5,
        json!({"app":"fixture", "window_id":"window-1"}),
    )
    .await;
    assert_eq!(changed["error"], "cua_permission_required");
    assert_ne!(changed["request"]["request_id"], request["request_id"]);
    let status = api::snapshot(&fixture.state, &fixture.owner()).unwrap();
    assert_eq!(status["pending"].as_array().unwrap().len(), 1);
    assert_eq!(
        status["pending"][0]["request_id"],
        changed["request"]["request_id"]
    );
    assert!(call(&fixture, 6, json!({"app":"fixture"}))
        .await
        .get("error")
        .is_none());
    assert_eq!(
        api::snapshot(&fixture.state, &fixture.owner()).unwrap()["grants"],
        json!([])
    );
    let repeated = call(&fixture, 7, json!({"app":"fixture"})).await;
    assert_eq!(repeated["error"], "cua_permission_required");
    assert_ne!(repeated["request"]["request_id"], request["request_id"]);
    fixture.operation("cancel").await.unwrap();
    helper.client.shutdown().await;
}

#[tokio::test]
async fn pending_projection_requires_exact_identity_capability_and_grant_scope() {
    let (fixture, helper, request) = pending_fixture().await;
    grant(&fixture, &request, "once").await;
    let pending = fixture
        .state
        .computer_use
        .pending_for(&fixture.owner())
        .remove(0);
    let grant = store::grants(
        &fixture.state.session_store.connection().unwrap(),
        &fixture.owner(),
    )
    .unwrap()
    .remove(0);
    assert!(!consent::needs_approval(&pending, &[grant.clone()]));
    for field in [
        "app",
        "identity_digest",
        "capability",
        "session_id",
        "request_id",
    ] {
        let mut changed = json!(grant);
        changed[field] = json!("other");
        assert!(
            consent::needs_approval(&pending, &[serde_json::from_value(changed).unwrap()]),
            "{field}"
        );
    }
    let mut invalid_broad = grant;
    invalid_broad.scope = store::GrantScope::Always;
    invalid_broad.capability = "microphone".into();
    let mut audio = pending;
    audio.capability = "microphone".into();
    assert!(consent::needs_approval(&audio, &[invalid_broad]));
    fixture.operation("cancel").await.unwrap();
    helper.client.shutdown().await;
}
