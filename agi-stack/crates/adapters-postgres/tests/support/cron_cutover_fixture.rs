//! Synthetic verification is permitted only inside isolated test databases/schemas.

use agistack_adapters_postgres::PgPool;
use serde_json::json;

pub async fn install_cutover_fixture(pool: &PgPool) {
    let isolated: bool = sqlx::query_scalar(
        "SELECT relation.relpersistence = 't' OR left(namespace.nspname, 3) = 'qa_' \
         OR (namespace.nspname = 'public' AND to_regclass('public.alembic_version') IS NULL) \
         FROM pg_class AS relation JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace \
         WHERE relation.oid = to_regclass('agistack_cron_scheduler_owners')",
    )
    .fetch_one(pool)
    .await
    .expect("inspect test schema isolation");
    assert!(
        isolated,
        "synthetic cutover evidence is forbidden in a migrated shared schema"
    );
    sqlx::query(
        "ALTER TABLE agistack_cron_scheduler_owners
        ADD COLUMN IF NOT EXISTS cutover_phase text NOT NULL DEFAULT 'unverified',
        ADD COLUMN IF NOT EXISTS cutover_revision bigint NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS cutover_evidence json NOT NULL DEFAULT '{}'",
    )
    .execute(pool)
    .await
    .expect("install isolated cutover columns");
}

pub async fn verify_cutover_fixture(pool: &PgPool) {
    install_cutover_fixture(pool).await;
    let evidence = json!({
        "protocol": "cron-cutover-evidence.v1",
        "manifest": {"deployment_id": "fixture-deployment"},
        "verification": {
            "protocol": "cron-deployment-verification.v1",
            "deployment_id": "fixture-deployment",
            "cutover_revision": 1,
            "receipt_id": "fixture-only-receipt", "verifier_id": "fixture-only-verifier",
            "inventory_sha256": "a".repeat(64), "evidence_sha256": "b".repeat(64)
        }
    });
    sqlx::query(
        "UPDATE agistack_cron_scheduler_owners SET cutover_phase='verified',
        cutover_revision=1, cutover_evidence=$1 WHERE scope_id='global'",
    )
    .bind(evidence)
    .execute(pool)
    .await
    .expect("write isolated verification fixture");
}
