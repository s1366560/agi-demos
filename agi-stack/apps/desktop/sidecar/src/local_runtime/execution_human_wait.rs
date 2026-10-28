//! Only trusted host prompts may suspend a cell's execution-time accounting.
use std::{
    future::Future,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

#[derive(Default)]
pub(crate) struct HumanWaitClock {
    state: Mutex<WaitState>,
}

#[derive(Default)]
struct WaitState {
    active: usize,
    started: Option<Instant>,
    excluded: Duration,
}

impl HumanWaitClock {
    pub(crate) fn excluded(&self) -> Duration {
        let state = self.state.lock().expect("human wait clock");
        state.excluded
            + state
                .started
                .map_or(Duration::ZERO, |start| start.elapsed())
    }

    fn enter(self: &Arc<Self>) -> HumanWaitGuard {
        let mut state = self.state.lock().expect("human wait clock");
        if state.active == 0 {
            state.started = Some(Instant::now());
        }
        state.active += 1;
        HumanWaitGuard {
            clock: self.clone(),
        }
    }
}

pub(crate) struct HumanWaitGuard {
    clock: Arc<HumanWaitClock>,
}

impl Drop for HumanWaitGuard {
    fn drop(&mut self) {
        let mut state = self.clock.state.lock().expect("human wait clock");
        state.active -= 1;
        if state.active == 0 {
            if let Some(started) = state.started.take() {
                state.excluded += started.elapsed();
            }
        }
    }
}

tokio::task_local! { static HUMAN_WAIT: Arc<HumanWaitClock>; }

pub(crate) fn begin_human_wait() -> Option<HumanWaitGuard> {
    HUMAN_WAIT.try_with(|clock| clock.enter()).ok()
}

pub(crate) async fn with_human_wait_clock<F: Future>(
    clock: Arc<HumanWaitClock>,
    future: F,
) -> F::Output {
    HUMAN_WAIT.scope(clock, future).await
}
