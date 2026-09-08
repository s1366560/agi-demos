use std::sync::Arc;

use agistack_adapters_postgres::PgCronSchedulerOwnerRepository;
use agistack_plugin_host::GenerationManagerV2;
use chrono::Utc;
use sqlx::postgres::PgPoolOptions;

use super::support::*;
use crate::background_worker_control_v2::BackgroundWorkerGenerationV2;

#[tokio::test]
async fn postgres_cron_generations_preserve_owner_fencing_and_private_resource_lifetimes() {
    let Ok(database_url) = crate::startup_config::repository_database_url() else {
        eprintln!("[skip] Cron generation Postgres test: repository DATABASE_URL unavailable");
        return;
    };
    let pool = PgPoolOptions::new()
        .max_connections(1)
        .connect(database_url.expose())
        .await
        .unwrap();
    // Only this connection's temporary owner row is changed. Production ownership is untouched.
    sqlx::query("CREATE TEMP TABLE agistack_cron_scheduler_owners (LIKE public.agistack_cron_scheduler_owners INCLUDING ALL)")
        .execute(&pool).await.unwrap();
    sqlx::query(
        "ALTER TABLE pg_temp.agistack_cron_scheduler_owners
        ADD COLUMN IF NOT EXISTS cutover_phase text NOT NULL DEFAULT 'unverified',
        ADD COLUMN IF NOT EXISTS cutover_revision bigint NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS cutover_evidence json NOT NULL DEFAULT '{}'",
    )
    .execute(&pool)
    .await
    .unwrap();
    let fixture = serde_json::json!({
        "protocol": "cron-cutover-evidence.v1",
        "manifest": {"deployment_id": "fixture-deployment"},
        "verification": {
            "protocol": "cron-deployment-verification.v1", "deployment_id": "fixture-deployment",
            "cutover_revision": 1, "receipt_id": "fixture-only", "verifier_id": "fixture-only",
            "inventory_sha256": "a".repeat(64), "evidence_sha256": "b".repeat(64)
        }
    });
    sqlx::query(
        "INSERT INTO pg_temp.agistack_cron_scheduler_owners
        (scope_id, owner_kind, cutover_phase, cutover_revision, cutover_evidence)
        VALUES ('global', 'rust', 'verified', 1, $1)",
    )
    .bind(fixture)
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query("CREATE TEMP TABLE agistack_legacy_cron_admissions (scope_id text, status text)")
        .execute(&pool)
        .await
        .unwrap();
    let repository = Arc::new(PgCronSchedulerOwnerRepository::new(pool.clone()));
    let prior = repository
        .try_acquire_global("prior-owner", 60, Utc::now())
        .await
        .unwrap()
        .unwrap();
    let probe = Probe::new();
    let old = loader(probe.factory_with_ownership(repository.clone()), false)
        .stage(profile(1))
        .await
        .unwrap();
    let candidate = loader(probe.factory_with_ownership(repository.clone()), false)
        .stage(profile(2))
        .await
        .unwrap();
    assert!(
        repository.is_current(&prior, Utc::now()).await.unwrap(),
        "candidate cannot disturb current lease"
    );
    assert_eq!(probe.driver(0).starts(), 0);
    assert_eq!(probe.driver(1).starts(), 0);
    assert!(repository.release(&prior, Utc::now()).await.unwrap());

    let manager = GenerationManagerV2::new();
    manager.publish(old.clone()).await;
    let first = BackgroundWorkerGenerationV2::start(manager.acquire().unwrap(), controllers(&old))
        .await
        .unwrap();
    probe.wait_entered(0).await;
    manager.publish(candidate.clone()).await;
    first.request_stop();
    let second =
        BackgroundWorkerGenerationV2::start(manager.acquire().unwrap(), controllers(&candidate))
            .await
            .unwrap();
    probe.wait_entered(1).await;
    let (epoch, token): (i64, Option<String>) = sqlx::query_as("SELECT owner_epoch, lease_token FROM pg_temp.agistack_cron_scheduler_owners WHERE scope_id = 'global'")
        .fetch_one(&pool).await.unwrap();
    assert_eq!(
        epoch,
        prior.owner_epoch + 2,
        "each active generation obtains a fresh fenced lease"
    );
    assert!(
        token.is_none(),
        "control lease released before draining admitted runtime work"
    );
    assert!(
        !repository.release(&prior, Utc::now()).await.unwrap(),
        "stale generation cannot release successor authority"
    );
    assert!(probe.alive(0) && probe.alive(1));
    probe.driver(0).finish.add_permits(1);
    first.shutdown().await.unwrap();
    assert!(!probe.alive(0) && probe.alive(1));
    second.request_stop();
    probe.driver(1).finish.add_permits(1);
    second.shutdown().await.unwrap();
    manager.close().await;
    assert!(!probe.alive(1));
    pool.close().await;
}
