//! Receipt and framed-helper tests never open microphones or other OS devices.
use super::management_lifecycle_tests::Helper;
use super::*;

struct Fixture {
    state: Arc<LocalRuntimeState>,
    helper: Helper,
    owner: Owner,
    context: CuaCallContext,
    receipt: Value,
}

#[tokio::test]
async fn saved_recordings_attach_owned_audio_without_duplicate_persistence() {
    let fixture = Fixture::new().await;
    fixture.stop().await;
    let native = fixture
        .helper
        .client
        .request_existing_session(&fixture.context, "audio_status", json!({}))
        .await
        .unwrap();
    let mut result = ToolResult::text(native.to_string());
    recordings::tool_result(&fixture.state, &fixture.session(), &mut result)
        .await
        .unwrap();
    assert_eq!(result.media.len(), 1);
    assert_eq!(result.media[0].mime_type, "audio/wav");
    let path = result.media[0].artifact_path.clone();
    artifacts::persist(
        &fixture.state,
        &fixture.owner,
        &fixture.context,
        &mut result,
    )
    .await
    .unwrap();
    assert_eq!(result.media[0].artifact_path, path);
    let id = fixture.snapshot()[0]["artifacts"][0]["artifact_id"]
        .as_str()
        .unwrap()
        .to_owned();
    assert!(
        artifacts::attachment(&fixture.state, &fixture.owner, "other-conversation", &id).is_err()
    );
    assert_eq!(
        artifacts::media_descriptors(&fixture.state, &fixture.owner, &result.media).unwrap()[0]["artifact_id"],
        id
    );
    fixture.close().await;
}
impl Fixture {
    async fn new() -> Self {
        let helper = Helper::new(false);
        let mut state = crate::local_runtime::tests::test_state("cua-recording-receipts");
        let mutable = Arc::get_mut(&mut state).unwrap();
        mutable.app_data_dir = Some(helper.root.join("app-data"));
        mutable.session_store = crate::local_runtime::session_store::DesktopSessionStore::open(
            &helper.root.join("sessions.sqlite"),
        )
        .unwrap();
        assert!(state.computer_use.client.set(helper.client.clone()).is_ok());
        let owner = tests::owner(&state);
        let context = CuaCallContext {
            user_id: owner.user_id.clone(),
            tenant_id: owner.tenant_id.clone(),
            project_id: owner.project_id.clone(),
            device_id: owner.device_id.clone(),
            conversation_id: "recording-conversation".into(),
            run_id: "recording-run".into(),
            session_id: "recording-session".into(),
            input_mode: agistack_adapters_cua::CuaInputMode::default(),
        };
        let source = helper.root.join("recording.wav");
        // A playable PCM WAV: mono, 16 kHz, 16-bit, 10 ms of silence.
        let mut wave = b"RIFF".to_vec();
        wave.extend_from_slice(&356u32.to_le_bytes());
        wave.extend_from_slice(b"WAVEfmt ");
        wave.extend_from_slice(&16u32.to_le_bytes());
        wave.extend_from_slice(&1u16.to_le_bytes());
        wave.extend_from_slice(&1u16.to_le_bytes());
        wave.extend_from_slice(&16000u32.to_le_bytes());
        wave.extend_from_slice(&32000u32.to_le_bytes());
        wave.extend_from_slice(&2u16.to_le_bytes());
        wave.extend_from_slice(&16u16.to_le_bytes());
        wave.extend_from_slice(b"data");
        wave.extend_from_slice(&320u32.to_le_bytes());
        wave.extend_from_slice(&[0; 320]);
        std::fs::write(&source, wave).unwrap();
        let receipt = json!({"recording_id":Uuid::new_v4().to_string(),"source":"microphone",
            "status":"recording","started_at":"2026-10-19T00:00:00Z","artifacts":[{
                "kind":"audio","mime_type":"audio/wav","source":"microphone",
                "url":url::Url::from_file_path(source).unwrap().to_string()}]});
        std::fs::write(
            helper.root.join("audio_receipts.json"),
            json!([receipt]).to_string(),
        )
        .unwrap();
        let output = helper
            .client
            .request_in_session(&context, "audio_start", json!({"source":"microphone"}))
            .await
            .unwrap();
        recordings::ingest(&state, &owner, &context, &output)
            .await
            .unwrap();
        Self {
            state,
            helper,
            owner,
            context,
            receipt,
        }
    }
    fn id(&self) -> &str {
        self.receipt["recording_id"].as_str().unwrap()
    }
    async fn stop(&self) {
        recordings::stop(
            &self.state,
            &self.owner,
            &self.context.session_id,
            self.id(),
        )
        .await
        .unwrap();
    }
    fn snapshot(&self) -> Value {
        json!(recordings::snapshot(&self.state, &self.owner).unwrap())
    }
    fn session(&self) -> Arc<Session> {
        Arc::new(Session {
            resources: Default::default(),
            dispatch: tokio::sync::Mutex::new(()),
            owner: self.owner.clone(),
            context: self.context.clone(),
            revision: 0,
            stopped: AtomicBool::new(false),
            paused: AtomicBool::new(false),
            user_control: Default::default(),
            presentation: Mutex::new(json!({"phase":"idle"})),
            child: None,
            cloud: None,
        })
    }
    async fn close(self) {
        self.helper.client.shutdown().await;
        std::fs::remove_dir_all(&self.helper.root).unwrap();
    }
}

#[tokio::test]
async fn independent_stop_saves_once_and_is_available_with_disabled_plugin_and_closed_parent() {
    let fixture = Fixture::new().await;
    assert!(
        !store::instance(
            &*fixture.state.session_store.connection().unwrap(),
            &fixture.owner
        )
        .unwrap()
        .enabled
    );
    fixture
        .helper
        .client
        .end_session(&fixture.context.session_id)
        .await
        .unwrap();
    fixture.stop().await;
    let receipt = fixture.snapshot()[0].clone();
    assert_eq!(receipt["status"], "saved");
    assert_eq!(receipt["conversation_id"], fixture.context.conversation_id);
    assert!(
        receipt["artifacts"][0]["artifact_id"]
            .as_str()
            .unwrap()
            .starts_with("cua-audio-")
    );
    assert!(!receipt.to_string().contains("file:"));
    fixture.stop().await;
    assert_eq!(fixture.snapshot()[0], receipt);
    let calls = fixture.helper.requests();
    assert_eq!(
        calls
            .iter()
            .filter(|call| call["method"] == "audio_start")
            .count(),
        1
    );
    assert_eq!(
        calls
            .iter()
            .filter(|call| call["method"] == "audio_stop")
            .count(),
        1
    );
    assert_eq!(
        calls
            .iter()
            .filter(|call| call["method"] == "begin_session")
            .count(),
        1
    );
    let id = receipt["artifacts"][0]["artifact_id"].as_str().unwrap();
    assert!(artifacts::audio_chunk(&fixture.state, &fixture.owner, id, 0).is_ok());
    fixture.close().await;
}

#[tokio::test]
async fn foreign_owner_session_and_unknown_recording_never_dispatch_native_stop() {
    let fixture = Fixture::new().await;
    let mut other = fixture.owner.clone();
    other.user_id = "other-user".into();
    assert!(
        recordings::snapshot(&fixture.state, &other)
            .unwrap()
            .is_empty()
    );
    for (owner, session, id) in [
        (&other, fixture.context.session_id.as_str(), fixture.id()),
        (&fixture.owner, "other-session", fixture.id()),
        (
            &fixture.owner,
            fixture.context.session_id.as_str(),
            "unknown",
        ),
    ] {
        assert_eq!(
            recordings::stop(&fixture.state, owner, session, id)
                .await
                .unwrap_err(),
            "cua_recording_not_found"
        );
    }
    assert!(
        !fixture
            .helper
            .requests()
            .iter()
            .any(|call| call["method"] == "audio_stop")
    );
    fixture.close().await;
}

#[tokio::test]
async fn failed_export_retains_source_and_retry_only_exports_without_restarting_or_stopping_again()
{
    let fixture = Fixture::new().await;
    let app_data = fixture.state.app_data_dir.as_ref().unwrap();
    std::fs::write(app_data, b"blocks directory creation").unwrap();
    fixture.stop().await;
    assert_eq!(fixture.snapshot()[0]["status"], "failed");
    assert_eq!(fixture.snapshot()[0]["can_retry_export"], true);
    assert!(fixture.helper.root.join("recording.wav").is_file());
    assert!(
        !fixture
            .helper
            .requests()
            .iter()
            .any(|call| call["method"] == "audio_ack")
    );
    std::fs::remove_file(app_data).unwrap();
    fixture.stop().await;
    assert_eq!(fixture.snapshot()[0]["status"], "saved");
    assert_eq!(
        fixture
            .helper
            .requests()
            .iter()
            .filter(|call| call["method"] == "audio_stop")
            .count(),
        1
    );
    fixture.close().await;
}

#[tokio::test]
async fn missing_sealed_file_or_root_is_terminal_without_losing_the_recording_history() {
    for remove_root in [false, true] {
        let fixture = Fixture::new().await;
        let root = fixture.helper.root.join("capture");
        std::fs::create_dir(&root).unwrap();
        let source = root.join("recording.wav");
        std::fs::rename(fixture.helper.root.join("recording.wav"), &source).unwrap();
        let mut record = recordings_store::get(&fixture.state, fixture.id())
            .unwrap()
            .unwrap();
        record.root = root.clone();
        record.native["artifacts"][0]["url"] =
            json!(url::Url::from_file_path(&source).unwrap().to_string());
        recordings_store::save(&fixture.state, &record).unwrap();
        std::fs::write(
            fixture.helper.root.join("audio_receipts.json"),
            json!([record.native]).to_string(),
        )
        .unwrap();
        if remove_root {
            std::fs::remove_dir_all(root).unwrap();
        } else {
            std::fs::remove_file(source).unwrap();
        }
        fixture.stop().await;
        let receipt = fixture.snapshot()[0].clone();
        assert_eq!(receipt["recording_id"], fixture.id());
        assert_eq!(receipt["status"], "failed");
        assert_eq!(receipt["error_code"], "cua_audio_source_missing");
        assert_eq!(receipt["can_retry_export"], false);
        assert_eq!(receipt["end_reason"], "user_stopped");
        assert_eq!(receipt["elapsed_ms"], 10000);
        let requests = fixture.helper.requests();
        assert!(!requests.iter().any(|call| call["method"] == "audio_ack"));
        fixture.stop().await;
        assert_eq!(fixture.snapshot()[0], receipt);
        assert_eq!(fixture.helper.requests(), requests);
        fixture.close().await;
    }
}

#[tokio::test]
async fn retry_reclassifies_an_old_unavailable_source_without_native_dispatch() {
    let fixture = Fixture::new().await;
    let app_data = fixture.state.app_data_dir.as_ref().unwrap();
    std::fs::write(app_data, b"blocks save").unwrap();
    fixture.stop().await;
    std::fs::remove_file(app_data).unwrap();
    std::fs::remove_file(fixture.helper.root.join("recording.wav")).unwrap();
    let mut previous = recordings_store::get(&fixture.state, fixture.id())
        .unwrap()
        .unwrap();
    previous.receipt["error_code"] = json!("cua_audio_source_unavailable");
    recordings_store::save(&fixture.state, &previous).unwrap();
    let requests = fixture.helper.requests();
    fixture.stop().await;
    let saved = recordings_store::get(&fixture.state, fixture.id())
        .unwrap()
        .unwrap();
    let mut expected = previous.receipt;
    expected["error_code"] = json!("cua_audio_source_missing");
    expected["can_retry_export"] = json!(false);
    assert_eq!(saved.receipt, expected);
    assert_eq!(saved.native, previous.native);
    assert!(!saved.acknowledged);
    assert_eq!(fixture.helper.requests(), requests);
    fixture.close().await;
}

#[cfg(unix)]
#[tokio::test]
async fn source_permission_denied_remains_retryable_and_recovers_without_recapture() {
    use std::os::unix::fs::PermissionsExt;
    let fixture = Fixture::new().await;
    let source = fixture.helper.root.join("recording.wav");
    std::fs::set_permissions(&source, std::fs::Permissions::from_mode(0o000)).unwrap();
    fixture.stop().await;
    let failed = fixture.snapshot()[0].clone();
    std::fs::set_permissions(&source, std::fs::Permissions::from_mode(0o600)).unwrap();
    assert_eq!(failed["error_code"], "cua_audio_source_unavailable");
    assert_eq!(failed["can_retry_export"], true);
    let before = fixture.helper.requests();
    assert!(!before.iter().any(|call| call["method"] == "audio_ack"));
    fixture.stop().await;
    let saved = fixture.snapshot()[0].clone();
    assert_eq!(saved["status"], "saved");
    assert_eq!(saved["can_retry_export"], false);
    assert_eq!(saved["end_reason"], failed["end_reason"]);
    assert_eq!(
        fixture
            .helper
            .requests()
            .iter()
            .filter(|call| call["method"] == "audio_start")
            .count(),
        1
    );
    assert_eq!(
        fixture
            .helper
            .requests()
            .iter()
            .filter(|call| call["method"] == "audio_stop")
            .count(),
        1
    );
    fixture.close().await;
}

#[tokio::test]
async fn terminal_receipt_cannot_be_reopened_by_late_start_or_stop_a_new_generation() {
    let fixture = Fixture::new().await;
    fixture.stop().await;
    let saved = fixture.snapshot()[0].clone();
    recordings::ingest(
        &fixture.state,
        &fixture.owner,
        &fixture.context,
        &json!({"recordings":[fixture.receipt]}),
    )
    .await
    .unwrap();
    assert_eq!(fixture.snapshot()[0], saved);
    let mut second = fixture.receipt.clone();
    second["recording_id"] = json!(Uuid::new_v4().to_string());
    recordings::ingest(
        &fixture.state,
        &fixture.owner,
        &fixture.context,
        &json!({"recordings":[second]}),
    )
    .await
    .unwrap();
    fixture.stop().await;
    let receipts = fixture.snapshot();
    assert_eq!(receipts[0]["status"], "recording");
    assert_eq!(receipts[1]["status"], "saved");
    fixture.close().await;
}

#[tokio::test]
async fn existing_resource_api_never_spawns_or_admits_and_rejects_input_methods() {
    let helper = Helper::new(false);
    let context = CuaCallContext {
        user_id: "user".into(),
        tenant_id: "tenant".into(),
        project_id: "project".into(),
        device_id: "device".into(),
        conversation_id: "conversation".into(),
        run_id: "run".into(),
        session_id: "session".into(),
        input_mode: agistack_adapters_cua::CuaInputMode::default(),
    };
    assert!(
        helper
            .client
            .request_existing_session(&context, "audio_stop", json!({}))
            .await
            .is_err()
    );
    assert!(!helper.root.join("requests").exists());
    helper
        .client
        .request_in_session(&context, "audio_status", json!({}))
        .await
        .unwrap();
    assert!(
        helper
            .client
            .request_existing_session(&context, "perform_action", json!({}))
            .await
            .is_err()
    );
    let mut foreign = context.clone();
    foreign.user_id = "foreign".into();
    assert!(
        helper
            .client
            .request_existing_session(&foreign, "audio_stop", json!({}))
            .await
            .is_err()
    );
    helper.client.shutdown().await;
    std::fs::remove_dir_all(&helper.root).unwrap();
}

#[tokio::test]
async fn stop_releases_native_recording_before_waiting_on_export_gate() {
    let fixture = Fixture::new().await;
    let gate = fixture.state.computer_use.recordings_gate.lock().await;
    let stopping = fixture.stop();
    tokio::pin!(stopping);
    assert!(
        tokio::time::timeout(std::time::Duration::from_millis(50), &mut stopping)
            .await
            .is_err()
    );
    assert!(
        fixture
            .helper
            .requests()
            .iter()
            .any(|call| call["method"] == "audio_stop")
    );
    let native: Value = serde_json::from_slice(
        &std::fs::read(fixture.helper.root.join("audio_receipts.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(native[0]["status"], "pending_export");
    drop(gate);
    stopping.await;
    assert_eq!(fixture.snapshot()[0]["status"], "saved");
    fixture.helper.client.shutdown().await;
    std::fs::remove_dir_all(&fixture.helper.root).unwrap();
}

#[tokio::test]
async fn helper_exit_ends_active_receipt_without_spawning_a_replacement() {
    let fixture = Fixture::new().await;
    fixture.helper.client.shutdown().await;
    let before = fixture.helper.requests().len();
    recordings::refresh_owner(&fixture.state, &fixture.owner).await;
    let receipt = fixture.snapshot()[0].clone();
    assert_eq!(receipt["status"], "failed");
    assert_eq!(receipt["error_code"], "cua_recording_resource_unavailable");
    assert_eq!(receipt["can_retry_export"], false);
    fixture.stop().await;
    assert_eq!(fixture.helper.requests().len(), before);
    fixture.close().await;
}

#[tokio::test]
async fn sealed_export_can_retry_after_helper_exit_using_only_its_persisted_owned_source() {
    let fixture = Fixture::new().await;
    let app_data = fixture.state.app_data_dir.as_ref().unwrap();
    std::fs::write(app_data, b"blocks save").unwrap();
    fixture.stop().await;
    assert_eq!(fixture.snapshot()[0]["can_retry_export"], true);
    fixture.helper.client.shutdown().await;
    let before = fixture.helper.requests().len();
    std::fs::remove_file(app_data).unwrap();
    fixture.stop().await;
    assert_eq!(fixture.snapshot()[0]["status"], "saved");
    assert_eq!(fixture.helper.requests().len(), before);
    fixture.close().await;
}

#[tokio::test]
async fn pause_lease_expiry_and_parent_close_finalize_and_preserve_playable_receipts() {
    for reason in [
        "pause",
        "lease",
        "close",
        "user_stop",
        "revoked",
        "disabled",
    ] {
        let fixture = Fixture::new().await;
        let session = fixture.session();
        fixture
            .state
            .computer_use
            .sessions
            .lock()
            .unwrap()
            .insert(session.context.session_id.clone(), session.clone());
        match reason {
            "pause" => presentation::pause_resume(
                &fixture.state,
                &fixture.owner,
                &session.context.session_id,
                false,
            )
            .await
            .unwrap(),
            "lease" => resource_lease::release_native(&fixture.state, &session).await,
            "user_stop" => fixture
                .state
                .computer_use
                .user_stop(
                    &fixture.state,
                    &fixture.owner,
                    Some(&session.context.session_id),
                )
                .await
                .unwrap(),
            "revoked" | "disabled" => {
                fixture
                    .state
                    .computer_use
                    .stop_owner(&fixture.state, &fixture.owner, reason)
                    .await
            }
            _ => {
                fixture
                    .state
                    .computer_use
                    .close_session(&fixture.state, &session.context.session_id)
                    .await
            }
        }
        let receipt = fixture.snapshot()[0].clone();
        assert_eq!(receipt["status"], "saved", "{reason}");
        assert_eq!(
            receipt["end_reason"],
            match reason {
                "pause" => "user_paused",
                "lease" => "lease_expired",
                "user_stop" => "user_stopped",
                "revoked" => "revoked",
                "disabled" => "disabled",
                _ => "session_ended",
            }
        );
        assert!(
            artifacts::audio_chunk(
                &fixture.state,
                &fixture.owner,
                receipt["artifacts"][0]["artifact_id"].as_str().unwrap(),
                0
            )
            .is_ok()
        );
        assert_eq!(
            fixture
                .helper
                .requests()
                .iter()
                .filter(|call| call["method"] == "audio_start")
                .count(),
            1
        );
        fixture.close().await;
    }
}

#[tokio::test]
async fn receipt_and_owned_export_retry_survive_store_reopen_without_starting_a_helper() {
    let fixture = Fixture::new().await;
    let app_data = fixture.state.app_data_dir.clone().unwrap();
    std::fs::write(&app_data, b"blocks save").unwrap();
    fixture.stop().await;
    let expected = fixture.snapshot();
    assert_eq!(expected[0]["can_retry_export"], true);
    fixture.helper.client.shutdown().await;
    let Fixture {
        state,
        helper,
        owner,
        context,
        receipt,
    } = fixture;
    drop(state);
    std::fs::remove_file(&app_data).unwrap();
    let before = helper.requests().len();
    let mut restored = crate::local_runtime::tests::test_state("cua-recording-reopened");
    let mutable = Arc::get_mut(&mut restored).unwrap();
    mutable.session_store = crate::local_runtime::session_store::DesktopSessionStore::open(
        &helper.root.join("sessions.sqlite"),
    )
    .unwrap();
    mutable.app_data_dir = Some(app_data);
    assert_eq!(
        json!(recordings::snapshot(&restored, &owner).unwrap()),
        expected
    );
    recordings::stop(
        &restored,
        &owner,
        &context.session_id,
        receipt["recording_id"].as_str().unwrap(),
    )
    .await
    .unwrap();
    let saved = recordings::snapshot(&restored, &owner).unwrap();
    assert_eq!(saved[0]["status"], "saved");
    assert!(
        artifacts::audio_chunk(
            &restored,
            &owner,
            saved[0]["artifacts"][0]["artifact_id"].as_str().unwrap(),
            0
        )
        .is_ok()
    );
    assert!(restored.computer_use.client.get().is_none());
    assert_eq!(helper.requests().len(), before);
    drop(restored);
    std::fs::remove_dir_all(&helper.root).unwrap();
}

#[tokio::test]
async fn missing_old_native_recording_cannot_fail_or_stop_the_new_generation() {
    let fixture = Fixture::new().await;
    let mut second = fixture.receipt.clone();
    second["recording_id"] = json!(Uuid::new_v4().to_string());
    std::fs::write(
        fixture.helper.root.join("audio_receipts.json"),
        json!([second]).to_string(),
    )
    .unwrap();
    recordings::ingest(
        &fixture.state,
        &fixture.owner,
        &fixture.context,
        &json!({"recordings":[second]}),
    )
    .await
    .unwrap();
    fixture.stop().await;
    let receipts = fixture.snapshot();
    assert_eq!(receipts[0]["recording_id"], second["recording_id"]);
    assert_eq!(receipts[0]["status"], "recording");
    assert_eq!(receipts[1]["status"], "failed");
    let native: Value = serde_json::from_slice(
        &std::fs::read(fixture.helper.root.join("audio_receipts.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(native[0]["status"], "recording");
    fixture.close().await;
}
