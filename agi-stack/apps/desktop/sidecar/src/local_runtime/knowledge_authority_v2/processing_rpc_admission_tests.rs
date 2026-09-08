use super::*;

#[tokio::test]
async fn query_and_command_enforce_closed_publication_scope_generation_and_no_client_profile() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    for (key, value) in [
        ("profile", json!({"dimensions":2})),
        ("vector", json!([1.0, 0.0])),
        ("lease_ms", json!(999)),
        ("credential_binding_digest", json!("fake")),
    ] {
        let mut body = configure(&route, "a", None);
        body[key] = value;
        assert_eq!(command(&f, body).await.0, StatusCode::UNPROCESSABLE_ENTITY);
    }
    let mut missing = configure(&route, "a", None);
    missing
        .as_object_mut()
        .unwrap()
        .remove("expected_config_revision");
    assert_eq!(
        command(&f, missing).await.0,
        StatusCode::UNPROCESSABLE_ENTITY
    );
    assert!(endpoint.state.requests.lock().unwrap().is_empty());
    let scope = json!(operation_scope(&f.auth, &f.operation._lease));
    assert_eq!(
        request(
            f.state.clone(),
            "/api/v1/knowledge/processing-query",
            json!({"scope":scope,"query":{"operation":"configuration"}}),
            false
        )
        .await
        .0,
        StatusCode::UNAUTHORIZED
    );
    for field in ["tenant_id", "project_id", "generation"] {
        let mut changed = scope.clone();
        changed[field] = if field == "generation" {
            json!(99)
        } else {
            json!("foreign")
        };
        let response = request(
            f.state.clone(),
            "/api/v1/knowledge/processing-query",
            json!({"scope":changed,"query":{"operation":"configuration"}}),
            true,
        )
        .await;
        assert_eq!(
            response.0,
            if field == "generation" {
                StatusCode::CONFLICT
            } else {
                StatusCode::FORBIDDEN
            }
        );
    }
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, false).await;
    let lease = state
        .platform_plugin_authority_v2
        .acquire_generation()
        .unwrap();
    let scope = operation_scope(&authenticated(&state), &lease);
    for (path, body) in [
        (
            "processing-query",
            json!({"scope":scope,"query":{"operation":"configuration"}}),
        ),
        (
            "processing-command",
            json!({"scope":scope,"command":{"operation":"process_one","workspace_id":"explicit-workspace"}}),
        ),
    ] {
        let response = request(
            state.clone(),
            &format!("/api/v1/knowledge/{path}"),
            body,
            true,
        )
        .await;
        assert_eq!(response.0, StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(response.1["error"]["code"], "knowledge_release_closed");
    }
    assert!(!directory.0.exists());
}

#[tokio::test]
async fn viewer_reads_configuration_and_literal_results_but_cannot_start_any_provider_work() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    f.state
        .session_store
        .connection()
        .unwrap()
        .execute_batch("UPDATE desktop_tenant_memberships SET role='viewer'")
        .unwrap();
    let discovered = query(&f, json!({"operation":"configuration"})).await;
    assert_eq!(discovered.0, StatusCode::OK);
    let memory = f
        .repo()
        .get(&f.operation.scope, &f.source.memory_id)
        .await
        .unwrap()
        .unwrap();
    let literal = query(
        &f,
        json!({"operation":"text","literal":memory.content,"request":{"limit":1}}),
    )
    .await;
    assert_eq!(literal.0, StatusCode::OK);
    assert_eq!(literal.1["result"]["items"].as_array().unwrap().len(), 1);
    for operation in ["entities", "relationships"] {
        assert_eq!(
            query(&f, json!({"operation":operation,"request":{"limit":1}}))
                .await
                .0,
            StatusCode::OK
        );
    }
    for body in [
        configure(&route, "a", None),
        json!({"operation":"select_embedding","build_id":"a","expected_config_revision":null}),
        json!({"operation":"index_one","build_id":"a","config_revision":1}),
        json!({"operation":"promote_index","build_id":"a","config_revision":1,"expected_active_build_id":null}),
        json!({"operation":"retry_index","build_id":"a","config_revision":1,"input":{"source":f.source,"audit_attempt":1,"input_digest":"digest"},"expected_attempt":1}),
        json!({"operation":"process_one","workspace_id":"explicit-workspace"}),
    ] {
        assert_eq!(command(&f, body).await.0, StatusCode::FORBIDDEN);
    }
    assert!(endpoint.state.requests.lock().unwrap().is_empty());
}
