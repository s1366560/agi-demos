//! Wave N — robustness: the structural doom-loop / cost triggers wired into the
//! ReAct loop, and the Agent-First split between a *fired trigger* (deterministic)
//! and the *verdict* (an injected [`SupervisorPort`] agent). These run against the
//! in-memory adapters, exactly like the recovery/HITL suites.

use std::sync::{Arc, Mutex};

use agistack_adapters_mem::{FixedClock, InMemoryCheckpointStore, ScriptedLlm};
use agistack_core::agent::types::TranscriptEntry;
use agistack_core::ports::{CheckpointStore, CoreResult, ToolHost};
use agistack_core::{
    AgentAction, CostBudget, Health, NextAction, ReActEngine, SessionStatus, SupervisorPort,
    SupervisorVerdict, TriggerReason,
};
use async_trait::async_trait;
use futures::executor::block_on;

/// A minimal tool host: one tool, echoes its input. (We assert on control flow,
/// not tool output here.)
struct SpinToolHost;

#[async_trait]
impl ToolHost for SpinToolHost {
    fn list_tools(&self) -> Vec<String> {
        vec!["noop".into()]
    }
    async fn call(&self, _tool: &str, input_json: &str) -> CoreResult<String> {
        Ok(input_json.to_string())
    }
}

/// A supervisor that returns a canned verdict and records every trigger reason it
/// was consulted about — enough to assert the engine consulted the *agent* rather
/// than deciding the outcome itself.
struct FakeSupervisor {
    verdict: SupervisorVerdict,
    calls: Arc<Mutex<Vec<TriggerReason>>>,
}

impl FakeSupervisor {
    fn new(verdict: SupervisorVerdict) -> Self {
        Self {
            verdict,
            calls: Arc::new(Mutex::new(Vec::new())),
        }
    }
    fn log(&self) -> Arc<Mutex<Vec<TriggerReason>>> {
        self.calls.clone()
    }
}

#[async_trait]
impl SupervisorPort for FakeSupervisor {
    async fn review(
        &self,
        reason: TriggerReason,
        _round: u64,
        _transcript: &[TranscriptEntry],
    ) -> CoreResult<SupervisorVerdict> {
        self.calls.lock().unwrap().push(reason);
        Ok(self.verdict.clone())
    }
}

/// A script that repeats the identical tool call every round (so the doom-loop
/// detector sees the same action key recur).
fn same_call_script(n: usize) -> Vec<AgentAction> {
    vec![
        AgentAction::CallTool {
            tool: "noop".into(),
            input_json: "{}".into(),
        };
        n
    ]
}

/// A script whose tool input differs every round (so the doom-loop detector never
/// fires — used to isolate the cost trigger).
fn distinct_call_script(n: usize) -> Vec<AgentAction> {
    (0..n)
        .map(|i| AgentAction::CallTool {
            tool: "noop".into(),
            input_json: format!("{{\"r\":{i}}}"),
        })
        .collect()
}

/// With no supervisor injected, a fired doom-loop trigger is a deterministic
/// structural stop — the engine ends the session itself (no semantic verdict).
#[test]
fn doom_loop_without_supervisor_is_structural_stop() {
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(same_call_script(20))),
        Arc::new(SpinToolHost),
        Arc::new(InMemoryCheckpointStore::new()),
        Arc::new(FixedClock(0)),
    )
    .with_doom_loop(5, 3);

    let state = block_on(engine.run("s-doom", "spin", None)).unwrap();

    assert_eq!(state.status, SessionStatus::Failed);
    // Threshold 3 -> fires on the 3rd identical call, i.e. round index 2, and the
    // loop breaks before advancing the round.
    assert_eq!(state.round, 2);
    assert_eq!(
        state.answer.as_deref(),
        Some("structural stop: DoomLoop"),
        "transcript: {:?}",
        state.transcript
    );
}

/// A fired trigger consults the supervisor; a `looping -> escalate` verdict ends
/// the session with the agent's rationale (Agent First: the verdict is the
/// agent's, the engine only acts on it).
#[test]
fn doom_loop_with_supervisor_escalate_ends_session() {
    let supervisor = Arc::new(FakeSupervisor::new(SupervisorVerdict::new(
        Health::Looping,
        NextAction::Escalate,
        "stuck repeating noop",
    )));
    let log = supervisor.log();

    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(same_call_script(20))),
        Arc::new(SpinToolHost),
        Arc::new(InMemoryCheckpointStore::new()),
        Arc::new(FixedClock(0)),
    )
    .with_doom_loop(5, 3)
    .with_supervisor(supervisor);

    let state = block_on(engine.run("s-esc", "spin", None)).unwrap();

    assert_eq!(state.status, SessionStatus::Failed);
    assert_eq!(state.round, 2);
    // The supervisor was consulted exactly once, about a doom-loop.
    assert_eq!(&*log.lock().unwrap(), &[TriggerReason::DoomLoop]);
    let answer = state.answer.unwrap();
    assert!(answer.contains("Escalate"), "answer: {answer}");
    assert!(answer.contains("stuck repeating noop"), "answer: {answer}");
    // The agent's judgment is audited in the transcript.
    assert!(
        state
            .transcript
            .iter()
            .any(|e| e.content.contains("supervisor[DoomLoop]")),
        "missing audit line: {:?}",
        state.transcript
    );
}

/// A `healthy -> continue` verdict overrules the structural trigger every round,
/// so the loop keeps going until the independent round-budget circuit-breaker
/// stops it. Proves the supervisor genuinely controls continuation.
#[test]
fn supervisor_continue_overrules_trigger_until_round_budget() {
    let supervisor = Arc::new(FakeSupervisor::new(SupervisorVerdict::new(
        Health::Healthy,
        NextAction::Continue,
        "making progress",
    )));
    let log = supervisor.log();

    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(same_call_script(20))),
        Arc::new(SpinToolHost),
        Arc::new(InMemoryCheckpointStore::new()),
        Arc::new(FixedClock(0)),
    )
    .with_doom_loop(5, 3)
    .with_supervisor(supervisor)
    .with_max_rounds(6);

    let state = block_on(engine.run("s-cont", "spin", None)).unwrap();

    assert_eq!(state.status, SessionStatus::Failed);
    assert!(state.round >= 6, "round: {}", state.round);
    // The round-budget circuit-breaker records its reason in the transcript.
    assert!(
        state
            .transcript
            .iter()
            .any(|e| e.content == "round budget exhausted"),
        "transcript: {:?}",
        state.transcript
    );
    // Consulted repeatedly (rounds 2..5), always about a doom-loop, always Continue.
    let calls = log.lock().unwrap();
    assert!(
        calls.len() >= 3,
        "supervisor consulted {} times",
        calls.len()
    );
    assert!(calls.iter().all(|r| *r == TriggerReason::DoomLoop));
}

/// The cost ceiling is pure arithmetic: with a 3-round budget and distinct actions
/// (so doom never fires), the session stops at the round that hits the budget.
#[test]
fn cost_ceiling_without_supervisor_stops() {
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(distinct_call_script(20))),
        Arc::new(SpinToolHost),
        Arc::new(InMemoryCheckpointStore::new()),
        Arc::new(FixedClock(0)),
    )
    .with_cost_budget(CostBudget::rounds(3));

    let state = block_on(engine.run("s-cost", "spin", None)).unwrap();

    assert_eq!(state.status, SessionStatus::Failed);
    // rounds counted at the boundary: 1,2,3 -> fires when the 3rd completes, i.e.
    // at round index 2, before the round is advanced.
    assert_eq!(state.round, 2);
    assert_eq!(
        state.answer.as_deref(),
        Some("structural stop: CostCeiling")
    );
}

/// A cost trigger with a supervisor: a `stalled -> reassign` verdict ends the
/// session and is recorded as consulted about a cost ceiling.
#[test]
fn cost_ceiling_with_supervisor_reassign_ends_session() {
    let supervisor = Arc::new(FakeSupervisor::new(SupervisorVerdict::new(
        Health::Stalled,
        NextAction::Reassign,
        "over budget",
    )));
    let log = supervisor.log();

    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(distinct_call_script(20))),
        Arc::new(SpinToolHost),
        Arc::new(InMemoryCheckpointStore::new()),
        Arc::new(FixedClock(0)),
    )
    .with_cost_budget(CostBudget::rounds(3))
    .with_supervisor(supervisor);

    let state = block_on(engine.run("s-cost2", "spin", None)).unwrap();

    assert_eq!(state.status, SessionStatus::Failed);
    assert_eq!(&*log.lock().unwrap(), &[TriggerReason::CostCeiling]);
    let answer = state.answer.unwrap();
    assert!(answer.contains("Reassign"), "answer: {answer}");
}

/// Without any trigger armed, the engine behaves exactly as before (no regression
/// from the Wave N wiring): a finishing script completes normally.
#[test]
fn no_triggers_armed_is_unchanged_behaviour() {
    let script = vec![
        AgentAction::CallTool {
            tool: "noop".into(),
            input_json: "{}".into(),
        },
        AgentAction::Finish {
            answer: "done".into(),
        },
    ];
    let checkpoints = Arc::new(InMemoryCheckpointStore::new());
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(script)),
        Arc::new(SpinToolHost),
        checkpoints.clone(),
        Arc::new(FixedClock(0)),
    );

    let state = block_on(engine.run("s-plain", "spin", None)).unwrap();
    assert_eq!(state.status, SessionStatus::Finished);
    assert_eq!(state.answer.as_deref(), Some("done"));
    let saved = block_on(checkpoints.load("s-plain")).unwrap().unwrap();
    assert_eq!(saved.status, SessionStatus::Finished);
}
