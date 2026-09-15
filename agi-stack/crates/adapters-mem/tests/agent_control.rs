//! Round-boundary pause/cancel control for the portable ReAct engine.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use agistack_adapters_mem::{FixedClock, InMemoryCheckpointStore, ScriptedLlm};
use agistack_core::agent::react::ReActObserver;
use agistack_core::ports::{CheckpointStore, CoreResult, LlmPort, MemoryDraft, ToolHost};
use agistack_core::{
    AgentAction, Episode, ReActControl, ReActEngine, Role, RunDirective, SessionState,
    SessionStatus, SteeringInstruction, TranscriptEntry,
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

struct PauseAfterFirstRound;

#[async_trait]
impl ReActControl for PauseAfterFirstRound {
    async fn directive(&self, _session_id: &str, round: u64) -> CoreResult<RunDirective> {
        Ok(if round == 0 {
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
        Arc::new(PauseAfterFirstRound),
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

struct AsyncGate {
    entered: Mutex<Option<futures::channel::oneshot::Sender<()>>>,
    release: Mutex<Option<futures::channel::oneshot::Receiver<()>>>,
}

impl AsyncGate {
    fn new() -> (
        Self,
        futures::channel::oneshot::Receiver<()>,
        futures::channel::oneshot::Sender<()>,
    ) {
        let (entered, waiting) = futures::channel::oneshot::channel();
        let (resume, release) = futures::channel::oneshot::channel();
        (
            Self {
                entered: Mutex::new(Some(entered)),
                release: Mutex::new(Some(release)),
            },
            waiting,
            resume,
        )
    }

    async fn wait_once(&self) {
        let entered = self.entered.lock().unwrap().take();
        let release = self.release.lock().unwrap().take();
        if let Some(entered) = entered {
            entered.send(()).unwrap();
        }
        if let Some(release) = release {
            release.await.unwrap();
        }
    }
}

struct MutableControl {
    pending: Mutex<RunDirective>,
    acknowledged: Mutex<Vec<String>>,
}

impl MutableControl {
    fn new(directive: RunDirective) -> Self {
        Self {
            pending: Mutex::new(directive),
            acknowledged: Mutex::new(vec![]),
        }
    }
    fn set(&self, directive: RunDirective) {
        *self.pending.lock().unwrap() = directive;
    }
}

#[async_trait]
impl ReActControl for MutableControl {
    async fn directive(&self, _: &str, _: u64) -> CoreResult<RunDirective> {
        Ok(self.pending.lock().unwrap().clone())
    }
    async fn acknowledge_steering(&self, _: &str, id: &str, _: u64) -> CoreResult<()> {
        let mut pending = self.pending.lock().unwrap();
        if matches!(&*pending, RunDirective::Steer(instruction) if instruction.id == id) {
            *pending = RunDirective::Continue;
        }
        self.acknowledged.lock().unwrap().push(id.into());
        Ok(())
    }
}

struct BlockedLlm {
    gate: AsyncGate,
    stale_action: Option<AgentAction>,
    calls: AtomicUsize,
    transcripts: Mutex<Vec<Vec<TranscriptEntry>>>,
}

#[async_trait]
impl LlmPort for BlockedLlm {
    async fn extract_memory(&self, _: &Episode) -> CoreResult<MemoryDraft> {
        unreachable!("not a memory test")
    }
    async fn decide(
        &self,
        _: &str,
        _: u64,
        transcript: &[TranscriptEntry],
        _: &[String],
    ) -> CoreResult<AgentAction> {
        self.transcripts.lock().unwrap().push(transcript.to_vec());
        if self.calls.fetch_add(1, Ordering::SeqCst) == 0 {
            self.gate.wait_once().await;
            self.stale_action.clone().ok_or_else(|| {
                agistack_core::ports::CoreError::Llm("request failed after control arrived".into())
            })
        } else {
            Ok(AgentAction::Finish {
                answer: "fresh decision".into(),
            })
        }
    }
}

#[test]
fn controls_arriving_during_model_wait_discard_stale_tool_and_finish_decisions() {
    for directive in [
        RunDirective::Cancel,
        RunDirective::Pause,
        RunDirective::Steer(SteeringInstruction {
            id: "mid-model-steering".into(),
            content: "Use this revised instruction.".into(),
        }),
    ] {
        for stale_action in [
            Some(AgentAction::CallTool {
                tool: "work".into(),
                input_json: "{}".into(),
            }),
            Some(AgentAction::Finish {
                answer: "stale answer".into(),
            }),
            None,
        ] {
            let checkpoints = Arc::new(InMemoryCheckpointStore::new());
            let tools = Arc::new(CountingToolHost {
                calls: AtomicUsize::new(0),
            });
            let (gate, entered, release) = AsyncGate::new();
            let llm = Arc::new(BlockedLlm {
                gate,
                stale_action,
                calls: AtomicUsize::new(0),
                transcripts: Mutex::new(vec![]),
            });
            let control = Arc::new(MutableControl::new(RunDirective::Continue));
            let engine = ReActEngine::new(
                llm.clone(),
                tools.clone(),
                checkpoints.clone(),
                Arc::new(FixedClock(0)),
            );
            let (result, ()) = block_on(futures::future::join(
                engine.run_controlled(
                    "blocked-model",
                    "Original goal",
                    Some("project"),
                    control.clone(),
                ),
                async {
                    entered.await.unwrap();
                    control.set(directive.clone());
                    release.send(()).unwrap();
                },
            ));
            let result = result.expect("controlled model completes at a safe boundary");
            assert_eq!(tools.calls.load(Ordering::SeqCst), 0, "{directive:?}");
            let expected = match directive {
                RunDirective::Cancel => SessionStatus::Cancelled,
                RunDirective::Pause => SessionStatus::Paused,
                RunDirective::Steer(_) => SessionStatus::Finished,
                RunDirective::Continue => unreachable!(),
            };
            assert_eq!(result.status, expected, "{directive:?}");
            let stored = block_on(checkpoints.load("blocked-model"))
                .unwrap()
                .unwrap();
            assert_eq!(stored.status, expected);
            assert!(result.completed_tool_calls.is_empty());
            if matches!(directive, RunDirective::Steer(_)) {
                assert_eq!(result.answer.as_deref(), Some("fresh decision"));
                assert_eq!(llm.calls.load(Ordering::SeqCst), 2);
                assert!(llm.transcripts.lock().unwrap()[1]
                    .iter()
                    .any(|entry| entry.role == Role::Human
                        && entry.content == "Use this revised instruction."));
                assert_eq!(
                    control.acknowledged.lock().unwrap().as_slice(),
                    &["mid-model-steering"]
                );
            } else {
                assert!(result.answer.is_none());
                assert_eq!(result.round, 0);
            }
        }
    }
}

struct BlockedSteeringStore {
    inner: InMemoryCheckpointStore,
    gate: AsyncGate,
}

#[async_trait]
impl CheckpointStore for BlockedSteeringStore {
    async fn save(&self, state: &SessionState) -> CoreResult<()> {
        if !state.applied_steering_ids.is_empty() {
            self.gate.wait_once().await;
        }
        self.inner.save(state).await
    }
    async fn load(&self, session_id: &str) -> CoreResult<Option<SessionState>> {
        self.inner.load(session_id).await
    }
    async fn delete(&self, session_id: &str) -> CoreResult<()> {
        self.inner.delete(session_id).await
    }
}

#[test]
fn cancel_during_steering_checkpoint_save_is_terminal_before_any_decision() {
    let (gate, entered, release) = AsyncGate::new();
    let checkpoints = Arc::new(BlockedSteeringStore {
        inner: InMemoryCheckpointStore::new(),
        gate,
    });
    let control = Arc::new(MutableControl::new(RunDirective::Steer(
        SteeringInstruction {
            id: "steering-to-save".into(),
            content: "Pending instruction".into(),
        },
    )));
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![AgentAction::Finish {
            answer: "must not finalize".into(),
        }])),
        Arc::new(CountingToolHost {
            calls: AtomicUsize::new(0),
        }),
        checkpoints.clone(),
        Arc::new(FixedClock(0)),
    );
    let (result, ()) = block_on(futures::future::join(
        engine.run_controlled(
            "blocked-save",
            "Original goal",
            Some("project"),
            control.clone(),
        ),
        async {
            entered.await.unwrap();
            control.set(RunDirective::Cancel);
            release.send(()).unwrap();
        },
    ));
    let result = result.unwrap();
    assert_eq!(result.status, SessionStatus::Cancelled);
    assert_eq!(result.round, 0);
    assert!(result.answer.is_none());
    assert_eq!(result.applied_steering_ids, ["steering-to-save"]);
    assert_eq!(
        block_on(checkpoints.load("blocked-save"))
            .unwrap()
            .unwrap()
            .status,
        SessionStatus::Cancelled
    );
}

struct BlockedToolObserver {
    gate: AsyncGate,
    errors: AtomicUsize,
}

#[async_trait]
impl ReActObserver for BlockedToolObserver {
    async fn on_tool_call(&self, _: &str, _: u64, _: &str, _: &str) -> CoreResult<()> {
        self.gate.wait_once().await;
        Ok(())
    }
    async fn on_tool_error(
        &self,
        _: &str,
        _: u64,
        _: &str,
        _: &str,
        _: &agistack_core::ports::CoreError,
    ) -> CoreResult<()> {
        self.errors.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

#[test]
fn cancel_during_pre_dispatch_observer_prevents_the_tool_side_effect() {
    let (gate, entered, release) = AsyncGate::new();
    let tools = Arc::new(CountingToolHost {
        calls: AtomicUsize::new(0),
    });
    let control = Arc::new(MutableControl::new(RunDirective::Continue));
    let observer = Arc::new(BlockedToolObserver {
        gate,
        errors: AtomicUsize::new(0),
    });
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![
            AgentAction::CallTool {
                tool: "work".into(),
                input_json: "{}".into(),
            },
            AgentAction::Finish {
                answer: "done".into(),
            },
        ])),
        tools.clone(),
        Arc::new(InMemoryCheckpointStore::new()),
        Arc::new(FixedClock(0)),
    );
    let (result, ()) = block_on(futures::future::join(
        engine.run_observed_controlled(
            "blocked-observer",
            "Work",
            Some("project"),
            observer.clone(),
            control.clone(),
        ),
        async {
            entered.await.unwrap();
            control.set(RunDirective::Cancel);
            release.send(()).unwrap();
        },
    ));
    assert_eq!(result.unwrap().status, SessionStatus::Cancelled);
    assert_eq!(tools.calls.load(Ordering::SeqCst), 0);
    assert_eq!(observer.errors.load(Ordering::SeqCst), 1);
}
