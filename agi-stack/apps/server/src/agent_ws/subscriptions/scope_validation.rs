use serde_json::Value;

use super::Subscription;

pub(super) fn sandbox_message_matches_scope(subscription: &Subscription, message: &Value) -> bool {
    let Some(scope) = subscription.scope.as_ref() else {
        return false;
    };
    scope_fields_match(
        message,
        &["/data/project_id", "/data/data/project_id"],
        &scope.project_id,
    ) && scope_fields_match(
        message,
        &["/data/tenant_id", "/data/data/tenant_id"],
        &scope.tenant_id,
    )
}

pub(super) fn workspace_message_matches_scope(
    subscription: &Subscription,
    message: &Value,
) -> bool {
    let Some(scope) = subscription.scope.as_ref() else {
        return false;
    };
    scope_fields_match(
        message,
        &["/project_id", "/data/project_id"],
        &scope.project_id,
    ) && scope_fields_match(
        message,
        &["/tenant_id", "/data/tenant_id"],
        &scope.tenant_id,
    )
}

fn scope_fields_match(message: &Value, pointers: &[&str], expected: &str) -> bool {
    pointers
        .iter()
        .filter_map(|pointer| message.pointer(pointer))
        .all(|value| value.as_str() == Some(expected))
}
