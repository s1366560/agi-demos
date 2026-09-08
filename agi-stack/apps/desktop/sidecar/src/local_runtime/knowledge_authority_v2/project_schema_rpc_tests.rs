//! Real router producer fixtures and the native schema protocol boundary.
use super::*;
use crate::local_runtime::local_router_with_generation_required;
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use tower::ServiceExt;

async fn call(
    state: &Arc<LocalRuntimeState>,
    action: &str,
    body: impl Into<Body>,
    extra: Option<(&str, &str)>,
) -> (StatusCode, Value) {
    let mut request = Request::builder()
        .method(if action == "capabilities" {
            "GET"
        } else {
            "POST"
        })
        .uri(format!("/api/v1/knowledge/schema/{action}"))
        .header("content-type", "application/json")
        .header("x-agistack-launch", TOKEN)
        .header("authorization", format!("Bearer {TOKEN}"));
    if let Some((key, value)) = extra {
        request = request.header(key, value);
    }
    let response = local_router_with_generation_required(Arc::clone(state))
        .oneshot(request.body(body.into()).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 3 * 1024 * 1024)
        .await
        .unwrap();
    (status, serde_json::from_slice(&bytes).unwrap())
}
fn scope(state: &LocalRuntimeState) -> Value {
    let lease = state
        .platform_plugin_authority_v2
        .acquire_generation()
        .unwrap();
    serde_json::to_value(operation_scope(&authenticated(state), &lease)).unwrap()
}
fn document(state: &LocalRuntimeState, revision: u32) -> Value {
    let auth = authenticated(state);
    json!({"format_version":1,"tenant_id":auth.workspace.tenant_id,"project_id":auth.workspace.project_id,
        "schema_id":"00000000-0000-4000-8000-000000000001","revision":revision,"deleted":false,
        "entity_types":[],"edge_types":[],"mappings":[],"tombstones":[]})
}
fn command(state: &LocalRuntimeState, revision: u32) -> Value {
    json!({"scope":scope(state),"change_id":Uuid::new_v4().to_string(),"expected_revision":revision-1,"document":document(state,revision)})
}
#[tokio::test]
async fn project_schema_rpc_producer_replays_original_receipt_and_snapshot_history() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let absent = call(
        &state,
        "read",
        json!({"scope":scope(&state)}).to_string(),
        None,
    )
    .await;
    assert_eq!(absent.0, StatusCode::OK);
    assert!(absent.1["result"]["document"].is_null());
    let cap = call(&state, "capabilities", "", None).await;
    assert_eq!(cap.0, StatusCode::OK);
    assert_eq!(
        cap.1["result"]["allowed_actions"].as_array().unwrap().len(),
        5
    );
    let first = command(&state, 1);
    let accepted = call(&state, "bootstrap", first.to_string(), None).await;
    assert_eq!(accepted.0, StatusCode::OK, "{}", accepted.1);
    let second = command(&state, 2);
    let replaced = call(&state, "replace", second.to_string(), None).await;
    assert_eq!(replaced.0, StatusCode::OK);
    let replay = call(&state, "bootstrap", first.to_string(), None).await;
    assert_eq!(replay, accepted);
    let receipt_request = json!({"scope":scope(&state),"change_id":first["change_id"]});
    let receipt = call(&state, "receipt", receipt_request.to_string(), None).await;
    assert_eq!(
        receipt.1["result"]["receipt"],
        accepted.1["result"]["receipt"]
    );
    let history_request = json!({"scope":scope(&state),"after_revision":0,"limit":1});
    let history = call(&state, "history", history_request.to_string(), None).await;
    assert_eq!(history.0, StatusCode::OK);
    assert_eq!(history.1["result"]["upper_revision"], 2);
    assert_eq!(history.1["result"]["next_after_revision"], 1);
    assert_eq!(history.1["result"]["has_more"], true);
    assert_eq!(
        history.1["result"]["items"][0],
        accepted.1["result"]["receipt"]
    );
    let read = call(
        &state,
        "read",
        json!({"scope":scope(&state)}).to_string(),
        None,
    )
    .await;
    assert_eq!(read.1["result"]["document"]["revision"], 2);
    if let Ok(path) = std::env::var("NATIVE_PROJECT_SCHEMA_RPC_FIXTURE") {
        fs::write(path,serde_json::to_vec(&json!({"actor":authenticated(&state).user.user_id,"scope":scope(&state),"capabilities":cap.1,
            "cases":[{"action":"schema_read","request":{"scope":scope(&state)},"response":absent.1},
            {"action":"schema_bootstrap","request":first,"response":accepted.1},
            {"action":"schema_replace","request":second,"response":replaced.1},
            {"action":"schema_receipt","request":receipt_request,"response":receipt.1},
            {"action":"schema_history","request":history_request,"response":history.1},
            {"action":"schema_read","request":{"scope":scope(&state)},"response":read.1}]})).unwrap()).unwrap();
    }
    state.platform_plugin_authority_v2.deactivate().await;
}
#[tokio::test]
async fn project_schema_rpc_rejects_raw_duplicates_tokens_and_conflicting_headers() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let first = command(&state, 1).to_string();
    for raw in [
        first.replace("\"revision\":1", "\"revision\":1,\"revision\":1"),
        first.replace("\"revision\":1", "\"revision\":1.0"),
        first.replace("\"context_revision\":0", "\"context_revision\":-0"),
        first.replace("\"entity_types\":[]", "\"entity_types\":[],\"extra\":true"),
        first.replace(
            "\"expected_revision\":0",
            "\"expected_revision\":0,\"expected_revision\":0",
        ),
    ] {
        assert_eq!(
            call(&state, "bootstrap", raw, None).await.0,
            StatusCode::UNPROCESSABLE_ENTITY
        );
    }
    assert_eq!(
        call(&state, "bootstrap", "{", None).await.0,
        StatusCode::BAD_REQUEST
    );
    assert_eq!(
        call(
            &state,
            "bootstrap",
            first.clone(),
            Some(("idempotency-key", "x"))
        )
        .await
        .0,
        StatusCode::UNPROCESSABLE_ENTITY
    );
    assert_eq!(
        call(&state, "bootstrap", first, None).await.0,
        StatusCode::OK
    );
    let mut wrong = command(&state, 2);
    wrong["document"]["project_id"] = json!("foreign");
    assert_eq!(
        call(&state, "replace", wrong.to_string(), None).await.0,
        StatusCode::FORBIDDEN
    );
    let huge = " ".repeat(2 * 1024 * 1024 + 1);
    assert_eq!(
        call(&state, "read", huge, None).await.0,
        StatusCode::PAYLOAD_TOO_LARGE
    );
    state.platform_plugin_authority_v2.deactivate().await;
}
#[tokio::test]
async fn project_schema_rpc_release_closed_never_opens_storage() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, false).await;
    let cap = call(&state, "capabilities", "", None).await;
    assert_eq!(cap.0, StatusCode::OK);
    assert_eq!(cap.1["result"]["allowed_actions"], json!([]));
    for (action, body) in [
        ("read", json!({"scope":scope(&state)})),
        ("bootstrap", command(&state, 1)),
        ("replace", command(&state, 2)),
        (
            "receipt",
            json!({"scope":scope(&state),"change_id":Uuid::new_v4().to_string()}),
        ),
        (
            "history",
            json!({"scope":scope(&state),"after_revision":0,"limit":100}),
        ),
    ] {
        assert_eq!(
            call(&state, action, body.to_string(), None).await.0,
            StatusCode::SERVICE_UNAVAILABLE
        );
    }
    assert!(!directory.0.join("knowledge").exists());
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn project_schema_rpc_live_viewer_cannot_replay_a_previously_accepted_write() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let first = command(&state, 1);
    assert_eq!(
        call(&state, "bootstrap", first.to_string(), None).await.0,
        StatusCode::OK
    );
    state
        .session_store
        .connection()
        .unwrap()
        .execute("UPDATE desktop_tenant_memberships SET role='viewer'", [])
        .unwrap();
    let cap = call(&state, "capabilities", "", None).await;
    assert_eq!(
        cap.1["result"]["allowed_actions"],
        json!(["schema_read", "schema_receipt", "schema_history"])
    );
    assert_eq!(
        call(&state, "bootstrap", first.to_string(), None).await.0,
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        call(
            &state,
            "read",
            json!({"scope":scope(&state)}).to_string(),
            None
        )
        .await
        .0,
        StatusCode::OK
    );
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn project_schema_rpc_generated_methods_and_paths_match_router() {
    use super::super::project_schema::SchemaAction;
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let source: Value = serde_json::from_str(include_str!(
        "../../../../../../../contracts/project-schema-v1/native-rpc.schema.json"
    ))
    .unwrap();
    for action in [
        SchemaAction::Read,
        SchemaAction::Bootstrap,
        SchemaAction::Replace,
        SchemaAction::Receipt,
        SchemaAction::History,
    ] {
        assert_eq!(action.method(), "POST");
        assert_eq!(
            source["x-actions"][action.as_str()]["method"],
            action.method()
        );
        assert_eq!(source["x-actions"][action.as_str()]["path"], action.path());
        let response = local_router_with_generation_required(Arc::clone(&state))
            .oneshot(
                Request::builder()
                    .method("GET")
                    .uri(action.path())
                    .header("x-agistack-launch", TOKEN)
                    .header("authorization", format!("Bearer {TOKEN}"))
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::METHOD_NOT_ALLOWED);
    }
    assert_eq!(source["x-capabilities"]["method"], "GET");
    assert_eq!(
        source["x-capabilities"]["path"],
        "/api/v1/knowledge/schema/capabilities"
    );
    state.platform_plugin_authority_v2.deactivate().await;
}

#[test]
fn project_schema_response_budget_reserves_nine_to_ten_cursor_and_true_to_false() {
    use super::super::project_schema::{response, SchemaAction, MAX_RESPONSE_BYTES};
    use agistack_adapters_device::knowledge::project_schema::{
        ProjectSchemaHistoryPage, ProjectSchemaStorageError,
    };
    let scope = KnowledgeOperationScopeV2 {
        tenant_id: "t".into(),
        project_id: "p".into(),
        context_revision: 0,
        profile_id: "schema".into(),
        generation: 1,
        digest: "ab".repeat(32),
    };
    let mut page = ProjectSchemaHistoryPage {
        schema_id: Some("00000000-0000-4000-8000-000000000001".into()),
        after_revision: 9,
        upper_revision: 10,
        next_after_revision: 9,
        has_more: true,
        items: Vec::new(),
    };
    let budget = response::item_budget("actor", &scope, &page).unwrap();
    let short = response::history("actor", &scope, &page).unwrap().len();
    page.next_after_revision = 10;
    page.has_more = false;
    let complete = response::history("actor", &scope, &page).unwrap().len();
    assert_eq!(
        complete,
        short + 2,
        "one digit and false's extra byte must both be reserved"
    );
    assert_eq!(budget + complete, MAX_RESPONSE_BYTES);
    assert_eq!(
        response::item_budget("actor", &scope, &page).unwrap(),
        budget
    );
    let overhead = response::encode("actor", &scope, SchemaAction::Read, json!({"padding":""}))
        .unwrap()
        .len();
    let exact = response::encode(
        "actor",
        &scope,
        SchemaAction::Read,
        json!({"padding":"x".repeat(MAX_RESPONSE_BYTES-overhead)}),
    )
    .unwrap();
    assert_eq!(exact.len(), MAX_RESPONSE_BYTES);
    assert!(matches!(
        response::encode(
            "actor",
            &scope,
            SchemaAction::Read,
            json!({"padding":"x".repeat(MAX_RESPONSE_BYTES-overhead+1)})
        ),
        Err(ProjectSchemaStorageError::ResponseTooLarge)
    ));
}

#[tokio::test]
async fn project_schema_rpc_rejects_capability_body_and_bound_action_substitution() {
    use super::super::project_schema::{ProjectSchemaOperationV2, SchemaAction};
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    assert_eq!(
        call(&state, "capabilities", "{}", None).await.0,
        StatusCode::UNPROCESSABLE_ENTITY
    );
    let auth = authenticated(&state);
    let lease = Arc::new(
        state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap(),
    );
    let scope = operation_scope(&auth, &lease);
    let operation =
        ProjectSchemaOperationV2::admit_action(&state, lease, &auth, &scope, SchemaAction::History)
            .unwrap();
    assert!(operation.read(&state, &auth).is_err());
    assert!(operation
        .receipt(&state, &auth, &Uuid::new_v4().to_string())
        .is_err());
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
}
