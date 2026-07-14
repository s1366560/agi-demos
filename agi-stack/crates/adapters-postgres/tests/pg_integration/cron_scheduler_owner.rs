use agistack_adapters_postgres::PgCronSchedulerOwnerRepository;

use super::support::*;

#[tokio::test]
async fn scheduler_owner_requires_rust_cutover_and_fences_every_lease_snapshot() {
    let Some(pool) =
        pool_or_skip("scheduler_owner_requires_rust_cutover_and_fences_every_lease_snapshot").await
    else {
        return;
    };
    ensure_owner_table(&pool).await;
    clean_rows(&pool).await;
    let now = ts(2026, 7, 14, 12, 0, 0);
    sqlx::query(
        "INSERT INTO agistack_cron_scheduler_owners ( \
            scope_id, owner_kind, owner_epoch, updated_at \
         ) VALUES ('global', 'off', 0, $1)",
    )
    .bind(now)
    .execute(&pool)
    .await
    .expect("insert disabled owner row");
    let repo = PgCronSchedulerOwnerRepository::new(pool.clone());

    assert!(repo
        .try_acquire_global("scheduler-1", 30, now)
        .await
        .expect("off acquisition query")
        .is_none());
    sqlx::query(
        "UPDATE agistack_cron_scheduler_owners SET owner_kind = 'python' \
         WHERE scope_id = 'global'",
    )
    .execute(&pool)
    .await
    .expect("delegate to Python");
    assert!(repo
        .try_acquire_global("scheduler-1", 30, now)
        .await
        .expect("Python acquisition query")
        .is_none());
    sqlx::query(
        "UPDATE agistack_cron_scheduler_owners SET owner_kind = 'rust' \
         WHERE scope_id = 'global'",
    )
    .execute(&pool)
    .await
    .expect("delegate to Rust");

    let first = repo
        .try_acquire_global("scheduler-1", 30, now)
        .await
        .expect("first acquisition")
        .expect("Rust owner acquires");
    assert_eq!(first.owner_epoch, 1);
    assert!(repo
        .try_acquire_global("scheduler-2", 30, now)
        .await
        .expect("competing acquisition")
        .is_none());
    let renewed = repo
        .renew(&first, 30, now + std::time::Duration::from_secs(10))
        .await
        .expect("renew current lease")
        .expect("exact lease renews");
    assert!(!repo
        .is_current(&first, now + std::time::Duration::from_secs(10))
        .await
        .expect("old snapshot check"));
    assert!(repo
        .is_current(&renewed, now + std::time::Duration::from_secs(10))
        .await
        .expect("renewed snapshot check"));
    assert!(!repo
        .release(&first, now + std::time::Duration::from_secs(11))
        .await
        .expect("old snapshot release"));
    assert!(repo
        .release(&renewed, now + std::time::Duration::from_secs(11))
        .await
        .expect("current snapshot release"));
    let second = repo
        .try_acquire_global("scheduler-2", 30, now + std::time::Duration::from_secs(12))
        .await
        .expect("second acquisition")
        .expect("released lease can be acquired");
    assert_eq!(second.owner_epoch, 2);
    clean_rows(&pool).await;
}

async fn ensure_owner_table(pool: &PgPool) {
    sqlx::query(
        "CREATE TABLE IF NOT EXISTS agistack_cron_scheduler_owners ( \
            scope_id varchar(100) PRIMARY KEY, owner_kind varchar(20) NOT NULL DEFAULT 'off', \
            owner_id varchar(255), owner_epoch bigint NOT NULL DEFAULT 0, \
            lease_token varchar(255), lease_expires_at timestamptz, acquired_at timestamptz, \
            updated_at timestamptz NOT NULL DEFAULT now())",
    )
    .execute(pool)
    .await
    .expect("ensure scheduler owner table");
}

async fn clean_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM agistack_cron_scheduler_owners WHERE scope_id = 'global'")
        .execute(pool)
        .await
        .expect("clean scheduler owner row");
}
