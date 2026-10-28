//! A committed human decision may continue only the exact suspended host operation.
use super::*;
use crate::local_runtime::execution_authority::{current_cell_lifetime, StepOrigin};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Receipt {
    kind: String,
    hitl_request_id: String,
    origin_request_id: String,
    previous_authorization_revision: u64,
    authorization_revision: u64,
    cell_id: String,
    step_id: String,
}

fn invalid() -> CoreError {
    CoreError::Tool("cua_cloud_continuation_invalid".into())
}

pub(super) fn verify(
    admission: &Admission,
    step: &str,
    origin: &StepOrigin,
    value: Option<&Value>,
) -> CoreResult<Option<ExecutionScope>> {
    let Some(value) = value else { return Ok(None) };
    let receipt: Receipt = serde_json::from_value(value.clone()).map_err(|_| invalid())?;
    let previous = origin.continuation_scope.as_ref().ok_or_else(invalid)?;
    let claim = &admission.claim;
    if receipt.kind != "hitl"
        || receipt.hitl_request_id.is_empty()
        || receipt.hitl_request_id.len() > 256
        || origin.parent_request_id.as_deref() != Some(&receipt.origin_request_id)
        || receipt.cell_id != origin.cell_id
        || receipt.step_id != step
        || receipt.previous_authorization_revision != previous.run_revision
        || receipt.authorization_revision != claim.authorization_revision
        || receipt.authorization_revision < receipt.previous_authorization_revision
        || receipt.previous_authorization_revision == 0
        || previous.tenant_id != claim.tenant_id
        || previous.project_id != claim.project_id
        || previous.conversation_id != claim.conversation_id
        || previous.run_id != claim.run_id
        || previous.engine_session_id != claim.session_id
        || previous.device_id.as_deref() != Some(&claim.device_id)
        || previous.connection_epoch != Some(admission.lease.epoch)
        || previous.generation != admission.lease.factory.descriptor().generation
        || current_cell_lifetime().is_none_or(|live| !live.load(Ordering::SeqCst))
    {
        return Err(invalid());
    }
    Ok(Some(previous.clone()))
}
