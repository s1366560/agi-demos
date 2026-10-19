//! Native IPC boundaries are held explicitly; no operating-system input is generated.
use super::*;
use std::time::Duration;

async fn wait_until(mut ready: impl FnMut() -> bool) {
    tokio::time::timeout(Duration::from_secs(3), async {
        while !ready() {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("fixture transition did not complete");
}

#[tokio::test]
async fn stop_during_native_reset_or_resume_cannot_recreate_resources_after_teardown() {
    for method in ["reset_session", "pause_session", "resume_session"] {
        let (fixture, helper, session) = if method == "resume_session" {
            paused_fixture().await
        } else {
            let fixture = paused_fixture_with_deadline(2).await;
            tokio::time::timeout(Duration::from_secs(3), async {
                while fixture
                    .1
                    .client
                    .session_artifact_root(&fixture.2.context.session_id)
                    .await
                    .is_some()
                {
                    tokio::time::sleep(Duration::from_millis(10)).await;
                }
            })
            .await
            .unwrap();
            fixture
        };
        std::fs::write(helper.root.join("hold_method"), method).unwrap();
        fixture.authority.resume_release.add_permits(1);
        let state = fixture.state.clone();
        let owner = fixture.owner();
        let id = session.context.session_id.clone();
        let resume =
            tokio::spawn(
                async move { presentation::pause_resume(&state, &owner, &id, true).await },
            );
        wait_until(|| helper.root.join("entered_method").exists()).await;
        let state = fixture.state.clone();
        let id = session.context.session_id.clone();
        let close = tokio::spawn(async move {
            state.computer_use.close_session(&state, &id).await;
        });
        wait_until(|| session.stopped.load(Ordering::SeqCst)).await;
        std::fs::write(helper.root.join("release_method"), "release").unwrap();
        assert!(resume.await.unwrap().is_err(), "{method}");
        close.await.unwrap();
        assert!(helper
            .client
            .session_artifact_root(&session.context.session_id)
            .await
            .is_none());
        assert_eq!(session.presentation.lock().unwrap()["phase"], "stopped");
        assert!(fixture
            .state
            .computer_use
            .sessions
            .lock()
            .unwrap()
            .is_empty());
        let requests = helper.requests();
        if method != "resume_session" {
            assert!(!requests
                .iter()
                .any(|request| request["method"] == "resume_session"));
        }
        let last_end = requests
            .iter()
            .rposition(|request| request["method"] == "end_session")
            .unwrap();
        assert!(!requests[last_end + 1..].iter().any(|request| matches!(
            request["method"].as_str(),
            Some("begin_session" | "reset_session" | "resume_session")
        )));
        assert!(requests.iter().all(|request| !matches!(
            request["method"].as_str(),
            Some("perform_action" | "audio_start")
        )));
        helper.client.shutdown().await;
    }
}

#[tokio::test]
async fn native_menu_stop_is_consumed_while_resume_http_response_is_pending() {
    let (fixture, helper, session) = paused_fixture().await;
    let notification = |phase: &str, action: &str| {
        json!({
            "context":session.context,
            "phase":phase,
            "updated_at":chrono::Utc::now().timestamp_millis() as f64 / 1000.0,
            "user_initiated":true,
            "user_action":action
        })
    };
    helper
        .client
        .request("fixture_native_status", notification("paused", "resume"))
        .await
        .unwrap();
    tokio::time::timeout(
        Duration::from_secs(3),
        fixture.authority.resume_entered.acquire(),
    )
    .await
    .unwrap()
    .unwrap()
    .forget();
    // The authority is deliberately blocked; a native Stop must still take effect.
    helper
        .client
        .request("fixture_native_status", notification("stopped", "stop"))
        .await
        .unwrap();
    wait_until(|| session.stopped.load(Ordering::SeqCst)).await;
    assert!(fixture
        .state
        .computer_use
        .sessions
        .lock()
        .unwrap()
        .is_empty());
    fixture.authority.resume_release.add_permits(1);
    wait_until(|| session.dispatch.try_lock().is_ok()).await;
    assert_eq!(session.presentation.lock().unwrap()["phase"], "stopped");
    assert!(!helper
        .requests()
        .iter()
        .any(|request| request["method"] == "resume_session"));
    helper.client.shutdown().await;
}

#[tokio::test]
async fn expired_pending_consent_stays_waiting_and_only_a_fresh_claim_rebuilds_resources() {
    let fixture = Fixture::new().await;
    let helper = super::super::super::management_lifecycle_tests::Helper::new(false);
    std::fs::write(helper.root.join("emit_stop_status"), "enabled").unwrap();
    assert!(fixture
        .state
        .computer_use
        .client
        .set(helper.client.clone())
        .is_ok());
    fixture.publish_factory(true).await;
    let owner = fixture.owner();
    store::update(
        &fixture.state.session_store.connection().unwrap(),
        &owner,
        0,
        "enable",
        None,
    )
    .unwrap();
    fixture.operation("describe").await.unwrap();
    fixture.authority.claim.lock().unwrap()["expires_at"] =
        json!(chrono::Utc::now().timestamp() + 2);
    fixture.authority.release.add_permits(1);
    let result = fixture.operation("call").await.unwrap();
    let output: Value = serde_json::from_str(result["output_json"].as_str().unwrap()).unwrap();
    let id = output["request"]["session_id"].as_str().unwrap().to_owned();
    let pending = output["request"]["request_id"].as_str().unwrap().to_owned();
    let session = fixture.state.computer_use.sessions.lock().unwrap()[&id].clone();
    let initial_updated = session.presentation.lock().unwrap()["updated_at"].clone();
    tokio::time::timeout(Duration::from_secs(4), async {
        while helper.client.session_artifact_root(&id).await.is_some() {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap();
    wait_until(|| session.presentation.lock().unwrap()["updated_at"] != initial_updated).await;
    assert_eq!(
        session.presentation.lock().unwrap()["phase"],
        "awaiting_permission"
    );
    assert_eq!(session.presentation.lock().unwrap()["can_resume"], false);
    assert!(!session.stopped.load(Ordering::SeqCst));
    assert_eq!(fixture.state.computer_use.pending_for(&owner).len(), 1);
    assert!(
        presentation::pause_resume(&fixture.state, &owner, &id, true)
            .await
            .is_err()
    );
    let before_grant = helper.requests().len();
    api::operation(
        &fixture.state,
        &owner,
        serde_json::from_value(json!({
            "action":"grant", "request_id":pending, "scope":"session"
        }))
        .unwrap(),
    )
    .await
    .unwrap();
    assert_eq!(
        helper.requests().len(),
        before_grant,
        "consent does not renew the expired invocation"
    );
    assert!(helper.client.session_artifact_root(&id).await.is_none());
    {
        let mut claim = fixture.authority.claim.lock().unwrap();
        claim["round"] = json!(5);
        claim["expires_at"] = json!(chrono::Utc::now().timestamp() + 30);
    }
    fixture.authority.release.add_permits(1);
    let resumed = fixture.operation("call").await.unwrap();
    assert!(
        serde_json::from_str::<Value>(resumed["output_json"].as_str().unwrap())
            .unwrap()
            .get("error")
            .is_none()
    );
    assert!(helper.client.session_artifact_root(&id).await.is_some());
    assert!(fixture.state.computer_use.pending_for(&owner).is_empty());
    assert_eq!(fixture.state.computer_use.sessions_for(&owner).len(), 1);
    assert_eq!(session.presentation.lock().unwrap()["phase"], "idle");
    assert!(helper.requests().iter().all(|request| !matches!(
        request["method"].as_str(),
        Some("resume_session" | "perform_action" | "audio_start")
    )));
    fixture.operation("cancel").await.unwrap();
    assert!(session.stopped.load(Ordering::SeqCst));
    assert!(fixture.state.computer_use.sessions_for(&owner).is_empty());
    assert_eq!(session.presentation.lock().unwrap()["phase"], "stopped");
    assert!(fixture.operation("call").await.is_err());
    assert!(helper.client.session_artifact_root(&id).await.is_none());
    helper.client.shutdown().await;
}
