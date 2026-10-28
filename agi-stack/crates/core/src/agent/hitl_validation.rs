//! Structural host authority checked before exposing an unanswered human request.
use super::types::HitlRequest;
use crate::ports::CoreResult;
use async_trait::async_trait;

pub struct HitlValidationContext<'a> {
    pub session_id: &'a str,
    pub round: u64,
}

/// Hosts validate exact persisted request bindings. Semantic risk and rationale
/// remain the agent's structured decision; this port never creates approvals.
#[async_trait]
pub trait HitlValidationPort: Send + Sync {
    /// Bind a newly decided request to its host execution before any answer
    /// lookup, observer event or suspension. Persisted pending requests bypass
    /// this hook during resume, preserving their original identity.
    fn bind_request_id(
        &self,
        _context: &HitlValidationContext<'_>,
        model_request_id: &str,
    ) -> CoreResult<String> {
        Ok(model_request_id.to_owned())
    }

    async fn validate(
        &self,
        context: &HitlValidationContext<'_>,
        request: &HitlRequest,
    ) -> CoreResult<()>;
}
