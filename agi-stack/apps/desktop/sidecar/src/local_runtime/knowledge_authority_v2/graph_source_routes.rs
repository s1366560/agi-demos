use super::*;
use agistack_core::knowledge::{processing::ProcessingSource, retrieval::RetrievedSourceGraph};

// Match the native renderer's complete JSON reply budget, including the envelope.
const MAX_GRAPH_REPLY_BYTES: usize = 2 * 1024 * 1024;

pub(super) async fn query(
    operation: &KnowledgeOperationV2,
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    scope: &KnowledgeOperationScopeV2,
    source: &ProcessingSource,
    expected_audit_attempt: u32,
) -> RouteResult {
    validate_retry_source(source).map_err(IntoResponse::into_response)?;
    let graph = processing_context::with_read_current(operation, state, auth, |clock| {
        operation
            .authority
            .repository()
            .map_err(|_| KnowledgeError::Conflict)?
            .graph_source_durable(&operation.scope, source, expected_audit_attempt, clock)
    })
    .map_err(IntoResponse::into_response)?;
    bounded_reply(scope, graph).map_err(|status| {
        let code = if status == StatusCode::PAYLOAD_TOO_LARGE {
            "knowledge_graph_source_too_large"
        } else {
            "knowledge_graph_source_serialization_failed"
        };
        (status, Json(json!({"code": code}))).into_response()
    })
}

fn bounded_reply(
    scope: &KnowledgeOperationScopeV2,
    graph: RetrievedSourceGraph,
) -> Result<Json<Value>, StatusCode> {
    let envelope = json!({"contract_version":VERSION,"scope":scope,"result":graph});
    // Serialize with the same serde_json encoding used by Json<Value>; count
    // UTF-8 bytes, escaped control characters and envelope fields, not text chars.
    let bytes = serde_json::to_vec(&envelope).map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    if bytes.len() > MAX_GRAPH_REPLY_BYTES {
        return Err(StatusCode::PAYLOAD_TOO_LARGE);
    }
    Ok(Json(envelope))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn graph_source_budget_counts_complete_utf8_and_escaped_envelope() {
        let scope = KnowledgeOperationScopeV2 {
            tenant_id: "tenant".into(),
            project_id: "project".into(),
            context_revision: 9_007_199_254_740_991,
            profile_id: "profile".into(),
            generation: 9_007_199_254_740_991,
            digest: "digest".into(),
        };
        let mut graph = RetrievedSourceGraph {
            source: ProcessingSource {
                tenant_id: "tenant".into(),
                project_id: "project".into(),
                memory_id: "memory".into(),
                revision: u32::MAX,
                change_sequence: 9_007_199_254_740_991,
            },
            audit_attempt: u32::MAX,
            title: "中文\n\"quoted\"".into(),
            content: String::new(),
            entities: vec![],
            relationships: vec![],
        };
        let overhead = serde_json::to_vec(&bounded_reply(&scope, graph.clone()).unwrap().0)
            .unwrap()
            .len();
        graph.content = "x".repeat(MAX_GRAPH_REPLY_BYTES - overhead);
        let accepted = bounded_reply(&scope, graph.clone()).unwrap();
        assert_eq!(
            serde_json::to_vec(&accepted.0).unwrap().len(),
            MAX_GRAPH_REPLY_BYTES
        );
        graph.content.push('x');
        assert_eq!(
            bounded_reply(&scope, graph.clone()).unwrap_err(),
            StatusCode::PAYLOAD_TOO_LARGE
        );
        graph.content = "界".repeat(MAX_GRAPH_REPLY_BYTES / 3);
        assert_eq!(
            bounded_reply(&scope, graph.clone()).unwrap_err(),
            StatusCode::PAYLOAD_TOO_LARGE
        );
        graph.content = "\n".repeat(MAX_GRAPH_REPLY_BYTES / 2);
        assert_eq!(
            bounded_reply(&scope, graph).unwrap_err(),
            StatusCode::PAYLOAD_TOO_LARGE
        );
    }
}
