use super::*;
use crate::local_runtime::knowledge_authority_v2::processing_context;
use agistack_core::knowledge::diagnostics::DiagnosticRequest;

#[tokio::test]
async fn diagnostics_rpc_exposes_safe_audit_and_persisted_index_failure_for_existing_retry() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    assert_eq!(
        command(&f, configure(&route, "a", None)).await.0,
        StatusCode::OK
    );
    let config = f
        .repo()
        .desired_index_config_durable(&f.operation.scope, &|| Ok(110))
        .unwrap()
        .unwrap();
    let lease = f
        .repo()
        .claim_index_durable(&config, "worker", 100, &|| Ok(110))
        .unwrap()
        .unwrap();
    f.repo()
        .fail_index_durable(&lease, IndexFailure::ProviderUnavailable, &|| Ok(111))
        .unwrap();
    let failed=query(&f,json!({"operation":"failed_index","build_id":"a","config_revision":1,"request":{"limit":1}})).await;
    assert_eq!(failed.0, StatusCode::OK, "{:?}", failed.1);
    assert_eq!(failed.1["result"]["items"][0]["input"], json!(lease.input));
    assert_eq!(failed.1["result"]["items"][0]["attempt"], 1);
    let audits = query(
        &f,
        json!({"operation":"processing_audits","source":f.source,"request":{"limit":1}}),
    )
    .await;
    assert_eq!(audits.0, StatusCode::OK);
    let record = &audits.1["result"]["items"][0];
    assert_eq!(record["status"], "applied");
    assert!(record.get("input").is_none());
    assert!(record.get("submission").is_none());
    assert!(!audits.1.to_string().contains("credential_binding_digest"));
    let retry = json!({"operation":"retry_index","build_id":"a","config_revision":1,"input":failed.1["result"]["items"][0]["input"],"expected_attempt":1});
    assert_eq!(command(&f, retry.clone()).await.0, StatusCode::OK);
    assert_eq!(command(&f, retry).await.0, StatusCode::CONFLICT);
    assert!(query(
        &f,
        json!({"operation":"failed_index","build_id":"a","config_revision":1,"request":{"limit":1}})
    )
    .await
    .1["result"]["items"]
        .as_array()
        .unwrap()
        .is_empty());
    assert_eq!(query(&f,json!({"operation":"failed_index","build_id":"a","config_revision":2,"request":{"limit":1}})).await.0,StatusCode::CONFLICT);
    let mut memory = f
        .repo()
        .get(&f.operation.scope, &f.source.memory_id)
        .await
        .unwrap()
        .unwrap();
    memory.content = "replaced".into();
    f.repo()
        .update(&f.operation.scope, memory, 1)
        .await
        .unwrap();
    assert_eq!(
        query(
            &f,
            json!({"operation":"processing_audits","source":f.source,"request":{"limit":1}})
        )
        .await
        .0,
        StatusCode::CONFLICT
    );
    let pending = f
        .repo()
        .claim(&f.operation.scope, "worker", 110, 100)
        .await
        .unwrap()
        .unwrap();
    f.repo()
        .fail(
            &f.operation.scope,
            &pending,
            ProcessingFailure::ModelUnconfigured,
            111,
        )
        .await
        .unwrap();
    let processing = query(
        &f,
        json!({"operation":"failed_processing","request":{"limit":1}}),
    )
    .await;
    assert_eq!(processing.0, StatusCode::OK);
    assert_eq!(
        processing.1["result"]["items"][0]["source"],
        json!(pending.source)
    );
    assert_eq!(endpoint.state.requests.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn diagnostics_rpc_validates_scope_source_generation_and_limits() {
    let f = Fixture::new().await;
    let bodies = [
        json!({"operation":"failed_processing","request":{"limit":1}}),
        json!({"operation":"processing_audits","source":f.source,"request":{"limit":1}}),
    ];
    let scope = json!(operation_scope(&f.auth, &f.operation._lease));
    for query_body in bodies {
        assert_eq!(
            request(
                f.state.clone(),
                "/api/v1/knowledge/processing-query",
                json!({"scope":scope,"query":query_body}),
                false
            )
            .await
            .0,
            StatusCode::UNAUTHORIZED
        );
        for field in ["tenant_id", "project_id", "generation", "context_revision"] {
            let mut changed = scope.clone();
            changed[field] = if field == "generation" || field == "context_revision" {
                json!(999)
            } else {
                json!("foreign")
            };
            let result = request(
                f.state.clone(),
                "/api/v1/knowledge/processing-query",
                json!({"scope":changed,"query":query_body}),
                true,
            )
            .await;
            assert!(!result.0.is_success(), "{field}: {:?}", result.1);
        }
        for limit in [0, 101] {
            let mut invalid = query_body.clone();
            invalid["request"]["limit"] = json!(limit);
            assert_eq!(query(&f, invalid).await.0, StatusCode::UNPROCESSABLE_ENTITY);
        }
    }
    let mut foreign = f.source.clone();
    foreign.tenant_id = "foreign".into();
    assert_eq!(
        query(
            &f,
            json!({"operation":"processing_audits","source":foreign,"request":{"limit":1}})
        )
        .await
        .0,
        StatusCode::UNPROCESSABLE_ENTITY
    );
}

#[tokio::test]
async fn diagnostics_viewer_can_read_but_actor_session_and_membership_changes_reject() {
    let f = Fixture::new().await;
    f.state
        .session_store
        .connection()
        .unwrap()
        .execute_batch("UPDATE desktop_tenant_memberships SET role='viewer'")
        .unwrap();
    assert_eq!(
        query(
            &f,
            json!({"operation":"processing_audits","source":f.source,"request":{"limit":1}})
        )
        .await
        .0,
        StatusCode::OK
    );
    assert_eq!(
        query(
            &f,
            json!({"operation":"failed_processing","request":{"limit":1}})
        )
        .await
        .0,
        StatusCode::OK
    );
    let mut auth = f.auth.clone();
    auth.user.user_id = "foreign-actor".into();
    assert!(
        processing_context::with_read_current(&f.operation, &f.state, &auth, |clock| f
            .repo()
            .failed_processing_durable(
                &f.operation.scope,
                &DiagnosticRequest {
                    limit: 1,
                    cursor: None
                },
                clock
            ))
        .is_err()
    );
    for sql in [
        "UPDATE desktop_user_sessions SET status='revoked'",
        "UPDATE desktop_user_sessions SET expires_at_ms=0",
        "DELETE FROM desktop_tenant_memberships",
    ] {
        let f = Fixture::new().await;
        f.state
            .session_store
            .connection()
            .unwrap()
            .execute_batch(sql)
            .unwrap();
        assert!(!query(
            &f,
            json!({"operation":"failed_processing","request":{"limit":1}})
        )
        .await
        .0
        .is_success());
        assert!(!query(
            &f,
            json!({"operation":"processing_audits","source":f.source,"request":{"limit":1}})
        )
        .await
        .0
        .is_success());
    }
}

#[tokio::test]
async fn diagnostics_generation_replacement_while_storage_waits_discards_result() {
    let f = Fixture::new().await;
    let connection =
        rusqlite::Connection::open(f.directory.0.join("knowledge/memories.db")).unwrap();
    connection.execute_batch("BEGIN EXCLUSIVE").unwrap();
    let (entered, wait) = std::sync::mpsc::channel();
    let op = f.operation.clone();
    let state = f.state.clone();
    let auth = f.auth.clone();
    let read = tokio::task::spawn_blocking(move || {
        processing_context::with_read_current(&op, &state, &auth, |clock| {
            entered.send(()).unwrap();
            op.authority
                .repository()
                .unwrap()
                .failed_processing_durable(
                    &op.scope,
                    &DiagnosticRequest {
                        limit: 1,
                        cursor: None,
                    },
                    clock,
                )
        })
    });
    wait.recv_timeout(std::time::Duration::from_secs(3))
        .unwrap();
    let (snapshot, generation) = stage(&f.directory, 2, false).await;
    let retirement = f.state.platform_plugin_authority_v2.replace_local_baseline(
        &snapshot,
        &serde_json::to_value(&snapshot).unwrap(),
        generation,
    );
    connection.execute_batch("COMMIT").unwrap();
    assert!(matches!(
        read.await.unwrap(),
        Err(KnowledgeAuthorityErrorV2::GenerationMismatch)
    ));
    drop(f.operation);
    retirement.dispose().await;
}

#[tokio::test]
async fn diagnostics_expiry_before_storage_return_discards_every_diagnostic_kind() {
    for kind in ["processing", "index", "audits"] {
        let f = Fixture::new().await;
        let endpoint = Endpoint::new().await;
        let route = f.provider(&endpoint).await;
        assert_eq!(
            command(&f, configure(&route, "a", None)).await.0,
            StatusCode::OK
        );
        let config = f
            .repo()
            .desired_index_config_durable(&f.operation.scope, &|| Ok(110))
            .unwrap()
            .unwrap();
        f.state
            .session_store
            .connection()
            .unwrap()
            .execute(
                "UPDATE desktop_user_sessions SET expires_at_ms=?1 WHERE id=?2",
                rusqlite::params![
                    chrono::Utc::now().timestamp_millis() + 200,
                    f.auth.session_id
                ],
            )
            .unwrap();
        let result =
            processing_context::with_read_current(&f.operation, &f.state, &f.auth, |clock| {
                let calls = std::cell::Cell::new(0);
                let delayed = || {
                    calls.set(calls.get() + 1);
                    if calls.get() == 2 {
                        std::thread::sleep(std::time::Duration::from_millis(250));
                    }
                    clock()
                };
                let request = DiagnosticRequest {
                    limit: 1,
                    cursor: None,
                };
                match kind {
                    "processing" => f
                        .repo()
                        .failed_processing_durable(&f.operation.scope, &request, &delayed)
                        .map(|_| ()),
                    "index" => f
                        .repo()
                        .failed_index_durable(&config, &request, &delayed)
                        .map(|_| ()),
                    _ => f
                        .repo()
                        .processing_audit_summaries_durable(
                            &f.operation.scope,
                            &f.source,
                            &request,
                            &delayed,
                        )
                        .map(|_| ()),
                }
            });
        assert!(
            matches!(result, Err(KnowledgeAuthorityErrorV2::Forbidden)),
            "{kind}: {result:?}"
        );
    }
}
