//! Model cancellation remains portable and does not require a Tokio runtime.

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::task::Poll;

use agistack_adapters_mem::{FixedClock, InMemoryCheckpointStore, ScriptedLlm};
use agistack_core::agent::react::ReActObserver;
use agistack_core::ports::{CoreResult, LlmPort, MemoryDraft, ToolDefinition, ToolHost};
use agistack_core::{
    AgentAction, Episode, ReActControl, ReActEngine, RunDirective, SessionStatus, TranscriptEntry,
};
use async_trait::async_trait;
use futures::channel::oneshot;
use futures::executor::block_on;
use futures::task::AtomicWaker;

struct InterruptControl {
    directive: Mutex<RunDirective>,
    waker: AtomicWaker,
}

impl InterruptControl {
    fn set(&self, directive: RunDirective) {
        *self.directive.lock().unwrap() = directive;
        self.waker.wake();
    }
}

#[async_trait]
impl ReActControl for InterruptControl {
    async fn directive(&self, _: &str, _: u64) -> CoreResult<RunDirective> {
        Ok(self.directive.lock().unwrap().clone())
    }

    async fn wait_for_interrupt(&self, _: &str, _: u64) -> CoreResult<()> {
        std::future::poll_fn(|cx| {
            self.waker.register(cx.waker());
            if matches!(
                *self.directive.lock().unwrap(),
                RunDirective::Pause | RunDirective::Cancel
            ) {
                Poll::Ready(Ok(()))
            } else {
                Poll::Pending
            }
        })
        .await
    }
}

struct PendingLlm {
    entered: Mutex<Option<oneshot::Sender<()>>>,
    dropped: Arc<AtomicBool>,
}

struct DropRequest(Arc<AtomicBool>);

impl Drop for DropRequest {
    fn drop(&mut self) {
        self.0.store(true, Ordering::SeqCst);
    }
}

#[async_trait]
impl LlmPort for PendingLlm {
    async fn extract_memory(&self, _: &Episode) -> CoreResult<MemoryDraft> {
        unreachable!("chat only")
    }

    async fn decide(
        &self,
        _: &str,
        _: u64,
        _: &[TranscriptEntry],
        _: &[String],
    ) -> CoreResult<AgentAction> {
        unreachable!("stream method must be preserved")
    }

    async fn decide_with_tools_stream(
        &self,
        _: &str,
        _: u64,
        _: &[TranscriptEntry],
        _: &[ToolDefinition],
        on_text: &(dyn for<'text> Fn(&'text str) + Send + Sync),
    ) -> CoreResult<AgentAction> {
        let _request = DropRequest(self.dropped.clone());
        on_text("unfinished answer");
        self.entered
            .lock()
            .unwrap()
            .take()
            .unwrap()
            .send(())
            .unwrap();
        std::future::pending().await
    }
}

#[derive(Default)]
struct Observer {
    ends: AtomicUsize,
    finishes: AtomicUsize,
}

#[async_trait]
impl ReActObserver for Observer {
    fn on_text_end(&self, _: &str, _: u64) {
        self.ends.fetch_add(1, Ordering::SeqCst);
    }

    async fn on_finish(&self, _: &str, _: u64, _: &str) -> CoreResult<()> {
        self.finishes.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

struct NoTools;

#[async_trait]
impl ToolHost for NoTools {
    fn list_tools(&self) -> Vec<String> {
        vec![]
    }
    async fn call(&self, _: &str, _: &str) -> CoreResult<String> {
        panic!("no tool may dispatch")
    }
}

fn interrupt_pending_decision(directive: RunDirective, expected: SessionStatus) {
    let checkpoints = Arc::new(InMemoryCheckpointStore::new());
    let (entered_tx, entered_rx) = oneshot::channel();
    let dropped = Arc::new(AtomicBool::new(false));
    let control = Arc::new(InterruptControl {
        directive: Mutex::new(RunDirective::Continue),
        waker: AtomicWaker::new(),
    });
    let observer = Arc::new(Observer::default());
    let engine = ReActEngine::new(
        Arc::new(PendingLlm {
            entered: Mutex::new(Some(entered_tx)),
            dropped: dropped.clone(),
        }),
        Arc::new(NoTools),
        checkpoints.clone(),
        Arc::new(FixedClock(0)),
    );
    let (result, ()) = block_on(futures::future::join(
        engine.run_observed_controlled(
            "interrupt",
            "wait",
            None,
            observer.clone(),
            control.clone(),
        ),
        async {
            entered_rx.await.unwrap();
            control.set(directive);
        },
    ));
    let result = result.unwrap();
    assert_eq!(result.status, expected);
    assert_eq!(result.round, 0);
    assert!(result.answer.is_none());
    assert!(result.completed_tool_calls.is_empty());
    assert!(dropped.load(Ordering::SeqCst));
    assert_eq!(observer.ends.load(Ordering::SeqCst), 1);
    assert_eq!(observer.finishes.load(Ordering::SeqCst), 0);
    if expected == SessionStatus::Paused {
        block_on(engine.accept_controlled_resume("interrupt")).unwrap();
        control.set(RunDirective::Continue);
        let resumed = ReActEngine::new(
            Arc::new(ScriptedLlm::new(vec![AgentAction::Finish {
                answer: "fresh answer".into(),
            }])),
            Arc::new(NoTools),
            checkpoints,
            Arc::new(FixedClock(0)),
        );
        let result = block_on(resumed.run_controlled("interrupt", "wait", None, control)).unwrap();
        assert_eq!(result.answer.as_deref(), Some("fresh answer"));
        assert_eq!(result.status, SessionStatus::Finished);
    }
}

#[test]
fn pause_drops_a_pending_decision_and_preserves_a_resumable_checkpoint() {
    interrupt_pending_decision(RunDirective::Pause, SessionStatus::Paused);
}

#[test]
fn cancel_drops_a_pending_decision_without_a_successful_answer() {
    interrupt_pending_decision(RunDirective::Cancel, SessionStatus::Cancelled);
}
