use super::*;

#[tokio::test]
async fn input_mode_and_generation_are_bound_and_background_never_falls_back() {
    let backend = Arc::new(MockBackend::default());
    let sessions = Sessions::new(backend.clone());
    let mut owner = context("background");
    owner["input_mode"] = json!("background");
    let bound = sessions.dispatch("begin_session", &owner).await.unwrap();
    let mut request = owner.clone();
    request["input_generation"] = bound["input_generation"].clone();
    request["app"] = json!("pid:101");
    request["window_id"] = json!("window:1");
    request["expected_identity_digest"] = json!(app().identity_digest);
    for method in ["activate_app", "launch_app", "perform_action"] {
        assert_eq!(
            sessions.dispatch(method, &request).await.unwrap_err().kind,
            "background_input_unsupported"
        );
    }
    assert_eq!(backend.calls.load(Ordering::SeqCst), 0);
    request["input_mode"] = json!("foreground");
    assert_eq!(
        sessions
            .dispatch("get_app_state", &request)
            .await
            .unwrap_err()
            .kind,
        "input_generation_mismatch"
    );
    request["input_mode"] = json!("background");
    request["input_generation"] = json!("old");
    assert_eq!(
        sessions
            .dispatch("get_app_state", &request)
            .await
            .unwrap_err()
            .kind,
        "input_generation_mismatch"
    );
    request["input_generation"] = bound["input_generation"].clone();
    sessions.dispatch("pause_session", &request).await.unwrap();
    let resumed = sessions.dispatch("resume_session", &request).await.unwrap();
    assert_ne!(resumed["input_generation"], bound["input_generation"]);
    assert_eq!(
        sessions
            .dispatch("get_app_state", &request)
            .await
            .unwrap_err()
            .kind,
        "input_generation_mismatch"
    );
    request["input_generation"] = resumed["input_generation"].clone();
    sessions.dispatch("end_session", &request).await.unwrap();
    let _ = std::fs::remove_dir(bound["artifact_root"].as_str().unwrap());
}
