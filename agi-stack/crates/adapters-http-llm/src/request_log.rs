//! Per-operation request recording at the actual serialized HTTP body boundary.

use std::{future::Future, sync::Arc};

use agistack_core::{
    model_request::{ModelRequestLog, ModelRequestStatus},
    ports::{CoreError, CoreResult},
};
use serde::Serialize;

tokio::task_local! {
    static REQUEST_LOG: Arc<dyn ModelRequestLog>;
}

/// Host decorators scope the recorder around each model operation, including
/// provider failover and structured-response repairs in that operation.
pub async fn with_model_request_log<F: Future>(
    log: Arc<dyn ModelRequestLog>,
    future: F,
) -> F::Output {
    REQUEST_LOG.scope(log, future).await
}

pub(crate) struct RequestAttempt {
    active: Option<(Arc<dyn ModelRequestLog>, String)>,
}

impl RequestAttempt {
    pub(crate) async fn prepare(protocol: &str, body: &impl Serialize) -> CoreResult<Self> {
        let log = REQUEST_LOG.try_with(Arc::clone).ok();
        let active = if let Some(log) = log {
            let mut body = serde_json::to_value(body)
                .map_err(|error| CoreError::Llm(format!("invalid prepared request: {error}")))?;
            crate::media::redact_payloads(&mut body);
            let id = log.prepare_request(protocol, body).await?;
            Some((log, id))
        } else {
            None
        };
        Ok(Self { active })
    }

    pub(crate) async fn finish<T>(mut self, result: &CoreResult<T>) -> CoreResult<()> {
        if let Some((log, id)) = self.active.as_ref() {
            log.settle_request(
                id,
                if result.is_ok() {
                    ModelRequestStatus::Completed
                } else {
                    ModelRequestStatus::Failed
                },
            )
            .await?;
        }
        self.active.take();
        Ok(())
    }
}

impl Drop for RequestAttempt {
    fn drop(&mut self) {
        if let Some((log, id)) = self.active.take() {
            // Prepared remains durable even if the storage device fails during
            // cancellation. Never make a second model request from this path.
            log.cancel_request(&id);
        }
    }
}

/// Persist before the first transport poll, then durably settle its outcome.
pub(crate) async fn record_request<T>(
    protocol: &str,
    body: &impl Serialize,
    request: impl Future<Output = CoreResult<T>>,
) -> CoreResult<T> {
    let attempt = RequestAttempt::prepare(protocol, body).await?;
    let result = request.await;
    attempt.finish(&result).await?;
    result
}
