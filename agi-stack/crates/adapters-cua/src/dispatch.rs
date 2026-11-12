//! A live-process signal at the first native frame byte, scoped to one trusted call ID.
use std::{
    future::Future,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};

#[derive(Clone)]
pub struct CuaDispatchSignal {
    request_id: String,
    sent: Arc<AtomicBool>,
}
impl CuaDispatchSignal {
    pub fn new(request_id: impl Into<String>) -> Self {
        Self {
            request_id: request_id.into(),
            sent: Arc::new(AtomicBool::new(false)),
        }
    }
    pub fn was_sent(&self) -> bool {
        self.sent.load(Ordering::Acquire)
    }
}
tokio::task_local! { static SIGNAL: CuaDispatchSignal; }
pub async fn scope_dispatch_signal<F: Future>(signal: CuaDispatchSignal, future: F) -> F::Output {
    SIGNAL.scope(signal, future).await
}
pub(crate) fn before_frame(request_id: Option<&str>) {
    let _ = SIGNAL.try_with(|signal| {
        if !signal.request_id.is_empty() && request_id == Some(signal.request_id.as_str()) {
            signal.sent.store(true, Ordering::Release);
        }
    });
}
#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn only_exact_trusted_request_marks_dispatch_and_scopes_do_not_leak() {
        let signal = CuaDispatchSignal::new("trusted");
        scope_dispatch_signal(signal.clone(), async {
            for value in [None, Some("other")] {
                before_frame(value);
            }
            assert!(!signal.was_sent());
            before_frame(Some("trusted"));
            assert!(signal.was_sent());
        })
        .await;
        let other = CuaDispatchSignal::new("trusted");
        before_frame(Some("trusted"));
        assert!(!other.was_sent());
    }
}
