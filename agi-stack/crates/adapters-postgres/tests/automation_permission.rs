//! Exact permission admission, using independent connections against real PostgreSQL.

#[path = "cron_hitl_admission/support.rs"]
#[allow(dead_code)]
mod admission_support;
#[path = "automation_permission/expiry.rs"]
mod expiry;
#[path = "automation_permission/revocation.rs"]
mod revocation;
#[path = "automation_permission/support.rs"]
mod support;

use agistack_adapters_postgres::{
    AutomationPermissionOutcome as Outcome, PgAutomationPermissionStore as Store,
};
use agistack_core::automation_permission::PermissionAnswer;
use support::{answer, count, intent, now, record, seed, Fixture};

#[tokio::test]
async fn exact_answer_replays_without_resuming_or_consuming() {
    let Some(f) = Fixture::open().await else {
        return;
    };
    seed(&f).await;
    record(&f).await;
    let checkpoint = f.checkpoint().await;
    let other = f.independent_pool().await;
    let command = answer(&f, PermissionAnswer::AllowOnce);
    let first = Store::new(f.pool.clone());
    let second = Store::new(other.clone());
    let (a, b) = tokio::join!(
        first.answer(&command, now()),
        second.answer(&command, now())
    );
    let outcomes = [a.unwrap(), b.unwrap()];
    assert!(outcomes.contains(&Outcome::Applied));
    assert!(outcomes.contains(&Outcome::Replayed));
    assert_eq!(
        count(&f, "agistack_automation_permission_receipts").await,
        1
    );
    let ledger: (String, i64, i64) = sqlx::query_as(
        "SELECT status,max_uses,use_count FROM agistack_automation_permission_consumptions",
    )
    .fetch_one(&f.pool)
    .await
    .unwrap();
    assert_eq!(ledger, ("awaiting_dispatch_binding".into(), 1, 0));
    let run: (String, i64) = sqlx::query_as("SELECT status,runtime_revision FROM cron_job_runs")
        .fetch_one(&f.pool)
        .await
        .unwrap();
    assert_eq!(run, ("waiting_human".into(), 7));
    assert_eq!(checkpoint, f.checkpoint().await);
    let metadata: serde_json::Value =
        sqlx::query_scalar("SELECT response_metadata FROM hitl_requests")
            .fetch_one(&f.pool)
            .await
            .unwrap();
    assert_eq!(metadata["permission_answer"], "allow_once");
    assert!(metadata.get("resume_answer").is_none());
    let mut conflict = answer(&f, PermissionAnswer::Deny);
    assert_eq!(
        Store::new(f.pool.clone())
            .answer(&conflict, now())
            .await
            .unwrap(),
        Outcome::NotAdmitted
    );
    conflict.answer = PermissionAnswer::AllowOnce;
    conflict.idempotency_key = "different-key".into();
    assert_eq!(
        Store::new(f.pool.clone())
            .answer(&conflict, now())
            .await
            .unwrap(),
        Outcome::NotAdmitted
    );
    other.close().await;
    f.close().await;
}

#[tokio::test]
async fn denial_has_no_consumption_grant() {
    let Some(f) = Fixture::open().await else {
        return;
    };
    seed(&f).await;
    record(&f).await;
    assert_eq!(
        Store::new(f.pool.clone())
            .answer(&answer(&f, PermissionAnswer::Deny), now())
            .await
            .unwrap(),
        Outcome::Applied
    );
    assert_eq!(
        count(&f, "agistack_automation_permission_receipts").await,
        1
    );
    assert_eq!(
        count(&f, "agistack_automation_permission_consumptions").await,
        0
    );
    f.close().await;
}

#[tokio::test]
async fn unassigned_request_requires_current_conversation_owner() {
    for owner in ["responder", "another-user"] {
        let Some(f) = Fixture::open().await else {
            return;
        };
        seed(&f).await;
        record(&f).await;
        sqlx::query("UPDATE hitl_requests SET user_id=NULL")
            .execute(&f.pool)
            .await
            .unwrap();
        sqlx::query("UPDATE conversations SET user_id=$1")
            .bind(owner)
            .execute(&f.pool)
            .await
            .unwrap();
        assert_eq!(
            Store::new(f.pool.clone())
                .answer(&answer(&f, PermissionAnswer::Deny), now())
                .await
                .unwrap(),
            if owner == "responder" {
                Outcome::Applied
            } else {
                Outcome::NotAdmitted
            }
        );
        f.close().await;
    }
}

#[tokio::test]
async fn recorded_intent_is_not_replaced_and_ledger_cannot_grant_two_uses() {
    let Some(f) = Fixture::open().await else {
        return;
    };
    seed(&f).await;
    record(&f).await;
    let mut replacement = intent(&f);
    replacement.binding =
        agistack_core::automation_permission::HostPermissionBinding::from_host_observation(
            "invocation".into(),
            "different-tool".into(),
            "9.0".into(),
            "b".repeat(64),
        );
    assert_eq!(
        Store::new(f.pool.clone())
            .record_intent(&replacement, now())
            .await
            .unwrap(),
        Outcome::NotAdmitted
    );
    let identity: (String, String, String) = sqlx::query_as(
        "SELECT tool_name, tool_version, input_sha256 FROM agistack_automation_permission_intents",
    )
    .fetch_one(&f.pool)
    .await
    .unwrap();
    assert_eq!(identity, ("write".into(), "1.2.0".into(), "a".repeat(64)));
    assert_eq!(
        Store::new(f.pool.clone())
            .answer(&answer(&f, PermissionAnswer::AllowOnce), now())
            .await
            .unwrap(),
        Outcome::Applied
    );
    for change in [
        "max_uses=2",
        "use_count=2",
        "use_count=-1",
        "status='ready'",
    ] {
        let error = sqlx::query(&format!(
            "UPDATE agistack_automation_permission_consumptions SET {change}"
        ))
        .execute(&f.pool)
        .await
        .unwrap_err();
        assert_eq!(
            error.as_database_error().and_then(|e| e.code()).as_deref(),
            Some("23514")
        );
    }
    f.close().await;
}

#[tokio::test]
async fn missing_host_proof_or_mismatched_request_cannot_record_intent() {
    let Some(f) = Fixture::open().await else {
        return;
    };
    seed(&f).await;
    let mut command = intent(&f);
    command.binding = None;
    assert_eq!(
        Store::new(f.pool.clone())
            .record_intent(&command, now())
            .await
            .unwrap(),
        Outcome::NotAdmitted
    );
    let mut command = intent(&f);
    command.scope.request_id = "foreign".into();
    assert_eq!(
        Store::new(f.pool.clone())
            .record_intent(&command, now())
            .await
            .unwrap(),
        Outcome::NotAdmitted
    );
    assert_eq!(count(&f, "agistack_automation_permission_intents").await, 0);
    f.close().await;
}

#[tokio::test]
async fn revoked_or_changed_authority_is_rechecked_before_accepting_answer() {
    for change in [
        "DELETE FROM user_projects WHERE user_id='responder'",
        "DELETE FROM user_tenants WHERE user_id='responder'",
        "UPDATE users SET is_active=false WHERE id='responder'",
        "UPDATE projects SET tenant_id='foreign'",
        "UPDATE cron_job_runs SET runtime_revision=8",
        "UPDATE cron_job_runs SET status='completed'",
        "UPDATE cron_job_runs SET deadline_at='2099-09-06'",
        "UPDATE hitl_requests SET expires_at='2099-09-06'",
        "UPDATE hitl_requests SET user_id='another-user'",
        "UPDATE hitl_requests SET status='cancelled'",
        "UPDATE agistack_automation_permission_intents SET expires_at='2099-09-07 00:00:01+00'",
        "UPDATE agistack_cron_operations SET actor_user_id='different-actor'",
        "UPDATE agistack_checkpoints SET state=jsonb_set(state,'{pending_hitl,id}','\"new-request\"')",
    ] {
        let Some(f)=Fixture::open().await else {return}; seed(&f).await; record(&f).await;
        sqlx::query(change).execute(&f.pool).await.unwrap();
        assert_eq!(Store::new(f.pool.clone()).answer(&answer(&f,PermissionAnswer::AllowOnce),now()+chrono::Duration::seconds(2)).await.unwrap(),Outcome::NotAdmitted,"{change}");
        assert_eq!(count(&f,"agistack_automation_permission_receipts").await,0,"{change}");
        assert_eq!(count(&f,"agistack_automation_permission_consumptions").await,0,"{change}");
        f.close().await;
    }
}

#[tokio::test]
async fn cross_scope_and_stale_answers_are_rejected() {
    let Some(f) = Fixture::open().await else {
        return;
    };
    seed(&f).await;
    record(&f).await;
    for part in 0..6 {
        let mut c = answer(&f, PermissionAnswer::AllowOnce);
        match part {
            0 => c.scope.tenant_id = "other".into(),
            1 => c.scope.project_id = "other".into(),
            2 => c.scope.expected_runtime_revision = 6,
            3 => c.intent_id = "other".into(),
            4 => c.scope.conversation_id = "other".into(),
            _ => c.responder_user_id = "other".into(),
        }
        assert_eq!(
            Store::new(f.pool.clone()).answer(&c, now()).await.unwrap(),
            Outcome::NotAdmitted
        );
    }
    assert_eq!(
        count(&f, "agistack_automation_permission_receipts").await,
        0
    );
    f.close().await;
}

#[tokio::test]
async fn revocation_committing_while_answer_waits_prevents_admission() {
    let Some(f) = Fixture::open().await else {
        return;
    };
    seed(&f).await;
    record(&f).await;
    let mut revocation = f.pool.begin().await.unwrap();
    sqlx::query("DELETE FROM user_projects WHERE user_id='responder'")
        .execute(&mut *revocation)
        .await
        .unwrap();
    let other = f.independent_pool().await;
    let command = answer(&f, PermissionAnswer::AllowOnce);
    let store = Store::new(other.clone());
    let pending = tokio::spawn(async move { store.answer(&command, now()).await });
    tokio::task::yield_now().await;
    revocation.commit().await.unwrap();
    assert_eq!(pending.await.unwrap().unwrap(), Outcome::NotAdmitted);
    assert_eq!(
        count(&f, "agistack_automation_permission_receipts").await,
        0
    );
    other.close().await;
    f.close().await;
}
