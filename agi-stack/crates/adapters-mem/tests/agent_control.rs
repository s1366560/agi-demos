//! Round-boundary pause/cancel control for the portable ReAct engine.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use agistack_adapters_mem::{FixedClock, InMemoryCheckpointStore, ScriptedLlm};
use agistack_core::ports::{CheckpointStore, CoreResult, ToolHost};
use agistack_core::{
    AgentAction, ReActControl, ReActEngine, Role, RunDirective, SessionStatus, SteeringInstruction,
};
use async_trait::async_trait;
use futures::executor::block_on;

struct CountingToolHost {
    calls: AtomicUsize,
}

#[async_trait]
impl ToolHost for CountingToolHost {
    fn list_tools(&self) -> Vec<String> {
        vec!["work".to_string()]
    }

    async fn call(&self, _tool: &str, _input_json: &str) -> CoreResult<String> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Ok(r#"{"worked":true}"#.to_string())
    }
}

struct PauseAfterFirstRound {
    checks: AtomicUsize,
}

#[async_trait]
impl ReActControl for PauseAfterFirstRound {
    async fn directive(&self, _session_id: &str, _round: u64) -> CoreResult<RunDirective> {
        let check = self.checks.fetch_add(1, Ordering::SeqCst);
        Ok(if check == 0 {
            RunDirective::Continue
        } else {
            RunDirective::Pause
        })
    }
}

struct ContinueControl;

#[async_trait]
impl ReActControl for ContinueControl {
    async fn directive(&self, _session_id: &str, _round: u64) -> CoreResult<RunDirective> {
        Ok(RunDirective::Continue)
    }
}

struct CancelImmediately;

#[async_trait]
impl ReActControl for CancelImmediately {
    async fn directive(&self, _session_id: &str, _round: u64) -> CoreResult<RunDirective> {
        Ok(RunDirective::Cancel)
    }
}

struct OneSteeringInstruction {
    instruction: Mutex<Option<SteeringInstruction>>,
    applied: Mutex<Vec<(String, u64)>>,
}

#[async_trait]
impl ReActControl for OneSteeringInstruction {
    async fn directive(&self, _session_id: &str, _round: u64) -> CoreResult<RunDirective> {
        Ok(self
            .instruction
            .lock()
            .expect("steering instruction")
            .clone()
            .map(RunDirective::Steer)
            .unwrap_or(RunDirective::Continue))
    }

    async fn acknowledge_steering(
        &self,
        _session_id: &str,
        instruction_id: &str,
        round: u64,
    ) -> CoreResult<()> {
        self.instruction
            .lock()
            .expect("steering instruction")
            .take();
        self.applied
            .lock()
            .expect("applied steering")
            .push((instruction_id.to_string(), round));
        Ok(())
    }
}

#[test]
fn pauses_only_at_a_checkpoint_and_resumes_without_repeating_work() {
    let checkpoints = Arc::new(InMemoryCheckpointStore::new());
    let tools = Arc::new(CountingToolHost {
        calls: AtomicUsize::new(0),
    });
    let script = vec![
        AgentAction::CallTool {
            tool: "work".to_string(),
            input_json: "{}".to_string(),
        },
        AgentAction::Finish {
            answer: "done".to_string(),
        },
    ];
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(script)),
        tools.clone(),
        checkpoints.clone(),
        Arc::new(FixedClock(0)),
    );

    let paused = block_on(engine.run_controlled(
        "controlled-pause",
        "do work",
        Some("project"),
        Arc::new(PauseAfterFirstRound {
            checks: AtomicUsize::new(0),
        }),
    ))
    .expect("pause at a round boundary");

    assert_eq!(paused.status, SessionStatus::Paused);
    assert_eq!(paused.round, 1);
    assert_eq!(tools.calls.load(Ordering::SeqCst), 1);
    let stored = block_on(checkpoints.load("controlled-pause"))
        .expect("load checkpoint")
        .expect("checkpoint exists");
    assert_eq!(stored.status, SessionStatus::Paused);

    block_on(engine.accept_controlled_resume("controlled-pause")).expect("resume checkpoint");
    let finished = block_on(engine.run_controlled(
        "controlled-pause",
        "do work",
        Some("project"),
        Arc::new(ContinueControl),
    ))
    .expect("finish after resume");

    assert_eq!(finished.status, SessionStatus::Finished);
    assert_eq!(tools.calls.load(Ordering::SeqCst), 1);
}

#[test]
fn cancel_persists_a_terminal_checkpoint_before_any_new_round() {
    let checkpoints = Arc::new(InMemoryCheckpointStore::new());
    let tools = Arc::new(CountingToolHost {
        calls: AtomicUsize::new(0),
    });
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![AgentAction::Finish {
            answer: "should not run".to_string(),
        }])),
        tools.clone(),
        checkpoints.clone(),
        Arc::new(FixedClock(0)),
    );

    let cancelled = block_on(engine.run_controlled(
        "controlled-cancel",
        "do work",
        Some("project"),
        Arc::new(CancelImmediately),
    ))
    .expect("cancel at the first boundary");

    assert_eq!(cancelled.status, SessionStatus::Cancelled);
    assert_eq!(cancelled.round, 0);
    assert_eq!(tools.calls.load(Ordering::SeqCst), 0);
    let stored = block_on(checkpoints.load("controlled-cancel"))
        .expect("load checkpoint")
        .expect("checkpoint exists");
    assert_eq!(stored.status, SessionStatus::Cancelled);
}

#[test]
fn steering_is_checkpointed_as_human_input_before_the_next_decision() {
    let checkpoints = Arc::new(InMemoryCheckpointStore::new());
    let control = Arc::new(OneSteeringInstruction {
        instruction: Mutex::new(Some(SteeringInstruction {
            id: "steer-1".to_string(),
            content: "Keep the public API stable.".to_string(),
        })),
        applied: Mutex::new(Vec::new()),
    });
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![AgentAction::Finish {
            answer: "done".to_string(),
        }])),
        Arc::new(CountingToolHost {
            calls: AtomicUsize::new(0),
        }),
        checkpoints.clone(),
        Arc::new(FixedClock(0)),
    );

    let finished = block_on(engine.run_controlled(
        "controlled-steering",
        "do work",
        Some("project"),
        control.clone(),
    ))
    .expect("apply steering at the first durable boundary");

    assert_eq!(finished.status, SessionStatus::Finished);
    assert_eq!(finished.applied_steering_ids, vec!["steer-1"]);
    assert!(finished.transcript.iter().any(|entry| {
        entry.role == Role::Human && entry.content == "Keep the public API stable."
    }));
    assert_eq!(
        control.applied.lock().expect("applied steering").as_slice(),
        &[("steer-1".to_string(), 0)]
    );
    let stored = block_on(checkpoints.load("controlled-steering"))
        .expect("load checkpoint")
        .expect("checkpoint exists");
    assert_eq!(stored.applied_steering_ids, vec!["steer-1"]);
}

#[test]
fn a_replayed_steering_id_is_acknowledged_without_duplicate_transcript_input() {
    let checkpoints = Arc::new(InMemoryCheckpointStore::new());
    let control = Arc::new(OneSteeringInstruction {
        instruction: Mutex::new(Some(SteeringInstruction {
            id: "steer-replayed".to_string(),
            content: "Do not duplicate this instruction.".to_string(),
        })),
        applied: Mutex::new(Vec::new()),
    });
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![AgentAction::Finish {
            answer: "done".to_string(),
        }])),
        Arc::new(CountingToolHost {
            calls: AtomicUsize::new(0),
        }),
        checkpoints.clone(),
        Arc::new(FixedClock(0)),
    );

    let first = block_on(engine.run_controlled(
        "controlled-steering-replay",
        "do work",
        Some("project"),
        control.clone(),
    ))
    .expect("apply steering");
    block_on(checkpoints.save(&agistack_core::SessionState {
        status: SessionStatus::Running,
        answer: None,
        ..first
    }))
    .expect("reopen checkpoint to simulate acknowledgement loss");
    *control.instruction.lock().expect("steering instruction") = Some(SteeringInstruction {
        id: "steer-replayed".to_string(),
        content: "Do not duplicate this instruction.".to_string(),
    });

    let replayed = block_on(engine.run_controlled(
        "controlled-steering-replay",
        "do work",
        Some("project"),
        control.clone(),
    ))
    .expect("acknowledge replayed steering");

    assert_eq!(
        replayed
            .transcript
            .iter()
            .filter(|entry| {
                entry.role == Role::Human && entry.content == "Do not duplicate this instruction."
            })
            .count(),
        1
    );
}
