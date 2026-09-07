//! Paused generation resources and cancellation-safe ownership of worker drains.

use std::sync::{Arc, Mutex};

use agistack_plugin_host::GenerationLeaseV2;
use tokio::sync::{oneshot, watch};

use crate::cron_readiness_v2::{CronReadinessBlockerV2, CronReadinessSnapshotV2, CronReadinessV2};
use crate::worker_lifecycle_v2::WorkerRuntimeV2;

pub(crate) type WorkerFactoryV2 = Arc<dyn Fn() -> Option<WorkerRuntimeV2> + Send + Sync>;

#[derive(Default)]
struct ControllerState {
    started: bool,
    stopped: bool,
    runtime: Option<Arc<WorkerRuntimeV2>>,
}

pub(crate) struct BackgroundWorkerControllerV2 {
    factory: WorkerFactoryV2,
    state: Mutex<ControllerState>,
    cron_readiness: Option<Arc<CronReadinessV2>>,
}

impl BackgroundWorkerControllerV2 {
    pub(crate) fn paused(factory: WorkerFactoryV2) -> Self {
        Self {
            factory,
            state: Mutex::new(ControllerState::default()),
            cron_readiness: None,
        }
    }

    pub(crate) fn paused_cron(factory: WorkerFactoryV2, readiness: Arc<CronReadinessV2>) -> Self {
        Self {
            factory,
            state: Mutex::new(ControllerState::default()),
            cron_readiness: Some(readiness),
        }
    }

    pub(crate) fn cron_readiness(&self) -> Option<CronReadinessSnapshotV2> {
        self.cron_readiness
            .as_ref()
            .map(|readiness| readiness.snapshot())
    }

    fn activate(&self) -> Result<(), String> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.stopped {
            return Err("background worker generation already stopped".into());
        }
        if !state.started {
            state.started = true;
            if let Some(readiness) = &self.cron_readiness {
                readiness.published();
                if !readiness.snapshot().blockers.is_empty() {
                    return Ok(());
                }
            }
            match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| (self.factory)())) {
                Ok(runtime) => {
                    if runtime.is_none() {
                        if let Some(readiness) = &self.cron_readiness {
                            if readiness.snapshot().blockers.is_empty() {
                                readiness.blocked(CronReadinessBlockerV2::SchedulerNotConstructed);
                            }
                        }
                    }
                    state.runtime = runtime.map(Arc::new);
                }
                Err(_) => {
                    state.stopped = true;
                    if let Some(readiness) = &self.cron_readiness {
                        readiness.stopped(true);
                    }
                    return Err("background worker factory panicked".to_owned());
                }
            }
        }
        Ok(())
    }

    pub(crate) fn request_stop(&self) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.stopped = true;
        if let Some(readiness) = &self.cron_readiness {
            readiness.draining();
        }
        if let Some(runtime) = &state.runtime {
            runtime.request_stop();
        }
    }

    pub(crate) async fn drain(&self) -> Result<(), String> {
        self.request_stop();
        let runtime = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .runtime
            .clone();
        match runtime {
            Some(runtime) => {
                let result = runtime.shutdown().await;
                if let Some(readiness) = &self.cron_readiness {
                    readiness.stopped(result.is_err());
                }
                result
            }
            None => {
                if let Some(readiness) = &self.cron_readiness {
                    readiness.stopped(false);
                }
                Ok(())
            }
        }
    }
}

pub(crate) struct BackgroundWorkerGenerationV2 {
    stop: watch::Sender<bool>,
    completion: watch::Receiver<Option<Result<(), String>>>,
}

impl BackgroundWorkerGenerationV2 {
    pub(crate) fn request_stop(&self) {
        self.stop.send_replace(true);
    }

    pub(crate) fn start(
        lease: GenerationLeaseV2,
        controllers: Vec<Arc<BackgroundWorkerControllerV2>>,
    ) -> impl std::future::Future<Output = Result<Self, String>> {
        let (stop, mut stopping) = watch::channel(false);
        let (completed, completion) = watch::channel(None);
        let (ready, started) = oneshot::channel();
        let owner = Self { stop, completion };
        // This task owns the lease through every worker drain, including when the
        // caller cancels startup/shutdown or drops its runtime handle.
        tokio::spawn(async move {
            let mut errors = Vec::new();
            for controller in &controllers {
                if *stopping.borrow() {
                    break;
                }
                if let Err(error) = controller.activate() {
                    errors.push(error);
                    break;
                }
            }
            let _ = ready.send(errors.is_empty());
            if errors.is_empty() {
                while !*stopping.borrow_and_update() {
                    if stopping.changed().await.is_err() {
                        break;
                    }
                }
            }
            for controller in &controllers {
                controller.request_stop();
            }
            for controller in &controllers {
                if let Err(error) = controller.drain().await {
                    errors.push(error);
                }
            }
            if let Err(error) = lease.release().await {
                errors.push(error.to_string());
            }
            let result = if errors.is_empty() {
                Ok(())
            } else {
                Err(errors.join("; "))
            };
            if let Err(error) = &result {
                eprintln!("[agistack] background worker generation drain failed: {error}");
            }
            completed.send_replace(Some(result));
        });
        async move {
            match started.await {
                Ok(true) => Ok(owner),
                _ => {
                    owner.shutdown().await?;
                    Err("background worker generation could not start".into())
                }
            }
        }
    }

    pub(crate) async fn shutdown(&self) -> Result<(), String> {
        self.stop.send_replace(true);
        let mut completion = self.completion.clone();
        loop {
            if let Some(result) = completion.borrow_and_update().clone() {
                return result;
            }
            completion
                .changed()
                .await
                .map_err(|_| "background worker generation observer ended".to_owned())?;
        }
    }
}

impl Drop for BackgroundWorkerGenerationV2 {
    fn drop(&mut self) {
        self.stop.send_replace(true);
    }
}

#[cfg(test)]
#[path = "background_worker_control_v2_tests.rs"]
mod tests;
