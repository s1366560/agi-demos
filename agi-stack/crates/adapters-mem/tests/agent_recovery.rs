//! ReAct engine behaviour against in-memory adapters: a happy-path two-round
//! loop, **crash recovery that reuses completed tool calls** (ADR-0005), and the
//! structural round-budget circuit-breaker.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use agistack_adapters_mem::{FixedClock, InMemoryCheckpointStore, ScriptedLlm, StubLlm};
use agistack_core::agent::types::{CompletedCall, Role, TranscriptEntry};
use agistack_core::ports::{CheckpointStore, CoreResult, ToolHost};
use agistack_core::{AgentAction, ReActEngine, SessionState, SessionStatus};
use async_trait::async_trait;
use futures::executor::block_on;

/// A `ToolHost` that counts how many times a tool was actually invoked — lets us
/// prove a resumed engine does NOT re-run a tool whose result was already saved.
struct CountingToolHost {
    tools: Vec<String>,
    calls: AtomicUsize,
}

impl CountingToolHost {
    fn new(tools: &[&str]) -> Self {
        Self {
            tools: tools.iter().map(|s| s.to_string()).collect(),
            calls: AtomicUsize::new(0),
        }
    }
    fn count(&self) -> usize {
        self.calls.load(Ordering::SeqCst)
    }
}

#[async_trait]
impl ToolHost for CountingToolHost {
    fn list_tools(&self) -> Vec<String> {
        self.tools.clone()
    }
    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Ok(serde_json::json!({ "tool": tool, "echo": input_json }).to_string())
    }
}

const LEN_INPUT: &str = r#"{"text":"hello"}"#;

/// StubLlm drives: round 0 calls the first available tool, round 1 finishes with
/// the last observation. The tool runs exactly once and the answer is its output.
#[test]
fn happy_path_runs_tool_once_then_finishes() {
    let tools = Arc::new(CountingToolHost::new(&["len"]));
    let checkpoints = Arc::new(InMemoryCheckpointStore::new());
    let engine = ReActEngine::new(
        Arc::new(StubLlm),
        tools.clone(),
        checkpoints.clone(),
        Arc::new(FixedClock(0)),
    );

    let state = block_on(engine.run("s-happy", "summarize hello", Some("p1"))).unwrap();

    assert_eq!(state.status, SessionStatus::Finished);
    assert_eq!(tools.count(), 1, "tool should run exactly once");
    let answer = state.answer.expect("answer set");
    assert!(
        answer.contains("\"tool\":\"len\""),
        "unexpected answer: {answer}"
    );

    // A checkpoint was persisted for the finished session.
    let saved = block_on(checkpoints.load("s-happy")).unwrap().unwrap();
    assert_eq!(saved.status, SessionStatus::Finished);
}

/// Crash recovery: a checkpoint already holds a completed round-0 tool call. A
/// fresh engine resuming it must REUSE that saved output (counter stays 0) and
/// must not duplicate the round-0 Action line.
#[test]
fn resume_reuses_completed_tool_call_without_reinvoking() {
    let tools = Arc::new(CountingToolHost::new(&["len"]));
    let checkpoints = Arc::new(InMemoryCheckpointStore::new());

    // Simulate a crash AFTER the round-0 tool executed and was persisted, but
    // BEFORE the round finished: round still 0, Action recorded, output saved.
    let mut seeded = SessionState::new("s-resume", "len of hello", Some("p1"));
    seeded.push_unique(TranscriptEntry::new(
        0,
        Role::Action,
        format!("len {LEN_INPUT}"),
    ));
    seeded.completed_tool_calls.push(CompletedCall {
        round: 0,
        tool: "len".into(),
        input_json: LEN_INPUT.into(),
        output_json: r#"{"reused":true,"len":5}"#.into(),
    });
    checkpoints.seed(seeded).unwrap();

    // The script replays the SAME round-0 call (so the engine matches it against
    // the saved completed call), then finishes.
    let script = vec![
        AgentAction::CallTool {
            tool: "len".into(),
            input_json: LEN_INPUT.into(),
        },
        AgentAction::Finish { answer: "5".into() },
    ];
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(script)),
        tools.clone(),
        checkpoints.clone(),
        Arc::new(FixedClock(0)),
    );

    let state = block_on(engine.run("s-resume", "len of hello", Some("p1"))).unwrap();

    assert_eq!(
        tools.count(),
        0,
        "saved tool output must be reused, not re-invoked"
    );
    assert_eq!(state.status, SessionStatus::Finished);
    assert_eq!(state.answer.as_deref(), Some("5"));

    // The reused output reached the transcript as the round-0 Observation.
    let obs: Vec<&TranscriptEntry> = state
        .transcript
        .iter()
        .filter(|e| e.role == Role::Observation && e.round == 0)
        .collect();
    assert_eq!(obs.len(), 1);
    assert!(obs[0].content.contains("reused"));

    // The pre-existing Action line was not duplicated on resume.
    let actions = state
        .transcript
        .iter()
        .filter(|e| e.role == Role::Action && e.round == 0)
        .count();
    assert_eq!(actions, 1, "round-0 Action must not be duplicated");
}

/// The round budget is a structural circuit-breaker: a tool-loop that never
/// finishes is forced to Failed once the budget is hit (not an infinite loop).
#[test]
fn round_budget_is_a_circuit_breaker() {
    // Script always calls a tool, never finishes.
    let action = AgentAction::CallTool {
        tool: "noop".into(),
        input_json: "{}".into(),
    };
    // Pad the script so every round within the budget calls the tool again.
    let script: Vec<AgentAction> = std::iter::repeat_n(action, 10).collect();

    let tools = Arc::new(CountingToolHost::new(&["noop"]));
    let checkpoints = Arc::new(InMemoryCheckpointStore::new());
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(script)),
        tools.clone(),
        checkpoints,
        Arc::new(FixedClock(0)),
    )
    .with_max_rounds(3);

    let state = block_on(engine.run("s-budget", "loop forever", None)).unwrap();
    assert_eq!(state.status, SessionStatus::Failed);
    assert!(state.round >= 3);
}
