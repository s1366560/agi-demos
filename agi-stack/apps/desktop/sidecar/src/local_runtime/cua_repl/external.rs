//! Host callbacks enter the cell queue and retain their exact continuation.
use std::sync::Arc;

use agistack_core::ports::{CoreError, CoreResult, ToolResult};
use futures_util::future::BoxFuture;
use serde_json::Value;
use tokio::sync::{mpsc, oneshot};

use super::super::execution_authority::ExecutionAuthority;

pub(crate) type ExternalDispatch = Arc<
    dyn Fn(Arc<ExecutionAuthority>) -> BoxFuture<'static, CoreResult<ToolResult>> + Send + Sync,
>;

pub(super) struct ExternalRequest {
    pub dispatch: ExternalDispatch,
    pub response: oneshot::Sender<Result<Value, String>>,
    pub step_id: String,
    pub parent_request_id: Option<String>,
}

pub(super) async fn submit(
    sender: &mpsc::Sender<ExternalRequest>,
    dispatch: ExternalDispatch,
    parent_request_id: Option<String>,
) -> CoreResult<Value> {
    let (response, receiver) = oneshot::channel();
    sender
        .try_send(ExternalRequest {
            dispatch,
            response,
            step_id: uuid::Uuid::new_v4().to_string(),
            parent_request_id,
        })
        .map_err(|_| CoreError::Tool("repl_callback_unavailable_or_busy".into()))?;
    receiver
        .await
        .map_err(|_| CoreError::Tool("repl_callback_cancelled".into()))?
        .map_err(CoreError::Tool)
}
