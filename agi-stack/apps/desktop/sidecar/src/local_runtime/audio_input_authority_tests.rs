use super::*;
use crate::local_runtime::{
    auth_context::ContextSwitchRequest,
    computer_use_v2::repl_media,
    cua_repl,
    execution_authority::ExecutionScope,
    knowledge_authority_v2::agent_access::{self, PluginNativeIdentityV2, RunAuthorization},
    DesktopRunStatus,
};
use agistack_core::{agent::types::MediaAttachment, ports::ToolResult};
use serde_json::{json, Value};
use std::{path::PathBuf, sync::Mutex};

struct Model {
    seen: Mutex<Vec<Vec<TranscriptEntry>>>,
    on_call: Option<Box<dyn Fn() + Send + Sync>>,
    audio_supported: bool,
}

impl Default for Model {
    fn default() -> Self {
        Self {
            seen: Mutex::new(Vec::new()),
            on_call: None,
            audio_supported: true,
        }
    }
}

#[async_trait]
impl LlmPort for Model {
    fn supports_audio_input(&self) -> bool {
        self.audio_supported
    }

    async fn extract_memory(&self, _: &Episode) -> CoreResult<MemoryDraft> {
        unreachable!()
    }

    async fn decide(
        &self,
        _: &str,
        _: u64,
        transcript: &[TranscriptEntry],
        _: &[String],
    ) -> CoreResult<AgentAction> {
        self.seen.lock().unwrap().push(transcript.to_vec());
        if let Some(on_call) = &self.on_call {
            on_call();
        }
        Ok(AgentAction::Finish {
            answer: "accepted explicit audio".into(),
        })
    }

    async fn decide_with_tools_stream(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        _: &[ToolDefinition],
        on_text: &(dyn for<'text> Fn(&'text str) + Send + Sync),
    ) -> CoreResult<AgentAction> {
        on_text("before");
        let result = self.decide(goal, round, transcript, &[]).await;
        on_text("after");
        result
    }

    async fn decide_with_tools(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        _: &[ToolDefinition],
    ) -> CoreResult<AgentAction> {
        self.decide(goal, round, transcript, &[]).await
    }
}

struct Fixture {
    state: Arc<LocalRuntimeState>,
    conversation: LocalConversation,
    run: DesktopRun,
    authorization: Arc<RunAuthorization>,
    audio: MediaAttachment,
    root: PathBuf,
}

impl Drop for Fixture {
    fn drop(&mut self) {
        self.state.cua_repl.shutdown();
        std::fs::remove_dir_all(&self.root).unwrap();
    }
}

async fn publish_factory(state: &Arc<LocalRuntimeState>) {
    let mut wire: Value = serde_json::from_str(include_str!(
        "../../../../../../shared/profiles/memstack-default-bootstrap.v2.json"
    ))
    .unwrap();
    wire["generation"] = json!(20);
    wire.as_object_mut().unwrap().remove("digest");
    wire["digest"] =
        json!(crate::local_runtime::tool_authority::canonical_json_digest(&wire).unwrap());
    let snapshot = agistack_plugin_host::parse_profile_snapshot_v2(&wire.to_string()).unwrap();
    let generation = crate::local_runtime::platform_plugin_sync_v2::desktop_loader(None, None)
        .stage(snapshot.clone())
        .await
        .unwrap();
    state
        .platform_plugin_authority_v2
        .replace_local_baseline(&snapshot, &wire, generation)
        .dispose()
        .await;
}

impl Fixture {
    async fn new() -> Self {
        let (state, conversation, run, root) = cua_repl::test_support::state("audio-session");
        publish_factory(&state).await;
        let auth = state
            .session_store
            .validate_session_credential("audio-session", chrono::Utc::now().timestamp_millis())
            .unwrap()
            .unwrap();
        let authorization = RunAuthorization::capture(
            auth,
            Some(
                state
                    .platform_plugin_authority_v2
                    .acquire_generation()
                    .unwrap()
                    .into(),
            ),
            &conversation,
            &run.message_id,
            Some(&run.id),
        )
        .unwrap();
        state
            .claim_agent_run(&conversation.id, Some(&run.id))
            .unwrap();
        let source = root.join("source.wav");
        std::fs::write(&source, b"RIFF\x24\0\0\0WAVEfmt \x10\0\0\0\x01\0\x01\0\x40\x1f\0\0\x80\x3e\0\0\x02\0\x10\0data\0\0\0\0").unwrap();
        let audio = agent_access::scope(Some(authorization.clone()), async {
            let identity =
                PluginNativeIdentityV2::capture(&state, &conversation, Some(&run)).unwrap();
            let mut result = ToolResult::text("{}");
            result.media.push(MediaAttachment {
                artifact_path: source.to_string_lossy().into_owned(),
                mime_type: "audio/wav".into(),
            });
            repl_media::persist_local(
                &state,
                &identity,
                &ExecutionScope {
                    tenant_id: conversation.tenant_id.clone(),
                    project_id: conversation.project_id.clone(),
                    conversation_id: conversation.id.clone(),
                    run_id: run.id.clone(),
                    run_revision: run.revision,
                    engine_session_id: "audio-engine".into(),
                    device_id: Some(state.session_store.installation_id().into()),
                    connection_epoch: None,
                    generation: 20,
                },
                &mut result,
            )
            .await
            .unwrap();
            assert_ne!(result.media[0].artifact_path, source.to_string_lossy());
            result.media.remove(0)
        })
        .await;
        Self {
            state,
            conversation,
            run,
            authorization,
            audio,
            root,
        }
    }

    fn model(&self, probe: Arc<Model>) -> VisualInputLlm {
        VisualInputLlm::new(
            &self.state,
            &self.conversation,
            Some(&self.run),
            None,
            probe.clone(),
            probe,
        )
    }

    fn transcript(&self) -> Vec<TranscriptEntry> {
        vec![
            TranscriptEntry::new(0, Role::Human, "listen to the attached recording")
                .with_media(vec![self.audio.clone()]),
        ]
    }
}

async fn dispatch(
    model: &VisualInputLlm,
    transcript: &[TranscriptEntry],
    mode: u8,
) -> CoreResult<AgentAction> {
    match mode {
        0 => model.decide("listen", 1, transcript, &[]).await,
        1 => model.decide_with_tools("listen", 1, transcript, &[]).await,
        _ => {
            model
                .decide_with_tools_stream("listen", 1, transcript, &[], &|_| {})
                .await
        }
    }
}

async fn assert_denied(model: &VisualInputLlm, transcript: &[TranscriptEntry], expected: &str) {
    for mode in 0..3 {
        let error = dispatch(model, transcript, mode).await.unwrap_err();
        assert!(error.to_string().contains(expected), "{error}");
    }
}

#[tokio::test]
async fn current_native_identity_delivers_owned_human_and_emitted_audio_on_every_decide_path() {
    let f = Fixture::new().await;
    agent_access::scope(Some(f.authorization.clone()), async {
        for role in [Role::Human, Role::Observation] {
            let probe = Arc::new(Model::default());
            let model = f.model(probe.clone());
            let mut transcript = f.transcript();
            transcript[0].role = role;
            let original = transcript.clone();
            for mode in 0..3 {
                assert!(matches!(
                    dispatch(&model, &transcript, mode).await.unwrap(),
                    AgentAction::Finish { .. }
                ));
            }
            let seen = probe.seen.lock().unwrap();
            assert_eq!(seen.len(), 3);
            for delivered in seen.iter() {
                assert_eq!(delivered[0].media, transcript[0].media);
            }
            assert_eq!(transcript[0].media, original[0].media);
            assert_eq!(transcript[0].content, original[0].content);
        }
    })
    .await;
}

#[tokio::test]
async fn emitted_audio_stays_in_ui_when_the_selected_model_does_not_declare_audio_support() {
    let f = Fixture::new().await;
    agent_access::scope(Some(f.authorization.clone()), async {
        let probe = Arc::new(Model {
            audio_supported: false,
            ..Default::default()
        });
        let model = f.model(probe.clone());
        let mut transcript = f.transcript();
        transcript[0].role = Role::Observation;
        let original = transcript.clone();
        for mode in 0..3 {
            dispatch(&model, &transcript, mode).await.unwrap();
        }
        let seen = probe.seen.lock().unwrap();
        assert_eq!(seen.len(), 3);
        for delivered in seen.iter() {
            assert!(delivered[0].media.is_empty());
            assert!(delivered[0].content.contains("Audio bytes were not sent"));
            assert!(delivered[0].content.contains("audio_input_unsupported"));
        }
        assert_eq!(transcript[0].media, original[0].media);
        assert_eq!(transcript[0].content, original[0].content);
    })
    .await;
}

#[tokio::test]
async fn missing_or_revoked_native_identity_omits_emitted_audio_but_preserves_ui_output() {
    for revoked in [false, true] {
        let f = Fixture::new().await;
        let authorization = revoked.then(|| f.authorization.clone());
        agent_access::scope(authorization, async {
            let probe = Arc::new(Model::default());
            let model = f.model(probe.clone());
            if revoked {
                f.state
                    .session_store
                    .revoke_session("audio-session", chrono::Utc::now().timestamp_millis())
                    .unwrap();
            }
            let mut transcript = f.transcript();
            transcript[0].role = Role::Observation;
            let original = transcript.clone();
            for mode in 0..3 {
                dispatch(&model, &transcript, mode).await.unwrap();
            }
            let seen = probe.seen.lock().unwrap();
            assert_eq!(seen.len(), 3);
            for delivered in seen.iter() {
                assert!(delivered[0].media.is_empty());
                assert!(delivered[0].content.contains("Audio bytes were not sent"));
                assert!(delivered[0]
                    .content
                    .contains("audio_input_authority_unavailable"));
            }
            assert_eq!(transcript[0].media, original[0].media);
            assert_eq!(transcript[0].content, original[0].content);
        })
        .await;
    }
}

#[tokio::test]
async fn missing_native_identity_rejects_even_an_owned_artifact_before_dispatch() {
    let f = Fixture::new().await;
    let probe = Arc::new(Model::default());
    assert_denied(
        &f.model(probe.clone()),
        &f.transcript(),
        "audio_input_authority_required",
    )
    .await;
    assert!(probe.seen.lock().unwrap().is_empty());
}

#[tokio::test]
async fn mime_and_path_must_match_the_persisted_owned_artifact_before_dispatch() {
    let f = Fixture::new().await;
    agent_access::scope(Some(f.authorization.clone()), async {
        let probe = Arc::new(Model::default());
        let model = f.model(probe.clone());
        let mut transcript = f.transcript();
        transcript[0].media[0].mime_type = "audio/mpeg".into();
        assert_denied(&model, &transcript, "audio_input_artifact_not_owned").await;
        transcript = f.transcript();
        transcript[0].media[0].artifact_path =
            f.root.join("source.wav").to_string_lossy().into_owned();
        assert_denied(&model, &transcript, "audio_input_artifact_not_owned").await;
        std::fs::remove_file(&f.audio.artifact_path).unwrap();
        std::os::unix::fs::symlink(f.root.join("source.wav"), &f.audio.artifact_path).unwrap();
        assert_denied(&model, &f.transcript(), "audio_input_artifact_not_owned").await;
        assert!(probe.seen.lock().unwrap().is_empty());
    })
    .await;
}

#[tokio::test]
async fn another_conversation_cannot_submit_the_same_installations_audio() {
    let f = Fixture::new().await;
    let mut conversation = f.conversation.clone();
    conversation.id = uuid::Uuid::new_v4().to_string();
    f.state
        .session_store
        .insert_conversation(&conversation)
        .unwrap();
    let auth = f
        .state
        .session_store
        .validate_session_credential("audio-session", chrono::Utc::now().timestamp_millis())
        .unwrap()
        .unwrap();
    let authorization = RunAuthorization::capture(
        auth,
        Some(
            f.state
                .platform_plugin_authority_v2
                .acquire_generation()
                .unwrap()
                .into(),
        ),
        &conversation,
        "foreign-message",
        None,
    )
    .unwrap();
    agent_access::scope(Some(authorization), async {
        let probe = Arc::new(Model::default());
        let model = VisualInputLlm::new(
            &f.state,
            &conversation,
            None,
            None,
            probe.clone(),
            probe.clone(),
        );
        assert_denied(&model, &f.transcript(), "audio_input_artifact_not_owned").await;
        assert!(probe.seen.lock().unwrap().is_empty());
    })
    .await;
}

#[tokio::test]
async fn an_artifact_from_another_installation_is_not_model_input() {
    let f = Fixture::new().await;
    let foreign = Fixture::new().await;
    assert_ne!(
        f.state.session_store.installation_id(),
        foreign.state.session_store.installation_id()
    );
    agent_access::scope(Some(f.authorization.clone()), async {
        let probe = Arc::new(Model::default());
        let mut transcript = f.transcript();
        transcript[0].media[0] = foreign.audio.clone();
        assert_denied(
            &f.model(probe.clone()),
            &transcript,
            "audio_input_artifact_not_owned",
        )
        .await;
        assert!(probe.seen.lock().unwrap().is_empty());
    })
    .await;
}

#[tokio::test]
async fn signout_or_context_revision_change_revokes_audio_before_dispatch() {
    for signout in [false, true] {
        let f = Fixture::new().await;
        agent_access::scope(Some(f.authorization.clone()), async {
            let probe = Arc::new(Model::default());
            let model = f.model(probe.clone());
            let now = chrono::Utc::now().timestamp_millis();
            if signout {
                f.state
                    .session_store
                    .revoke_session("audio-session", now)
                    .unwrap();
            } else {
                let auth = f
                    .state
                    .session_store
                    .validate_session_credential("audio-session", now)
                    .unwrap()
                    .unwrap();
                f.state
                    .session_store
                    .switch_workspace_context(
                        &auth,
                        &ContextSwitchRequest {
                            tenant_id: auth.workspace.tenant_id.clone(),
                            project_id: auth.workspace.project_id.clone(),
                            expected_revision: auth.workspace.revision,
                            idempotency_key: "audio-context-revision".into(),
                        },
                        now,
                    )
                    .unwrap();
            }
            assert_denied(&model, &f.transcript(), "audio_input_authority_revoked").await;
            assert!(probe.seen.lock().unwrap().is_empty());
        })
        .await;
    }
}

#[tokio::test]
async fn paused_or_revised_running_execution_cannot_reuse_captured_audio_authority() {
    for resume in [false, true] {
        let f = Fixture::new().await;
        agent_access::scope(Some(f.authorization.clone()), async {
            let probe = Arc::new(Model::default());
            let model = f.model(probe.clone());
            let paused = f
                .state
                .session_store
                .transition_run(
                    &f.run.id,
                    f.run.revision,
                    DesktopRunStatus::Paused,
                    None,
                    &crate::local_runtime::now_iso(),
                )
                .unwrap();
            if resume {
                f.state
                    .session_store
                    .transition_run(
                        &paused.id,
                        paused.revision,
                        DesktopRunStatus::Running,
                        None,
                        &crate::local_runtime::now_iso(),
                    )
                    .unwrap();
            }
            assert_denied(&model, &f.transcript(), "audio_input_authority_revoked").await;
            assert!(probe.seen.lock().unwrap().is_empty());
        })
        .await;
    }
}

#[tokio::test]
async fn signout_during_provider_dispatch_discards_the_returned_finish() {
    for mode in 0..3 {
        let f = Fixture::new().await;
        agent_access::scope(Some(f.authorization.clone()), async {
            let state = f.state.clone();
            let probe = Arc::new(Model {
                on_call: Some(Box::new(move || {
                    state
                        .session_store
                        .revoke_session("audio-session", chrono::Utc::now().timestamp_millis())
                        .unwrap();
                })),
                ..Default::default()
            });
            let model = f.model(probe.clone());
            let received = Mutex::new(Vec::new());
            let error = if mode == 2 {
                model
                    .decide_with_tools_stream("listen", 1, &f.transcript(), &[], &|text| {
                        received.lock().unwrap().push(text.to_owned());
                    })
                    .await
            } else {
                dispatch(&model, &f.transcript(), mode).await
            }
            .unwrap_err();
            assert!(
                error.to_string().contains("audio_input_authority_revoked"),
                "{error}"
            );
            assert_eq!(probe.seen.lock().unwrap().len(), 1);
            if mode == 2 {
                assert_eq!(*received.lock().unwrap(), vec!["before"]);
            }
        })
        .await;
    }
}
