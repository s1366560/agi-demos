use agistack_adapters_postgres::{
    CronOperationErrorCode, CronOperationFailure, CronOperationKind, CronOperationScope,
    CronOperationStatus, NewCronOperation, PgCronOperationRepository,
};
use serde_json::json;
use std::time::Duration;

use super::support::*;

#[tokio::test]
async fn cron_operations_enforce_scope_and_fenced_lease_transitions() {
    let Some(pool) =
        pool_or_skip("cron_operations_enforce_scope_and_fenced_lease_transitions").await
    else {
        return;
    };
    ensure_cron_operation_table(&pool).await;
    clean_rows(&pool).await;

    let repo = PgCronOperationRepository::new(pool.clone());
    let now = ts(2026, 7, 14, 12, 0, 0);
    let scope = CronOperationScope {
        tenant_id: "cron_operation_tenant",
        project_id: "cron_operation_project",
    };
    let operation = repo
        .enqueue(NewCronOperation {
            id: "cron_operation_retry".to_string(),
            tenant_id: scope.tenant_id.to_string(),
            project_id: scope.project_id.to_string(),
            job_id: "cron_operation_job".to_string(),
            job_revision: 7,
            schedule_revision: Some(3),
            kind: CronOperationKind::ExecuteRun,
            run_id: Some("cron_operation_run".to_string()),
            trigger_type: Some("manual".to_string()),
            scheduled_for: None,
            input_json: json!({"conversation_id": "conversation-1"}),
            actor_user_id: Some("user-1".to_string()),
            actor_api_key_id: None,
            request_receipt_id: Some("receipt-1".to_string()),
            max_attempts: 2,
            next_attempt_at: Some(now),
            created_at: now,
        })
        .await
        .expect("enqueue operation");
    assert_eq!(operation.status, CronOperationStatus::Pending);
    assert_eq!(operation.job_revision, 7);
    assert_eq!(operation.input_json["conversation_id"], "conversation-1");

    let wrong_scope = CronOperationScope {
        tenant_id: scope.tenant_id,
        project_id: "other-project",
    };
    assert!(repo
        .claim_due(wrong_scope, 10, "worker-1", 30, now)
        .await
        .expect("wrong scope claim")
        .is_empty());

    let first_claim = repo
        .claim_due(scope, 10, "worker-1", 30, now)
        .await
        .expect("first claim")
        .pop()
        .expect("operation claimed");
    let first_token = first_claim
        .lease_token
        .as_deref()
        .expect("claim has fencing token");
    assert_eq!(first_claim.attempt_count, 1);
    assert!(!repo
        .renew(scope, &first_claim.id, "worker-1", "wrong-token", 30, now)
        .await
        .expect("wrong token renew is rejected"));
    assert!(repo
        .complete(
            scope,
            &first_claim.id,
            "worker-1",
            "wrong-token",
            &json!({"status": "ignored"}),
            now,
        )
        .await
        .expect("wrong token completion query")
        .is_none());

    let failed = repo
        .fail(
            scope,
            &first_claim.id,
            "worker-1",
            first_token,
            CronOperationFailure::new(
                CronOperationErrorCode::HandlerUnavailable,
                "handler unavailable",
                5,
            ),
            now + Duration::from_secs(1),
        )
        .await
        .expect("first failure query")
        .expect("active lease records failure");
    assert_eq!(failed.status, CronOperationStatus::Failed);
    assert_eq!(
        failed.last_error_code,
        Some(CronOperationErrorCode::HandlerUnavailable)
    );

    let second_claim = repo
        .claim_due(scope, 10, "worker-2", 30, now + Duration::from_secs(6))
        .await
        .expect("retry claim")
        .pop()
        .expect("failed operation reclaimed");
    let second_token = second_claim
        .lease_token
        .as_deref()
        .expect("retry claim has fencing token");
    assert_eq!(second_claim.attempt_count, 2);

    let dead_letter = repo
        .fail(
            scope,
            &second_claim.id,
            "worker-2",
            second_token,
            CronOperationFailure::new(
                CronOperationErrorCode::ExecutionFailed,
                "typed execution failure",
                5,
            ),
            now + Duration::from_secs(7),
        )
        .await
        .expect("terminal failure query")
        .expect("active retry lease records failure");
    assert_eq!(dead_letter.status, CronOperationStatus::DeadLetter);
    assert!(dead_letter.next_attempt_at.is_none());
    assert!(dead_letter.completed_at.is_some());

    clean_rows(&pool).await;
}

#[tokio::test]
async fn cron_operation_dispatch_acceptance_waits_for_runtime_under_fenced_lease() {
    let Some(pool) =
        pool_or_skip("cron_operation_dispatch_acceptance_waits_for_runtime_under_fenced_lease")
            .await
    else {
        return;
    };
    ensure_cron_operation_table(&pool).await;
    clean_rows(&pool).await;

    let repo = PgCronOperationRepository::new(pool.clone());
    let now = ts(2026, 7, 14, 13, 0, 0);
    let scope = CronOperationScope {
        tenant_id: "cron_operation_tenant",
        project_id: "cron_operation_project",
    };
    let operation = repo
        .enqueue(NewCronOperation {
            id: "cron_operation_waiting_runtime".to_string(),
            tenant_id: scope.tenant_id.to_string(),
            project_id: scope.project_id.to_string(),
            job_id: "cron_operation_job".to_string(),
            job_revision: 8,
            schedule_revision: None,
            kind: CronOperationKind::ExecuteRun,
            run_id: Some("runtime-message-1".to_string()),
            trigger_type: Some("manual".to_string()),
            scheduled_for: None,
            input_json: json!({"runtime_execution_id": "runtime-message-1"}),
            actor_user_id: Some("user-1".to_string()),
            actor_api_key_id: Some("api-key-1".to_string()),
            request_receipt_id: Some("receipt-2".to_string()),
            max_attempts: 2,
            next_attempt_at: Some(now),
            created_at: now,
        })
        .await
        .expect("enqueue operation");
    let claim = repo
        .claim_due(scope, 1, "worker-1", 30, now)
        .await
        .expect("claim operation")
        .pop()
        .expect("operation claimed");
    let token = claim
        .lease_token
        .as_deref()
        .expect("claim has fencing token");

    let waiting = repo
        .mark_waiting_runtime(
            scope,
            &operation.id,
            "worker-1",
            token,
            &json!({"message_id": "runtime-message-1", "dispatch": "accepted"}),
            now + Duration::from_secs(1),
        )
        .await
        .expect("waiting-runtime transition")
        .expect("active lease accepts transition");

    assert_eq!(waiting.status, CronOperationStatus::WaitingRuntime);
    assert_eq!(waiting.result_json["message_id"], "runtime-message-1");
    assert!(waiting.lease_owner.is_none());
    assert!(waiting.lease_token.is_none());
    assert!(waiting.lease_expires_at.is_none());
    assert!(waiting.completed_at.is_none());
    assert!(repo
        .complete(
            scope,
            &operation.id,
            "worker-1",
            token,
            &json!({"status": "premature"}),
            now + Duration::from_secs(2),
        )
        .await
        .expect("stale completion query")
        .is_none());
    assert!(repo
        .claim_due(scope, 1, "worker-2", 30, now + Duration::from_secs(60))
        .await
        .expect("waiting runtime is not reclaimed")
        .is_empty());

    clean_rows(&pool).await;
}

#[tokio::test]
async fn cron_operation_dispatch_ack_reconciles_an_already_terminal_runtime() {
    let Some(pool) =
        pool_or_skip("cron_operation_dispatch_ack_reconciles_an_already_terminal_runtime").await
    else {
        return;
    };
    ensure_cron_operation_table(&pool).await;
    clean_rows(&pool).await;
    let Some((project_id, tenant_id)) = sqlx::query_as::<_, (String, String)>(
        "SELECT id, tenant_id FROM projects ORDER BY created_at LIMIT 1",
    )
    .fetch_optional(&pool)
    .await
    .expect("load project scope") else {
        return;
    };

    let job_id = "cron_operation_terminal_job";
    let run_id = "cron_operation_terminal_run";
    sqlx::query(
        "INSERT INTO cron_jobs ( \
            id, project_id, tenant_id, name, revision, schedule_revision, \
            enabled, delete_after_run, schedule_type, schedule_config, payload_type, \
            payload_config, delivery_type, delivery_config, conversation_mode, timezone, \
            stagger_seconds, timeout_seconds, max_retries, state \
         ) VALUES ( \
            $1, $2, $3, 'Runtime terminal probe', 1, 1, true, false, 'every', \
            '{}'::json, 'agent_turn', '{}'::json, 'none', '{}'::json, 'reuse', 'UTC', \
            0, 300, 3, '{}'::json \
         )",
    )
    .bind(job_id)
    .bind(&project_id)
    .bind(&tenant_id)
    .execute(&pool)
    .await
    .expect("insert cron job");

    let now = ts(2026, 7, 14, 14, 0, 0);
    sqlx::query(
        "INSERT INTO cron_job_runs ( \
            id, job_id, project_id, status, trigger_type, accepted_at, job_revision, \
            schedule_revision, runtime_execution_id, started_at, finished_at, result_summary \
         ) VALUES ( \
            $1, $2, $3, 'success', 'manual', $4, 1, 1, $1, $4, $4, \
            '{\"event_count\":2}'::json \
         )",
    )
    .bind(run_id)
    .bind(job_id)
    .bind(&project_id)
    .bind(now)
    .execute(&pool)
    .await
    .expect("insert terminal cron run");

    let repo = PgCronOperationRepository::new(pool.clone());
    let scope = CronOperationScope {
        tenant_id: &tenant_id,
        project_id: &project_id,
    };
    let operation = repo
        .enqueue(NewCronOperation {
            id: "cron_operation_terminal_ack".to_string(),
            tenant_id: tenant_id.clone(),
            project_id: project_id.clone(),
            job_id: job_id.to_string(),
            job_revision: 1,
            schedule_revision: None,
            kind: CronOperationKind::ExecuteRun,
            run_id: Some(run_id.to_string()),
            trigger_type: Some("manual".to_string()),
            scheduled_for: None,
            input_json: json!({"runtime_execution_id": run_id}),
            actor_user_id: None,
            actor_api_key_id: None,
            request_receipt_id: None,
            max_attempts: 2,
            next_attempt_at: Some(now),
            created_at: now,
        })
        .await
        .expect("enqueue operation");
    let claim = repo
        .claim_due(scope, 1, "worker-1", 30, now)
        .await
        .expect("claim operation")
        .pop()
        .expect("operation claimed");
    let token = claim
        .lease_token
        .as_deref()
        .expect("claim has fencing token");

    let reconciled = repo
        .mark_waiting_runtime(
            scope,
            &operation.id,
            "worker-1",
            token,
            &json!({"dispatch": "accepted"}),
            now,
        )
        .await
        .expect("dispatch acknowledgement")
        .expect("active lease transitions");

    assert_eq!(reconciled.status, CronOperationStatus::Completed);
    assert_eq!(reconciled.result_json["runtime_status"], "success");
    assert_eq!(reconciled.result_json["event_count"], 2);
    assert!(reconciled.completed_at.is_some());
    assert!(reconciled.lease_token.is_none());

    clean_rows(&pool).await;
}

async fn ensure_cron_operation_table(pool: &PgPool) {
    sqlx::query(
        "CREATE TABLE IF NOT EXISTS agistack_cron_operations ( \
            id VARCHAR PRIMARY KEY, tenant_id VARCHAR NOT NULL, project_id VARCHAR NOT NULL, \
            job_id VARCHAR NOT NULL, job_revision BIGINT NOT NULL, schedule_revision BIGINT, \
            operation_kind VARCHAR(40) NOT NULL, run_id VARCHAR, trigger_type VARCHAR(40), \
            scheduled_for TIMESTAMPTZ, input_json JSONB NOT NULL DEFAULT '{}'::jsonb, \
            status VARCHAR(32) NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, \
            max_attempts INTEGER NOT NULL DEFAULT 5, next_attempt_at TIMESTAMPTZ, \
            lease_owner VARCHAR(255), lease_token VARCHAR(255), lease_expires_at TIMESTAMPTZ, \
            actor_user_id VARCHAR, actor_api_key_id VARCHAR, request_receipt_id VARCHAR, \
            result_json JSONB NOT NULL DEFAULT '{}'::jsonb, last_error_code VARCHAR(100), \
            last_error_redacted TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), \
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), started_at TIMESTAMPTZ, \
            completed_at TIMESTAMPTZ, cancel_requested_at TIMESTAMPTZ \
        )",
    )
    .execute(pool)
    .await
    .expect("ensure cron operation table");
}

async fn clean_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM agistack_cron_operations WHERE id LIKE 'cron_operation_%'")
        .execute(pool)
        .await
        .expect("clean cron operation rows");
    sqlx::query("DELETE FROM cron_job_runs WHERE id LIKE 'cron_operation_%'")
        .execute(pool)
        .await
        .expect("clean cron run rows");
    sqlx::query("DELETE FROM cron_jobs WHERE id LIKE 'cron_operation_%'")
        .execute(pool)
        .await
        .expect("clean cron job rows");
}
