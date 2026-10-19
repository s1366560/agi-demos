//! Model input persistence independent of transport credentials and plugin replay.

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::ports::CoreResult;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ModelRequestStatus {
    Completed,
    Failed,
    Cancelled,
}

/// A read result explicitly distinguishes legacy/missing snapshots from exact
/// recorded requests. Hosts must authorize the conversation before constructing it.
#[derive(Debug, Serialize, PartialEq)]
pub struct ModelRequestReplay {
    pub schema_version: u8,
    pub status: &'static str,
    pub attempt_id: String,
    pub request: Option<Value>,
    pub reason_code: Option<&'static str>,
}

impl ModelRequestReplay {
    pub fn from_stored_request(attempt_id: String, request: Option<Value>) -> Self {
        let available = request.is_some();
        Self {
            schema_version: 1,
            status: if available {
                "available"
            } else {
                "snapshot_missing"
            },
            attempt_id,
            request,
            reason_code: if available {
                None
            } else {
                Some("model_request_snapshot_missing")
            },
        }
    }
}

/// Provider attempts are durable before transport begins. Cancellation is handed
/// to the owning host because Rust future destructors cannot await storage.
#[async_trait::async_trait]
pub trait ModelRequestLog: Send + Sync {
    async fn prepare_request(&self, protocol: &str, body: Value) -> CoreResult<String>;

    async fn settle_request(&self, attempt_id: &str, status: ModelRequestStatus) -> CoreResult<()>;

    fn cancel_request(&self, attempt_id: &str);
}
