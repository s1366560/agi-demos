//! Atomic HITL recovery over independent PostgreSQL connections.

#[path = "cron_hitl_admission/support.rs"]
mod support;

use agistack_adapters_postgres::{AutomationHitlAdmissionOutcome, PgAutomationHitlAdmission};
use support::Fixture;

#[tokio::test]
async fn stale_revision_and_cross_scope_cannot_touch_checkpoint() {
    let Some(fixture) = Fixture::open().await else {
        return;
    };
    fixture.seed().await;
    let repository = PgAutomationHitlAdmission::new(fixture.pool.clone());
    let original = fixture.checkpoint().await;
    let mut stale = fixture.command();
    stale.expected_runtime_revision = 6;
    let mut foreign = fixture.command();
    foreign.tenant_id = "another-tenant".into();
    let mut wrong_request = fixture.command();
    wrong_request.request_id = "another-request".into();
    for command in [stale, foreign, wrong_request] {
        assert_eq!(
            repository.admit(&command, support::now()).await.unwrap(),
            AutomationHitlAdmissionOutcome::NotAdmitted
        );
        assert_eq!(fixture.checkpoint().await, original);
    }
    fixture.close().await;
}

#[tokio::test]
async fn terminal_expired_and_secret_requests_are_not_admitted() {
    for update in [
        "UPDATE cron_job_runs SET status = 'completed'",
        "UPDATE cron_job_runs SET deadline_at = '2099-09-06'",
        "UPDATE hitl_requests SET expires_at = '2099-09-06'",
        "UPDATE hitl_requests SET request_type = 'env_var'",
        "UPDATE hitl_requests SET status = 'pending'",
        "UPDATE agistack_cron_operations SET status = 'cancelled'",
    ] {
        let Some(fixture) = Fixture::open().await else {
            return;
        };
        fixture.seed().await;
        let original = fixture.checkpoint().await;
        sqlx::query(update).execute(&fixture.pool).await.unwrap();
        assert_eq!(
            PgAutomationHitlAdmission::new(fixture.pool.clone())
                .admit(&fixture.command(), support::now())
                .await
                .unwrap(),
            AutomationHitlAdmissionOutcome::NotAdmitted,
            "{update}"
        );
        assert_eq!(fixture.checkpoint().await, original);
        fixture.close().await;
    }
}

#[tokio::test]
async fn newer_checkpoint_or_mismatched_kind_is_never_rewound() {
    for patch in [
        serde_json::json!({"status":"finished", "answer":"newer result", "round":12}),
        serde_json::json!({"pending_hitl":null, "round":12}),
        serde_json::json!({"pending_hitl":{"id":"newer-request", "kind":"clarification", "prompt":"Next?"}}),
        serde_json::json!({"pending_hitl":{"id":"request", "kind":"permission", "prompt":"Allow?"}}),
    ] {
        let Some(fixture) = Fixture::open().await else {
            return;
        };
        fixture.seed().await;
        sqlx::query("UPDATE agistack_checkpoints SET state = state || $1")
            .bind(patch)
            .execute(&fixture.pool)
            .await
            .unwrap();
        let before = fixture.checkpoint().await;
        assert!(PgAutomationHitlAdmission::new(fixture.pool.clone())
            .admit(&fixture.command(), support::now())
            .await
            .is_err());
        assert_eq!(fixture.checkpoint().await, before);
        fixture.close().await;
    }
}

#[tokio::test]
async fn failed_queue_update_rolls_back_checkpoint_acceptance() {
    let Some(fixture) = Fixture::open().await else {
        return;
    };
    fixture.seed().await;
    sqlx::query(
        "CREATE FUNCTION reject_queue() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'injected queue failure'; END; $$",
    )
    .execute(&fixture.pool)
    .await
    .unwrap();
    sqlx::query(
        "CREATE TRIGGER reject_queue BEFORE UPDATE ON cron_job_runs
        FOR EACH ROW EXECUTE FUNCTION reject_queue()",
    )
    .execute(&fixture.pool)
    .await
    .unwrap();
    let before = fixture.checkpoint().await;
    assert!(PgAutomationHitlAdmission::new(fixture.pool.clone())
        .admit(&fixture.command(), support::now())
        .await
        .is_err());
    assert_eq!(fixture.checkpoint().await, before);
    sqlx::query("DROP TRIGGER reject_queue ON cron_job_runs")
        .execute(&fixture.pool)
        .await
        .unwrap();
    PgAutomationHitlAdmission::new(fixture.pool.clone())
        .admit(&fixture.command(), support::now())
        .await
        .unwrap();
    fixture.assert_resumed().await;
    fixture.close().await;
}

#[tokio::test]
async fn old_accept_before_queue_crash_is_recovered_without_duplicate_answer() {
    use agistack_core::agent::{SessionState, SessionStatus};
    let Some(fixture) = Fixture::open().await else {
        return;
    };
    fixture.seed().await;
    let mut state: SessionState = serde_json::from_value(fixture.checkpoint().await).unwrap();
    state.record_hitl_answer("request", "confirmed");
    state.status = SessionStatus::Running;
    sqlx::query("UPDATE agistack_checkpoints SET state = state || $1")
        .bind(serde_json::to_value(&state).unwrap())
        .execute(&fixture.pool)
        .await
        .unwrap();
    PgAutomationHitlAdmission::new(fixture.pool.clone())
        .admit(&fixture.command(), support::now())
        .await
        .unwrap();
    fixture.assert_resumed().await;
    let resumed: SessionState = serde_json::from_value(fixture.checkpoint().await).unwrap();
    assert_eq!(resumed.hitl_responses.len(), 1);
    fixture.close().await;
}

#[tokio::test]
async fn resumed_run_gets_a_fresh_runtime_lease_and_old_admission_cannot_replay() {
    use agistack_adapters_postgres::{AutomationRuntimeScope, PgCronAutomationRuntimeRepository};
    let Some(fixture) = Fixture::open().await else {
        return;
    };
    fixture.seed().await;
    let repository = PgAutomationHitlAdmission::new(fixture.pool.clone());
    repository
        .admit(&fixture.command(), support::now())
        .await
        .unwrap();
    let leases = PgCronAutomationRuntimeRepository::new(fixture.pool.clone())
        .claim_due(
            &AutomationRuntimeScope {
                tenant_id: "tenant".into(),
                project_id: "project".into(),
            },
            1,
            "new-worker",
            30,
            support::now(),
        )
        .await
        .unwrap();
    assert_eq!(leases.len(), 1);
    assert_eq!(leases[0].runtime_revision, 9);
    assert_ne!(leases[0].lease_token, "old-token");
    let before = fixture.checkpoint().await;
    assert_eq!(
        repository
            .admit(&fixture.command(), support::now())
            .await
            .unwrap(),
        AutomationHitlAdmissionOutcome::NotAdmitted
    );
    assert_eq!(fixture.checkpoint().await, before);
    fixture.close().await;
}

#[tokio::test]
async fn cancelling_a_resume_waiter_releases_database_locks_without_partial_acceptance() {
    let Some(fixture) = Fixture::open().await else {
        return;
    };
    fixture.seed().await;
    let before = fixture.checkpoint().await;
    let mut blocker = fixture.pool.begin().await.unwrap();
    sqlx::query("SELECT state FROM agistack_checkpoints WHERE session_id = 'run' FOR UPDATE")
        .fetch_one(&mut *blocker)
        .await
        .unwrap();
    let repository = PgAutomationHitlAdmission::new(fixture.pool.clone());
    let command = fixture.command();
    let waiter = tokio::spawn(async move { repository.admit(&command, support::now()).await });
    // The checkpoint is locked above. Wait for the admission to hold the run
    // row, proving it entered its transaction before cancelling the waiter.
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let mut probe = fixture.pool.begin().await.unwrap();
            let result =
                sqlx::query("SELECT id FROM cron_job_runs WHERE id = 'run' FOR UPDATE NOWAIT")
                    .fetch_one(&mut *probe)
                    .await;
            probe.rollback().await.unwrap();
            match result {
                Err(sqlx::Error::Database(error)) if error.code().as_deref() == Some("55P03") => {
                    break
                }
                Ok(_) => tokio::task::yield_now().await,
                Err(error) => panic!("unexpected lock probe error: {error}"),
            }
        }
    })
    .await
    .unwrap();
    waiter.abort();
    assert!(waiter.await.unwrap_err().is_cancelled());
    blocker.rollback().await.unwrap();
    assert_eq!(fixture.checkpoint().await, before);
    tokio::time::timeout(
        std::time::Duration::from_secs(5),
        PgAutomationHitlAdmission::new(fixture.pool.clone())
            .admit(&fixture.command(), support::now()),
    )
    .await
    .unwrap()
    .unwrap();
    fixture.assert_resumed().await;
    fixture.close().await;
}

#[tokio::test]
async fn expiry_at_queue_boundary_rolls_back_the_accepted_checkpoint() {
    for expire in [
        "UPDATE cron_job_runs SET deadline_at = '2099-09-06';",
        "UPDATE hitl_requests SET expires_at = '2099-09-06';",
    ] {
        let Some(fixture) = Fixture::open().await else {
            return;
        };
        fixture.seed().await;
        let before = fixture.checkpoint().await;
        // Inject expiry after acceptance but before the queue CAS, without a
        // wall-clock race or changing any application-owned schema.
        sqlx::query(&format!(
            "CREATE FUNCTION expire_answer() RETURNS trigger LANGUAGE plpgsql AS $$
             BEGIN {expire} RETURN NEW; END; $$"
        ))
        .execute(&fixture.pool)
        .await
        .unwrap();
        sqlx::query(
            "CREATE TRIGGER expire_answer BEFORE UPDATE ON agistack_checkpoints
            FOR EACH ROW EXECUTE FUNCTION expire_answer()",
        )
        .execute(&fixture.pool)
        .await
        .unwrap();
        assert!(PgAutomationHitlAdmission::new(fixture.pool.clone())
            .admit(&fixture.command(), support::now())
            .await
            .is_err());
        assert_eq!(fixture.checkpoint().await, before);
        fixture.close().await;
    }
}

#[tokio::test]
async fn decision_and_both_permission_answers_resume_without_minting_tool_authority() {
    use agistack_core::agent::SessionState;
    for (kind, answer) in [
        ("decision", "choice-a"),
        ("permission", "allow"),
        ("permission", "deny"),
    ] {
        let Some(fixture) = Fixture::open().await else {
            return;
        };
        fixture.seed().await;
        sqlx::query("UPDATE hitl_requests SET request_type = $1, response_metadata = $2")
            .bind(kind)
            .bind(serde_json::json!({"resume_answer": answer}))
            .execute(&fixture.pool)
            .await
            .unwrap();
        sqlx::query(
            "UPDATE agistack_checkpoints SET state = jsonb_set(state, '{pending_hitl,kind}', $1)",
        )
        .bind(serde_json::json!(kind))
        .execute(&fixture.pool)
        .await
        .unwrap();
        assert_eq!(
            PgAutomationHitlAdmission::new(fixture.pool.clone())
                .admit(&fixture.command(), support::now())
                .await
                .unwrap(),
            AutomationHitlAdmissionOutcome::Applied {
                runtime_revision: 8
            }
        );
        let after = fixture.checkpoint().await;
        let state: SessionState = serde_json::from_value(after).unwrap();
        assert_eq!(state.hitl_answer("request"), Some(answer));
        assert!(state.completed_tool_calls.is_empty());
        let operation: String = sqlx::query_scalar("SELECT status FROM agistack_cron_operations")
            .fetch_one(&fixture.pool)
            .await
            .unwrap();
        assert_eq!(operation, "waiting_runtime");
        fixture.close().await;
    }
}

#[tokio::test]
async fn answer_and_queue_commit_once_across_independent_pools() {
    let Some(fixture) = Fixture::open().await else {
        return;
    };
    fixture.seed().await;
    let first = PgAutomationHitlAdmission::new(fixture.pool.clone());
    let second_pool = fixture.independent_pool().await;
    let second = PgAutomationHitlAdmission::new(second_pool.clone());
    let command = fixture.command();
    let (a, b) = tokio::join!(
        first.admit(&command, support::now()),
        second.admit(&command, support::now())
    );
    let results = [a.unwrap(), b.unwrap()];
    assert_eq!(
        results
            .iter()
            .filter(|value| matches!(
                value,
                AutomationHitlAdmissionOutcome::Applied {
                    runtime_revision: 8
                }
            ))
            .count(),
        1
    );
    assert_eq!(
        results
            .iter()
            .filter(|value| matches!(value, AutomationHitlAdmissionOutcome::NotAdmitted))
            .count(),
        1
    );
    fixture.assert_resumed().await;
    second_pool.close().await;
    fixture.close().await;
}
