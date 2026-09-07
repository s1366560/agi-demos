//! A legacy admission remains a blocker even after control-plane delegation changes.

use agistack_adapters_postgres::PgCronSchedulerOwnerRepository;
use chrono::Utc;
use sqlx::postgres::PgPoolOptions;

#[tokio::test]
async fn rust_owner_fails_closed_for_missing_schema_and_active_legacy_execution() {
    let Ok(url) = std::env::var("DATABASE_URL") else {
        eprintln!("[skip] legacy cron fencing: DATABASE_URL unset");
        return;
    };
    let admin = PgPoolOptions::new()
        .max_connections(1)
        .connect(&url)
        .await
        .unwrap();
    let schema = format!(
        "qa_legacy_fence_{}",
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
        acquired_at timestamptz, updated_at timestamptz NOT NULL DEFAULT now())",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query("INSERT INTO agistack_cron_scheduler_owners (scope_id, owner_kind) VALUES ('global', 'rust')")
        .execute(&pool).await.unwrap();
    let repository = PgCronSchedulerOwnerRepository::new(pool.clone());
    let missing_schema = repository.try_acquire_global("rust", 60, Utc::now()).await;
    if let Ok(Some(lease)) = &missing_schema {
        repository.release(lease, Utc::now()).await.unwrap();
    }
    let epoch_after_missing: i64 = sqlx::query_scalar(
        "SELECT owner_epoch FROM agistack_cron_scheduler_owners WHERE scope_id = 'global'",
    )
    .fetch_one(&pool)
    .await
    .unwrap();
    sqlx::query("CREATE TABLE agistack_legacy_cron_admissions (scope_id text, status text)")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("INSERT INTO agistack_legacy_cron_admissions VALUES ('global', 'active')")
        .execute(&pool)
        .await
        .unwrap();
    let active = repository
        .try_acquire_global("rust", 60, Utc::now())
        .await
        .unwrap();
    if let Some(lease) = &active {
        repository.release(lease, Utc::now()).await.unwrap();
    }
    sqlx::query("UPDATE agistack_legacy_cron_admissions SET status = 'success'")
        .execute(&pool)
        .await
        .unwrap();
    let terminal = repository
        .try_acquire_global("rust", 60, Utc::now())
        .await
        .unwrap();
    pool.close().await;
    sqlx::query(&format!("DROP SCHEMA {schema} CASCADE"))
        .execute(&admin)
        .await
        .unwrap();
    admin.close().await;
    assert_eq!(
        epoch_after_missing, 0,
        "missing schema must not mutate owner"
    );
    assert!(
        missing_schema.is_err(),
        "old schema must fail closed instead of acquiring"
    );
    assert!(
        active.is_none(),
        "unresolved legacy work must fence Rust ownership"
    );
    assert!(
        terminal.is_some(),
        "explicit Rust delegation may acquire after true terminal"
    );
}
