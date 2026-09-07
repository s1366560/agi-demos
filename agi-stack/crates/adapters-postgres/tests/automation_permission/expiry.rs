use agistack_adapters_postgres::{
    AutomationPermissionOutcome as Outcome, PgAutomationPermissionStore as Store,
};
use agistack_core::automation_permission::PermissionAnswer;

use crate::support::{answer, count, intent, seed, Fixture};

#[tokio::test]
async fn deadlines_crossed_during_writes_roll_back_intent_and_answer() {
    let mut incorrectly_admitted = Vec::new();
    for phase in ["intent", "answer"] {
        for expired in ["intent", "run", "hitl"] {
            let Some(f) = Fixture::open().await else {
                return;
            };
            seed(&f).await;
            let store = Store::new(f.pool.clone());
            if phase == "answer" {
                assert_eq!(
                    store
                        .record_intent(&intent(&f), chrono::Utc::now())
                        .await
                        .unwrap(),
                    Outcome::Applied
                );
            }
            let update=match expired {
                "intent"=>"UPDATE agistack_automation_permission_intents SET expires_at=clock_timestamp()+interval '100 milliseconds' WHERE id='intent'",
                "run"=>"UPDATE cron_job_runs SET deadline_at=clock_timestamp()+interval '100 milliseconds' WHERE id='run'",
                _=>"UPDATE hitl_requests SET expires_at=clock_timestamp()+interval '100 milliseconds' WHERE id='request'",
            };
            let event = if phase == "intent" {
                "INSERT ON agistack_automation_permission_intents"
            } else {
                "UPDATE OF status ON hitl_requests"
            };
            // Updating only expires_at does not recursively fire UPDATE OF status.
            let trigger=format!("CREATE FUNCTION cross_permission_expiry() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {update}; PERFORM pg_sleep(0.25); RETURN NEW; END $$;
                CREATE TRIGGER cross_expiry AFTER {event} FOR EACH ROW EXECUTE FUNCTION cross_permission_expiry();");
            sqlx::raw_sql(&trigger).execute(&f.pool).await.unwrap();
            let result = if phase == "intent" {
                store
                    .record_intent(&intent(&f), chrono::Utc::now())
                    .await
                    .unwrap()
            } else {
                store
                    .answer(&answer(&f, PermissionAnswer::AllowOnce), chrono::Utc::now())
                    .await
                    .unwrap()
            };
            if result != Outcome::NotAdmitted {
                incorrectly_admitted.push(format!("{phase}/{expired}: {result:?}"));
            }
            if result == Outcome::NotAdmitted {
                assert_eq!(
                    count(&f, "agistack_automation_permission_intents").await,
                    if phase == "intent" { 0 } else { 1 }
                );
                assert_eq!(
                    count(&f, "agistack_automation_permission_receipts").await,
                    0
                );
                assert_eq!(
                    count(&f, "agistack_automation_permission_consumptions").await,
                    0
                );
                let status: String = sqlx::query_scalar("SELECT status FROM hitl_requests")
                    .fetch_one(&f.pool)
                    .await
                    .unwrap();
                assert_eq!(status, "pending");
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
