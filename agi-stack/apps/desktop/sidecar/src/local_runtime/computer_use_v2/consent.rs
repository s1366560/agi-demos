//! Scope limits come from declared capability metadata, never operation names.
use super::store::GrantScope;
use super::PendingConsent;
use agistack_core::ports::{PermissionBinding, PermissionKind, PermissionRequired, ToolResult};
use serde_json::{json, Value};

/// Keep granted requests internally for exact once retries, but do not prompt again.
pub(super) fn needs_approval(pending: &PendingConsent, grants: &[super::store::Grant]) -> bool {
    !grants.iter().any(|grant| {
        grant.covers(
            &pending.app,
            &pending.identity_digest,
            &pending.capability,
            &pending.session_id,
            &pending.request_id,
        )
    })
}

pub(super) fn scopes(capability: &str) -> &'static [GrantScope] {
    if matches!(
        capability,
        "connector_action" | "microphone" | "system_audio" | "audio_mixed" | "locked_use"
    ) {
        &[GrantScope::Once]
    } else {
        &[GrantScope::Once, GrantScope::Session, GrantScope::Always]
    }
}

fn object(properties: Value, required: &[&str]) -> Value {
    json!({"type":"object","properties":properties,"required":required,"additionalProperties":false})
}

pub(super) fn permission_required(
    pending: PendingConsent,
    binding: PermissionBinding,
) -> ToolResult {
    let text = json!({"type":"string","minLength":1});
    let decision = object(
        json!({
            "action":object(json!({"name":{"const":pending.tool_name},"label":text}),&["name","label"]),
            "target":object(json!({"kind":{"const":"computer_app"},"id":{"const":pending.request_id}}),&["kind","id"]),
            "data":object(json!({"summary":text,"redacted_fields":{"type":"array","items":{"type":"string"}}}),&["summary"]),
            "reason":text,
            "risk":object(json!({"level":{"enum":["low","medium","high"]},"rationale":text}),&["level","rationale"]),
            "reversibility":object(json!({"mode":{"enum":["reversible","partial","irreversible"]},"recovery":{"type":["string","null"]}}),&["mode"]),
            "scope":object(json!({"kind":text,"ids":{"type":"array","minItems":1,"items":text}}),&["kind","ids"]),
            "evidence":{"type":"array","minItems":1,"items":object(json!({"kind":text,"id":text,"label":text,"uri":{"type":["string","null"]},"digest":{"type":["string","null"]}}),&["kind","id","label"])}
        }),
        &[
            "action",
            "target",
            "data",
            "reason",
            "risk",
            "reversibility",
            "scope",
            "evidence",
        ],
    );
    PermissionRequired::new(
        PermissionKind::NativeConsent,
        binding,
        json!({"error":"cua_permission_required","scopes":scopes(&pending.capability),"request":pending,
            "decision_context_schema":decision,
            "hint":"Use the runtime's structured RequestHuman action (kind=request_human, request.kind=permission, request.id your approval id, request.prompt your question, request.decision the complete context) or its advertised request_permission tool (input.decision). Copy target.kind=computer_app and target.id=request.request_id exactly. Include ALL action, target, data, reason, risk, reversibility, scope, evidence fields using decision_context_schema; reversibility.mode is required. Judge risk.level/rationale and reversibility yourself from this exact proposed input; the schema supplies no verdict. Use genuine native request/artifact identities for evidence and scope. Offer only the returned scopes. Wait for the human before retrying this exact action."}),
    ).into_result()
}
