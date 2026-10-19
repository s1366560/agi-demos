//! Exact recorded input is readable with the same authority as conversation history.

use agistack_core::model_request::ModelRequestReplay;

use super::*;

#[derive(Deserialize)]
pub(super) struct RequestQuery {
    project_id: String,
}

pub(super) async fn get(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((conversation_id, message_id, attempt_id)): Path<(String, String, String)>,
    Query(query): Query<RequestQuery>,
) -> Result<Json<ModelRequestReplay>, (StatusCode, Json<Value>)> {
    ensure_active_project(&authenticated, &query.project_id)?;
    scoped_conversation(&state, &authenticated, &conversation_id)?;
    let request = agent_boundary_v2::replay_prepared_model_request(
        &state.session_store,
        &conversation_id,
        &message_id,
        &attempt_id,
    )
    .map_err(local_store_error)?;
    Ok(Json(ModelRequestReplay::from_stored_request(
        attempt_id, request,
    )))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tower::ServiceExt;

    #[tokio::test]
    async fn replay_route_is_scoped_and_missing_snapshot_is_explicit() {
        let state = super::super::tests::test_state("replay-route-test");
        super::super::tests::seed_plan_conversation(&state, "replay-conversation");
        let request = json!({"protocol":"openai.chat_completions","body":{"model":"old-model","messages":[{"role":"user","content":"exact old input"}]}});
        state.session_store.append_timeline("replay-conversation", &json!({
            "id":"prepared","type":"model_request_prepared","message_id":"message",
            "data":{"attempt_id":"attempt","schema_version":1,"format":"provider.http.json/v1","request":request}
        })).unwrap();
        state
            .session_store
            .append_timeline(
                "replay-conversation",
                &json!({
                    "id":"legacy","type":"model_request_prepared","message_id":"message",
                    "data":{"attempt_id":"legacy","request":{"partial":"not exact"}}
                }),
            )
            .unwrap();
        let app = super::super::local_router(state);
        for (message, attempt, project, expected, status) in [
            (
                "message",
                "attempt",
                "local-project",
                StatusCode::OK,
                "available",
            ),
            (
                "wrong-message",
                "attempt",
                "local-project",
                StatusCode::OK,
                "snapshot_missing",
            ),
            (
                "message",
                "legacy",
                "local-project",
                StatusCode::OK,
                "snapshot_missing",
            ),
            (
                "message",
                "missing",
                "local-project",
                StatusCode::OK,
                "snapshot_missing",
            ),
            (
                "message",
                "attempt",
                "other-project",
                StatusCode::FORBIDDEN,
                "",
            ),
        ] {
            let response = app.clone().oneshot(axum::http::Request::builder()
                .uri(format!("/api/v1/agent/conversations/replay-conversation/messages/{message}/model-requests/{attempt}?project_id={project}"))
                .header("authorization","Bearer replay-route-test")
                .body(axum::body::Body::empty()).unwrap()).await.unwrap();
            assert_eq!(response.status(), expected);
            let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
                .await
                .unwrap();
            let body: Value = serde_json::from_slice(&bytes).unwrap();
            if expected == StatusCode::OK {
                assert_eq!(body["status"], status);
                if status == "available" {
                    assert_eq!(body["request"], request);
                } else {
                    assert_eq!(body["reason_code"], "model_request_snapshot_missing");
                }
            }
        }
        let unauthorized = app.oneshot(axum::http::Request::builder()
            .uri("/api/v1/agent/conversations/replay-conversation/messages/message/model-requests/attempt?project_id=local-project")
            .body(axum::body::Body::empty()).unwrap()).await.unwrap();
        assert_eq!(unauthorized.status(), StatusCode::UNAUTHORIZED);
    }
}
