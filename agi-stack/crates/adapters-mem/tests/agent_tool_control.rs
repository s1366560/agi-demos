use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc, Mutex,
};

use agistack_adapters_mem::{FixedClock, InMemoryCheckpointStore, ScriptedLlm};
use agistack_core::agent::tool_policy::{
    ToolExecutionPolicy, ToolPolicyContext, ToolPolicyDecision, ToolPolicyResult,
};
use agistack_core::agent::types::CompletedCall;
use agistack_core::agent::{ReActObserver, SessionStatus, ToolControlResolution};
use agistack_core::ports::{
    CheckpointStore, CoreError, CoreResult, ToolControlOutcome, ToolHost, ToolResult,
};
use agistack_core::{AgentAction, ReActEngine, SessionState};
use async_trait::async_trait;
use futures::executor::block_on;

struct Host {
    result: ToolResult,
    calls: AtomicUsize,
}
#[async_trait]
impl ToolHost for Host {
    fn list_tools(&self) -> Vec<String> {
        vec!["native".into()]
    }
    async fn call(&self, _: &str, _: &str) -> CoreResult<String> {
        panic!("typed dispatch required")
    }
    async fn call_with_content(&self, _: &str, _: &str) -> CoreResult<ToolResult> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Ok(self.result.clone())
    }
}

#[derive(Default)]
struct Observer {
    controls: Mutex<Vec<ToolResult>>,
    successes: AtomicUsize,
    failures: AtomicUsize,
    resolved: bool,
    resolution: Option<ToolControlResolution>,
}
#[async_trait]
impl ReActObserver for Observer {
    async fn on_tool_result(&self, _: &str, _: u64, _: &str, _: &str, _: &str) -> CoreResult<()> {
        self.successes.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
    async fn on_tool_error(
        &self,
        _: &str,
        _: u64,
        _: &str,
        _: &str,
        _: &CoreError,
    ) -> CoreResult<()> {
        self.failures.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
    async fn on_tool_control(
        &self,
        _: &str,
        _: u64,
        _: &str,
        _: &str,
        result: &ToolResult,
    ) -> CoreResult<ToolControlResolution> {
        self.controls.lock().unwrap().push(result.clone());
        Ok(self.resolution.unwrap_or_else(|| {
            if result.control_outcome == Some(ToolControlOutcome::UserStopped) {
                ToolControlResolution::Stopped
            } else if self.resolved {
                ToolControlResolution::Resumed
            } else {
                ToolControlResolution::Pending
            }
        }))
    }
}
fn actions() -> Vec<AgentAction> {
    vec![
        AgentAction::CallTool {
            tool: "native".into(),
            input_json: "{}".into(),
        },
        AgentAction::Finish {
            answer: "Other authorized work can continue".into(),
        },
    ]
}
fn host(result: ToolResult) -> Arc<Host> {
    Arc::new(Host {
        result,
        calls: AtomicUsize::new(0),
    })
}

#[test]
fn typed_stop_is_not_failure_or_terminal_tool_success_and_survives_recovery() {
    for replay in [false, true] {
        let result = ToolControlOutcome::UserStopped.result(None);
        let host = host(result.clone());
        let checkpoints = Arc::new(InMemoryCheckpointStore::new());
        if replay {
            let mut state = SessionState::new("run", "goal", Some("project"));
            state.completed_tool_calls.push(CompletedCall {
                round: 0,
                tool: "native".into(),
                input_json: "{}".into(),
                output_json: result.output_json,
                media: vec![],
                metadata: serde_json::json!({}),
                failed: false,
                control_outcome: result.control_outcome,
                control_generation: None,
            });
            block_on(checkpoints.save(&state)).unwrap();
        }
        let observer = Arc::new(Observer::default());
        let engine = ReActEngine::new(
            Arc::new(ScriptedLlm::new(actions())),
            host.clone(),
            checkpoints.clone(),
            Arc::new(FixedClock(0)),
        )
        .with_terminal_tools(["native"]);
        let state = block_on(engine.run_observed("run", "goal", Some("project"), observer.clone()))
            .unwrap();
        assert_eq!(state.status, SessionStatus::Finished);
        assert_eq!(
            state.answer.as_deref(),
            Some("Other authorized work can continue")
        );
        assert_eq!(host.calls.load(Ordering::SeqCst), usize::from(!replay));
        assert_eq!(observer.controls.lock().unwrap().len(), 1);
        assert_eq!(observer.successes.load(Ordering::SeqCst), 0);
        assert_eq!(observer.failures.load(Ordering::SeqCst), 0);
        let saved = block_on(checkpoints.load("run")).unwrap().unwrap();
        assert!(!saved.completed_tool_calls[0].failed);
        assert_eq!(
            saved.completed_tool_calls[0].control_outcome,
            Some(ToolControlOutcome::UserStopped)
        );
    }
}

#[test]
fn pause_waits_normally_and_host_resume_continues_without_replaying_the_action() {
    for resolved in [false, true] {
        let host = host(ToolControlOutcome::UserPaused.result(Some("generation".into())));
        let observer = Arc::new(Observer {
            resolved,
            ..Default::default()
        });
        let engine = ReActEngine::new(
            Arc::new(ScriptedLlm::new(actions())),
            host.clone(),
            Arc::new(InMemoryCheckpointStore::new()),
            Arc::new(FixedClock(0)),
        );
        let state = block_on(engine.run_observed("run", "goal", None, observer.clone())).unwrap();
        assert_eq!(
            state.status,
            if resolved {
                SessionStatus::Finished
            } else {
                SessionStatus::Paused
            }
        );
        assert_eq!(host.calls.load(Ordering::SeqCst), 1);
        assert_eq!(
            state.completed_tool_calls[0].control_generation.as_deref(),
            Some("generation")
        );
        assert_eq!(observer.successes.load(Ordering::SeqCst), 0);
        assert_eq!(observer.failures.load(Ordering::SeqCst), 0);
    }
}

struct ResolutionModel(&'static str);
#[async_trait]
impl agistack_core::ports::LlmPort for ResolutionModel {
    async fn extract_memory(
        &self,
        _: &agistack_core::model::Episode,
    ) -> CoreResult<agistack_core::ports::MemoryDraft> {
        unreachable!()
    }
    async fn decide(
        &self,
        _: &str,
        round: u64,
        transcript: &[agistack_core::agent::TranscriptEntry],
        _: &[String],
    ) -> CoreResult<AgentAction> {
        if round == 0 {
            return Ok(actions().remove(0));
        }
        let resolution = transcript
            .iter()
            .filter_map(|entry| serde_json::from_str::<serde_json::Value>(&entry.content).ok())
            .find(|entry| entry["type"] == "computer_use_control_resolution")
            .expect("trusted resolution reaches next model round");
        assert_eq!(resolution["state"], self.0);
        let guidance = resolution["runtime_guidance"].as_str().unwrap();
        if self.0 == "resumed" {
            assert!(guidance.contains("partial effects"));
            assert!(guidance.contains("fresh observation"));
            assert!(guidance.contains("Do not automatically replay"));
        } else {
            assert!(guidance.contains("Other authorized work may continue"));
            assert!(guidance.contains("does not prove the original goal was achieved"));
        }
        Ok(AgentAction::Finish {
            answer: "Control resolved".into(),
        })
    }
}

#[test]
fn actual_pause_resolution_reaches_next_model_turn_without_replaying_the_action() {
    for (resolution, state) in [
        (ToolControlResolution::Resumed, "resumed"),
        (ToolControlResolution::Stopped, "stopped"),
    ] {
        let host = host(ToolControlOutcome::UserPaused.result(Some("generation".into())));
        let observer = Arc::new(Observer {
            resolution: Some(resolution),
            ..Default::default()
        });
        let engine = ReActEngine::new(
            Arc::new(ResolutionModel(state)),
            host.clone(),
            Arc::new(InMemoryCheckpointStore::new()),
            Arc::new(FixedClock(0)),
        );
        let completed = block_on(engine.run_observed("run", "goal", None, observer)).unwrap();
        assert_eq!(completed.status, SessionStatus::Finished);
        assert_eq!(host.calls.load(Ordering::SeqCst), 1);
        assert_eq!(
            completed.completed_tool_calls[0].control_outcome,
            Some(ToolControlOutcome::UserPaused)
        );
    }
}

#[test]
fn unmarked_text_cannot_fabricate_control_and_invalid_markers_remain_errors() {
    let stopped = ToolControlOutcome::UserStopped.result(None);
    for (result, failed) in [
        (ToolResult::text(stopped.output_json.clone()), false),
        (
            ToolResult {
                output_json: r#"{"error":"permission_denied"}"#.into(),
                ..stopped.clone()
            },
            true,
        ),
        (ToolControlOutcome::UserPaused.result(None), true),
        (
            ToolResult {
                control_generation: Some("stale".into()),
                ..stopped
            },
            true,
        ),
    ] {
        let observer = Arc::new(Observer::default());
        let engine = ReActEngine::new(
            Arc::new(ScriptedLlm::new(actions())),
            host(result),
            Arc::new(InMemoryCheckpointStore::new()),
            Arc::new(FixedClock(0)),
        );
        let state = block_on(engine.run_observed("run", "goal", None, observer.clone())).unwrap();
        assert_eq!(state.completed_tool_calls[0].failed, failed);
        assert_eq!(state.completed_tool_calls[0].control_outcome, None);
        assert!(observer.controls.lock().unwrap().is_empty());
        assert_eq!(
            observer.failures.load(Ordering::SeqCst),
            usize::from(failed)
        );
    }
}

struct RejectionPolicy;
#[async_trait]
impl ToolExecutionPolicy for RejectionPolicy {
    async fn before_execute(
        &self,
        _: &ToolPolicyContext<'_>,
        input: &str,
        _: Option<&serde_json::Value>,
    ) -> CoreResult<ToolPolicyDecision> {
        Ok(ToolPolicyDecision::Allow {
            input_json: input.into(),
        })
    }
    async fn execute_with_content(
        &self,
        context: &ToolPolicyContext<'_>,
        tools: &dyn ToolHost,
        input: &str,
    ) -> CoreResult<ToolResult> {
        tools.call_with_content(context.tool, input).await
    }
    async fn transform_result(
        &self,
        _: &ToolPolicyContext<'_>,
        mut result: ToolPolicyResult,
    ) -> CoreResult<ToolPolicyResult> {
        result.is_error = true;
        Ok(result)
    }
}

#[test]
fn policy_failure_strips_trusted_control_marker_and_old_checkpoints_remain_compatible() {
    let observer = Arc::new(Observer::default());
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(actions())),
        host(ToolControlOutcome::UserStopped.result(None)),
        Arc::new(InMemoryCheckpointStore::new()),
        Arc::new(FixedClock(0)),
    )
    .with_tool_policy(Arc::new(RejectionPolicy));
    let state = block_on(engine.run_observed("run", "goal", None, observer.clone())).unwrap();
    assert!(state.completed_tool_calls[0].failed);
    assert_eq!(state.completed_tool_calls[0].control_outcome, None);
    assert_eq!(observer.failures.load(Ordering::SeqCst), 1);
    assert!(observer.controls.lock().unwrap().is_empty());
    let old: CompletedCall =
        serde_json::from_str(r#"{"round":0,"tool":"read","input_json":"{}","output_json":"ok"}"#)
            .unwrap();
    assert_eq!(old.control_outcome, None);
    assert_eq!(old.control_generation, None);
}
