//! Host-side observation of an exact invocation for a permission receipt.
//!
//! The snapshot proves only name/version. It does not provide a durable plugin
//! generation, so this binding is insufficient to resume or dispatch a mutation.

use agistack_core::automation_permission::HostPermissionBinding;
use sha2::{Digest, Sha256};

use crate::{ToolAccessClass, ToolRegistry};

/// `invocation_id` must be allocated by the host, never copied from agent input.
pub fn observe_permission_binding(
    snapshot: &ToolRegistry,
    invocation_id: String,
    tool_name: &str,
    input: &serde_json::Value,
) -> Option<HostPermissionBinding> {
    let tool = snapshot.get(tool_name)?;
    if tool.access_class() != ToolAccessClass::Mutating {
        return None;
    }
    let canonical = serde_jcs::to_vec(input).ok()?;
    HostPermissionBinding::from_host_observation(
        invocation_id,
        tool.name().to_owned(),
        tool.version().to_owned(),
        format!("{:x}", Sha256::digest(canonical)),
    )
}
