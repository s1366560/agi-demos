//! Synthetic protocol fixtures exercise fencing; they are not deployment drain evidence.

use agistack_adapters_postgres::PgCronSchedulerOwnerRepository;
use chrono::Utc;
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;

fn verified_fixture() -> Value {
    json!({
        "protocol": "cron-cutover-evidence.v1",
        "manifest": {"deployment_id": "fixture-deployment"},
        "verification": {
            "protocol": "cron-deployment-verification.v1",
            "deployment_id": "fixture-deployment",
            "cutover_revision": 1,
            "receipt_id": "fixture-only-receipt",
            "verifier_id": "fixture-only-verifier",
            "inventory_sha256": "a".repeat(64),
            "evidence_sha256": "b".repeat(64)
        }
    })
}

#[tokio::test]
async fn cutover_requires_deployment_verification_not_empty_admissions_or_enable_flags() {
    let Ok(url) = std::env::var("DATABASE_URL") else {
        eprintln!("[skip] cron deployment barrier: DATABASE_URL unset");
        return;
    };
    let admin = PgPoolOptions::new()
        .max_connections(1)
        .connect(&url)
        .await
        .unwrap();
    let schema = format!(
        "qa_cron_cutover_{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    );
    sqlx::query(&format!("CREATE SCHEMA {schema}"))
        .execute(&admin)
        .await
        .unwrap();
    let search_path = format!("SET search_path TO {schema}");
    let pool = PgPoolOptions::new()
        .max_connections(1)
        .after_connect(move |connection, _| {
            let query = search_path.clone();
            Box::pin(async move {
                sqlx::query(&query).execute(connection).await?;
                Ok(())
            })
        })
        .connect(&url)
        .await
        .unwrap();
    sqlx::query(
        "CREATE TABLE agistack_cron_scheduler_owners (
        scope_id text PRIMARY KEY, owner_kind text NOT NULL, owner_id text,
        owner_epoch bigint NOT NULL DEFAULT 0, lease_token text, lease_expires_at timestamptz,
        acquired_at timestamptz, updated_at timestamptz NOT NULL DEFAULT now(),
        cutover_phase text NOT NULL DEFAULT 'unverified',
        cutover_revision bigint NOT NULL DEFAULT 0,
        cutover_evidence json NOT NULL DEFAULT '{}')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query("CREATE TABLE agistack_legacy_cron_admissions (scope_id text, status text)")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("CREATE TABLE cron_job_runs (id text, status text)")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("INSERT INTO cron_job_runs VALUES ('old-untracked', 'success')")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO agistack_cron_scheduler_owners (scope_id, owner_kind)
        VALUES ('global', 'rust')",
    )
    .execute(&pool)
    .await
    .unwrap();
    let repository = PgCronSchedulerOwnerRepository::new(pool.clone());
    let mut denied = Vec::new();
    for phase in ["unverified", "prepared", "blocked", "verified"] {
        sqlx::query(
            "UPDATE agistack_cron_scheduler_owners SET cutover_phase=$1,
            cutover_evidence=$2, cutover_revision=1",
        )
        .bind(phase)
        .bind(json!({"verified": true}))
        .execute(&pool)
        .await
        .unwrap();
        let lease = repository
            .try_acquire_global("new-owner", 60, Utc::now())
            .await
            .unwrap();
        denied.push(lease.is_none());
        if let Some(lease) = lease {
            repository.release(&lease, Utc::now()).await.unwrap();
        }
    }
    for (field, value) in [
        ("cutover_revision", json!(2)),
        ("cutover_revision", json!("1")),
        ("deployment_id", json!("different-deployment")),
        ("inventory_sha256", json!("z".repeat(64))),
        ("protocol", json!("unknown-verifier-protocol")),
    ] {
        let mut evidence = verified_fixture();
        evidence["verification"][field] = value;
        sqlx::query(
            "UPDATE agistack_cron_scheduler_owners SET cutover_phase='verified',
            cutover_evidence=$1, cutover_revision=1",
        )
        .bind(evidence)
        .execute(&pool)
        .await
        .unwrap();
        let lease = repository
            .try_acquire_global("invalid-receipt", 60, Utc::now())
            .await
            .unwrap();
        denied.push(lease.is_none());
        if let Some(lease) = lease {
            repository.release(&lease, Utc::now()).await.unwrap();
        }
    }
    sqlx::query(
        "UPDATE agistack_cron_scheduler_owners SET cutover_phase='verified',
        cutover_evidence=$1, cutover_revision=1",
    )
    .bind(verified_fixture())
    .execute(&pool)
    .await
    .unwrap();
    let valid = repository
        .try_acquire_global("verified-owner", 60, Utc::now())
        .await
        .unwrap();
    let mut current_after_revocation = false;
    let mut renewed_after_revocation = false;
    let mut released = false;
    if let Some(lease) = &valid {
        sqlx::query("UPDATE agistack_cron_scheduler_owners SET cutover_phase='blocked'")
            .execute(&pool)
            .await
            .unwrap();
        current_after_revocation = repository.is_current(lease, Utc::now()).await.unwrap();
        let renewed = repository.renew(lease, 60, Utc::now()).await.unwrap();
        renewed_after_revocation = renewed.is_some();
        released = repository
            .release(renewed.as_ref().unwrap_or(lease), Utc::now())
            .await
            .unwrap();
    }
    pool.close().await;
    sqlx::query(&format!("DROP SCHEMA {schema} CASCADE"))
        .execute(&admin)
        .await
        .unwrap();
    admin.close().await;
    assert!(
        denied.into_iter().all(|denied| denied),
        "neither zero admissions nor booleans prove drain"
    );
    assert!(
        valid.is_some(),
        "a structured verifier receipt is required by the future verifier contract"
    );
    assert!(!current_after_revocation && !renewed_after_revocation);
    assert!(
        released,
        "revocation must still allow exact-lease resource cleanup"
    );
}
