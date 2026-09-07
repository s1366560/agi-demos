//! Cross-runtime enrollment fencing over the real Alembic-owned schema.

#[path = "memory_legacy_admission/mod.rs"]
mod support;

use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use agistack_adapters_postgres::PgMemoryRepository;
use agistack_core::MemoryService;
use support::*;

#[tokio::test]
async fn enrolled_ingestion_rejects_before_model_or_vector_work() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let project = seed_project(&pool, "enrolled").await;
    let bootstrap = start_bootstrap(&project).await;
    bootstrap.await.unwrap();
    let probes = Arc::new(Probes::default());
    let service = MemoryService::new(
        Arc::new(PgMemoryRepository::new(pool.clone()).await.unwrap()),
        probes.clone(),
        probes.clone(),
        Arc::new(FixedClock),
    );
    let result = service
        .ingest_episode(&project, "actor", &episode(&project))
        .await;
    assert!(result.is_err(), "enrolled legacy ingest must be rejected");
    assert_eq!(probes.extractions.load(Ordering::SeqCst), 0);
    assert_eq!(probes.embeddings.load(Ordering::SeqCst), 0);
    pool.close().await;
}

#[tokio::test]
async fn bootstrap_waits_until_vector_side_effect_finishes() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let project = seed_project(&pool, "vector").await;
    let probes = Arc::new(Probes::default());
    let vectors = Arc::new(PausedVectors::default());
    let service = MemoryService::new(
        Arc::new(PgMemoryRepository::new(pool.clone()).await.unwrap()),
        probes.clone(),
        probes.clone(),
        Arc::new(FixedClock),
    )
    .with_vectors(vectors.clone());
    let writing_project = project.clone();
    let writer = tokio::spawn(async move {
        service
            .ingest_episode(&writing_project, "actor", &episode(&writing_project))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), vectors.entered.notified())
        .await
        .unwrap();
    let bootstrap = start_bootstrap(&project).await;
    tokio::time::sleep(Duration::from_secs(1)).await;
    let completed_early = bootstrap.is_finished();
    vectors.release.notify_one();
    writer.await.unwrap().unwrap();
    bootstrap.await.unwrap();
    assert!(
        !completed_early,
        "bootstrap crossed the pending vector side effect"
    );
    pool.close().await;
}

#[tokio::test]
async fn small_data_pool_allows_four_leases_and_releases_cancelled_work() {
    use agistack_core::ports::MemoryRepository;
    let Some(pool) = test_pool().await else {
        return;
    };
    let project = seed_project(&pool, "capacity").await;
    let repo = Arc::new(PgMemoryRepository::new(pool.clone()).await.unwrap());
    let mut leases = Vec::new();
    for _ in 0..4 {
        leases.push(
            tokio::time::timeout(
                Duration::from_secs(3),
                repo.begin_legacy_write(&project, None),
            )
            .await
            .unwrap()
            .unwrap(),
        );
    }
    assert_eq!(leases[0].scope().tenant_id.as_deref(), Some("tenant"));
    // Every data-pool connection remains available while admission is saturated.
    let first = pool.acquire().await.unwrap();
    let second = tokio::time::timeout(Duration::from_secs(2), pool.acquire())
        .await
        .unwrap()
        .unwrap();
    drop((first, second));
    let waiting_repo = repo.clone();
    let waiting_project = project.clone();
    let waiter = tokio::spawn(async move {
        waiting_repo
            .begin_legacy_write(&waiting_project, None)
            .await
    });
    tokio::time::sleep(Duration::from_millis(30)).await;
    assert!(!waiter.is_finished());
    waiter.abort();
    assert!(matches!(waiter.await, Err(error) if error.is_cancelled()));
    drop(leases);
    let probes = Arc::new(Probes::default());
    let service = MemoryService::new(repo.clone(), probes.clone(), probes, Arc::new(FixedClock));
    let saved = service
        .ingest_episode(&project, "actor", &episode(&project))
        .await
        .unwrap();
    assert_eq!(saved.project_id, project);
    tokio::time::timeout(Duration::from_secs(3), repo.close_write_admission())
        .await
        .unwrap();
    assert!(repo.begin_legacy_write(&project, None).await.is_err());
    pool.close().await;
}

#[tokio::test]
async fn live_and_tombstoned_ids_use_actual_scope_and_enrollment() {
    use agistack_core::ports::{
        legacy_memory::LegacyMemoryWriteError as E, CoreError, MemoryRepository,
    };
    let Some(pool) = test_pool().await else {
        return;
    };
    let project = seed_project(&pool, "actual").await;
    let other = seed_project(&pool, "other").await;
    let repo = Arc::new(PgMemoryRepository::new(pool.clone()).await.unwrap());
    let probes = Arc::new(Probes::default());
    let service = MemoryService::new(
        repo.clone(),
        probes.clone(),
        probes.clone(),
        Arc::new(FixedClock),
    );
    let saved = service
        .ingest_episode(&project, "actor", &episode(&project))
        .await
        .unwrap();
    let mut mismatched = saved.clone();
    mismatched.project_id = other.clone();
    assert!(matches!(
        repo.save(mismatched).await,
        Err(CoreError::MemoryWrite(E::Conflict))
    ));
    assert!(matches!(
        service.delete(&other, &saved.id).await,
        Err(CoreError::MemoryWrite(E::Conflict))
    ));
    start_bootstrap(&project).await.await.unwrap();
    assert!(matches!(
        repo.save(saved.clone()).await,
        Err(CoreError::MemoryWrite(E::ContextRequired))
    ));
    assert!(matches!(
        repo.delete(&saved.id).await,
        Err(CoreError::MemoryWrite(E::ContextRequired))
    ));
    assert!(matches!(
        service
            .create_memory(&project, "actor", "QA", "content", "text", vec![], vec![])
            .await,
        Err(CoreError::MemoryWrite(E::ContextRequired))
    ));
    // A tombstone is a durable ID reservation, including through another project.
    sqlx::query("INSERT INTO knowledge_sync_tombstones (memory_id, tenant_id, project_id, revision, snapshot) VALUES ('rust-tombstone', 'tenant', $1, 1, '{}'::json)")
        .bind(&project).execute(&pool).await.unwrap();
    assert!(matches!(
        repo.delete("rust-tombstone").await,
        Err(CoreError::MemoryWrite(E::ContextRequired))
    ));
    let mut tombstoned = saved;
    tombstoned.id = "rust-tombstone".into();
    tombstoned.project_id = other;
    assert!(matches!(
        repo.save(tombstoned).await,
        Err(CoreError::MemoryWrite(E::Conflict))
    ));
    repo.close_write_admission().await;
    pool.close().await;
}

#[tokio::test]
async fn missing_fence_is_a_structured_error_before_embedding() {
    use agistack_core::ports::{legacy_memory::LegacyMemoryWriteError as E, CoreError};
    let Some(pool) = test_pool().await else {
        return;
    };
    let project = seed_project(&pool, "missing").await;
    sqlx::query("DELETE FROM knowledge_sync_enrollments WHERE project_id = $1")
        .bind(&project)
        .execute(&pool)
        .await
        .unwrap();
    let probes = Arc::new(Probes::default());
    let service = MemoryService::new(
        Arc::new(PgMemoryRepository::new(pool.clone()).await.unwrap()),
        probes.clone(),
        probes.clone(),
        Arc::new(FixedClock),
    );
    assert!(matches!(
        service
            .ingest_episode(&project, "actor", &episode(&project))
            .await,
        Err(CoreError::MemoryWrite(E::FenceMissing))
    ));
    assert_eq!(probes.extractions.load(Ordering::SeqCst), 0);
    service.close_write_admission().await;
    pool.close().await;
}

#[tokio::test]
async fn queued_bootstrap_does_not_deadlock_the_inner_sql_admission() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let project = seed_project(&pool, "queued").await;
    let probes = Arc::new(Probes::default());
    let service = MemoryService::new(
        Arc::new(PgMemoryRepository::new(pool.clone()).await.unwrap()),
        probes.clone(),
        probes,
        Arc::new(FixedClock),
    );
    let lease = service.begin_legacy_write(&project, None).await.unwrap();
    let bootstrap = start_bootstrap(&project).await;
    tokio::time::sleep(Duration::from_secs(1)).await;
    assert!(!bootstrap.is_finished());
    let saved = tokio::time::timeout(
        Duration::from_secs(3),
        service.ingest_episode_with_lease(&project, "actor", &episode(&project), &lease),
    )
    .await;
    drop(lease);
    tokio::time::timeout(Duration::from_secs(5), bootstrap)
        .await
        .unwrap()
        .unwrap();
    assert!(saved.is_ok(), "queued bootstrap starved inner admission");
    saved.unwrap().unwrap();
    service.close_write_admission().await;
    pool.close().await;
}
