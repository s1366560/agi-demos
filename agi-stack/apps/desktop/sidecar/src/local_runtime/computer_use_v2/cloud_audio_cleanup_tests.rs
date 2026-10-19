//! Offline audio cleanup uses only a previously authenticated current owner.
use super::super::management_lifecycle_tests::Helper;
use super::*;

struct AudioFixture {
    cloud: Fixture,
    helper: Helper,
    context: CuaCallContext,
    recording_id: String,
}
impl AudioFixture {
    async fn new(binding: Option<&str>) -> Self {
        let mut cloud = Fixture::new().await;
        let helper = Helper::new(false);
        Arc::get_mut(&mut cloud.state).unwrap().app_data_dir = Some(helper.root.join("app-data"));
        assert!(
            cloud
                .state
                .computer_use
                .client
                .set(helper.client.clone())
                .is_ok()
        );
        let owner = cloud.owner();
        let context = CuaCallContext {
            user_id: owner.user_id.clone(),
            tenant_id: owner.tenant_id.clone(),
            project_id: owner.project_id.clone(),
            device_id: owner.device_id.clone(),
            conversation_id: "conversation".into(),
            run_id: "audio-run".into(),
            session_id: "audio-session".into(),
        };
        let recording_id = Uuid::new_v4().to_string();
        // One mono, 16-bit PCM sample at 16 kHz.
        let mut wave = b"RIFF".to_vec();
        wave.extend_from_slice(&38u32.to_le_bytes());
        wave.extend_from_slice(b"WAVEfmt ");
        for value in [16u32, 0x00010001, 16000, 32000, 0x00100002] {
            wave.extend_from_slice(&value.to_le_bytes());
        }
        wave.extend_from_slice(b"data\x02\0\0\0\0\0");
        let source = helper.root.join("recording.wav");
        std::fs::write(&source, wave).unwrap();
        std::fs::write(
            helper.root.join("audio_receipts.json"),
            json!([{
                "recording_id":recording_id,"source":"microphone","status":"recording",
                "started_at":"2026-10-19T00:00:00Z","artifacts":[{
                    "kind":"audio","mime_type":"audio/wav","source":"microphone",
                    "url":url::Url::from_file_path(source).unwrap().to_string()
                }]
            }])
            .to_string(),
        )
        .unwrap();
        let output = helper
            .client
            .request_in_session(&context, "audio_start", json!({"source":"microphone"}))
            .await
            .unwrap();
        recordings::ingest(&cloud.state, &owner, &context, &output)
            .await
            .unwrap();
        let fixture = Self {
            cloud,
            helper,
            context,
            recording_id,
        };
        match binding {
            Some("describe") => {
                fixture.cloud.operation("describe").await.unwrap();
            }
            Some("status") => {
                fixture.manage(json!({"action":"status"})).await.unwrap();
            }
            _ => {}
        }
        fixture
    }
    fn input(&self, operation: Value) -> Value {
        json!({"mode":"cloud","tenant_id":"cloud-tenant","project_id":"cloud-project",
            "operation":operation})
    }
    fn stop(&self) -> Value {
        self.input(
            json!({"action":"audio_stop","session_id":self.context.session_id,
            "recording_id":self.recording_id}),
        )
    }
    async fn manage(&self, operation: Value) -> Result<Value, String> {
        api::native_operation(&self.cloud.state, &self.cloud.broker, self.input(operation)).await
    }
    async fn offline(&self) {
        self.cloud.server.abort();
        while !self.cloud.server.is_finished() {
            tokio::task::yield_now().await;
        }
    }
}

#[tokio::test]
async fn authenticated_audio_stop_remains_local_after_cloud_disconnect_without_new_admission() {
    for binding in ["describe", "status"] {
        let fixture = AudioFixture::new(Some(binding)).await;
        // Disconnect removes the execution connection, while cleanup authority remains.
        fixture.cloud.operation("close").await.unwrap();
        fixture.offline().await;
        let result =
            api::native_operation(&fixture.cloud.state, &fixture.cloud.broker, fixture.stop())
                .await
                .unwrap();
        assert_eq!(result["recordings"][0]["status"], "saved");
        assert!(!result["instance"]["enabled"].as_bool().unwrap());
        assert!(result["sessions"].as_array().unwrap().is_empty());
        let calls = fixture.helper.requests();
        for method in ["begin_session", "audio_start", "audio_stop"] {
            assert_eq!(
                calls.iter().filter(|call| call["method"] == method).count(),
                1,
                "{binding}/{method}"
            );
        }
        assert!(!calls.iter().any(|call| call["method"] == "resume_session" || call["method"] == "reset_session"));
        // The cache cannot grant resume or broaden any other offline operation.
        assert_eq!(
            fixture
                .manage(json!({"action":"resume","session_id":fixture.context.session_id}))
                .await
                .unwrap_err(),
            "cua_identity_unavailable"
        );
        assert_eq!(fixture.helper.requests().len(), calls.len());
        fixture.helper.client.shutdown().await;
    }
}

#[tokio::test]
async fn offline_audio_cleanup_rejects_foreign_scope_owner_session_and_recording() {
    let fixture = AudioFixture::new(Some("describe")).await;
    fixture.offline().await;
    let before = fixture.helper.requests().len();
    let mut foreign = recordings_store::get(&fixture.cloud.state, &fixture.recording_id)
        .unwrap()
        .unwrap();
    foreign.owner.user_id = "other-user".into();
    foreign.context.user_id = "other-user".into();
    foreign.receipt["recording_id"] = json!(Uuid::new_v4().to_string());
    recordings_store::save(&fixture.cloud.state, &foreign).unwrap();
    for input in [
        {
            let mut value = fixture.stop();
            value["tenant_id"] = json!("other-tenant");
            value
        },
        {
            let mut value = fixture.stop();
            value["project_id"] = json!("other-project");
            value
        },
        {
            let mut value = fixture.stop();
            value["operation"]["session_id"] = json!("other-session");
            value
        },
        {
            let mut value = fixture.stop();
            value["operation"]["recording_id"] = json!("missing");
            value
        },
        {
            let mut value = fixture.stop();
            value["operation"]["recording_id"] = foreign.receipt["recording_id"].clone();
            value
        },
    ] {
        assert!(
            api::native_operation(&fixture.cloud.state, &fixture.cloud.broker, input)
                .await
                .is_err()
        );
    }
    let other = TrustedSessionBroker::new(Arc::new(MemoryCredential::default()));
    let mut record = fixture.cloud.broker.snapshot().unwrap().record.unwrap();
    record.credential = "different-fixture-credential".into();
    other.save(record).unwrap();
    assert_eq!(
        other.snapshot().unwrap().epoch,
        fixture.cloud.broker.snapshot().unwrap().epoch
    );
    assert!(
        api::native_operation(&fixture.cloud.state, &other, fixture.stop())
            .await
            .is_err()
    );
    assert_eq!(fixture.helper.requests().len(), before);
    assert_eq!(
        recordings_store::get(&fixture.cloud.state, &fixture.recording_id)
            .unwrap()
            .unwrap()
            .receipt["status"],
        "recording"
    );
    assert_eq!(
        recordings_store::get(
            &fixture.cloud.state,
            foreign.receipt["recording_id"].as_str().unwrap()
        )
        .unwrap()
        .unwrap()
        .receipt["status"],
        "recording"
    );
    fixture.helper.client.shutdown().await;
}

#[tokio::test]
async fn offline_audio_cleanup_needs_prior_identity_and_rejects_logout_or_epoch_rotation() {
    let unbound = AudioFixture::new(None).await;
    unbound.offline().await;
    let before = unbound.helper.requests().len();
    assert_eq!(
        api::native_operation(&unbound.cloud.state, &unbound.cloud.broker, unbound.stop())
            .await
            .unwrap_err(),
        "cua_cleanup_owner_unavailable"
    );
    assert_eq!(unbound.helper.requests().len(), before);
    unbound.helper.client.shutdown().await;
    for logout in [false, true] {
        let fixture = AudioFixture::new(Some("describe")).await;
        fixture.offline().await;
        let before = fixture.helper.requests().len();
        if logout {
            fixture.cloud.broker.clear().unwrap();
        } else {
            let record = fixture.cloud.broker.snapshot().unwrap().record.unwrap();
            fixture.cloud.broker.save(record).unwrap();
        }
        assert!(
            api::native_operation(&fixture.cloud.state, &fixture.cloud.broker, fixture.stop())
                .await
                .is_err()
        );
        assert_eq!(fixture.helper.requests().len(), before);
        fixture.helper.client.shutdown().await;
    }
}

#[tokio::test]
async fn identity_rotation_during_cleanup_cannot_return_the_previous_owner_snapshot() {
    for reauthenticate in [false, true] {
        let fixture = AudioFixture::new(Some("describe")).await;
        std::fs::write(fixture.helper.root.join("hold_method"), "audio_stop").unwrap();
        let state = fixture.cloud.state.clone();
        let broker = fixture.cloud.broker.clone();
        let input = fixture.stop();
        let stopping =
            tokio::spawn(async move { api::native_operation(&state, &broker, input).await });
        tokio::time::timeout(std::time::Duration::from_secs(2), async {
            while !fixture.helper.root.join("entered_method").is_file() {
                tokio::time::sleep(std::time::Duration::from_millis(5)).await;
            }
        })
        .await
        .unwrap();
        if reauthenticate {
            let record = fixture.cloud.broker.snapshot().unwrap().record.unwrap();
            fixture.cloud.broker.save(record).unwrap();
            // The new epoch authenticates the same owner, but cannot validate the old call.
            fixture.cloud.operation("describe").await.unwrap();
        } else {
            fixture.cloud.broker.clear().unwrap();
        }
        std::fs::write(fixture.helper.root.join("release_method"), "release").unwrap();
        assert!(stopping.await.unwrap().is_err());
        // The already-authorized reduction completes, but cannot expose old-owner data.
        assert_eq!(
            recordings_store::get(&fixture.cloud.state, &fixture.recording_id)
                .unwrap()
                .unwrap()
                .receipt["status"],
            "saved"
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
        fixture.helper.client.shutdown().await;
    }
}
