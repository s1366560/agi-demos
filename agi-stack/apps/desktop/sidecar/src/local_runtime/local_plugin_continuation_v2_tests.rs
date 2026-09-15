use super::*;
use agistack_core::{
    agent::types::{
        AgentAction, HitlKind, HitlRequest, SessionState, SessionStatus, TranscriptEntry,
    },
    model::Episode,
    ports::{CoreResult, LlmPort, MemoryDraft, ToolDefinition},
};
use std::sync::atomic::{AtomicBool, Ordering};

#[derive(Default)]
struct ContinuationLlm {
    saw_catalog: AtomicBool,
    saw_marker: AtomicBool,
    executed: AtomicBool,
    signout_before_dispatch: Option<std::sync::Weak<LocalRuntimeState>>,
}
#[async_trait::async_trait]
impl LlmPort for ContinuationLlm {
    async fn extract_memory(&self, _: &Episode) -> CoreResult<MemoryDraft> {
        unreachable!()
    }
    async fn decide(
        &self,
        _: &str,
        _: u64,
        _: &[TranscriptEntry],
        _: &[String],
    ) -> CoreResult<AgentAction> {
        panic!("typed catalog required")
    }
    async fn decide_with_tools(
        &self,
        _: &str,
        _: u64,
        transcript: &[TranscriptEntry],
        tools: &[ToolDefinition],
    ) -> CoreResult<AgentAction> {
        let first = !self.saw_catalog.swap(true, Ordering::SeqCst);
        let marker = tools.iter().find(|tool| {
            tool.description
                .as_deref()
                .is_some_and(|description| description.contains("qa_marketplace_marker"))
        });
        self.saw_marker.store(marker.is_some(), Ordering::SeqCst);
        if let Some(marker) = marker.filter(|_| first) {
            if let Some(state) = self
                .signout_before_dispatch
                .as_ref()
                .and_then(std::sync::Weak::upgrade)
            {
                let (status, body) =
                    request(&state, "POST", "/api/v1/auth/signout", json!({})).await;
                assert_eq!(status, StatusCode::OK, "{body}");
            }
            return Ok(AgentAction::CallTool {
                tool: marker.name.clone(),
                input_json: r#"{"input":"中"}"#.into(),
            });
        }
        self.executed.store(
            transcript
                .iter()
                .any(|item| item.content.contains("20260914") && item.content.contains("15")),
            Ordering::SeqCst,
        );
        Ok(AgentAction::Finish {
            answer: "Continuation checked".into(),
        })
    }
}
async fn wait_continuation(
    state: &Arc<LocalRuntimeState>,
    conversation_id: &str,
    llm: &ContinuationLlm,
) {
    tokio::time::timeout(std::time::Duration::from_secs(10), async {
        loop {
            if llm.saw_catalog.load(Ordering::SeqCst)
                && !state
                    .agent_runs
                    .lock()
                    .unwrap()
                    .contains_key(conversation_id)
            {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap();
}
async fn revoke_package(state: &Arc<LocalRuntimeState>, reference: &Value) {
    let (status, body) = request(
        state,
        "POST",
        &format!(
            "/api/v1/local-plugins/v2/installations/{}/revoke",
            reference["bundle_id"].as_str().unwrap()
        ),
        json!({"tenant_id":"local","project_id":"local-project","reference":reference}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
}

#[tokio::test]
async fn signed_plugin_resume_uses_current_request_identity_and_current_approval() {
    for mode in ["valid", "revoked", "signedout"] {
        let revoked = mode == "revoked";
        let (state, bytes) = setup().await;
        let reference = import(&state, &bytes).await;
        let (conversation, run) = run(&state).await;
        let paused = state
            .session_store
            .transition_run(
                &run.id,
                run.revision,
                local_runtime::DesktopRunStatus::Paused,
                None,
                &local_runtime::now_iso(),
            )
            .unwrap();
        let mut checkpoint = SessionState::new(
            conversation.id.clone(),
            &run.request_message,
            Some(&conversation.project_id),
        );
        checkpoint.status = SessionStatus::Paused;
        state.checkpoints.save(&checkpoint).await.unwrap();
        state
            .session_store
            .bind_checkpoint_authority(&paused, &local_runtime::now_iso())
            .unwrap();
        if revoked {
            revoke_package(&state, &reference).await;
        }
        let llm = Arc::new(ContinuationLlm {
            signout_before_dispatch: (mode == "signedout").then(|| Arc::downgrade(&state)),
            ..Default::default()
        });
        *state.test_llm_override.lock().unwrap() = Some(llm.clone());
        let (status, body) = request(
            &state,
            "POST",
            &format!("/api/v1/agent/runs/{}/resume", run.id),
            json!({"expected_revision":paused.revision}),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{body}");
        wait_continuation(&state, &conversation.id, &llm).await;
        assert_eq!(llm.saw_marker.load(Ordering::SeqCst), mode == "valid");
        assert_eq!(llm.executed.load(Ordering::SeqCst), mode == "valid");
    }
}

#[tokio::test]
async fn signed_plugin_plan_and_build_hitl_responses_use_fresh_operation_authority() {
    for build in [false, true] {
        for revoked in [false, true] {
            let (state, bytes) = setup().await;
            let reference = import(&state, &bytes).await;
            let (conversation, run) = if build {
                let (conversation, run) = run(&state).await;
                (conversation, Some(run))
            } else {
                local_runtime::tests::seed_plan_conversation(&state, "plugin-plan-hitl");
                (
                    state
                        .session_store
                        .conversation("plugin-plan-hitl")
                        .unwrap()
                        .unwrap(),
                    None,
                )
            };
            let mut checkpoint = SessionState::new(
                conversation.id.clone(),
                run.as_ref()
                    .map(|run| run.request_message.as_str())
                    .unwrap_or("Clarify then marker"),
                Some(&conversation.project_id),
            );
            checkpoint.status = SessionStatus::AwaitingInput;
            checkpoint.pending_hitl = Some(HitlRequest::new(
                "plugin-clarification",
                HitlKind::Clarification,
                "Which marker?",
            ));
            state.checkpoints.save(&checkpoint).await.unwrap();
            if let Some(run) = run.as_ref() {
                state
                    .session_store
                    .bind_checkpoint_authority(run, &local_runtime::now_iso())
                    .unwrap();
            }
            let pending = state
                .persist_pending_hitl(
                    &conversation.id,
                    run.as_ref().map(|run| run.id.as_str()),
                    &checkpoint,
                )
                .unwrap()
                .unwrap();
            if let Some(run) = run.as_ref() {
                state
                    .session_store
                    .transition_run(
                        &run.id,
                        run.revision,
                        local_runtime::DesktopRunStatus::NeedsInput,
                        None,
                        &local_runtime::now_iso(),
                    )
                    .unwrap();
            }
            if revoked {
                revoke_package(&state, &reference).await;
            }
            let llm = Arc::new(ContinuationLlm::default());
            *state.test_llm_override.lock().unwrap() = Some(llm.clone());
            let command = json!({"request_id":pending.id,"hitl_type":"clarification","response_data":{"answer":"Use signed marker"},"expected_revision":pending.authority_revision,"idempotency_key":"plugin-hitl-response"});
            let (status, body) = request(
                &state,
                "POST",
                "/api/v1/agent/hitl/respond",
                command.clone(),
            )
            .await;
            assert_eq!(status, StatusCode::OK, "{body}");
            wait_continuation(&state, &conversation.id, &llm).await;
            assert_eq!(
                llm.saw_marker.load(Ordering::SeqCst),
                !revoked,
                "build={build}, revoked={revoked}"
            );
            assert_eq!(llm.executed.load(Ordering::SeqCst), !revoked);
            let (status, body) =
                request(&state, "POST", "/api/v1/agent/hitl/respond", command).await;
            assert_eq!(status, StatusCode::OK, "{body}");
            assert_eq!(body["duplicate"], true);
        }
    }
}

#[tokio::test]
async fn signed_plugin_queued_input_promotion_gets_its_own_plan_identity() {
    let (state, bytes) = setup().await;
    import(&state, &bytes).await;
    let (conversation, run) = run(&state).await;
    let control = state
        .claim_agent_run(&conversation.id, Some(&run.id))
        .unwrap();
    let (status,queued)=request(&state,"POST",&format!("/api/v1/agent/runs/{}/inputs",run.id),json!({"expected_run_revision":run.revision,"message":"Marker in next plan","message_id":"plugin-queue-message","idempotency_key":"plugin-queue-input","delivery":"queue_next","references":[]})).await;
    assert_eq!(status, StatusCode::OK, "{queued}");
    let ready = state
        .session_store
        .transition_run(
            &run.id,
            run.revision,
            local_runtime::DesktopRunStatus::ReadyReview,
            None,
            &local_runtime::now_iso(),
        )
        .unwrap();
    let completed = state
        .session_store
        .transition_run(
            &run.id,
            ready.revision,
            local_runtime::DesktopRunStatus::Completed,
            None,
            &local_runtime::now_iso(),
        )
        .unwrap();
    state.release_agent_run_if_control(&conversation.id, &control);
    let llm = Arc::new(ContinuationLlm::default());
    *state.test_llm_override.lock().unwrap() = Some(llm.clone());
    let input_id = queued["input"]["id"].as_str().unwrap();
    let (status,body)=request(&state,"POST",&format!("/api/v1/agent/run-inputs/{input_id}/promote-to-plan"),json!({"expected_source_run_revision":completed.revision,"idempotency_key":"plugin-promotion"})).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    wait_continuation(&state, &conversation.id, &llm).await;
    assert!(llm.saw_marker.load(Ordering::SeqCst));
    assert!(llm.executed.load(Ordering::SeqCst));
}

#[tokio::test]
async fn signed_plugin_review_and_fork_continuations_bind_the_new_authoritative_run() {
    for action in ["review", "artifact", "fork"] {
        let (state, bytes) = setup().await;
        import(&state, &bytes).await;
        if action == "fork" {
            let root = state.workspace_root.lock().unwrap().clone();
            for args in [
                vec!["init", "-q"],
                vec![
                    "-c",
                    "user.name=QA Fixture",
                    "-c",
                    "user.email=qa@example.invalid",
                    "commit",
                    "--allow-empty",
                    "-qm",
                    "test: initialize recovery fixture",
                ],
            ] {
                let result = std::process::Command::new("git")
                    .arg("-C")
                    .arg(&root)
                    .args(args)
                    .output()
                    .unwrap();
                assert!(
                    result.status.success(),
                    "{}",
                    String::from_utf8_lossy(&result.stderr)
                );
            }
        }
        let (conversation, run) = run(&state).await;
        let next_status = if action == "fork" {
            local_runtime::DesktopRunStatus::Disconnected
        } else {
            local_runtime::DesktopRunStatus::ReadyReview
        };
        let ready = state
            .session_store
            .transition_run(
                &run.id,
                run.revision,
                next_status,
                None,
                &local_runtime::now_iso(),
            )
            .unwrap();
        let mut checkpoint = SessionState::new(
            conversation.id.clone(),
            &run.request_message,
            Some(&conversation.project_id),
        );
        checkpoint.status = if action == "fork" {
            SessionStatus::Paused
        } else {
            SessionStatus::Finished
        };
        checkpoint.answer = Some("Review the previous work".into());
        state.checkpoints.save(&checkpoint).await.unwrap();
        state
            .session_store
            .bind_checkpoint_authority(&ready, &local_runtime::now_iso())
            .unwrap();
        let (path, body) = match action {
            "review" => (
                format!("/api/v1/agent/runs/{}/review", run.id),
                json!({"expected_revision":ready.revision,"action":"request_changes","feedback":"Call marker for review"}),
            ),
            "fork" => (
                format!("/api/v1/agent/runs/{}/fork", run.id),
                json!({"expected_revision":ready.revision,"idempotency_key":"plugin-recovery-fork"}),
            ),
            _ => {
                let version=state.session_store.record_artifact_version(&conversation.id,Some(&run.id),&json!({"artifact_id":"plugin-report","artifact_version_id":"plugin-report-version","filename":"report.md","path":state.workspace_root.lock().unwrap().join("report.md"),"relative_path":"report.md","bytes":0,"sources":[],"checks":[]}),&local_runtime::now_iso()).unwrap();
                (
                    format!("/api/v1/agent/artifact-versions/{}/review", version.id),
                    json!({"expected_revision":version.revision,"run_expected_revision":ready.revision,"action":"request_changes","feedback":"Call marker for artifact review"}),
                )
            }
        };
        let llm = Arc::new(ContinuationLlm::default());
        *state.test_llm_override.lock().unwrap() = Some(llm.clone());
        let (status, body) = request(&state, "POST", &path, body).await;
        assert_eq!(status, StatusCode::OK, "{action}: {body}");
        wait_continuation(&state, &conversation.id, &llm).await;
        assert!(llm.saw_marker.load(Ordering::SeqCst), "{action}");
        assert!(llm.executed.load(Ordering::SeqCst), "{action}");
    }
}

#[tokio::test]
async fn signed_plugin_unstarted_recovery_captures_the_fresh_resume_request() {
    let (state, bytes) = setup().await;
    import(&state, &bytes).await;
    local_runtime::tests::seed_plan_conversation(&state, "queued-plugin-recovery");
    let conversation = state
        .session_store
        .conversation("queued-plugin-recovery")
        .unwrap()
        .unwrap();
    let now = local_runtime::now_iso();
    state.session_store.replace_agent_plan_tasks(&conversation.id,&[json!({"id":"queued-plugin-task","conversation_id":conversation.id,"content":"Run marker after approved restart","status":"pending","priority":"high","order_index":0,"created_at":now,"updated_at":now})]).unwrap();
    let plan = state
        .session_store
        .latest_draft_plan(&conversation.id)
        .unwrap()
        .unwrap();
    let environment = state
        .worktree_manager()
        .prepare(
            local_runtime::DesktopExecutionEnvironmentKind::Local,
            "queued-plugin-environment",
            &now,
        )
        .unwrap()
        .environment;
    let queued = state
        .session_store
        .approve_plan_and_start_in_environment(
            local_runtime::session_store::ApprovePlanStartInput {
                conversation_id: &conversation.id,
                project_id: &conversation.project_id,
                plan_version_id: &plan.id,
                expected_plan_version: plan.version,
                idempotency_key: "queued-plugin-approved",
                message_id: "queued-plugin-message",
                request_message: "Run marker after approved restart",
                environment: Some(environment),
                requested_environment_kind: local_runtime::DesktopExecutionEnvironmentKind::Local,
                permission_profile: local_runtime::DesktopPermissionProfile::ReadOnly,
                now: &now,
            },
        )
        .unwrap()
        .run;
    local_runtime::authority_store::recover_interrupted_runs(
        &state.session_store.connection().unwrap(),
        &local_runtime::now_iso(),
    )
    .unwrap();
    let interrupted = state.session_store.run(&queued.id).unwrap().unwrap();
    assert!(local_runtime::authority_store::is_recovered_unstarted_run(
        &interrupted
    ));
    let llm = Arc::new(ContinuationLlm::default());
    *state.test_llm_override.lock().unwrap() = Some(llm.clone());
    let (status, body) = request(
        &state,
        "POST",
        &format!("/api/v1/agent/runs/{}/resume", queued.id),
        json!({"expected_revision":interrupted.revision}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["status"], "restart_requested");
    wait_continuation(&state, &conversation.id, &llm).await;
    assert!(llm.saw_marker.load(Ordering::SeqCst));
    assert!(llm.executed.load(Ordering::SeqCst));
}
