use super::*;

#[test]
fn completion_fault_rolls_back_receipt_and_projection_together() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        repo.create(&scope(), memory()).await.unwrap();
        let lease = repo
            .claim(&scope(), "worker", 0, 100)
            .await
            .unwrap()
            .unwrap();
        db.connection().execute_batch("CREATE TRIGGER reject_processing_projection BEFORE INSERT ON knowledge_derived_projections BEGIN SELECT RAISE(ABORT,'injected projection storage failure'); END;").unwrap();
        assert!(matches!(
            repo.complete(&scope(), &lease, projection(), 1).await,
            Err(KnowledgeError::Storage(_))
        ));
        let status = repo
            .processing_status(&scope(), &lease.source)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(status.state, ProcessingState::Leased);
        assert!(status.result.is_none());
        assert!(repo.projection(&scope(), "memory").await.unwrap().is_none());
        db.connection()
            .execute_batch("DROP TRIGGER reject_processing_projection")
            .unwrap();
        repo.complete(&scope(), &lease, projection(), 2)
            .await
            .unwrap();
    });
}

#[test]
fn projection_read_revalidates_source_when_enqueue_trigger_is_missing() {
    for deleted in [false, true] {
        block_on(async {
            let db = Database::new();
            let repo = db.open();
            let current = repo.create(&scope(), memory()).await.unwrap();
            let lease = repo
                .claim(&scope(), "worker", 0, 100)
                .await
                .unwrap()
                .unwrap();
            repo.complete(&scope(), &lease, projection(), 1)
                .await
                .unwrap();
            db.connection()
                .execute_batch("DROP TRIGGER knowledge_processing_enqueue")
                .unwrap();
            if deleted {
                repo.delete(&scope(), "memory", 1).await.unwrap();
            } else {
                repo.update(&scope(), current, 1).await.unwrap();
            }
            let physically_retained: i64 = db
                .connection()
                .query_row(
                    "SELECT count(*) FROM knowledge_derived_projections",
                    [],
                    |row| row.get(0),
                )
                .unwrap();
            assert_eq!(physically_retained, 1);
            assert!(repo.projection(&scope(), "memory").await.unwrap().is_none());
        });
    }
}

#[test]
fn expired_reopen_reclaims_persisted_work_and_retains_typed_failures() {
    let db = Database::new();
    let lease = block_on(async {
        let repo = db.open();
        repo.create(&scope(), memory()).await.unwrap();
        repo.claim(&scope(), "first-process", 10, 20)
            .await
            .unwrap()
            .unwrap()
    });
    block_on(async {
        let repo = db.open();
        assert!(repo
            .claim(&scope(), "second-process", 29, 20)
            .await
            .unwrap()
            .is_none());
        let next = repo
            .claim(&scope(), "second-process", 30, 20)
            .await
            .unwrap()
            .unwrap();
        assert_ne!(lease.token, next.token);
        repo.fail(&scope(), &next, ProcessingFailure::ModelUnconfigured, 31)
            .await
            .unwrap();
    });
    let status = block_on(db.open().processing_status(&scope(), &lease.source))
        .unwrap()
        .unwrap();
    assert_eq!(status.state, ProcessingState::Failed);
    assert_eq!(status.failure, Some(ProcessingFailure::ModelUnconfigured));
    assert_eq!(status.attempt, 2);
}

#[test]
fn v7_migration_backfills_only_current_live_sources_without_sync_echoes() {
    let db = Database::new();
    block_on(async {
        let repo = db.open();
        let mut current = repo.create(&scope(), memory()).await.unwrap();
        current.content = "revision 2".into();
        repo.update(&scope(), current, 1).await.unwrap();
        let mut deleted = memory();
        deleted.id = "deleted".into();
        repo.create(&scope(), deleted).await.unwrap();
        repo.delete(&scope(), "deleted", 1).await.unwrap();
    });
    let count = || {
        db.connection().query_row("SELECT (SELECT count(*) FROM knowledge_processing_changes),(SELECT count(*) FROM knowledge_sync_outbox)", [], |row| Ok((row.get::<_,i64>(0)?,row.get::<_,i64>(1)?))).unwrap()
    };
    let before = count();
    db.connection().execute_batch("DROP TABLE knowledge_processing_audits; DROP TRIGGER knowledge_processing_enqueue; DROP TABLE knowledge_processing_jobs; DROP TABLE knowledge_derived_projections; UPDATE knowledge_schema SET version=7;").unwrap();
    block_on(async {
        let repo = db.open();
        let lease = repo
            .claim(&scope(), "worker", 10, 20)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(lease.source.memory_id, "memory");
        assert_eq!(lease.source.revision, 2);
        assert!(repo
            .claim(&scope(), "another", 10, 20)
            .await
            .unwrap()
            .is_none());
    });
    assert_eq!(count(), before);
    let version: i64 = db
        .connection()
        .query_row("SELECT version FROM knowledge_schema", [], |row| row.get(0))
        .unwrap();
    assert_eq!(
        version,
        agistack_adapters_device::knowledge::KNOWLEDGE_SCHEMA_VERSION
    );
    drop(db.open());
    let jobs: i64 = db
        .connection()
        .query_row(
            "SELECT count(*) FROM knowledge_processing_jobs",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(jobs, 1);
}

#[test]
fn current_schema_damage_and_future_version_fail_closed() {
    for damage in [
        "DROP TABLE knowledge_processing_audits",
        "DROP TABLE knowledge_processing_jobs",
        "DROP TABLE knowledge_derived_projections",
        "DROP TRIGGER knowledge_processing_enqueue",
        "UPDATE knowledge_schema SET version=999",
    ] {
        let db = Database::new();
        drop(db.open());
        db.connection().execute_batch(damage).unwrap();
        assert!(SqliteKnowledgeRepository::open(db.0.to_str().unwrap()).is_err());
    }
}

#[test]
fn invalid_or_noncurrent_changes_do_not_enqueue_jobs_or_remove_projection() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        repo.create(&scope(), memory()).await.unwrap();
        let lease = repo
            .claim(&scope(), "worker", 0, 100)
            .await
            .unwrap()
            .unwrap();
        repo.complete(&scope(), &lease, projection(), 1)
            .await
            .unwrap();
        db.connection().execute_batch("INSERT INTO knowledge_processing_changes(tenant_id,project_id,memory_id,revision,operation,payload) SELECT tenant_id,project_id,id,revision+1,'upsert',payload FROM knowledge_memories").unwrap();
        assert!(repo
            .claim(&scope(), "worker", 2, 100)
            .await
            .unwrap()
            .is_none());
        assert_eq!(
            repo.projection(&scope(), "memory")
                .await
                .unwrap()
                .unwrap()
                .projection,
            projection()
        );
    });
}
