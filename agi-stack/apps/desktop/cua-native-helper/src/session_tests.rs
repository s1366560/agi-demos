use super::*;
use crate::backend::{Rect, Window};
use async_trait::async_trait;
use std::sync::atomic::AtomicUsize;
#[derive(Default)]
struct MockBackend {
    calls: AtomicUsize,
    releases: AtomicUsize,
    audio_stops: AtomicUsize,
    session_releases: AtomicUsize,
    audio_pending: Mutex<BTreeMap<String, PathBuf>>,
}
fn app() -> App {
    App::new(
        "pid:101".into(),
        "Fixture".into(),
        Some(101),
        Some(
            std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("src/main.rs")
                .to_string_lossy()
                .into_owned(),
        ),
    )
}
fn context(id: &str) -> Value {
    json!({"device_id":"device","user_id":"u","tenant_id":"t","project_id":"p","conversation_id":id,"run_id":id,"session_id":id})
}
fn params(id: &str) -> Value {
    let mut params = context(id);
    params["app"] = json!("pid:101");
    params["window_id"] = json!("window:1");
    params["expected_identity_digest"] = json!(app().identity_digest);
    params
}
#[async_trait]
impl Backend for MockBackend {
    async fn capabilities(&self) -> Value {
        json!({"capabilities":{}})
    }
    async fn apps(&self) -> Result<Vec<App>> {
        Ok(vec![app()])
    }
    async fn windows(&self, _: &App) -> Result<Vec<Window>> {
        Ok(vec![Window {
            window_id: "window:1".into(),
            app: "pid:101".into(),
            title: "Fixture".into(),
            bounds: Rect {
                x: 0.0,
                y: 0.0,
                width: 100.0,
                height: 100.0,
            },
            focused: true,
            modal: Some(false),
            window_type: Some("fixture:window".into()),
        }])
    }
    async fn observe(&self, _: &App, window: &Window, _: &std::path::Path) -> Result<Observation> {
        Ok(Observation {
            window: window.clone(),
            text: "[0] Fixture".into(),
            screenshot: None,
            native: json!({}),
        })
    }
    async fn audio_start(
        &self,
        id: &str,
        _: &str,
        root: &std::path::Path,
        _: Arc<AtomicBool>,
    ) -> Result<Value> {
        self.audio_pending
            .lock()
            .await
            .insert(id.into(), root.into());
        Ok(json!({"recording":true}))
    }
    async fn audio_status(&self, id: &str) -> Result<Value> {
        Ok(json!({"recording":self.audio_pending.lock().await.contains_key(id)}))
    }
    async fn audio_stop(&self, id: &str) -> Result<Value> {
        self.audio_stops.fetch_add(1, Ordering::SeqCst);
        if let Some(root) = self.audio_pending.lock().await.remove(id) {
            let path = root.join(format!("{id}.wav"));
            let format = [1, 0, 1, 0, 0x80, 0xbb, 0, 0, 0, 0x77, 1, 0, 2, 0, 16, 0];
            let mut wave = crate::wave::Wave::create(&path, &format)?;
            wave.append(&[1, 2, 3, 4])?;
            wave.finish()?;
            return Ok(
                json!({"artifact":{"url":url::Url::from_file_path(path).unwrap().as_str(),"mime_type":"audio/wav","source":"microphone"}}),
            );
        }
        Ok(json!({"state":"idle"}))
    }
    async fn release_session(&self, _: &str) {
        self.session_releases.fetch_add(1, Ordering::SeqCst);
    }
    async fn release(&self) {
        self.releases.fetch_add(1, Ordering::SeqCst);
    }
    async fn activate(&self, _: &Window) -> Result<()> {
        Ok(())
    }
    async fn locked(&self) -> Result<bool> {
        Ok(false)
    }
    async fn action(&self, _: &Observation, _: &Value, cancel: Arc<AtomicBool>) -> Result<()> {
        for _ in 0..50 {
            check_cancel(&cancel)?;
            tokio::time::sleep(std::time::Duration::from_millis(2)).await;
        }
        self.calls.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}
#[tokio::test]
async fn cancel_of_another_session_does_not_release_the_input_owner() {
    let backend = Arc::new(MockBackend::default());
    let sessions = Sessions::new(backend.clone());
    let first = sessions
        .dispatch("begin_session", &context("first"))
        .await
        .unwrap();
    let second = sessions
        .dispatch("begin_session", &context("second"))
        .await
        .unwrap();
    sessions
        .dispatch("get_app_state", &params("first"))
        .await
        .unwrap();
    sessions
        .dispatch("stop_session", &context("second"))
        .await
        .unwrap();
    assert_eq!(backend.releases.load(Ordering::SeqCst), 0);
    sessions
        .dispatch("stop_session", &context("first"))
        .await
        .unwrap();
    assert_eq!(backend.releases.load(Ordering::SeqCst), 1);
    let _ = std::fs::remove_dir(first["artifact_root"].as_str().unwrap());
    let _ = std::fs::remove_dir(second["artifact_root"].as_str().unwrap());
}
#[tokio::test]
async fn device_context_is_required_and_immutable() {
    let sessions = Sessions::new(Arc::new(MockBackend::default()));
    let mut invalid = context("one");
    invalid.as_object_mut().unwrap().remove("device_id");
    assert_eq!(
        sessions
            .dispatch("begin_session", &invalid)
            .await
            .unwrap_err()
            .kind,
        "invalid_params"
    );
    let root = sessions
        .dispatch("begin_session", &context("one"))
        .await
        .unwrap();
    let mut other = context("one");
    other["device_id"] = json!("different-device");
    assert_eq!(
        sessions
            .dispatch("begin_session", &other)
            .await
            .unwrap_err()
            .kind,
        "session_owner_mismatch"
    );
    let _ = std::fs::remove_dir(root["artifact_root"].as_str().unwrap());
}
#[tokio::test]
async fn reset_releases_owned_input_and_invalidates_the_old_observation() {
    let backend = Arc::new(MockBackend::default());
    let sessions = Sessions::new(backend.clone());
    let root = sessions
        .dispatch("begin_session", &context("reset"))
        .await
        .unwrap();
    let old = sessions
        .dispatch("get_app_state", &params("reset"))
        .await
        .unwrap();
    sessions
        .dispatch("reset_session", &context("reset"))
        .await
        .unwrap();
    assert_eq!(backend.releases.load(Ordering::SeqCst), 1);
    let mut action = params("reset");
    action["snapshot_id"] = old["snapshot_id"].clone();
    action["action"] = json!({"kind":"click","x":1,"y":1});
    action["expected_identity_digest"] = json!(app().identity_digest);
    assert_eq!(
        sessions
            .dispatch("perform_action", &action)
            .await
            .unwrap_err()
            .kind,
        "stale_element"
    );
    let fresh = sessions
        .dispatch("get_app_state", &params("reset"))
        .await
        .unwrap();
    assert_ne!(old["lease_epoch"], fresh["lease_epoch"]);
    action["snapshot_id"] = fresh["snapshot_id"].clone();
    sessions.dispatch("perform_action", &action).await.unwrap();
    assert_eq!(backend.calls.load(Ordering::SeqCst), 1);
    sessions
        .dispatch("end_session", &context("reset"))
        .await
        .unwrap();
    let _ = std::fs::remove_dir(root["artifact_root"].as_str().unwrap());
}
#[tokio::test]
async fn host_context_identity_and_global_desktop_lease_are_exact() {
    let sessions = Sessions::new(Arc::new(MockBackend::default()));
    let root = sessions
        .dispatch("begin_session", &context("one"))
        .await
        .unwrap()["artifact_root"]
        .as_str()
        .unwrap()
        .to_owned();
    let mut foreign = context("one");
    foreign["project_id"] = json!("foreign");
    assert_eq!(
        sessions
            .dispatch("begin_session", &foreign)
            .await
            .unwrap_err()
            .kind,
        "session_owner_mismatch"
    );
    sessions
        .dispatch("get_app_state", &params("one"))
        .await
        .unwrap();
    let second = sessions
        .dispatch("begin_session", &context("two"))
        .await
        .unwrap()["artifact_root"]
        .as_str()
        .unwrap()
        .to_owned();
    assert_eq!(
        sessions
            .dispatch("get_app_state", &params("two"))
            .await
            .unwrap_err()
            .kind,
        "desktop_busy"
    );
    sessions
        .dispatch("end_session", &context("one"))
        .await
        .unwrap();
    sessions
        .dispatch("get_app_state", &params("two"))
        .await
        .unwrap();
    let _ = std::fs::remove_dir(root);
    let _ = std::fs::remove_dir(second);
}
#[tokio::test]
async fn snapshots_and_application_identity_cannot_cross_sessions_or_replay() {
    let backend = Arc::new(MockBackend::default());
    let sessions = Sessions::new(backend.clone());
    let root = sessions
        .dispatch("begin_session", &context("one"))
        .await
        .unwrap()["artifact_root"]
        .as_str()
        .unwrap()
        .to_owned();
    let observed = sessions
        .dispatch("get_app_state", &params("one"))
        .await
        .unwrap();
    let mut action = params("one");
    action["snapshot_id"] = observed["snapshot_id"].clone();
    action["action"] = json!({"kind":"click","x":1,"y":1});
    action["expected_identity_digest"] = json!("wrong");
    assert_eq!(
        sessions
            .dispatch("perform_action", &action)
            .await
            .unwrap_err()
            .kind,
        "application_identity_changed"
    );
    action["expected_identity_digest"] = json!(app().identity_digest);
    sessions.dispatch("perform_action", &action).await.unwrap();
    assert_eq!(
        sessions
            .dispatch("perform_action", &action)
            .await
            .unwrap_err()
            .kind,
        "stale_element"
    );
    assert_eq!(backend.calls.load(Ordering::SeqCst), 1);
    let _ = std::fs::remove_dir(root);
}
#[tokio::test]
async fn cancellation_interrupts_an_inflight_action_without_success_or_replay() {
    let backend = Arc::new(MockBackend::default());
    let sessions = Arc::new(Sessions::new(backend.clone()));
    let root = sessions
        .dispatch("begin_session", &context("one"))
        .await
        .unwrap()["artifact_root"]
        .as_str()
        .unwrap()
        .to_owned();
    let observed = sessions
        .dispatch("get_app_state", &params("one"))
        .await
        .unwrap();
    let mut action = params("one");
    action["snapshot_id"] = observed["snapshot_id"].clone();
    action["action"] = json!({"kind":"type_text","text":"long unicode input"});
    let worker = sessions.clone();
    let call = tokio::spawn(async move { worker.dispatch("perform_action", &action).await });
    tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    sessions.cancel("one").await;
    assert_eq!(
        call.await.unwrap().unwrap_err().kind,
        "user_stopped_session"
    );
    assert_eq!(backend.calls.load(Ordering::SeqCst), 0);
    let _ = std::fs::remove_dir(root);
}
#[test]
fn native_png_codec_keeps_real_capture_dimensions() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("capture.png");
    image::RgbImage::from_pixel(37, 23, image::Rgb([17, 93, 201]))
        .save(&path)
        .unwrap();
    assert_eq!(image::image_dimensions(path).unwrap(), (37, 23));
}

#[tokio::test]
async fn pause_resume_requires_fresh_observation_and_releases_resources() {
    let backend = Arc::new(MockBackend::default());
    let sessions = Sessions::new(backend.clone());
    let started = sessions
        .dispatch("begin_session", &context("pause"))
        .await
        .unwrap();
    let root = PathBuf::from(started["artifact_root"].as_str().unwrap());
    let artifact = root.join("private-capture.png");
    std::fs::write(&artifact, b"owned fixture").unwrap();
    let observed = sessions
        .dispatch("get_app_state", &params("pause"))
        .await
        .unwrap();
    assert!(observed.get("app_icon").is_none());
    assert_eq!(
        observed["app_icon_unavailable_reason"],
        "capability_unsupported"
    );
    let result = sessions
        .dispatch("pause_session", &context("pause"))
        .await
        .unwrap();
    assert_eq!(result["phase"], "paused");
    assert!(!artifact.exists());
    assert!(root.is_dir());
    assert!(backend.releases.load(Ordering::SeqCst) > 0);
    assert_eq!(backend.audio_stops.load(Ordering::SeqCst), 0);
    assert_eq!(backend.session_releases.load(Ordering::SeqCst), 1);
    assert_eq!(
        sessions
            .dispatch("get_app_state", &params("pause"))
            .await
            .unwrap_err()
            .kind,
        "session_paused"
    );
    assert_eq!(
        sessions
            .dispatch("resume_session", &context("pause"))
            .await
            .unwrap()["requires_observation"],
        true
    );
    let mut action = params("pause");
    action["snapshot_id"] = observed["snapshot_id"].clone();
    action["action"] = json!({"kind":"click","x":5,"y":5});
    assert_eq!(
        sessions
            .dispatch("perform_action", &action)
            .await
            .unwrap_err()
            .kind,
        "stale_element"
    );
    let fresh = sessions
        .dispatch("get_app_state", &params("pause"))
        .await
        .unwrap();
    action["snapshot_id"] = fresh["snapshot_id"].clone();
    sessions.dispatch("perform_action", &action).await.unwrap();
    assert_eq!(backend.calls.load(Ordering::SeqCst), 1);
    sessions
        .dispatch("stop_session", &context("pause"))
        .await
        .unwrap();
    assert_eq!(
        sessions
            .dispatch("resume_session", &context("pause"))
            .await
            .unwrap_err()
            .kind,
        "user_stopped_session"
    );
    let _ = std::fs::remove_dir(root);
}
#[tokio::test]
async fn pause_interrupts_in_flight_input_and_rejects_a_different_owner() {
    let backend = Arc::new(MockBackend::default());
    let sessions = Arc::new(Sessions::new(backend.clone()));
    let started = sessions
        .dispatch("begin_session", &context("pause-race"))
        .await
        .unwrap();
    let root = PathBuf::from(started["artifact_root"].as_str().unwrap());
    let observed = sessions
        .dispatch("get_app_state", &params("pause-race"))
        .await
        .unwrap();
    let mut other = context("pause-race");
    other["device_id"] = json!("another-device");
    assert_eq!(
        sessions
            .dispatch("pause_session", &other)
            .await
            .unwrap_err()
            .kind,
        "session_owner_mismatch"
    );
    let mut action = params("pause-race");
    action["snapshot_id"] = observed["snapshot_id"].clone();
    action["action"] = json!({"kind":"type_text","text":"cancel fixture"});
    let task = {
        let sessions = sessions.clone();
        tokio::spawn(async move { sessions.dispatch("perform_action", &action).await })
    };
    tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    sessions
        .dispatch("pause_session", &context("pause-race"))
        .await
        .unwrap();
    assert_eq!(
        task.await.unwrap().unwrap_err().kind,
        "user_stopped_session"
    );
    assert_eq!(backend.calls.load(Ordering::SeqCst), 0);
    sessions
        .dispatch("stop_session", &context("pause-race"))
        .await
        .unwrap();
    assert_eq!(
        sessions
            .dispatch("resume_session", &context("pause-race"))
            .await
            .unwrap_err()
            .kind,
        "user_stopped_session"
    );
    let _ = std::fs::remove_dir(root);
}

#[tokio::test]
async fn concurrent_terminal_stop_cannot_be_downgraded_by_pause_cleanup() {
    let sessions = Arc::new(Sessions::new(Arc::new(MockBackend::default())));
    let started = sessions
        .dispatch("begin_session", &context("lifecycle-race"))
        .await
        .unwrap();
    let root = PathBuf::from(started["artifact_root"].as_str().unwrap());
    let gate = sessions.operation.lock().await;
    let paused = {
        let sessions = sessions.clone();
        tokio::spawn(async move {
            sessions
                .dispatch("pause_session", &context("lifecycle-race"))
                .await
        })
    };
    let state = sessions.session("lifecycle-race").await.unwrap();
    for _ in 0..100 {
        if state.lock().await.phase == Phase::Pausing {
            break;
        }
        tokio::task::yield_now().await;
    }
    assert!(state.lock().await.phase == Phase::Pausing);
    let stopped = {
        let sessions = sessions.clone();
        tokio::spawn(async move {
            sessions
                .dispatch("stop_session", &context("lifecycle-race"))
                .await
        })
    };
    for _ in 0..100 {
        if state.lock().await.phase == Phase::Stopped {
            break;
        }
        tokio::task::yield_now().await;
    }
    assert!(state.lock().await.phase == Phase::Stopped);
    drop(gate);
    assert_eq!(
        paused.await.unwrap().unwrap_err().kind,
        "user_stopped_session"
    );
    stopped.await.unwrap().unwrap();
    assert_eq!(
        sessions
            .dispatch("resume_session", &context("lifecycle-race"))
            .await
            .unwrap_err()
            .kind,
        "user_stopped_session"
    );
    let _ = std::fs::remove_dir(root);
}

#[tokio::test]
async fn reset_recovers_cancel_but_cannot_rearm_paused_or_terminal_sessions() {
    let sessions = Sessions::new(Arc::new(MockBackend::default()));
    let started = sessions
        .dispatch("begin_session", &context("reset-boundary"))
        .await
        .unwrap();
    let root = PathBuf::from(started["artifact_root"].as_str().unwrap());
    sessions
        .dispatch("cancel", &context("reset-boundary"))
        .await
        .unwrap();
    sessions
        .dispatch("reset_session", &context("reset-boundary"))
        .await
        .unwrap();
    sessions
        .dispatch("get_app_state", &params("reset-boundary"))
        .await
        .unwrap();
    sessions
        .dispatch("pause_session", &context("reset-boundary"))
        .await
        .unwrap();
    assert_eq!(
        sessions
            .dispatch("reset_session", &context("reset-boundary"))
            .await
            .unwrap_err()
            .kind,
        "session_paused"
    );
    sessions
        .dispatch("resume_session", &context("reset-boundary"))
        .await
        .unwrap();
    sessions
        .dispatch("stop_session", &context("reset-boundary"))
        .await
        .unwrap();
    assert_eq!(
        sessions
            .dispatch("reset_session", &context("reset-boundary"))
            .await
            .unwrap_err()
            .kind,
        "user_stopped_session"
    );
    assert_eq!(
        sessions
            .dispatch("cancel", &context("reset-boundary"))
            .await
            .unwrap_err()
            .kind,
        "user_stopped_session"
    );
    let _ = std::fs::remove_dir(root);
}

#[tokio::test]
async fn recording_receipts_survive_pause_end_rebegin_and_ack_without_stopping_new_capture() {
    let backend = Arc::new(MockBackend::default());
    let sessions = Sessions::new(backend.clone());
    let base = context("audio-lifecycle");
    let begun = sessions.dispatch("begin_session", &base).await.unwrap();
    let old_root = PathBuf::from(begun["artifact_root"].as_str().unwrap());
    let mut start = base.clone();
    start["source"] = json!("microphone");
    let first = sessions.dispatch("audio_start", &start).await.unwrap();
    let first_id = first["recording_id"].as_str().unwrap();
    sessions.dispatch("pause_session", &base).await.unwrap();
    let receipt = sessions.dispatch("audio_status", &base).await.unwrap();
    assert_eq!(receipt["recordings"][0]["status"], "pending_export");
    assert_eq!(receipt["recordings"][0]["end_reason"], "user_paused");
    assert_eq!(receipt["recordings"][0]["artifacts"][0]["kind"], "audio");
    let path = url::Url::parse(
        receipt["recordings"][0]["artifacts"][0]["url"]
            .as_str()
            .unwrap(),
    )
    .unwrap()
    .to_file_path()
    .unwrap();
    assert!(path.is_file());
    sessions.dispatch("end_session", &base).await.unwrap();
    let mut selected = base.clone();
    selected["recording_id"] = json!(first_id);
    assert_eq!(
        sessions.dispatch("audio_stop", &selected).await.unwrap()["recordings"],
        receipt["recordings"]
    );
    let mut foreign = selected.clone();
    foreign["user_id"] = json!("foreign");
    assert_eq!(
        sessions
            .dispatch("audio_ack", &foreign)
            .await
            .unwrap_err()
            .kind,
        "session_owner_mismatch"
    );
    assert!(
        sessions
            .dispatch("get_app_state", &params("audio-lifecycle"))
            .await
            .is_err()
    );
    let new_begun = sessions.dispatch("begin_session", &base).await.unwrap();
    let new_root = PathBuf::from(new_begun["artifact_root"].as_str().unwrap());
    assert_ne!(old_root, new_root);
    let second = sessions.dispatch("audio_start", &start).await.unwrap();
    assert_ne!(first["recording_id"], second["recording_id"]);
    sessions.dispatch("audio_stop", &selected).await.unwrap();
    assert_eq!(backend.audio_stops.load(Ordering::SeqCst), 1);
    let active = sessions.dispatch("audio_status", &base).await.unwrap();
    assert_eq!(active["recording"], true);
    let mut unknown = selected.clone();
    unknown["recording_id"] = json!("unknown");
    assert_eq!(
        sessions
            .dispatch("audio_ack", &unknown)
            .await
            .unwrap_err()
            .kind,
        "recording_not_found"
    );
    let ack = sessions.dispatch("audio_ack", &selected).await.unwrap();
    assert_eq!(ack["recordings"][0]["status"], "saved");
    assert!(!path.exists());
    assert_eq!(
        sessions.dispatch("audio_ack", &selected).await.unwrap(),
        ack
    );
    sessions.dispatch("end_session", &base).await.unwrap();
    assert_eq!(backend.audio_stops.load(Ordering::SeqCst), 2);
    std::fs::remove_dir_all(old_root).unwrap();
    std::fs::remove_dir_all(new_root).unwrap();
}

#[tokio::test]
async fn recording_stop_bypasses_input_queue_and_preserves_requested_reason() {
    let backend = Arc::new(MockBackend::default());
    let sessions = Sessions::new(backend);
    let base = context("audio-independent-stop");
    let begun = sessions.dispatch("begin_session", &base).await.unwrap();
    let root = PathBuf::from(begun["artifact_root"].as_str().unwrap());
    let mut start = base.clone();
    start["source"] = json!("microphone");
    let first = sessions.dispatch("audio_start", &start).await.unwrap();
    let operation = sessions.operation.lock().await;
    let mut stop = base.clone();
    stop["recording_id"] = first["recording_id"].clone();
    stop["end_reason"] = json!("user_stopped");
    let receipt = tokio::time::timeout(
        std::time::Duration::from_millis(250),
        sessions.dispatch("audio_stop", &stop),
    )
    .await
    .expect("audio stop queued behind input")
    .unwrap();
    assert_eq!(receipt["recordings"][0]["end_reason"], "user_stopped");
    drop(operation);
    let mut bad_stop = stop.clone();
    bad_stop["end_reason"] = json!("unrecognized_reason");
    assert_eq!(
        sessions.cancel_request(&bad_stop).await.unwrap_err().kind,
        "invalid_params"
    );
    let again = sessions.dispatch("audio_stop", &base).await.unwrap();
    assert_eq!(again["recordings"], receipt["recordings"]);
    let second = sessions.dispatch("audio_start", &start).await.unwrap();
    let mut expiry = base.clone();
    expiry["end_reason"] = json!("lease_expired");
    sessions.cancel_request(&expiry).await.unwrap();
    sessions.dispatch("stop_session", &expiry).await.unwrap();
    let mut selected = base.clone();
    selected["recording_id"] = second["recording_id"].clone();
    assert_eq!(
        sessions.dispatch("audio_status", &selected).await.unwrap()["recordings"][0]["end_reason"],
        "lease_expired"
    );
    sessions.dispatch("end_session", &base).await.unwrap();
    std::fs::remove_dir_all(root).unwrap();
}
