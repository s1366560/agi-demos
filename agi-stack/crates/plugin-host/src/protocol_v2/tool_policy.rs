//! Trusted bundled waterfall dispatch, scoped to the pinned native generation.

use std::collections::BTreeMap;

use serde_json::Value;

use super::{ContextV2, RuntimeV2Error, ScopeV2};

/// Structural source identities for the exact active request/policy generation.
/// Configuration and credentials are intentionally absent from this projection.
pub fn request_contributors_v2(
    snapshot: &super::ProfileSnapshotV2,
    target: &super::DataPlaneTargetV2,
    scope: &ScopeV2,
) -> Value {
    let events = [
        "agent.session.start",
        "agent.before_request",
        "agent.before_prompt_build",
        "tools.before_execute",
        "tools.result_transform",
    ];
    Value::Array(super::project_snapshot_entries_v2(snapshot, target).into_iter()
        .filter(|entry| entry.enabled)
        .filter(|entry| [&entry.scope.tenant_id, &entry.scope.project_id, &entry.scope.session_id]
            .into_iter().zip([&scope.tenant_id, &scope.project_id, &scope.session_id])
            .all(|(declared, active)| declared.is_none() || declared == active))
        .filter_map(|entry| {
            let module = snapshot.manifests.iter().find(|manifest| manifest.plugin_id == entry.plugin_ref)?
                .modules.iter().find(|module| module.module_ref == entry.module_ref)?;
            let handled = module.contract.events.handles.iter().filter(|event| events.contains(&event.event.as_str()))
                .map(|event| event.event.clone()).collect::<Vec<_>>();
            let services = module.contract.services.provides.iter().filter(|service| service.service == TOOL_EXECUTION_POLICY_SERVICE_V2)
                .map(|service| service.service.clone()).collect::<Vec<_>>();
            if handled.is_empty() && services.is_empty() { return None; }
            Some(serde_json::json!({"entry_id":entry.entry_id,"module_ref":entry.module_ref,"events":handled,"services":services}))
        }).collect())
}

pub const TOOL_EXECUTION_POLICY_SERVICE_V2: &str = "service:tool-execution-policy";
pub const TOOLS_BEFORE_EXECUTE_EVENT_V2: &str = "tools.before_execute";
pub const TOOLS_RESULT_TRANSFORM_EVENT_V2: &str = "tools.result_transform";

#[derive(Clone)]
pub struct TrustedToolPolicyV2 {
    context: ContextV2,
}

impl TrustedToolPolicyV2 {
    pub(super) fn new(context: ContextV2) -> Self {
        Self { context }
    }

    pub async fn dispatch(
        &self,
        scope: ScopeV2,
        event: &str,
        payload: Value,
    ) -> Result<Value, RuntimeV2Error> {
        if !matches!(
            event,
            TOOLS_BEFORE_EXECUTE_EVENT_V2 | TOOLS_RESULT_TRANSFORM_EVENT_V2
        ) {
            return Err(RuntimeV2Error::Module("unknown tool policy event".into()));
        }
        let context = self
            .context
            .extend(self.context.entry_id(), scope, BTreeMap::new());
        let result = context.dispatch(event, payload.clone()).await?;
        for field in [
            "tenant_id",
            "project_id",
            "session_id",
            "operation_id",
            "generation_digest",
            "tool_name",
            "call_id",
        ] {
            if result.get(field) != payload.get(field) {
                return Err(RuntimeV2Error::InvalidEventResult {
                    event: event.into(),
                    detail: format!("tool policy changed {field}"),
                });
            }
        }
        Ok(result)
    }
}

/// Revalidate rewritten arguments against the declared tool schema, before the
/// ordinary host's authorization and execution wrappers see them.
pub fn validate_tool_arguments_v2(
    schema: Option<&Value>,
    arguments: &Value,
) -> Result<(), RuntimeV2Error> {
    if !arguments.is_object() {
        return Err(RuntimeV2Error::Module(
            "tool arguments must be an object".into(),
        ));
    }
    if let Some(schema) = schema {
        let validator = jsonschema::draft202012::new(schema)
            .map_err(|_| RuntimeV2Error::Module("invalid tool input schema".into()))?;
        if !validator.is_valid(arguments) {
            return Err(RuntimeV2Error::Module(
                "rewritten tool arguments violate input schema".into(),
            ));
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "tool_policy_tests.rs"]
mod tests;
