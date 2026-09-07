use crate::support::{answer, intent, now, record, seed, Fixture};

#[tokio::test]
async fn superseded_or_consumed_receipt_does_not_regrant() {
    for status in [
        "revoked",
        "reserved",
        "dispatched",
        "completed",
        "outcome_unknown",
    ] {
        let Some(f) = Fixture::open().await else {
            return;
        };
        seed(&f).await;
        record(&f).await;
        let store = Store::new(f.pool.clone());
        let command = answer(&f, PermissionAnswer::AllowOnce);
        assert_eq!(
            store.answer(&command, now()).await.unwrap(),
            Outcome::Applied
        );
        sqlx::query("UPDATE agistack_automation_permission_consumptions SET status=$1,use_count=1")
            .bind(status)
            .execute(&f.pool)
            .await
            .unwrap();
        assert_eq!(
            store.answer(&command, now()).await.unwrap(),
            Outcome::Replayed
        );
        let persisted: (String, i64) = sqlx::query_as(
            "SELECT status,use_count FROM agistack_automation_permission_consumptions",
        )
        .fetch_one(&f.pool)
        .await
        .unwrap();
        assert_eq!(persisted, (status.to_string(), 1));
        f.close().await;
    }
}

#[tokio::test]
async fn key_expiring_during_admission_rolls_back_receipt_and_answer() {
    let Some(f) = Fixture::open().await else {
        return;
    };
    seed(&f).await;
    sqlx::query("UPDATE agistack_cron_operations SET actor_api_key_id='actor-key'")
        .execute(&f.pool)
        .await
        .unwrap();
    let store = Store::new(f.pool.clone());
    assert_eq!(
        store
            .record_intent(&intent(&f), chrono::Utc::now())
            .await
            .unwrap(),
        Outcome::Applied
    );
    sqlx::raw_sql("CREATE FUNCTION slow_permission_receipt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(1); RETURN NEW; END $$;
        CREATE TRIGGER slow_receipt AFTER INSERT ON agistack_automation_permission_receipts FOR EACH ROW EXECUTE FUNCTION slow_permission_receipt();")
        .execute(&f.pool).await.unwrap();
    sqlx::query("UPDATE api_keys SET expires_at=clock_timestamp()+interval '600 milliseconds'")
        .execute(&f.pool)
        .await
        .unwrap();
    assert_eq!(
        store
            .answer(&answer(&f, PermissionAnswer::AllowOnce), chrono::Utc::now())
            .await
            .unwrap(),
        Outcome::NotAdmitted
    );
    assert_eq!(
        crate::support::count(&f, "agistack_automation_permission_receipts").await,
        0
    );
    assert_eq!(
        crate::support::count(&f, "agistack_automation_permission_consumptions").await,
        0
    );
    let status: String = sqlx::query_scalar("SELECT status FROM hitl_requests")
        .fetch_one(&f.pool)
        .await
        .unwrap();
    assert_eq!(status, "pending");
    f.close().await;
}

#[tokio::test]
async fn key_revocation_in_another_transaction_prevents_answer() {
    let Some(f) = Fixture::open().await else {
        return;
    };
    seed(&f).await;
    sqlx::query("UPDATE agistack_cron_operations SET actor_api_key_id='actor-key'")
        .execute(&f.pool)
        .await
        .unwrap();
    record(&f).await;
    let mut revoke = f.pool.begin().await.unwrap();
    sqlx::query("UPDATE api_keys SET is_active=false WHERE id='actor-key'")
        .execute(&mut *revoke)
        .await
        .unwrap();
    let other = f.independent_pool().await;
    let store = Store::new(other.clone());
    let command = answer(&f, PermissionAnswer::AllowOnce);
    let mut pending = tokio::spawn(async move { store.answer(&command, now()).await });
    assert!(
        tokio::time::timeout(std::time::Duration::from_millis(30), &mut pending)
            .await
            .is_err()
    );
    revoke.commit().await.unwrap();
    assert_eq!(pending.await.unwrap().unwrap(), Outcome::NotAdmitted);
    assert_eq!(
        crate::support::count(&f, "agistack_automation_permission_receipts").await,
        0
    );
    other.close().await;
    f.close().await;
}
use agistack_adapters_postgres::{
    AutomationPermissionOutcome as Outcome, PgAutomationPermissionStore as Store,
};
use agistack_core::automation_permission::PermissionAnswer;

#[tokio::test]
async fn actor_and_key_revocation_rejects_intent_answer_and_replay() {
    let mut incorrectly_admitted = Vec::new();
    for phase in ["intent", "answer", "replay"] {
        for change in [
            "UPDATE users SET is_active=false WHERE id='actor'",
            "DELETE FROM user_tenants WHERE user_id='actor'",
            "DELETE FROM user_projects WHERE user_id='actor'",
            "UPDATE user_projects SET role='viewer' WHERE user_id='actor'",
            "UPDATE api_keys SET is_active=false WHERE id='actor-key'",
            "UPDATE api_keys SET expires_at='2099-09-06' WHERE id='actor-key'",
            "UPDATE api_keys SET user_id='responder' WHERE id='actor-key'",
            "DELETE FROM api_keys WHERE id='actor-key'",
        ] {
            let Some(f) = Fixture::open().await else {
                return;
            };
            seed(&f).await;
            sqlx::query("UPDATE agistack_cron_operations SET actor_api_key_id='actor-key'")
                .execute(&f.pool)
                .await
                .unwrap();
            let store = Store::new(f.pool.clone());
            if phase != "intent" {
                record(&f).await;
            }
            if phase == "replay" {
                assert_eq!(
                    store
                        .answer(&answer(&f, PermissionAnswer::AllowOnce), now())
                        .await
                        .unwrap(),
                    Outcome::Applied
                );
            }
            sqlx::query(change).execute(&f.pool).await.unwrap();
            let result = if phase == "intent" {
                store.record_intent(&intent(&f), now()).await.unwrap()
            } else {
                store
                    .answer(&answer(&f, PermissionAnswer::AllowOnce), now())
                    .await
                    .unwrap()
            };
            if result != Outcome::NotAdmitted {
                incorrectly_admitted.push(format!("{phase}: {change}: {result:?}"));
            }
            f.close().await;
        }
    }
    assert!(
        incorrectly_admitted.is_empty(),
        "{}",
        incorrectly_admitted.join("\n")
    );
}

#[tokio::test]
async fn viewer_responder_cannot_allow_but_can_deny_and_owner_keeps_write_right() {
    for (outcome, owner, expected) in [
        (PermissionAnswer::AllowOnce, false, Outcome::NotAdmitted),
        (PermissionAnswer::Deny, false, Outcome::Applied),
        (PermissionAnswer::AllowOnce, true, Outcome::Applied),
    ] {
        let Some(f) = Fixture::open().await else {
            return;
        };
        seed(&f).await;
        record(&f).await;
        sqlx::query("UPDATE user_projects SET role='viewer' WHERE user_id='responder'")
            .execute(&f.pool)
            .await
            .unwrap();
        if owner {
            sqlx::query("UPDATE projects SET owner_id='responder'")
                .execute(&f.pool)
                .await
                .unwrap();
        }
        assert_eq!(
            Store::new(f.pool.clone())
                .answer(&answer(&f, outcome), now())
                .await
                .unwrap(),
            expected
        );
        f.close().await;
    }
}
