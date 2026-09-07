use super::*;
struct Database(std::path::PathBuf);
impl Database {
    fn new() -> Self {
        Self(std::env::temp_dir().join(format!("cloud-resolution-{}.db", uuid::Uuid::new_v4())))
    }
    fn open(&self) -> SqliteKnowledgeRepository {
        SqliteKnowledgeRepository::open(self.0.to_str().unwrap()).unwrap()
    }
    fn sql(&self) -> rusqlite::Connection {
        rusqlite::Connection::open(&self.0).unwrap()
    }
}
impl Drop for Database {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

const DROP_CLOUD_SCHEMA:&str="DROP VIEW knowledge_active_pull_conflicts; DROP VIEW knowledge_pending_outbox; DROP VIEW knowledge_unsettled_pushes; DROP TABLE knowledge_cloud_resolved_pushes; DROP TABLE knowledge_cloud_resolved_pull_conflicts; DROP TABLE knowledge_cloud_superseded_outbox; DROP TABLE knowledge_cloud_resolutions;";

#[test]
fn concurrent_connections_prepare_one_stable_request_and_ack_exactly_once() {
    let db = Database::new();
    let repo = db.open();
    let (seq, verified) = block_on(setup(&repo, false));
    let cmd = command(seq, &verified, KnowledgeCloudChoice::KeepCurrent {});
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let workers: Vec<_> = [repo, db.open()]
        .into_iter()
        .map(|repo| {
            let barrier = barrier.clone();
            let cmd = cmd.clone();
            let verified = verified.clone();
            std::thread::spawn(move || {
                barrier.wait();
                repo.prepare_cloud_resolution_durable(
                    &scope(),
                    &target(),
                    "actor",
                    "same",
                    cmd,
                    verified,
                )
                .unwrap()
            })
        })
        .collect();
    let records: Vec<_> = workers.into_iter().map(|w| w.join().unwrap()).collect();
    assert_eq!(records[0].request_json, records[1].request_json);
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let workers: Vec<_> = [db.open(), db.open()]
        .into_iter()
        .map(|repo| {
            let barrier = barrier.clone();
            let record = records[0].clone();
            std::thread::spawn(move || {
                barrier.wait();
                repo.accept_cloud_resolution_receipt_durable(
                    &scope(),
                    &target(),
                    "actor",
                    &record.resolution_id,
                    response(&record, remote(2, false)),
                )
                .unwrap()
            })
        })
        .collect();
    let results: Vec<_> = workers.into_iter().map(|w| w.join().unwrap()).collect();
    assert_eq!(results.iter().filter(|r| r.replayed).count(), 1);
    assert_eq!(
        block_on(db.open().changes(&scope(), 0, 10)).unwrap().len(),
        3
    );
    let count: i64 = db
        .sql()
        .query_row(
            "SELECT count(*) FROM knowledge_cloud_resolutions",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(count, 1);
}

#[test]
fn injected_ack_failures_roll_back_receipt_baseline_maps_and_content_together() {
    block_on(async {
        for (table, event) in [
            ("knowledge_cloud_resolutions", "UPDATE"),
            ("knowledge_cloud_resolved_pushes", "INSERT"),
            ("knowledge_memories", "UPDATE"),
            ("knowledge_processing_changes", "INSERT"),
            ("knowledge_cloud_superseded_outbox", "INSERT"),
            ("knowledge_cloud_resolved_pull_conflicts", "INSERT"),
        ] {
            let db = Database::new();
            let repo = db.open();
            let (seq, verified) = setup(&repo, false).await;
            edit(&repo, "before choice", "reviewed latest").await;
            let mut cmd = command(seq, &verified, KnowledgeCloudChoice::KeepCurrent {});
            cmd.guard.expected_local_revision = 3;
            let record = repo
                .prepare_cloud_resolution_durable(
                    &scope(),
                    &target(),
                    "actor",
                    "choose",
                    cmd,
                    verified,
                )
                .unwrap();
            db.sql().execute_batch(&format!("CREATE TRIGGER injected BEFORE {event} ON {table} BEGIN SELECT RAISE(ABORT,'injected'); END;")).unwrap();
            assert!(
                repo.accept_cloud_resolution_receipt_durable(
                    &scope(),
                    &target(),
                    "actor",
                    &record.resolution_id,
                    response(&record, remote(2, false))
                )
                .is_err(),
                "{table}"
            );
            assert!(repo
                .cloud_resolution_record_durable(
                    &scope(),
                    &target(),
                    "actor",
                    &record.resolution_id
                )
                .unwrap()
                .receipt
                .is_none());
            assert_eq!(
                repo.remote_baseline(&scope(), "memory")
                    .await
                    .unwrap()
                    .unwrap(),
                remote(1, false)
            );
            assert_eq!(
                repo.get(&scope(), "memory").await.unwrap().unwrap().content,
                "reviewed latest"
            );
            assert_eq!(repo.sync_status(&scope()).await.unwrap().pending_changes, 2);
            assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 2);
            db.sql().execute_batch("DROP TRIGGER injected;").unwrap();
            repo.accept_cloud_resolution_receipt_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
                response(&record, remote(2, false)),
            )
            .unwrap();
        }
    });
}

#[test]
fn pending_reconciliation_failure_keeps_cloud_success_and_never_rolls_it_back() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let (seq, verified) = setup(&repo, false).await;
        let record = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "choose",
                command(seq, &verified, KnowledgeCloudChoice::KeepCurrent {}),
                verified,
            )
            .unwrap();
        edit(&repo, "network edit", "keep me").await;
        let ack = response(&record, remote(2, false));
        repo.accept_cloud_resolution_receipt_durable(
            &scope(),
            &target(),
            "actor",
            &record.resolution_id,
            ack.clone(),
        )
        .unwrap();
        let ctx = repo
            .cloud_reconciliation_context_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
            )
            .unwrap();
        let cmd = KnowledgeCloudReconciliationCommand {
            guard: guard(&ctx),
            choice: KnowledgeConflictChoice::KeepBoth {},
        };
        db.sql().execute_batch("CREATE TRIGGER injected BEFORE INSERT ON knowledge_cloud_resolved_pull_conflicts BEGIN SELECT RAISE(ABORT,'injected'); END;").unwrap();
        assert!(repo
            .reconcile_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
                cmd.clone()
            )
            .is_err());
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "keep me"
        );
        let journal = repo
            .cloud_resolution_record_durable(&scope(), &target(), "actor", &record.resolution_id)
            .unwrap();
        assert_eq!(journal.receipt, Some(ack["receipt"].clone()));
        assert!(journal.reconciliation.is_none());
        db.sql().execute_batch("DROP TRIGGER injected;").unwrap();
        drop(repo);
        let repo = db.open();
        assert!(
            repo.accept_cloud_resolution_receipt_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
                ack
            )
            .unwrap()
            .pending_reconciliation
        );
        repo.reconcile_cloud_resolution_durable(
            &scope(),
            &target(),
            "actor",
            &record.resolution_id,
            cmd,
        )
        .unwrap();
    });
}

#[test]
fn version_six_migrates_without_losing_original_conflicts_and_missing_current_objects_fail() {
    let db = Database::new();
    let repo = db.open();
    let (seq, verified) = block_on(setup(&repo, false));
    drop(repo);
    db.sql().execute_batch(DROP_CLOUD_SCHEMA).unwrap();
    db.sql()
        .execute_batch("UPDATE knowledge_schema SET version=6;")
        .unwrap();
    let repo = db.open();
    assert_eq!(
        block_on(repo.push_conflicts(&scope(), 10)).unwrap().len(),
        1
    );
    repo.prepare_cloud_resolution_durable(
        &scope(),
        &target(),
        "actor",
        "after upgrade",
        command(seq, &verified, KnowledgeCloudChoice::KeepCurrent {}),
        verified,
    )
    .unwrap();
    drop(repo);
    let version: i64 = db
        .sql()
        .query_row("SELECT version FROM knowledge_schema", [], |r| r.get(0))
        .unwrap();
    assert_eq!(version, 7);
    for (kind, name) in [
        ("VIEW", "knowledge_pending_outbox"),
        ("TABLE", "knowledge_cloud_resolutions"),
    ] {
        let broken = Database::new();
        drop(broken.open());
        broken
            .sql()
            .execute_batch(&format!("DROP {kind} {name};"))
            .unwrap();
        assert!(SqliteKnowledgeRepository::open(broken.0.to_str().unwrap()).is_err());
        let count: i64 = broken
            .sql()
            .query_row(
                "SELECT count(*) FROM sqlite_master WHERE name=?1",
                [name],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(count, 0);
    }
}

#[test]
fn older_valid_receipt_never_replaces_a_newer_baseline_or_current_local_work() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let (seq, verified) = setup(&repo, false).await;
        let record = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "choose",
                command(seq, &verified, KnowledgeCloudChoice::UseProposed {}),
                verified,
            )
            .unwrap();
        db.sql()
            .execute(
                "UPDATE knowledge_sync_remote_versions SET version_json=?1",
                [remote(4, false).to_string()],
            )
            .unwrap();
        let result = repo
            .accept_cloud_resolution_receipt_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
                response(&record, applied_version(&record)),
            )
            .unwrap();
        assert!(result.pending_reconciliation);
        assert_eq!(
            repo.remote_baseline(&scope(), "memory")
                .await
                .unwrap()
                .unwrap(),
            remote(4, false)
        );
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "local proposal"
        );
    });
}

#[test]
fn lost_keep_current_response_restarts_with_same_bytes_and_immutable_mutation_history() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let (seq, verified) = setup(&repo, false).await;
        let original:String=db.sql().query_row("SELECT request_json||receipt_json||conflict_json FROM knowledge_sync_pushes WHERE sequence=?1",[seq],|r|r.get(0)).unwrap();
        let cmd = command(seq, &verified, KnowledgeCloudChoice::KeepCurrent {});
        let record = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "stable",
                cmd.clone(),
                verified,
            )
            .unwrap();
        drop(repo);
        let repo = db.open();
        let replay = repo
            .prepare_cloud_resolution_durable(
                &scope(),
                &target(),
                "actor",
                "stable",
                cmd,
                Value::Null,
            )
            .unwrap();
        assert_eq!(record.request_json, replay.request_json);
        let ack = response(&record, remote(2, false));
        repo.accept_cloud_resolution_receipt_durable(
            &scope(),
            &target(),
            "actor",
            &record.resolution_id,
            ack.clone(),
        )
        .unwrap();
        drop(repo);
        let repo = db.open();
        assert!(
            repo.accept_cloud_resolution_receipt_durable(
                &scope(),
                &target(),
                "actor",
                &record.resolution_id,
                ack
            )
            .unwrap()
            .replayed
        );
        let after:String=db.sql().query_row("SELECT request_json||receipt_json||conflict_json FROM knowledge_sync_pushes WHERE sequence=?1",[seq],|r|r.get(0)).unwrap();
        assert_eq!(original, after);
    });
}
