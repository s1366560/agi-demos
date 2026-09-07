//! Cooperative worker retirement with independently observed task completion.

use std::future::Future;

use tokio::sync::watch;

type WorkerResult = Result<(), String>;

pub(crate) struct WorkerRuntimeV2 {
    shutdown: watch::Sender<bool>,
    completion: watch::Receiver<Option<WorkerResult>>,
}

impl WorkerRuntimeV2 {
    pub(crate) fn spawn<F, Fut>(name: &'static str, run: F) -> Self
    where
        F: FnOnce(watch::Receiver<bool>) -> Fut + Send + 'static,
        Fut: Future<Output = ()> + Send + 'static,
    {
        let (shutdown, receiver) = watch::channel(false);
        let (completed, completion) = watch::channel(None);
        let worker = tokio::spawn(async move { run(receiver).await });
        // This observer owns the JoinHandle even if a caller drops its runtime or
        // cancels shutdown(). Neither case may abort an already admitted operation.
        tokio::spawn(async move {
            let result = worker.await.map_err(|error| {
                let reason = if error.is_panic() {
                    "panicked"
                } else {
                    "was cancelled"
                };
                format!("{name}: worker task {reason}")
            });
            if let Err(error) = &result {
                eprintln!("[agistack] background worker terminated with an error: {error}");
            }
            completed.send_replace(Some(result));
        });
        Self {
            shutdown,
            completion,
        }
    }

    pub(crate) fn request_stop(&self) {
        self.shutdown.send_replace(true);
    }

    pub(crate) async fn shutdown(&self) -> WorkerResult {
        self.request_stop();
        let mut completion = self.completion.clone();
        loop {
            if let Some(result) = completion.borrow_and_update().clone() {
                return result;
            }
            completion
                .changed()
                .await
                .map_err(|_| "background worker completion observer ended".to_owned())?;
        }
    }
}

impl Drop for WorkerRuntimeV2 {
    fn drop(&mut self) {
        self.request_stop();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{sync::Arc, time::Duration};
    use tokio::sync::oneshot;

    #[tokio::test]
    async fn shutdown_waits_for_started_work_and_can_be_repeated() {
        let (entered, started) = oneshot::channel();
        let (finish, finished) = oneshot::channel();
        let runtime = WorkerRuntimeV2::spawn("blocked-worker", move |_stop| async move {
            entered.send(()).expect("announce started work");
            finished.await.expect("finish admitted work");
        });
        started.await.expect("worker started");
        assert!(
            tokio::time::timeout(Duration::from_millis(20), runtime.shutdown())
                .await
                .is_err()
        );
        finish.send(()).expect("worker was not aborted");
        runtime.shutdown().await.expect("work drained");
        runtime.shutdown().await.expect("repeat drain");
    }

    #[tokio::test]
    async fn dropping_runtime_requests_stop_without_cancelling_admitted_work() {
        let (entered, started) = oneshot::channel();
        let (finish, finished) = oneshot::channel();
        let (settled, settlement) = oneshot::channel();
        let runtime = WorkerRuntimeV2::spawn("dropped-worker", move |stop| async move {
            entered.send(()).expect("announce work");
            finished.await.expect("finish admitted work");
            assert!(*stop.borrow());
            settled.send(()).expect("record settlement");
        });
        started.await.expect("worker started");
        drop(runtime);
        finish.send(()).expect("admitted work remains alive");
        settlement.await.expect("work settled after owner drop");
    }

    #[tokio::test]
    async fn panic_is_observed_and_repeated_shutdown_preserves_failure() {
        let runtime = Arc::new(WorkerRuntimeV2::spawn("panicking-worker", |_| async {
            panic!("injected worker failure");
        }));
        let first = runtime
            .shutdown()
            .await
            .expect_err("panic must be observed");
        assert!(first.contains("panicking-worker"));
        assert_eq!(
            runtime.shutdown().await.expect_err("failure persists"),
            first
        );
    }
}
