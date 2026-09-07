use super::*;

#[tokio::test]
async fn delayed_provider_renews_lease_and_cancellation_records_terminal_audit() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new(&f, action(&f.source)).await;
    let run = f.spawn(
        endpoint.provider(),
        ProcessingRunOptions {
            lease_ms: 500,
            renew_every_ms: 25,
        },
    );
    endpoint.wait().await;
    tokio::time::sleep(std::time::Duration::from_millis(650)).await;
    assert!(f
        .repo()
        .claim(
            &f.operation.scope,
            "competing",
            chrono::Utc::now().timestamp_millis(),
            500
        )
        .await
        .unwrap()
        .is_none());
    run.abort();
    assert!(run.await.unwrap_err().is_cancelled());
    assert_failure(
        f.audit().outcome.as_ref().unwrap(),
        ProcessingAuditFailure::Cancelled,
    );
    f.no_projection().await;
}

#[tokio::test]
async fn admission_revoked_during_provider_call_never_publishes() {
    for sql in [
        "UPDATE desktop_user_sessions SET status='revoked'",
        "UPDATE desktop_user_sessions SET expires_at_ms=0",
        "UPDATE desktop_users SET status='disabled'",
        "UPDATE desktop_tenant_memberships SET status='suspended'",
        "UPDATE desktop_tenant_memberships SET role='viewer'",
        "UPDATE desktop_projects SET status='archived'",
        "UPDATE desktop_workspace_contexts SET revision=revision+1",
    ] {
        let f = Fixture::new().await;
        let endpoint = Endpoint::new(&f, action(&f.source)).await;
        let run = f.spawn(endpoint.provider(), ProcessingRunOptions::default());
        endpoint.wait().await;
        f.state
            .session_store
            .connection()
            .unwrap()
            .execute_batch(sql)
            .unwrap();
        endpoint.release.notify_one();
        let receipt = run.await.unwrap().unwrap().unwrap();
        assert_failure(&receipt.outcome, ProcessingAuditFailure::AdmissionChanged);
        f.no_projection().await;
    }
}

#[tokio::test]
async fn source_revision_or_deletion_invalidates_inflight_projection() {
    for deleted in [false, true] {
        let f = Fixture::new().await;
        let endpoint = Endpoint::new(&f, action(&f.source)).await;
        let run = f.spawn(endpoint.provider(), ProcessingRunOptions::default());
        endpoint.wait().await;
        let mutation = if deleted {
            MemoryMutation::Delete {
                id: f.source.memory_id.clone(),
                expected_revision: 1,
            }
        } else {
            let mut memory = f.operation.get(&f.source.memory_id).await.unwrap().unwrap();
            memory.content = "new revision".into();
            MemoryMutation::Update {
                memory,
                expected_revision: 1,
            }
        };
        f.operation.mutate("change", mutation).await.unwrap();
        endpoint.release.notify_one();
        let receipt = run.await.unwrap().unwrap().unwrap();
        assert_failure(&receipt.outcome, ProcessingAuditFailure::LeaseLost);
        f.no_projection().await;
    }
}

#[tokio::test]
async fn generation_replacement_waits_for_processing_before_disposing_storage() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new(&f, action(&f.source)).await;
    let escaped = f.operation.authority.clone();
    let run = f.spawn(endpoint.provider(), ProcessingRunOptions::default());
    endpoint.wait().await;
    let (snapshot, generation) = stage(&f.directory, 2, false).await;
    let retirement = f.state.platform_plugin_authority_v2.replace_local_baseline(
        &snapshot,
        &serde_json::to_value(&snapshot).unwrap(),
        generation,
    );
    assert!(escaped.repository().is_ok());
    endpoint.release.notify_one();
    assert!(matches!(
        run.await.unwrap().unwrap().unwrap().outcome,
        ProcessingAuditOutcome::Applied { .. }
    ));
    drop(f.operation);
    retirement.dispose().await;
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        while escaped.repository().is_ok() {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("retired generation must dispose after processing releases its lease");
    assert!(matches!(
        escaped.repository(),
        Err(KnowledgeAuthorityErrorV2::Disposed)
    ));
}

#[tokio::test]
async fn internal_entry_uses_verified_workspace_policy_and_existing_provider_binding() {
    use crate::local_runtime::{local_router, workspace_core_bridge};
    use axum::{body::Body, extract::Path, http::Request, routing::get};
    use tower::ServiceExt;
    let f = Fixture::new().await;
    assert!(f
        .operation
        .process_one(
            f.state.clone(),
            f.auth.clone(),
            "explicit-workspace",
            ProcessingRunOptions::default()
        )
        .await
        .is_err());
    assert!(f
        .repo()
        .processing_audit_durable(&f.operation.scope, &f.source, 1)
        .unwrap()
        .is_none());
    let endpoint = Endpoint::new(&f, action(&f.source)).await;
    let request=Request::builder().method("PUT").uri("/api/v1/llm-providers/local-runtime")
        .header("authorization",format!("Bearer {TOKEN}")).header("x-agistack-launch",TOKEN).header("content-type","application/json")
        .body(Body::from(json!({"provider_type":"openai_compatible","base_url":endpoint.base,"auth_method":"none","llm_model":"fixture-model","allowed_models":["fixture-model"],"is_active":true,"expected_revision":0}).to_string())).unwrap();
    let configured = local_router(f.state.clone())
        .oneshot(request)
        .await
        .unwrap();
    assert_eq!(configured.status(), axum::http::StatusCode::OK);
    let app=Router::new().route("/api/v1/tenants/:tenant/projects/:project/workspaces/:workspace",get(|Path((tenant,project,workspace)):Path<(String,String,String)>|async move {Json(json!({"id":workspace,"tenant_id":tenant,"project_id":project}))}))
        .route("/api/v1/tenants/:tenant/projects/:project/workspaces/:workspace/agent-policy",get(|Path((tenant,project,workspace)):Path<(String,String,String)>|async move {Json(json!({"workspace_id":workspace,"tenant_id":tenant,"project_id":project,"roles":{"default":{"provider_id":"local-runtime","model_id":"fixture-model"},"fast":null,"coding":null,"vision":null},"fallbacks":[]}))}));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}/", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    workspace_core_bridge::install_authority(
        &f.state,
        base,
        "fixture-service".into(),
        "fixture-registry".into(),
        "fixture-webhook".into(),
        "fixture-event".into(),
    )
    .unwrap();
    let operation = f.operation.clone();
    let state = f.state.clone();
    let auth = f.auth.clone();
    let run = tokio::spawn(async move {
        operation
            .process_one(
                state,
                auth,
                "explicit-workspace",
                ProcessingRunOptions::default(),
            )
            .await
    });
    endpoint.wait().await;
    endpoint.release.notify_one();
    assert!(matches!(
        run.await.unwrap().unwrap().unwrap().outcome,
        ProcessingAuditOutcome::Applied { .. }
    ));
    assert_eq!(f.audit().invocation.provider_id, "local-runtime");
    server.abort();
}

#[tokio::test]
async fn session_time_expiry_after_storage_wait_or_before_commit_rolls_back_projection() {
    use agistack_core::knowledge::processing::worker::{ProcessingInput, SUBMIT_PROJECTION_TOOL};
    for before_commit in [false, true] {
        let f = Fixture::new().await;
        let lease = f
            .repo()
            .claim_processing_durable(
                &f.operation.scope,
                "worker",
                chrono::Utc::now().timestamp_millis(),
                30_000,
            )
            .unwrap()
            .unwrap();
        let invocation = ProcessingInvocation {
            agent_id: "agent".into(),
            provider_id: "fixture-provider".into(),
            model_id: "fixture-model".into(),
            tool_name: SUBMIT_PROJECTION_TOOL.into(),
            contract_version: 1,
            input: ProcessingInput {
                source: f.source.clone(),
                title: "Knowledge".into(),
                content: "generation-owned content".into(),
            },
        };
        f.repo()
            .begin_processing_audit_durable(
                &f.operation.scope,
                &lease,
                invocation,
                chrono::Utc::now().timestamp_millis(),
            )
            .unwrap();
        f.state
            .session_store
            .connection()
            .unwrap()
            .execute(
                "UPDATE desktop_user_sessions SET expires_at_ms=?1 WHERE id=?2",
                rusqlite::params![
                    chrono::Utc::now().timestamp_millis() + 1000,
                    f.auth.session_id
                ],
            )
            .unwrap();
        let db = rusqlite::Connection::open(f.directory.0.join("knowledge/memories.db")).unwrap();
        if !before_commit {
            db.execute_batch("BEGIN IMMEDIATE").unwrap();
        }
        let (entered, wait) = std::sync::mpsc::channel();
        let operation = f.operation.clone();
        let state = f.state.clone();
        let auth = f.auth.clone();
        let handle = std::thread::spawn(move || {
            super::super::super::processing_context::with_current(
                &operation,
                &state,
                &auth,
                |clock| {
                    entered.send(()).unwrap();
                    let calls = std::cell::Cell::new(0);
                    let checked_clock = || {
                        let call = calls.get();
                        calls.set(call + 1);
                        if before_commit && call == 1 {
                            std::thread::sleep(std::time::Duration::from_millis(1100));
                        }
                        clock()
                    };
                    operation
                        .authority
                        .repository()
                        .unwrap()
                        .finish_processing_audit_durable_with_clock(
                            &operation.scope,
                            &lease,
                            ProcessingAuditOutcome::Applied {
                                submission: ProjectionSubmission {
                                    source: lease.source.clone(),
                                    entities: vec![],
                                    relationships: vec![],
                                    rationale: "No facts.".into(),
                                },
                            },
                            0,
                            &checked_clock,
                        )
                },
            )
        });
        wait.recv_timeout(std::time::Duration::from_secs(3))
            .unwrap();
        if !before_commit {
            std::thread::sleep(std::time::Duration::from_millis(1100));
            db.execute_batch("COMMIT").unwrap();
        }
        assert!(matches!(
            handle.join().unwrap(),
            Err(KnowledgeAuthorityErrorV2::Forbidden)
        ));
        f.no_projection().await;
        assert!(f.audit().outcome.is_none());
    }
}
