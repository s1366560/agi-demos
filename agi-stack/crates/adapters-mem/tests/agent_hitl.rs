//! HITL suspend/resume (ADR-0004/0005) against in-memory adapters: a ReAct loop
//! does real work, then suspends on a human-in-the-loop request at a round
//! boundary; a *fresh* engine resumes with the answer and drives to completion —
//! reusing the already-completed tool call (counter stays 1) and never re-asking.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use async_trait::async_trait;
use futures::executor::block_on;

use agistack_adapters_mem::{FixedClock, InMemoryCheckpointStore, ScriptedLlm};
use agistack_core::model::Episode;
use agistack_core::ports::{
    CheckpointStore, CoreError, CoreResult, LlmPort, MemoryDraft, ToolHost,
};
use agistack_core::{
    AgentAction, HitlKind, HitlRequest, ReActEngine, Role, SessionStatus, TranscriptEntry,
};

/// A non-deterministic resume stub: it asks for HITL once by call count, then
/// finishes on every later decision instead of re-emitting the same request.
struct NonReemittingHitlLlm {
    calls: Arc<AtomicUsize>,
}

#[async_trait]
impl LlmPort for NonReemittingHitlLlm {
    async fn extract_memory(&self, _episode: &Episode) -> CoreResult<MemoryDraft> {
        Err(CoreError::Llm(
            "NonReemittingHitlLlm does not extract memory".into(),
        ))
    }

    async fn decide(
        &self,
        _goal: &str,
        _round: u64,
        _transcript: &[TranscriptEntry],
        _available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        if self.calls.fetch_add(1, Ordering::SeqCst) == 0 {
            Ok(AgentAction::RequestHuman {
                request: HitlRequest::new("approve-nonrepeat", HitlKind::Decision, "approve?"),
            })
        } else {
            Ok(AgentAction::Finish {
                answer: "finished after resume".into(),
            })
        }
    }
}

/// Counts tool invocations so we can prove a resumed loop does NOT re-run a tool
/// whose output was already persisted before the suspension.
struct CountingToolHost {
    calls: AtomicUsize,
}
#[async_trait]
impl ToolHost for CountingToolHost {
    fn list_tools(&self) -> Vec<String> {
        vec!["work".into()]
    }
    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Ok(serde_json::json!({ "tool": tool, "echo": input_json }).to_string())
    }
}

/// round 0 does work, round 1 asks a human for permission, round 2 finishes.
fn script() -> Vec<AgentAction> {
    vec![
        AgentAction::CallTool {
            tool: "work".into(),
            input_json: r#"{"text":"deploy"}"#.into(),
        },
        AgentAction::RequestHuman {
            request: HitlRequest::new("approve-1", HitlKind::Permission, "approve deploy?"),
        },
        AgentAction::Finish {
            answer: "deployed".into(),
        },
    ]
}

#[test]
fn suspends_on_hitl_then_resumes_reusing_completed_work() {
    let checkpoints = Arc::new(InMemoryCheckpointStore::new());
    let tools = Arc::new(CountingToolHost {
        calls: AtomicUsize::new(0),
    });

    // --- Engine #1: run until it suspends on the HITL request. ---
    let engine1 = ReActEngine::new(
        Arc::new(ScriptedLlm::new(script())),
        tools.clone(),
        checkpoints.clone(),
        Arc::new(FixedClock(0)),
    );
    let suspended = block_on(engine1.run("s-hitl", "deploy the app", Some("p1"))).unwrap();

    assert_eq!(suspended.status, SessionStatus::AwaitingInput);
    assert_eq!(
        suspended.round, 1,
        "suspends at the request round, not past it"
    );
    let pending = suspended.pending_hitl.as_ref().expect("a pending request");
    assert_eq!(pending.id, "approve-1");
    assert_eq!(pending.kind, HitlKind::Permission);
    assert_eq!(
        tools.calls.load(Ordering::SeqCst),
        1,
        "round-0 tool ran once"
    );
    assert!(suspended.answer.is_none());

    // A plain re-run while suspended is a no-op (status != Running).
    let still = block_on(engine1.run("s-hitl", "deploy the app", Some("p1"))).unwrap();
    assert_eq!(still.status, SessionStatus::AwaitingInput);
    assert_eq!(tools.calls.load(Ordering::SeqCst), 1);

    // --- Engine #2 (fresh process): resume with the human answer. ---
    let engine2 = ReActEngine::new(
        Arc::new(ScriptedLlm::new(script())),
        tools.clone(),
        checkpoints.clone(),
        Arc::new(FixedClock(0)),
    );
    let done = block_on(engine2.resume("s-hitl", "approve-1", "approved!")).unwrap();

    assert_eq!(done.status, SessionStatus::Finished);
    assert_eq!(done.answer.as_deref(), Some("deployed"));
    // Crucial: the round-0 tool was NOT re-run across the suspension.
    assert_eq!(
        tools.calls.load(Ordering::SeqCst),
        1,
        "completed tool call must be reused, not re-invoked, across resume"
    );
    // The human answer reached the transcript exactly once, at the request round.
    let human: Vec<&_> = done
        .transcript
        .iter()
        .filter(|e| e.role == Role::Human)
        .collect();
    assert_eq!(human.len(), 1);
    assert_eq!(human[0].round, 1);
    assert_eq!(human[0].content, "approved!");
    // The pending request was cleared and the answer persisted.
    assert!(done.pending_hitl.is_none());
    assert_eq!(done.hitl_answer("approve-1"), Some("approved!"));

    // The durable checkpoint reflects completion.
    let saved = block_on(checkpoints.load("s-hitl")).unwrap().unwrap();
    assert_eq!(saved.status, SessionStatus::Finished);
}

#[test]
fn resume_is_idempotent_and_validates_request_id() {
    let checkpoints = Arc::new(InMemoryCheckpointStore::new());
    let tools = Arc::new(CountingToolHost {
        calls: AtomicUsize::new(0),
    });
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(script())),
        tools.clone(),
        checkpoints.clone(),
        Arc::new(FixedClock(0)),
    );

    block_on(engine.run("s2", "deploy", Some("p1"))).unwrap();

    // Wrong request id is rejected (a structural guard, not a semantic verdict).
    let err = block_on(engine.resume("s2", "wrong-id", "x"));
    assert!(err.is_err(), "mismatched request id must error");

    // Correct resume finishes.
    let done = block_on(engine.resume("s2", "approve-1", "ok")).unwrap();
    assert_eq!(done.status, SessionStatus::Finished);

    // Resuming an already-finished session is a no-op returning the final state.
    let again = block_on(engine.resume("s2", "approve-1", "ok-again")).unwrap();
    assert_eq!(again.status, SessionStatus::Finished);
    assert_eq!(again.answer.as_deref(), Some("deployed"));
    // The original answer was not overwritten by the second resume.
    assert_eq!(again.hitl_answer("approve-1"), Some("ok"));
}

#[test]
fn resume_replays_answer_without_redeciding_suspended_round() {
    let checkpoints = Arc::new(InMemoryCheckpointStore::new());
    let tools = Arc::new(CountingToolHost {
        calls: AtomicUsize::new(0),
    });
    let decide_calls = Arc::new(AtomicUsize::new(0));
    let engine = ReActEngine::new(
        Arc::new(NonReemittingHitlLlm {
            calls: decide_calls.clone(),
        }),
        tools,
        checkpoints.clone(),
        Arc::new(FixedClock(0)),
    );

    let suspended = block_on(engine.run("s-hitl-nonrepeat", "decide", Some("p1"))).unwrap();

    assert_eq!(suspended.status, SessionStatus::AwaitingInput);
    let pending = agistack_core::pending_request(&suspended).expect("a pending request");
    assert_eq!(pending.id, "approve-nonrepeat");
    assert_eq!(decide_calls.load(Ordering::SeqCst), 1);

    let done =
        block_on(engine.resume("s-hitl-nonrepeat", "approve-nonrepeat", "approved")).unwrap();

    assert_eq!(done.status, SessionStatus::Finished);
    assert_eq!(done.answer.as_deref(), Some("finished after resume"));
    assert_eq!(
        decide_calls.load(Ordering::SeqCst),
        2,
        "resume must replay the HITL answer, advance, then decide the next round once"
    );
    assert!(
        done.transcript
            .iter()
            .any(|e| e.role == Role::Human && e.content == "approved"),
        "human answer must be observed even though decide did not re-emit HITL"
    );
    assert!(done.pending_hitl.is_none());
}
