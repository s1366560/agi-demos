//! Only structured, read-only App RPCs may be re-admitted after exact approval.
use super::{Pending, RpcOutput};
use agistack_adapters_browser::facade::{operation_effect, FacadeEffect};
use futures_util::{future::BoxFuture, stream::FuturesUnordered};
use std::{
    future::Future,
    pin::Pin,
    task::{Context, Poll},
};

type JobResult = (Pending, Result<RpcOutput, String>);

pub(super) struct OperationJob {
    future: BoxFuture<'static, JobResult>,
    read: Option<Pending>,
}

impl OperationJob {
    pub(super) fn from_parts(read: Option<Pending>, future: BoxFuture<'static, JobResult>) -> Self {
        Self { future, read }
    }
}

impl Future for OperationJob {
    type Output = JobResult;
    fn poll(mut self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        self.future.as_mut().poll(context)
    }
}

pub(super) fn pending_read(pending: &Pending) -> Option<Pending> {
    let input = &pending.frame["params"];
    if pending.external.is_some()
        || pending.interrupted
        || pending.frame["method"] != "browser.operation"
        || input["browserId"] != "mcpapps"
        || !matches!(operation_effect(input), Ok(FacadeEffect::Read))
    {
        return None;
    }
    Some(Pending {
        frame: pending.frame.clone(),
        step_id: pending.step_id.clone(),
        parent_request_id: pending.parent_request_id.clone(),
        external: None,
        interrupted: false,
    })
}

pub(super) fn suspend_reads(jobs: &mut FuturesUnordered<OperationJob>) -> Vec<Pending> {
    let mut reads = Vec::new();
    for mut job in std::mem::take(jobs) {
        if let Some(read) = job.read.take() {
            reads.push(read);
            // Drop the actual in-flight future before returning the approval
            // receipt. An abort flag alone leaves the old receiver alive.
            drop(job);
        } else {
            jobs.push(job);
        }
    }
    reads
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use tokio::sync::oneshot;

    #[test]
    fn suspension_drops_only_app_read_futures_and_preserves_rpc_identity() {
        let mut jobs = FuturesUnordered::new();
        let mut receivers = Vec::new();
        for (index, (method, browser, operation, action)) in [
            (
                "browser.operation",
                "mcpapps",
                "playwright.locator",
                "waitFor",
            ),
            (
                "browser.operation",
                "mcpapps",
                "playwright.locator",
                "click",
            ),
            ("browser.operation", "iab", "playwright.locator", "waitFor"),
            ("process.spawn", "mcpapps", "playwright.locator", "waitFor"),
            (
                "browser.operation",
                "mcpapps",
                "capability.cdp.send",
                "",
            ),
        ]
        .into_iter()
        .enumerate()
        {
            let pending = Pending {
                frame: json!({"id":format!("rpc-{index}"),"method":method,"params":{"browserId":browser,"operation":operation,"args":[[],action,[]]}}),
                step_id: format!("step-{index}"),
                parent_request_id: Some("request".into()),
                external: None,
                interrupted: false,
            };
            let read = pending_read(&pending);
            let (sender, receiver) = oneshot::channel::<()>();
            receivers.push(receiver);
            jobs.push(OperationJob::from_parts(
                read,
                Box::pin(async move {
                    let _sender = sender;
                    std::future::pending::<()>().await;
                    (pending, Ok(RpcOutput::Value(json!(null))))
                }),
            ));
        }
        let reads = suspend_reads(&mut jobs);
        assert_eq!(reads.len(), 1);
        assert_eq!(reads[0].frame["id"], "rpc-0");
        assert_eq!(reads[0].step_id, "step-0");
        assert_eq!(reads[0].parent_request_id.as_deref(), Some("request"));
        assert_eq!(jobs.len(), 4);
        assert_eq!(
            receivers[0].try_recv(),
            Err(oneshot::error::TryRecvError::Closed)
        );
        for receiver in &mut receivers[1..] {
            assert_eq!(
                receiver.try_recv(),
                Err(oneshot::error::TryRecvError::Empty)
            );
        }
    }
}
