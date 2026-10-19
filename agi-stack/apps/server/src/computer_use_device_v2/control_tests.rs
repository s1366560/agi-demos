use super::*;
use agistack_core::ports::ToolControlOutcome;
fn frame(id: &str, generation: &str, state: &str) -> super::super::control::Frame {
    super::super::control::Frame {
        request_id: id.into(),
        session_id: "engine-session".into(),
        control_generation: generation.into(),
        state: state.into(),
    }
}
#[tokio::test]
async fn paused_control_accepts_early_native_resume_and_never_replays_claim() {
    let (broker, _, mut receive) = fixture();
    let call = dispatch(&broker, 1, "computer_get_app_state", "{}");
    let wire = receive.recv().await.unwrap();
    let id = wire["request_id"].as_str().unwrap();
    broker.claim(id, "user", "device").unwrap();
    let generation = uuid::Uuid::new_v4().to_string();
    broker
        .receive_control_state("connection", frame(id, &generation, "resumed"))
        .await
        .unwrap();
    let result = ToolControlOutcome::UserPaused.result(Some(generation.clone()));
    broker
        .receive_control_result(
            "connection",
            id,
            result.output_json.clone(),
            false,
            vec![],
            result.control_outcome,
            result.control_generation.clone(),
        )
        .unwrap();
    assert_eq!(call.await.unwrap().unwrap(), result);
    assert_eq!(
        broker
            .wait_for_control(&owner(), "engine-session", &generation)
            .await
            .unwrap(),
        agistack_core::agent::react::ToolControlResolution::Resumed
    );
    broker
        .receive_control_state("connection", frame(id, &generation, "stopped"))
        .await
        .unwrap();
    broker
        .receive_control_state("connection", frame(id, &generation, "resumed"))
        .await
        .unwrap();
    assert_eq!(
        broker
            .wait_for_control(&owner(), "engine-session", &generation)
            .await
            .unwrap(),
        agistack_core::agent::react::ToolControlResolution::Stopped
    );
    assert!(receive.try_recv().is_err());
    assert!(broker.claim(id, "user", "device").is_err());
    let mut foreign = owner();
    foreign.user_id = "foreign".into();
    assert!(broker
        .wait_for_control(&foreign, "engine-session", &generation)
        .await
        .is_err());
    assert!(broker
        .receive_control_state("foreign", frame(id, &generation, "stopped"))
        .await
        .is_err());
    assert!(broker
        .receive_control_state(
            "connection",
            frame(id, &uuid::Uuid::new_v4().to_string(), "resumed")
        )
        .await
        .is_err());
    broker.cancel(id);
    assert!(broker
        .wait_for_control(&owner(), "engine-session", &generation)
        .await
        .is_err());
    assert!(broker
        .receive_control_state("connection", frame(id, &generation, "resumed"))
        .await
        .is_err());
}
#[tokio::test]
async fn control_marker_requires_exact_shape_no_media_and_live_parent() {
    let (broker, authority, mut receive) = fixture();
    let call = dispatch(&broker, 2, "computer_get_app_state", "{}");
    let wire = receive.recv().await.unwrap();
    let id = wire["request_id"].as_str().unwrap();
    broker.claim(id, "user", "device").unwrap();
    let generation = uuid::Uuid::new_v4().to_string();
    let result = ToolControlOutcome::UserPaused.result(Some(generation.clone()));
    for (output, error, generation) in [
        (result.output_json.clone(), true, Some(generation.clone())),
        ("{}".into(), false, Some(generation.clone())),
        (result.output_json.clone(), false, None),
    ] {
        assert!(broker
            .receive_control_result(
                "connection",
                id,
                output,
                error,
                vec![],
                Some(ToolControlOutcome::UserPaused),
                generation
            )
            .is_err());
    }
    broker
        .receive_control_result(
            "connection",
            id,
            result.output_json,
            false,
            vec![],
            Some(ToolControlOutcome::UserPaused),
            Some(generation.clone()),
        )
        .unwrap();
    call.await.unwrap().unwrap();
    authority
        .running
        .store(false, std::sync::atomic::Ordering::SeqCst);
    assert!(broker
        .receive_control_state("connection", frame(id, &generation, "resumed"))
        .await
        .is_err());
    assert!(broker
        .wait_for_control(&owner(), "engine-session", &generation)
        .await
        .is_err());
}
#[tokio::test]
async fn unmarked_lookalike_json_remains_an_ordinary_result() {
    let (broker, _, mut receive) = fixture();
    let call = dispatch(&broker, 3, "computer_get_app_state", "{}");
    let wire = receive.recv().await.unwrap();
    let id = wire["request_id"].as_str().unwrap();
    broker.claim(id, "user", "device").unwrap();
    let output = ToolControlOutcome::UserStopped.result(None).output_json;
    broker
        .receive_result("connection", id, output, false, vec![])
        .unwrap();
    assert_eq!(call.await.unwrap().unwrap().control_outcome, None);
}
