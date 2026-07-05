use super::*;

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub(crate) struct WorkspacePlanOutboxRunReport {
    pub claimed: usize,
    pub completed: usize,
    pub failed: usize,
    pub released: usize,
    pub parked: usize,
    pub missing_handler: usize,
    pub skipped: usize,
}

pub(crate) struct WorkspacePlanOutboxWorkerRuntime {
    pub(super) join: Option<JoinHandle<()>>,
}

impl WorkspacePlanOutboxWorkerRuntime {
    #[cfg(test)]
    pub(in crate::workspace_outbox_worker) async fn shutdown(mut self) {
        if let Some(join) = self.join.take() {
            join.abort();
            let _ = join.await;
        }
    }
}

impl Drop for WorkspacePlanOutboxWorkerRuntime {
    fn drop(&mut self) {
        if let Some(join) = &self.join {
            join.abort();
        }
    }
}
