//! Real HTTP authority plus authenticated helper protocol, without operating-system access.
use super::*;

#[path = "cloud_resume_race_tests.rs"]
mod race_tests;
#[path = "cloud_stop_tests.rs"]
mod stop_tests;
#[path = "cloud_control_tests.rs"]
mod control_tests;

async fn paused_fixture() -> (
    Fixture,
    super::super::management_lifecycle_tests::Helper,
    Arc<Session>,
) {
    paused_fixture_with_deadline(60).await
}

async fn paused_fixture_with_deadline(
    seconds: i64,
) -> (
    Fixture,
    super::super::management_lifecycle_tests::Helper,
    Arc<Session>,
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
    fixture.operation("ready").await.unwrap();
    fixture.authority.release.add_permits(1);
    let output = fixture.operation("call").await.unwrap();
    let output: Value = serde_json::from_str(output["output_json"].as_str().unwrap()).unwrap();
    let native_id = output["request"]["session_id"].as_str().unwrap().to_owned();
    api::operation(
        &fixture.state,
        &fixture.owner(),
        serde_json::from_value(json!({
            "action":"grant", "request_id":output["request"]["request_id"], "scope":"session"
        }))
        .unwrap(),
    )
    .await
    .unwrap();
    fixture.authority.claim.lock().unwrap()["round"] = json!(5);
    fixture.authority.claim.lock().unwrap()["expires_at"] =
        json!(chrono::Utc::now().timestamp() + seconds);
    fixture.authority.release.add_permits(1);
    fixture.operation("call").await.unwrap();
    let session = fixture.state.computer_use.sessions.lock().unwrap()[&native_id].clone();
    presentation::pause_resume(&fixture.state, &fixture.owner(), &native_id, false)
        .await
        .unwrap();
    (fixture, helper, session)
}

#[tokio::test]
async fn explicit_cloud_resume_rebuilds_expired_native_resources_as_paused_before_resuming() {
    let (fixture, helper, session) = paused_fixture_with_deadline(2).await;
    tokio::time::sleep(std::time::Duration::from_secs(3)).await;
    assert!(helper
        .client
        .session_artifact_root(&session.context.session_id)
        .await
        .is_none());
    assert!(session.paused.load(Ordering::SeqCst));
    fixture.authority.resume_release.add_permits(1);
    presentation::pause_resume(
        &fixture.state,
        &fixture.owner(),
        &session.context.session_id,
        true,
    )
    .await
    .unwrap();
    assert!(!session.paused.load(Ordering::SeqCst));
    let methods: Vec<_> = helper
        .requests()
        .iter()
        .map(|r| r["method"].as_str().unwrap().to_owned())
        .collect();
    assert!(methods.ends_with(&[
        "begin_session".into(),
        "reset_session".into(),
        "pause_session".into(),
        "resume_session".into()
    ]));
    assert!(!methods
        .iter()
        .any(|method| method == "perform_action" || method == "audio_start"));
    fixture.operation("close").await.unwrap();
    helper.client.shutdown().await;
}

#[tokio::test]
async fn explicit_cloud_resume_checks_fresh_authority_and_never_replays_action_or_recording() {
    let (fixture, helper, session) = paused_fixture().await;
    assert_eq!(session.presentation.lock().unwrap()["can_resume"], true);
    assert_eq!(fixture.authority.resume_entered.available_permits(), 0);
    let before = helper.requests();
    fixture.authority.resume_release.add_permits(1);
    presentation::pause_resume(
        &fixture.state,
        &fixture.owner(),
        &session.context.session_id,
        true,
    )
    .await
    .unwrap();
    assert!(!session.paused.load(Ordering::SeqCst));
    assert_eq!(fixture.authority.resume_entered.available_permits(), 1);
    let after = helper.requests();
    assert_eq!(
        after
            .iter()
            .filter(|r| r["method"] == "get_app_state")
            .count(),
        before
            .iter()
            .filter(|r| r["method"] == "get_app_state")
            .count()
    );
    assert_eq!(
        after
            .iter()
            .filter(|r| r["method"] == "resume_session")
            .count(),
        1
    );
    assert!(!after
        .iter()
        .any(|r| r["method"] == "perform_action" || r["method"] == "audio_start"));
    assert!(CuaToolHost::new(helper.client.clone())
        .with_context(session.context.clone())
        .call(
            "computer_click",
            r#"{"app":"fixture","snapshot_id":"snapshot-round1","x":10,"y":20}"#
        )
        .await
        .is_err());
    fixture.operation("close").await.unwrap();
    helper.client.shutdown().await;
}

#[tokio::test]
async fn cloud_resume_rejects_every_foreign_binding_expiry_revision_and_server_denial() {
    let (fixture, helper, session) = paused_fixture().await;
    for (field, value) in [
        ("request_id", json!("other")),
        ("user_id", json!("other")),
        ("tenant_id", json!("other")),
        ("project_id", json!("other")),
        ("device_id", json!("other")),
        ("conversation_id", json!("other")),
        ("run_id", json!("other")),
        ("session_id", json!("other")),
        ("authorization_revision", json!(4)),
        ("expires_at", json!(0)),
        ("expires_at", json!(chrono::Utc::now().timestamp() + 3600)),
        ("denied", json!(true)),
    ] {
        let mut response = fixture.authority.claim.lock().unwrap().clone();
        response["expires_at"] = json!(chrono::Utc::now().timestamp() + 30);
        response[field] = value;
        *fixture.authority.resume_response.lock().unwrap() = Some(response);
        fixture.authority.resume_release.add_permits(1);
        assert!(
            presentation::pause_resume(
                &fixture.state,
                &fixture.owner(),
                &session.context.session_id,
                true
            )
            .await
            .is_err(),
            "{field}"
        );
        assert!(session.paused.load(Ordering::SeqCst));
    }
    assert!(!helper
        .requests()
        .iter()
        .any(|r| r["method"] == "resume_session"));
    fixture.operation("close").await.unwrap();
    helper.client.shutdown().await;
}

#[tokio::test]
async fn cloud_resume_cannot_finish_after_stop_disconnect_or_identity_switch() {
    for transition in ["stop", "close", "identity"] {
        let (fixture, helper, session) = paused_fixture().await;
        let state = fixture.state.clone();
        let owner = fixture.owner();
        let native_id = session.context.session_id.clone();
        let resume = tokio::spawn(async move {
            presentation::pause_resume(&state, &owner, &native_id, true).await
        });
        fixture
            .authority
            .resume_entered
            .acquire()
            .await
            .unwrap()
            .forget();
        match transition {
            "stop" => {
                fixture
                    .state
                    .computer_use
                    .close_session(&fixture.state, &session.context.session_id)
                    .await
            }
            "close" => {
                fixture.operation("close").await.unwrap();
            }
            _ => {
                fixture.broker.clear().unwrap();
            }
        }
        fixture.authority.resume_release.add_permits(1);
        assert!(resume.await.unwrap().is_err(), "{transition}");
        assert!(!helper
            .requests()
            .iter()
            .any(|r| r["method"] == "resume_session"));
        helper.client.shutdown().await;
    }
}

#[tokio::test]
async fn revoked_plugin_and_foreign_owner_cannot_request_cloud_resume() {
    let (fixture, helper, session) = paused_fixture().await;
    let mut foreign = fixture.owner();
    foreign.user_id = "other".into();
    assert!(presentation::pause_resume(
        &fixture.state,
        &foreign,
        &session.context.session_id,
        true
    )
    .await
    .is_err());
    fixture.publish_factory(false).await;
    assert!(presentation::pause_resume(
        &fixture.state,
        &fixture.owner(),
        &session.context.session_id,
        true
    )
    .await
    .is_err());
    assert_eq!(fixture.authority.resume_entered.available_permits(), 0);
    fixture.operation("close").await.unwrap();
    helper.client.shutdown().await;
}
