//! Sanitized diagnostics export. The document is built from a field whitelist
//! (never filtered after the fact); a deterministic credential-marker pass is
//! defense in depth only. Every export is recorded as a durable read audit.
use agistack_core::knowledge::diagnostics::DiagnosticRequest;

use super::super::processing_context;
use super::*;

const EXPORT_FAILURE_LIMIT: usize = 100;
const REDACTED: &str = "[redacted-credential-marker]";

pub(super) async fn query(
    operation: &KnowledgeOperationV2,
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    scope: &KnowledgeOperationScopeV2,
) -> RouteResult {
    let started = std::time::Instant::now();
    let result = assemble(operation, state, auth, scope);
    audit(state, auth, scope, &result, started);
    result
        .map(|export| Json(json!({"contract_version":VERSION,"scope":scope,"result":export})))
        .map_err(IntoResponse::into_response)
}

fn assemble(
    operation: &KnowledgeOperationV2,
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    scope: &KnowledgeOperationScopeV2,
) -> Result<Value, KnowledgeAuthorityErrorV2> {
    let sync_permitted = operation.authority.require_sync_release().is_ok();
    let bundle = processing_context::with_read_current(operation, state, auth, |clock| {
        let generated_at = clock()?;
        if generated_at < 0 || generated_at as u64 > MAX_WIRE_INTEGER {
            return Err(KnowledgeError::InvalidInput);
        }
        let repository = operation
            .authority
            .repository()
            .map_err(|_| KnowledgeError::Conflict)?;
        let status = repository.index_configuration_status_durable(&operation.scope, clock)?;
        let request = DiagnosticRequest {
            limit: EXPORT_FAILURE_LIMIT,
            cursor: None,
        };
        let failed_processing =
            repository.failed_processing_durable(&operation.scope, &request, clock)?;
        let failed_index = status
            .configuration
            .as_ref()
            .map(|config| repository.failed_index_durable(config, &request, clock))
            .transpose()?;
        let success = repository.diagnostics_success_timestamps_durable(
            &operation.scope,
            status
                .configuration
                .as_ref()
                .map(|config| config.build.build_id.as_str()),
            clock,
        )?;
        let sync = if sync_permitted {
            Some(repository.sync_diagnostics_durable(&operation.scope, clock)?)
        } else {
            None
        };
        Ok((
            generated_at,
            status,
            failed_processing,
            failed_index,
            success,
            sync,
        ))
    })?;
    let (generated_at, status, failed_processing, failed_index, success, sync) = bundle;
    let configuration = status
        .configuration
        .as_ref()
        .map(summary)
        .transpose()?;
    let processing_failed = serde_json::to_value(failed_processing.items)
        .map_err(|_| KnowledgeAuthorityErrorV2::Knowledge(KnowledgeError::InvalidInput))?;
    let (index_failed, index_truncated) = match failed_index {
        Some(page) => (
            serde_json::to_value(page.items)
                .map_err(|_| KnowledgeAuthorityErrorV2::Knowledge(KnowledgeError::InvalidInput))?,
            page.next_cursor.is_some(),
        ),
        None => (json!([]), false),
    };
    let mut export = json!({
        "diagnostics_export_version": 1,
        "generated_at_ms": generated_at,
        "application": {
            "module_ref": MODULE_REF,
            "service": SERVICE,
            "version": VERSION,
            "knowledge_schema_version": agistack_adapters_device::knowledge::KNOWLEDGE_SCHEMA_VERSION,
        },
        "scope": {
            "tenant_id": scope.tenant_id,
            "project_id": scope.project_id,
            "context_revision": scope.context_revision,
            "profile_id": scope.profile_id,
            "generation": scope.generation,
            "digest": scope.digest,
        },
        "processing": {
            "coverage": processing_coverage(&status.processing),
            "last_success_ms": success.processing_ms,
            "failed": processing_failed,
            "truncated": failed_processing.next_cursor.is_some(),
        },
        "index": {
            "configuration": configuration,
            "active_build_id": status.active_build_id,
            "coverage": status.index.as_ref().map(index_coverage),
            "last_success_ms": success.index_ms,
            "failed": index_failed,
            "truncated": index_truncated,
        },
        "sync": sync.map(|diagnostics| json!({
            "linked": diagnostics.linked,
            "pending_changes": diagnostics.pending_changes,
            "pending_graph_changes": diagnostics.pending_graph_changes,
            "pull_conflicts": diagnostics.pull_conflicts,
            "push_conflicts": diagnostics.push_conflicts,
            "graph_pull_conflicts": diagnostics.graph_pull_conflicts,
            "graph_push_conflicts": diagnostics.graph_push_conflicts,
            "pull_cursor": diagnostics.pull_cursor,
            "graph_pull_cursor": diagnostics.graph_pull_cursor,
            "last_receipt_sequence": diagnostics.last_receipt_sequence,
        })),
    });
    redact_export(&mut export);
    Ok(export)
}

/// Durable read evidence, mirroring the audited native knowledge reads. The
/// audit records the actor, scope and outcome — never the exported document.
/// Fire-and-forget like every other native audit sink: auditing must never
/// fail the read itself.
fn audit(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    scope: &KnowledgeOperationScopeV2,
    result: &Result<Value, KnowledgeAuthorityErrorV2>,
    started: std::time::Instant,
) {
    let conversation = format!(
        "knowledge-diagnostics-export:{}:{}",
        scope.tenant_id, scope.project_id
    );
    let (status, summary) = match result {
        Ok(export) => (
            "exported",
            json!({
                "failed_processing": export["processing"]["failed"].as_array().map_or(0, Vec::len),
                "failed_index": export["index"]["failed"].as_array().map_or(0, Vec::len),
                "sync_included": !export["sync"].is_null(),
            }),
        ),
        Err(_) => ("failed", Value::Null),
    };
    let item = state.timeline_item(
        "knowledge_diagnostics_export",
        conversation.clone(),
        None,
        None,
        None,
        json!({
            "actor_id": auth.user.user_id,
            "membership_role": auth.membership_role,
            "action": "diagnostics_export",
            "status": status,
            "scope": {
                "tenant_id": scope.tenant_id,
                "project_id": scope.project_id,
                "context_revision": scope.context_revision,
                "generation": scope.generation,
                "digest": scope.digest,
            },
            "summary": summary,
            "latency_ms": started.elapsed().as_millis(),
        }),
    );
    if let Err(error) = state.session_store.append_timeline(&conversation, &item) {
        eprintln!("failed to persist knowledge diagnostics export audit: {error}");
    }
}

/// Defense in depth: the document is already whitelist-built, so any string
/// that still resembles a credential is replaced deterministically.
fn redact_export(value: &mut Value) {
    match value {
        Value::String(text) => {
            if credential_marker(text) {
                *text = REDACTED.into();
            }
        }
        Value::Array(items) => items.iter_mut().for_each(redact_export),
        Value::Object(fields) => fields.values_mut().for_each(redact_export),
        _ => {}
    }
}

fn credential_marker(text: &str) -> bool {
    const MARKERS: &[&str] = &[
        "ms_sk_",
        "sk-",
        "bearer ",
        "-----begin",
        "api_key",
        "apikey",
        "api-key",
        "secret",
        "password",
        "authorization",
        "access_token",
        "refresh_token",
        "token=",
        "token:",
    ];
    let lower = text.to_ascii_lowercase();
    MARKERS.iter().any(|marker| lower.contains(marker))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redaction_replaces_credential_markers_and_preserves_legitimate_fields() {
        let digest = "ab".repeat(32);
        let mut export = json!({
            "scope": {"tenant_id": "tenant", "digest": digest},
            "processing": {"failed": [{"source": {"memory_id": "memory"}, "failure": "provider_unavailable"}]},
            "index": {"configuration": {"model_id": "text-embedding-tokenizer", "provider_id": "provider"}},
            "planted": [
                "ms_sk_0123456789abcdef",
                "sk-live-fake-key",
                "Bearer abc.def.ghi",
                "api_key=abc",
                "-----BEGIN PRIVATE KEY-----",
            ],
        });
        redact_export(&mut export);
        assert_eq!(export["scope"]["digest"], json!(digest));
        assert_eq!(export["scope"]["tenant_id"], "tenant");
        assert_eq!(
            export["index"]["configuration"]["model_id"],
            "text-embedding-tokenizer"
        );
        for planted in export["planted"].as_array().unwrap() {
            assert_eq!(planted, REDACTED);
        }
        let serialized = export.to_string();
        for marker in ["ms_sk_", "sk-live", "Bearer abc", "BEGIN PRIVATE"] {
            assert!(!serialized.contains(marker), "{marker}");
        }
    }
}
