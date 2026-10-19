//! Explicit control outcomes and authenticated, generation-bound native receipts.
use super::*;

async fn paused_call(fixture: &Fixture, id: &str, round: u64) -> Value {
    {
        let mut claim = fixture.authority.claim.lock().unwrap();
        claim["request_id"] = json!(id);
        claim["round"] = json!(round);
    }
    let mut input = fixture.input("call");
    input["request_id"] = json!(id);
    fixture.authority.release.add_permits(1);
    cloud::operation(&fixture.state, &fixture.broker, input)
        .await
        .unwrap()
}

#[tokio::test]
async fn pause_returns_normal_control_without_native_dispatch_and_only_successful_resume_notifies()
{
    let (fixture, helper, session) = paused_fixture().await;
    let before = helper
        .requests()
        .iter()
        .filter(|r| r["method"] == "get_app_state")
        .count();
    let result = paused_call(&fixture, "paused-call", 6).await;
    assert_eq!(result["control_outcome"], "user_paused");
    assert_eq!(result["is_error"], false);
    assert_eq!(result["media"], json!([]));
    let generation = result["control_generation"].as_str().unwrap();
    Uuid::parse_str(generation).unwrap();
    let output: Value = serde_json::from_str(result["output_json"].as_str().unwrap()).unwrap();
    assert_eq!(
        output,
        json!({"type":"computer_use_control","status":"user_paused","retry_allowed":false})
    );
    assert_eq!(
        before,
        helper
            .requests()
            .iter()
            .filter(|r| r["method"] == "get_app_state")
            .count()
    );
    assert_eq!(
        fixture.operation("control_events").await.unwrap()["events"],
        json!([])
    );
    fixture.authority.resume_release.add_permits(1);
    presentation::pause_resume(
        &fixture.state,
        &fixture.owner(),
        &session.context.session_id,
        true,
    )
    .await
    .unwrap();
    let events = fixture.operation("control_events").await.unwrap()["events"].clone();
    assert_eq!(
        events,
        json!([{"request_id":"paused-call","session_id":"engine-session","control_generation":generation,"state":"resumed"}])
    );
    assert_eq!(
        fixture.operation("control_events").await.unwrap()["events"],
        events
    );
    let mut foreign = fixture.input("control_events");
    foreign["connection_id"] = json!("unknown");
    assert!(cloud::operation(&fixture.state, &fixture.broker, foreign)
        .await
        .is_err());
    fixture.operation("close").await.unwrap();
    assert!(fixture.operation("control_events").await.is_err());
    helper.client.shutdown().await;
}

#[tokio::test]
async fn stop_retains_pending_generation_notification_after_native_session_removed() {
    let (fixture, helper, session) = paused_fixture().await;
    let result = paused_call(&fixture, "stopped-paused-call", 6).await;
    fixture
        .state
        .computer_use
        .user_stop(
            &fixture.state,
            &fixture.owner(),
            Some(&session.context.session_id),
        )
        .await
        .unwrap();
    let events = fixture.operation("control_events").await.unwrap();
    assert_eq!(events["events"][0]["state"], "stopped");
    assert_eq!(
        events["events"][0]["control_generation"],
        result["control_generation"]
    );
    assert_eq!(events["events"][0]["request_id"], "stopped-paused-call");
    assert!(fixture
        .state
        .computer_use
        .sessions_for(&fixture.owner())
        .is_empty());
    fixture.operation("close").await.unwrap();
    helper.client.shutdown().await;
}

#[test]
fn generation_retains_early_resume_but_new_pause_cannot_be_woken_by_old_receipt() {
    let control = user_control::Control::default();
    let first = control.pause();
    assert_eq!(control.pause(), first);
    control.resume();
    assert_eq!(control.completed(&first), Some("resumed"));
    // Resume may finish between the caller's paused atomic read and snapshot.
    assert_eq!(
        control.outcome(true).unwrap().control_generation.as_deref(),
        Some(first.as_str())
    );
    let second = control.pause();
    assert_ne!(first, second);
    assert_eq!(control.completed(&second), None);
    assert_eq!(control.completed("foreign"), None);
    control.stop();
    control.resume();
    assert_eq!(control.completed(&second), Some("stopped"));
    assert_eq!(
        control.outcome(true).unwrap().control_outcome,
        Some(agistack_core::ports::ToolControlOutcome::UserStopped)
    );
}

#[tokio::test]
async fn in_flight_native_interrupt_is_normal_only_with_explicit_user_control() {
    for (kind, controlled, revoked) in [
        ("user_stopped_session", true, false),
        ("focus_denied", false, false),
        ("user_stopped_session", false, true),
    ] {
        let (fixture, helper, session) = paused_fixture().await;
        fixture.authority.resume_release.add_permits(1);
        presentation::pause_resume(
            &fixture.state,
            &fixture.owner(),
            &session.context.session_id,
            true,
        )
        .await
        .unwrap();
        std::fs::write(helper.root.join("hold_method"), "get_app_state").unwrap();
        std::fs::write(helper.root.join("error_kind"), kind).unwrap();
        {
            let mut claim = fixture.authority.claim.lock().unwrap();
            claim["request_id"] = json!("inflight");
            claim["round"] = json!(10);
        }
        let mut input = fixture.input("call");
        input["request_id"] = json!("inflight");
        fixture.authority.release.add_permits(1);
        let state = fixture.state.clone();
        let broker = fixture.broker.clone();
        let call = tokio::spawn(async move { cloud::operation(&state, &broker, input).await });
        tokio::time::timeout(std::time::Duration::from_secs(2), async {
            while !helper.root.join("entered_method").exists() {
                tokio::time::sleep(std::time::Duration::from_millis(5)).await;
            }
        })
        .await
        .unwrap();
        let state = fixture.state.clone();
        let owner = fixture.owner();
        let id = session.context.session_id.clone();
        let pause =
            tokio::spawn(
                async move { presentation::pause_resume(&state, &owner, &id, false).await },
            );
        tokio::time::timeout(std::time::Duration::from_secs(2), async {
            while !session.paused.load(Ordering::SeqCst) {
                tokio::time::sleep(std::time::Duration::from_millis(5)).await;
            }
        })
        .await
        .unwrap();
        if revoked {
            store::update(
                &fixture.state.session_store.connection().unwrap(),
                &fixture.owner(),
                session.revision,
                "disable",
                None,
            )
            .unwrap();
        }
        std::fs::write(helper.root.join("release_method"), "").unwrap();
        let result = call.await.unwrap();
        pause.await.unwrap().unwrap();
        if controlled {
            let result = result.unwrap();
            assert_eq!(result["control_outcome"], "user_paused");
            assert_eq!(result["is_error"], false);
            assert_eq!(result["media"], json!([]));
        } else {
            assert!(result.unwrap_err().contains(if revoked {
                "cua_authorization_revoked"
            } else {
                "focus_denied"
            }));
        }
        fixture.operation("close").await.unwrap();
        helper.client.shutdown().await;
    }
}

#[tokio::test]
async fn newer_pause_supersedes_native_resume_without_emitting_a_resume_receipt() {
    use std::future::Future;
    let (fixture, helper, session) = paused_fixture().await;
    let paused = paused_call(&fixture, "paused-again", 6).await;
    std::fs::write(helper.root.join("hold_method"), "resume_session").unwrap();
    fixture.authority.resume_release.add_permits(1);
    let state = fixture.state.clone();
    let owner = fixture.owner();
    let id = session.context.session_id.clone();
    let resume =
        tokio::spawn(async move { presentation::pause_resume(&state, &owner, &id, true).await });
    tokio::time::timeout(std::time::Duration::from_secs(2), async {
        while !helper.root.join("entered_method").exists() {
            tokio::time::sleep(std::time::Duration::from_millis(5)).await;
        }
    })
    .await
    .unwrap();
    let owner = fixture.owner();
    let mut pause = Box::pin(presentation::pause_resume(
        &fixture.state,
        &owner,
        &session.context.session_id,
        false,
    ));
    std::future::poll_fn(|context| {
        assert!(pause.as_mut().poll(context).is_pending());
        std::task::Poll::Ready(())
    })
    .await;
    std::fs::write(helper.root.join("release_method"), "").unwrap();
    assert_eq!(resume.await.unwrap().unwrap_err(), "cua_resume_superseded");
    pause.await.unwrap();
    assert!(session.paused.load(Ordering::SeqCst));
    assert_eq!(
        fixture.operation("control_events").await.unwrap()["events"],
        json!([])
    );
    assert_eq!(
        session
            .user_control
            .completed(paused["control_generation"].as_str().unwrap()),
        None
    );
    fixture.operation("close").await.unwrap();
    helper.client.shutdown().await;
}
