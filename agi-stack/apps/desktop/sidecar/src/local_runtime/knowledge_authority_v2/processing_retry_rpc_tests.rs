use super::*;
use crate::local_runtime::knowledge_authority_v2::processing_context;
use agistack_core::knowledge::processing::{ProcessingLease, ProcessingState};

async fn failed_source(f: &Fixture) -> ProcessingLease {
    let repo = f.repo();
    let mut memory = repo
        .get(&f.operation.scope, &f.source.memory_id)
        .await
        .unwrap()
        .unwrap();
    memory.content = "New source requiring extraction".into();
    repo.update(&f.operation.scope, memory, 1).await.unwrap();
    let lease = repo
        .claim(&f.operation.scope, "test-worker", 100, 50)
        .await
        .unwrap()
        .unwrap();
    repo.fail(
        &f.operation.scope,
        &lease,
        ProcessingFailure::ProviderUnavailable,
        101,
    )
    .await
    .unwrap();
    lease
}
fn retry(lease: &ProcessingLease) -> Value {
    json!({"operation":"retry_processing","source":lease.source,"expected_attempt":lease.attempt})
}

#[tokio::test]
async fn retry_processing_rpc_queues_exact_failure_without_provider_or_worker_dispatch() {
    let f = Fixture::new().await;
    let failed = failed_source(&f).await;
    let task = json!({"operation":"processing_task","source":failed.source});
    assert_eq!(
        query(&f, task.clone()).await.1["result"]["task"]["state"],
        "failed"
    );
    let mut wrong = retry(&failed);
    wrong["expected_attempt"] = json!(2);
    assert_eq!(command(&f, wrong).await.0, StatusCode::CONFLICT);
    let accepted = command(&f, retry(&failed)).await;
    assert_eq!(accepted.0, StatusCode::OK, "{accepted:?}");
    assert_eq!(
        accepted.1["result"],
        json!({"accepted":true,"source":failed.source,"attempt":1})
    );
    let observed = query(&f, task.clone()).await;
    assert_eq!(observed.1["result"]["task"]["state"], "pending");
    assert_eq!(observed.1["result"]["task"]["attempt"], 1);
    assert_eq!(command(&f, retry(&failed)).await.0, StatusCode::CONFLICT);
    let reopened = SqliteKnowledgeRepository::open(
        f.directory
            .0
            .join("knowledge/memories.db")
            .to_str()
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        reopened
            .processing_task_durable(&f.operation.scope, &failed.source, &|| Ok(110))
            .unwrap()
            .task
            .unwrap()
            .state,
        ProcessingState::Pending
    );
    let next = reopened
        .claim(&f.operation.scope, "explicit-worker", 110, 50)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(next.attempt, 2);
    reopened
        .fail(&f.operation.scope, &next, ProcessingFailure::Cancelled, 111)
        .await
        .unwrap();
    assert_eq!(command(&f, retry(&failed)).await.0, StatusCode::CONFLICT);
    let current = reopened
        .get(&f.operation.scope, &failed.source.memory_id)
        .await
        .unwrap()
        .unwrap();
    reopened
        .update(&f.operation.scope, current, 2)
        .await
        .unwrap();
    let obsolete = query(&f, task).await;
    assert_eq!(obsolete.1["result"]["current"], false);
    assert!(obsolete.1["result"]["task"].is_null());
    assert_eq!(command(&f, retry(&next)).await.0, StatusCode::CONFLICT);
}

#[tokio::test]
async fn retry_processing_rejects_foreign_source_scope_generation_and_live_permissions() {
    let f = Fixture::new().await;
    let failed = failed_source(&f).await;
    let scope = json!(operation_scope(&f.auth, &f.operation._lease));
    for field in [
        "tenant_id",
        "project_id",
        "context_revision",
        "generation",
        "digest",
    ] {
        let mut changed = scope.clone();
        changed[field] = if field == "context_revision" || field == "generation" {
            json!(999)
        } else {
            json!("other")
        };
        assert!(!request(
            f.state.clone(),
            "/api/v1/knowledge/processing-command",
            json!({"scope":changed,"command":retry(&failed)}),
            true
        )
        .await
        .0
        .is_success());
    }
    let mut foreign = retry(&failed);
    foreign["source"]["tenant_id"] = json!("other");
    assert_eq!(
        command(&f, foreign).await.0,
        StatusCode::UNPROCESSABLE_ENTITY
    );
    let mut actor = f.auth.clone();
    actor.user.user_id = "other".into();
    assert!(processing_context::with_read_current_checked(
        &f.operation,
        &f.state,
        &actor,
        true,
        |_| Ok(()),
        |clock| f
            .repo()
            .retry_processing_durable(&f.operation.scope, &failed.source, 1, clock)
    )
    .is_err());
    f.state
        .session_store
        .connection()
        .unwrap()
        .execute_batch("UPDATE desktop_tenant_memberships SET role='viewer'")
        .unwrap();
    assert_eq!(
        query(
            &f,
            json!({"operation":"processing_task","source":failed.source})
        )
        .await
        .0,
        StatusCode::OK
    );
    assert_eq!(command(&f, retry(&failed)).await.0, StatusCode::FORBIDDEN);
    for sql in [
        "UPDATE desktop_user_sessions SET status='revoked'",
        "UPDATE desktop_user_sessions SET expires_at_ms=0",
        "DELETE FROM desktop_tenant_memberships",
    ] {
        let f = Fixture::new().await;
        let failed = failed_source(&f).await;
        f.state
            .session_store
            .connection()
            .unwrap()
            .execute_batch(sql)
            .unwrap();
        assert!(!command(&f, retry(&failed)).await.0.is_success());
        assert_eq!(
            f.repo()
                .processing_task_durable(&f.operation.scope, &failed.source, &|| Ok(105))
                .unwrap()
                .task
                .unwrap()
                .state,
            ProcessingState::Failed
        );
    }
}

#[tokio::test]
async fn retry_processing_expiry_before_commit_rolls_back_state_transition() {
    let f = Fixture::new().await;
    let failed = failed_source(&f).await;
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
    let result = processing_context::with_read_current_checked(
        &f.operation,
        &f.state,
        &f.auth,
        true,
        |_| Ok(()),
        |clock| {
            let calls = std::cell::Cell::new(0);
            f.repo()
                .retry_processing_durable(&f.operation.scope, &failed.source, 1, &|| {
                    calls.set(calls.get() + 1);
                    if calls.get() == 2 {
                        std::thread::sleep(std::time::Duration::from_millis(250));
                    }
                    clock()
                })
        },
    );
    assert!(matches!(result, Err(KnowledgeAuthorityErrorV2::Forbidden)));
    assert_eq!(
        f.repo()
            .processing_task_durable(&f.operation.scope, &failed.source, &|| Ok(105))
            .unwrap()
            .task
            .unwrap()
            .state,
        ProcessingState::Failed
    );
}

#[tokio::test]
async fn retry_processing_final_admission_rechecks_exact_action_and_active_generation() {
    let f = Fixture::new().await;
    let failed = failed_source(&f).await;
    let op = KnowledgeOperationV2::admit(
        f.operation._lease.clone(),
        &f.auth,
        &operation_scope(&f.auth, &f.operation._lease),
    )
    .unwrap()
    .admit_capability(&f.state, &f.auth, "retry_processing")
    .unwrap();
    f.operation
        .authority
        .inner
        .lock()
        .unwrap()
        .validation_actions = Some(["processing_task".to_owned()].into_iter().collect());
    let result = processing_context::with_read_current_checked(
        &op,
        &f.state,
        &f.auth,
        true,
        |_| Ok(()),
        |clock| {
            f.repo()
                .retry_processing_durable(&op.scope, &failed.source, 1, clock)
        },
    );
    assert!(result.is_err());
    assert_eq!(command(&f, retry(&failed)).await.0, StatusCode::FORBIDDEN);
    assert_eq!(
        f.repo()
            .processing_task_durable(&op.scope, &failed.source, &|| Ok(103))
            .unwrap()
            .task
            .unwrap()
            .state,
        ProcessingState::Failed
    );
    f.operation
        .authority
        .inner
        .lock()
        .unwrap()
        .validation_actions = None;
    let repo = f.repo();
    let (snapshot, generation) = stage(&f.directory, 2, false).await;
    let retirement = f.state.platform_plugin_authority_v2.replace_local_baseline(
        &snapshot,
        &serde_json::to_value(&snapshot).unwrap(),
        generation,
    );
    let result = processing_context::with_read_current_checked(
        &op,
        &f.state,
        &f.auth,
        true,
        |_| Ok(()),
        |clock| repo.retry_processing_durable(&op.scope, &failed.source, 1, clock),
    );
    assert!(matches!(
        result,
        Err(KnowledgeAuthorityErrorV2::GenerationMismatch)
    ));
    assert_eq!(
        repo.processing_task_durable(&op.scope, &failed.source, &|| Ok(104))
            .unwrap()
            .task
            .unwrap()
            .state,
        ProcessingState::Failed
    );
    drop(op);
    drop(f.operation);
    retirement.dispose().await;
}
