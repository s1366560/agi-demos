//! Bound proposals cannot be released through ordinary HITL replay.
use std::sync::{Arc, Mutex};

use agistack_adapters_mem::{FixedClock, InMemoryCheckpointStore, ScriptedLlm};
use agistack_core::automation_permission::PermissionSuspensionPort;
use agistack_core::ports::{CheckpointStore, CoreResult, ToolHost};
use agistack_core::{AgentAction, HitlRequest, ReActEngine, SessionState, SessionStatus};
use async_trait::async_trait;
use futures::executor::block_on;

struct NoTools;
#[async_trait]
impl ToolHost for NoTools {
    fn list_tools(&self) -> Vec<String> {
        vec!["workspace.write".into()]
    }
    async fn call(&self, _: &str, _: &str) -> CoreResult<String> {
        panic!("permission proposal must not dispatch")
    }
}

#[derive(Default)]
struct Capture(Mutex<Vec<SessionState>>);
#[async_trait]
impl PermissionSuspensionPort for Capture {
    async fn suspend(&self, state: &SessionState) -> CoreResult<()> {
        self.0.lock().unwrap().push(state.clone());
        Ok(())
    }
}

fn request() -> HitlRequest {
    serde_json::from_value(serde_json::json!({
        "id": "permission-1", "kind": "permission", "prompt": "Apply patch?",
        "permission_invocation": {"tool": "workspace.write", "input": {"path": "a.rs"}},
        "decision": {
            "action": {"name": "workspace.write", "label": "Write file"},
            "target": {"kind": "file", "id": "a.rs"},
            "data": {"summary": "Replace file", "redacted_fields": []},
            "reason": "Requested change", "risk": {"level": "low", "rationale": "Single file"},
            "reversibility": {"mode": "reversible", "recovery": "Restore file"},
            "scope": {"kind": "files", "ids": ["a.rs"]},
            "evidence": [{"kind": "diff", "id": "diff-1", "label": "Proposed patch"}]
        }
    }))
    .unwrap()
}

fn engine(request: HitlRequest, checkpoints: Arc<InMemoryCheckpointStore>) -> ReActEngine {
    ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![AgentAction::RequestHuman {
            request,
        }])),
        Arc::new(NoTools),
        checkpoints,
        Arc::new(FixedClock(0)),
    )
}

#[test]
fn complete_postdecision_state_goes_only_to_atomic_port() {
    block_on(async {
        let checkpoints = Arc::new(InMemoryCheckpointStore::new());
        let capture = Arc::new(Capture::default());
        let result = engine(request(), checkpoints.clone())
            .with_permission_suspension(capture.clone())
            .run("session", "write", Some("project"))
            .await
            .unwrap();
        assert_eq!(result.status, SessionStatus::AwaitingInput);
        assert!(result
            .pending_hitl
            .as_ref()
            .unwrap()
            .permission_invocation
            .is_some());
        assert!(!result.transcript.is_empty());
        assert_eq!(
            serde_json::to_value(&capture.0.lock().unwrap()[0]).unwrap(),
            serde_json::to_value(&result).unwrap()
        );
        assert!(checkpoints.load("session").await.unwrap().is_none());
    });
}

#[test]
fn missing_port_or_invalid_kind_or_incomplete_decision_fails_without_checkpoint() {
    block_on(async {
        for case in 0..3 {
            let checkpoints = Arc::new(InMemoryCheckpointStore::new());
            let mut proposal = request();
            if case == 1 {
                proposal.kind = agistack_core::HitlKind::Decision;
            }
            if case == 2 {
                proposal.decision = None;
            }
            let mut engine = engine(proposal, checkpoints.clone());
            if case != 0 {
                engine = engine.with_permission_suspension(Arc::new(Capture::default()));
            }
            assert!(engine
                .run("session", "write", Some("project"))
                .await
                .is_err());
            assert!(checkpoints.load("session").await.unwrap().is_none());
        }
    });
}

#[test]
fn ordinary_resume_and_recorded_answer_replay_cannot_release_bound_request() {
    block_on(async {
        for status in [SessionStatus::AwaitingInput, SessionStatus::Running] {
            let checkpoints = Arc::new(InMemoryCheckpointStore::new());
            let mut state = SessionState::new("session", "write", Some("project"));
            state.pending_hitl = Some(request());
            state.status = status;
            state.record_hitl_answer("permission-1", "allow_once");
            checkpoints.save(&state).await.unwrap();
            let runner = engine(request(), checkpoints.clone());
            assert!(runner
                .accept_human_response("session", "permission-1", "allow_once")
                .await
                .is_err());
            if status == SessionStatus::Running {
                assert!(runner
                    .run("session", "write", Some("project"))
                    .await
                    .is_err());
            }
            assert_eq!(
                serde_json::to_value(checkpoints.load("session").await.unwrap()).unwrap(),
                serde_json::to_value(Some(state)).unwrap()
            );
        }
    });
}
