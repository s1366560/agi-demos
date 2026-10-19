//! User Stop fences the cloud run across fresh requests, sessions, and connections.
use super::*;
use std::time::Duration;

fn fresh_call(fixture: &Fixture) -> Value {
    {
        let mut claim = fixture.authority.claim.lock().unwrap();
        claim["request_id"] = json!("fresh-request");
        claim["session_id"] = json!("replacement-engine");
        claim["round"] = json!(99);
    }
    let mut input = fixture.input("call");
    input["request_id"] = json!("fresh-request");
    input
}

async fn stop(fixture: &Fixture, id: &str, all: bool) {
    api::operation(
        &fixture.state,
        &fixture.owner(),
        serde_json::from_value(json!({
            "action":if all {"stop_all"} else {"stop"}, "session_id":id
        }))
        .unwrap(),
    )
    .await
    .unwrap();
}

#[tokio::test]
async fn explicit_cloud_stop_rejects_fresh_requests_after_reconnect_but_allows_a_new_run() {
    for source in ["session", "all", "menu"] {
        let (fixture, helper, session) = paused_fixture().await;
        if source == "menu" {
            helper
                .client
                .request(
                    "fixture_native_status",
                    json!({
                        "context":session.context, "phase":"stopped",
                        "updated_at":chrono::Utc::now().timestamp(),
                        "user_initiated":true, "user_action":"stop"
                    }),
                )
                .await
                .unwrap();
            tokio::time::timeout(Duration::from_secs(3), async {
                while fixture
                    .state
                    .computer_use
                    .helper_closing
                    .load(Ordering::SeqCst)
                    || !fixture
                        .state
                        .computer_use
                        .sessions_for(&fixture.owner())
                        .is_empty()
                {
                    tokio::time::sleep(Duration::from_millis(10)).await;
                }
            })
            .await
            .unwrap();
        } else {
            stop(&fixture, &session.context.session_id, source == "all").await;
        }
        assert!(session.stopped.load(Ordering::SeqCst));
        assert!(cloud::resume_available(&fixture.state, &session).is_err());
        let before = helper.requests().len();
        let mut input = fresh_call(&fixture);
        fixture.authority.release.add_permits(1);
        let result = cloud::operation(&fixture.state, &fixture.broker, input.clone())
            .await
            .unwrap();
        assert_stopped(&result);
        assert_eq!(helper.requests().len(), before);
        fixture.operation("close").await.unwrap();
        let mut describe = fixture.input("describe");
        describe["connection_id"] = json!("replacement-connection");
        cloud::operation(&fixture.state, &fixture.broker, describe)
            .await
            .unwrap();
        input["connection_id"] = json!("replacement-connection");
        // Simulate losing only in-memory state: the persisted Stop still fences this run.
        fixture
            .state
            .computer_use
            .stopped_cloud_runs
            .lock()
            .unwrap()
            .clear();
        fixture.authority.release.add_permits(1);
        assert_stopped(
            &cloud::operation(&fixture.state, &fixture.broker, input.clone())
                .await
                .unwrap(),
        );
        assert_eq!(helper.requests().len(), before);
        {
            let db = fixture.state.session_store.connection().unwrap();
            let mut other = fixture.owner();
            other.user_id = "other-user".into();
            assert!(denials::ensure(&db, &other, "approved-run").is_ok());
        }
        {
            let mut claim = fixture.authority.claim.lock().unwrap();
            claim["run_id"] = json!("new-approved-run");
            claim["request_id"] = json!("new-run-request");
        }
        input["request_id"] = json!("new-run-request");
        fixture.authority.release.add_permits(1);
        let output = cloud::operation(&fixture.state, &fixture.broker, input)
            .await
            .unwrap();
        let result: Value = serde_json::from_str(output["output_json"].as_str().unwrap()).unwrap();
        assert_eq!(result["error"], "cua_permission_required");
        assert!(helper.requests().len() > before);
        fixture.state.computer_use.shutdown(&fixture.state).await;
        helper.client.shutdown().await;
    }
}

#[tokio::test]
async fn user_stop_fences_a_fresh_claim_already_waiting_on_the_authority_server() {
    let (fixture, helper, session) = paused_fixture().await;
    let input = fresh_call(&fixture);
    let entered = fixture.authority.entered.available_permits();
    let state = fixture.state.clone();
    let broker = fixture.broker.clone();
    let call = tokio::spawn(async move { cloud::operation(&state, &broker, input).await });
    tokio::time::timeout(Duration::from_secs(3), async {
        while fixture.authority.entered.available_permits() == entered {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap();
    stop(&fixture, &session.context.session_id, false).await;
    let before = helper.requests().len();
    fixture.authority.release.add_permits(1);
    assert_stopped(&call.await.unwrap().unwrap());
    assert_eq!(helper.requests().len(), before);
    assert!(fixture
        .state
        .computer_use
        .sessions_for(&fixture.owner())
        .is_empty());
    helper.client.shutdown().await;
}

#[tokio::test]
async fn user_stop_still_fences_native_execution_when_its_persistence_fails() {
    let (fixture, helper, session) = paused_fixture().await;
    fixture
        .state
        .session_store
        .connection()
        .unwrap()
        .execute_batch(
            "CREATE TRIGGER reject_fixture_stop BEFORE INSERT ON desktop_cua_user_stops_v2
             BEGIN SELECT RAISE(ABORT, 'fixture write failure'); END;",
        )
        .unwrap();
    let result = api::operation(
        &fixture.state,
        &fixture.owner(),
        serde_json::from_value(json!({
            "action":"stop", "session_id":session.context.session_id
        }))
        .unwrap(),
    )
    .await;
    assert!(result.is_err());
    assert!(session.stopped.load(Ordering::SeqCst));
    assert!(fixture
        .state
        .computer_use
        .sessions_for(&fixture.owner())
        .is_empty());
    let before = helper.requests().len();
    let input = fresh_call(&fixture);
    fixture.authority.release.add_permits(1);
    assert_stopped(
        &cloud::operation(&fixture.state, &fixture.broker, input)
            .await
            .unwrap(),
    );
    assert_eq!(helper.requests().len(), before);
    helper.client.shutdown().await;
}

fn assert_stopped(result: &Value) {
    assert_eq!(result["control_outcome"], "user_stopped");
    assert_eq!(result["is_error"], false);
    assert_eq!(result["media"], json!([]));
    assert!(result.get("control_generation").is_none());
    let output: Value = serde_json::from_str(result["output_json"].as_str().unwrap()).unwrap();
    assert_eq!(
        output,
        json!({"type":"computer_use_control","status":"user_stopped","retry_allowed":false})
    );
}
