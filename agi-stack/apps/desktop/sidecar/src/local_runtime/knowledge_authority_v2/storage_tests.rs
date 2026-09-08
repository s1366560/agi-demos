use super::*;
use rusqlite::Connection;

pub(super) const DROP_PROCESSING_SCHEMA: &str = "DROP TABLE knowledge_processing_audits; DROP TRIGGER knowledge_processing_enqueue; DROP TABLE knowledge_derived_projections; DROP TABLE knowledge_processing_jobs;";

#[tokio::test]
async fn v7_processing_upgrade_backs_up_source_and_rebuilds_only_pending_work() {
    use agistack_core::knowledge::{processing::ProcessingRepository, ScopedMemoryRepository};

    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    let auth = authenticated(&state);
    let scope = agistack_core::knowledge::KnowledgeScope {
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
    };
    let MemoryMutation::Create { memory } = mutation(&auth) else {
        panic!("create fixture")
    };
    let repo = storage_lifecycle::open(&directory.0).unwrap();
    let source = repo.create(&scope, memory).await.unwrap();
    drop(repo);
    let knowledge = directory.0.join("knowledge");
    let db = Connection::open(knowledge.join("memories.db")).unwrap();
    db.execute_batch(DROP_PROCESSING_SCHEMA).unwrap();
    db.execute_batch("UPDATE knowledge_schema SET version=7;")
        .unwrap();
    let repo = storage_lifecycle::open(&directory.0).unwrap();
    let backups: Vec<_> = fs::read_dir(&knowledge)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.file_name().unwrap().to_string_lossy().contains("pre-v7-"))
        .collect();
    assert_eq!(backups.len(), 1);
    let backup = Connection::open(&backups[0]).unwrap();
    let original: (i64, i64, String) = backup
        .query_row(
            "SELECT (SELECT version FROM knowledge_schema),
         (SELECT count(*) FROM sqlite_master WHERE name='knowledge_processing_jobs'),
         (SELECT payload FROM knowledge_memories)",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .unwrap();
    assert_eq!((original.0, original.1), (7, 0));
    let saved: Memory = serde_json::from_str(&original.2).unwrap();
    assert_eq!(saved.content, source.content);
    assert_eq!(saved.version, source.version);
    let lease = repo
        .claim(&scope, "upgrade-test", 100, 100)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(lease.source.memory_id, source.id);
    assert_eq!(lease.source.revision, source.version);
    drop(repo);
    let reopened = storage_lifecycle::open(&directory.0).unwrap();
    assert!(reopened
        .claim(&scope, "other", 101, 100)
        .await
        .unwrap()
        .is_none());
    assert_eq!(
        fs::read_dir(&knowledge)
            .unwrap()
            .filter_map(Result::ok)
            .filter(|e| e.file_name().to_string_lossy().contains("pre-v7-"))
            .count(),
        1
    );
}

pub(super) const DROP_CLOUD_SCHEMA: &str = "DROP TABLE knowledge_processing_audits; DROP TRIGGER knowledge_processing_enqueue; DROP TABLE knowledge_derived_projections; DROP TABLE knowledge_processing_jobs;DROP VIEW knowledge_active_pull_conflicts; DROP VIEW knowledge_pending_outbox; DROP VIEW knowledge_unsettled_pushes; DROP TABLE knowledge_cloud_resolved_pushes; DROP TABLE knowledge_cloud_resolved_pull_conflicts; DROP TABLE knowledge_cloud_superseded_outbox; DROP TABLE knowledge_cloud_resolutions;";

#[test]
fn v6_cloud_resolution_upgrade_backs_up_before_journal_and_mapping_creation() {
    let directory = TestDirectory::new();
    drop(storage_lifecycle::open(&directory.0).unwrap());
    let knowledge = directory.0.join("knowledge");
    let db = Connection::open(knowledge.join("memories.db")).unwrap();
    db.execute_batch(DROP_CLOUD_SCHEMA).unwrap();
    db.execute_batch("UPDATE knowledge_schema SET version=6;")
        .unwrap();
    drop(storage_lifecycle::open(&directory.0).unwrap());
    let backups: Vec<_> = fs::read_dir(&knowledge)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.file_name().unwrap().to_string_lossy().contains("pre-v6-"))
        .collect();
    assert_eq!(backups.len(), 1);
    let backup = Connection::open(&backups[0]).unwrap();
    let original:(i64,i64)=backup.query_row("SELECT (SELECT version FROM knowledge_schema),(SELECT count(*) FROM sqlite_master WHERE name='knowledge_cloud_resolutions')",[],|r|Ok((r.get(0)?,r.get(1)?))).unwrap();
    assert_eq!(original, (6, 0));
    let version: i64 = db
        .query_row("SELECT version FROM knowledge_schema", [], |r| r.get(0))
        .unwrap();
    assert_eq!(
        version,
        agistack_adapters_device::knowledge::KNOWLEDGE_SCHEMA_VERSION
    );
}

#[test]
fn v3_push_upgrade_preserves_replica_and_backs_up_before_new_receipt_tables() {
    let directory = TestDirectory::new();
    drop(storage_lifecycle::open(&directory.0).unwrap());
    let knowledge = directory.0.join("knowledge");
    let database = knowledge.join("memories.db");
    let connection = Connection::open(&database).unwrap();
    let replica: String = connection
        .query_row("SELECT replica_id FROM knowledge_replica", [], |row| {
            row.get(0)
        })
        .unwrap();
    connection.execute_batch(DROP_CLOUD_SCHEMA).unwrap();
    connection.execute_batch("DROP TABLE knowledge_sync_outbox_metadata; DROP TABLE knowledge_sync_superseded_outbox; DROP TABLE knowledge_sync_resolved_pull_conflicts; DROP TABLE knowledge_sync_resolutions; DROP TABLE knowledge_sync_pull_cursors; DROP TABLE knowledge_sync_pull_events; DROP TABLE knowledge_sync_pull_conflicts; DROP TABLE knowledge_sync_pushes; DROP TABLE knowledge_sync_remote_versions; DROP TABLE knowledge_sync_targets; UPDATE knowledge_schema SET version=3;").unwrap();
    drop(storage_lifecycle::open(&directory.0).unwrap());
    let backups: Vec<_> = fs::read_dir(&knowledge)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| {
            path.file_name()
                .unwrap()
                .to_string_lossy()
                .contains("pre-v3-")
        })
        .collect();
    assert_eq!(backups.len(), 1);
    let backup = Connection::open(&backups[0]).unwrap();
    let (version,old_replica):(i64,String)=backup.query_row("SELECT (SELECT version FROM knowledge_schema),(SELECT replica_id FROM knowledge_replica)",[],|row|Ok((row.get(0)?,row.get(1)?))).unwrap();
    assert_eq!(version, 3);
    assert_eq!(old_replica, replica);
    let current: String = connection
        .query_row("SELECT replica_id FROM knowledge_replica", [], |row| {
            row.get(0)
        })
        .unwrap();
    assert_eq!(current, replica);
    let push_tables: i64 = backup
        .query_row(
            "SELECT count(*) FROM sqlite_master WHERE name='knowledge_sync_pushes'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(push_tables, 0);
}

#[test]
fn v2_upgrade_backs_up_before_creating_persistent_replica() {
    let directory = TestDirectory::new();
    drop(storage_lifecycle::open(&directory.0).unwrap());
    let knowledge = directory.0.join("knowledge");
    let database = knowledge.join("memories.db");
    let connection = Connection::open(&database).unwrap();
    connection.execute_batch(DROP_CLOUD_SCHEMA).unwrap();
    connection.execute_batch("DROP TABLE knowledge_sync_outbox_metadata; DROP TABLE knowledge_sync_superseded_outbox; DROP TABLE knowledge_sync_resolved_pull_conflicts; DROP TABLE knowledge_sync_resolutions; DROP TABLE knowledge_sync_pull_cursors; DROP TABLE knowledge_sync_pull_events; DROP TABLE knowledge_sync_pull_conflicts; DROP TABLE knowledge_sync_pushes; DROP TABLE knowledge_sync_remote_versions; DROP TABLE knowledge_sync_targets; DROP TABLE knowledge_sync_outbox; DROP TABLE knowledge_sync_links; DROP TABLE knowledge_replica; UPDATE knowledge_schema SET version=2;").unwrap();
    drop(storage_lifecycle::open(&directory.0).unwrap());
    let backups: Vec<_> = fs::read_dir(&knowledge)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| {
            path.file_name()
                .unwrap()
                .to_string_lossy()
                .contains("pre-v2-")
        })
        .collect();
    assert_eq!(backups.len(), 1);
    let backup = Connection::open(&backups[0]).unwrap();
    let old_version: i64 = backup
        .query_row("SELECT version FROM knowledge_schema", [], |row| row.get(0))
        .unwrap();
    assert_eq!(old_version, 2);
    let old_replica: i64 = backup
        .query_row(
            "SELECT count(*) FROM sqlite_master WHERE name='knowledge_replica'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(old_replica, 0);
    let replica: String = connection
        .query_row("SELECT replica_id FROM knowledge_replica", [], |row| {
            row.get(0)
        })
        .unwrap();
    drop(storage_lifecycle::open(&directory.0).unwrap());
    let replay: String = connection
        .query_row("SELECT replica_id FROM knowledge_replica", [], |row| {
            row.get(0)
        })
        .unwrap();
    assert_eq!(replica, replay);
}

#[test]
fn version_upgrade_backs_up_wal_and_validates_before_modifying() {
    let directory = TestDirectory::new();
    let knowledge = directory.0.join("knowledge");
    fs::create_dir_all(&knowledge).unwrap();
    let database = knowledge.join("memories.db");
    let source = Connection::open(&database).unwrap();
    source.execute_batch("PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0; CREATE TABLE knowledge_schema(version INTEGER NOT NULL); INSERT INTO knowledge_schema VALUES(1); CREATE TABLE retained(value TEXT); INSERT INTO retained VALUES('committed in WAL');").unwrap();
    let repository = storage_lifecycle::open(&directory.0).unwrap();
    let backups: Vec<_> = fs::read_dir(&knowledge)
        .unwrap()
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| {
            path.file_name()
                .unwrap()
                .to_string_lossy()
                .contains(".backup.db")
        })
        .collect();
    assert_eq!(backups.len(), 1);
    let backup = Connection::open(&backups[0]).unwrap();
    let (version, value): (i64, String) = backup
        .query_row(
            "SELECT (SELECT version FROM knowledge_schema),(SELECT value FROM retained)",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .unwrap();
    assert_eq!(version, 1);
    assert_eq!(value, "committed in WAL");
    let migrated: i64 = source
        .query_row("SELECT version FROM knowledge_schema", [], |row| row.get(0))
        .unwrap();
    assert_eq!(
        migrated,
        agistack_adapters_device::knowledge::KNOWLEDGE_SCHEMA_VERSION
    );
    drop(repository);
    drop(storage_lifecycle::open(&directory.0).unwrap());
    assert_eq!(
        fs::read_dir(&knowledge)
            .unwrap()
            .filter_map(Result::ok)
            .filter(|entry| entry.file_name().to_string_lossy().contains(".backup.db"))
            .count(),
        1
    );
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            fs::metadata(&knowledge).unwrap().permissions().mode() & 0o777,
            0o700
        );
        assert_eq!(
            fs::metadata(&database).unwrap().permissions().mode() & 0o777,
            0o600
        );
        assert_eq!(
            fs::metadata(&backups[0]).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
}

#[test]
fn unknown_schema_and_corruption_never_trigger_migration() {
    let directory = TestDirectory::new();
    let knowledge = directory.0.join("knowledge");
    fs::create_dir_all(&knowledge).unwrap();
    let database = knowledge.join("memories.db");
    let source = Connection::open(&database).unwrap();
    source.execute_batch("CREATE TABLE knowledge_schema(version INTEGER NOT NULL); INSERT INTO knowledge_schema VALUES(999);").unwrap();
    assert!(storage_lifecycle::open(&directory.0).is_err());
    let version: i64 = source
        .query_row("SELECT version FROM knowledge_schema", [], |row| row.get(0))
        .unwrap();
    assert_eq!(version, 999);
    drop(source);
    fs::write(&database, b"corrupt sqlite bytes").unwrap();
    assert!(storage_lifecycle::open(&directory.0).is_err());
    assert_eq!(fs::read(&database).unwrap(), b"corrupt sqlite bytes");
    assert_eq!(fs::read_dir(&knowledge).unwrap().count(), 1);
}

#[cfg(unix)]
#[test]
fn symlinked_database_is_rejected_without_touching_target() {
    let directory = TestDirectory::new();
    fs::create_dir_all(directory.0.join("knowledge")).unwrap();
    let target = directory.0.join("target");
    fs::write(&target, b"unchanged").unwrap();
    std::os::unix::fs::symlink(&target, directory.0.join("knowledge/memories.db")).unwrap();
    assert!(storage_lifecycle::open(&directory.0).is_err());
    assert_eq!(fs::read(target).unwrap(), b"unchanged");
}

#[tokio::test]
async fn v8_to_v9_backup_contains_committed_wal_source_and_lease_before_audit_migration() {
    use agistack_core::knowledge::{
        processing::{ProcessingRepository, ProcessingState},
        ScopedMemoryRepository,
    };
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    let auth = authenticated(&state);
    let scope = KnowledgeScope {
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
    };
    let MemoryMutation::Create { memory } = mutation(&auth) else {
        panic!("create fixture");
    };
    let repo = storage_lifecycle::open(&directory.0).unwrap();
    let source = repo.create(&scope, memory).await.unwrap();
    let lease = repo
        .claim(&scope, "v8-worker", 100, 500)
        .await
        .unwrap()
        .unwrap();
    drop(repo);
    let knowledge = directory.0.join("knowledge");
    let db = Connection::open(knowledge.join("memories.db")).unwrap();
    db.execute_batch("PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0; DROP TABLE knowledge_processing_audits; UPDATE knowledge_schema SET version=8; CREATE TABLE retained_v8_wal(value TEXT); INSERT INTO retained_v8_wal VALUES('v8 committed WAL');").unwrap();
    assert!(
        fs::metadata(knowledge.join("memories.db-wal"))
            .unwrap()
            .len()
            > 0
    );
    let upgraded = storage_lifecycle::open(&directory.0).unwrap();
    let backups: Vec<_> = fs::read_dir(&knowledge)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.file_name().unwrap().to_string_lossy().contains("pre-v8-"))
        .collect();
    assert_eq!(backups.len(), 1);
    let backup = Connection::open(&backups[0]).unwrap();
    let original:(i64,i64,String,String,String,i64)=backup.query_row("SELECT (SELECT version FROM knowledge_schema),(SELECT count(*) FROM sqlite_master WHERE name='knowledge_processing_audits'),(SELECT value FROM retained_v8_wal),(SELECT payload FROM knowledge_memories),(SELECT token FROM knowledge_processing_jobs),(SELECT expires_at_ms FROM knowledge_processing_jobs)",[],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?))).unwrap();
    assert_eq!((original.0, original.1), (8, 0));
    assert_eq!(original.2, "v8 committed WAL");
    assert_eq!(
        serde_json::from_str::<Memory>(&original.3).unwrap().content,
        source.content
    );
    assert_eq!(original.4, lease.token);
    assert_eq!(original.5, lease.expires_at_ms);
    assert_eq!(
        db.query_row("SELECT version FROM knowledge_schema", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        agistack_adapters_device::knowledge::KNOWLEDGE_SCHEMA_VERSION
    );
    let saved = upgraded.get(&scope, &source.id).await.unwrap().unwrap();
    assert_eq!(saved.version, source.version);
    assert_eq!(saved.content, source.content);
    let status = upgraded
        .processing_status(&scope, &lease.source)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(status.state, ProcessingState::Leased);
    assert_eq!(status.attempt, lease.attempt);
    assert!(upgraded
        .processing_audit_durable(&scope, &lease.source, lease.attempt)
        .unwrap()
        .is_none());
    let renewed = upgraded.renew(&scope, &lease, 200, 500).await.unwrap();
    assert_eq!(renewed.token, lease.token);
}

#[test]
fn index_upgrade_backs_up_v9_before_schema_creation_and_reopens_idempotently() {
    let directory = TestDirectory::new();
    drop(storage_lifecycle::open(&directory.0).unwrap());
    let knowledge = directory.0.join("knowledge");
    let connection = Connection::open(knowledge.join("memories.db")).unwrap();
    connection
        .execute_batch(
            "DROP TABLE knowledge_index_configuration;
        DROP TABLE knowledge_index_vectors;
        DROP TABLE knowledge_index_jobs; DROP TABLE knowledge_index_active;
        DROP TABLE knowledge_index_builds; UPDATE knowledge_schema SET version=9;
        CREATE TABLE index_upgrade_retained(value TEXT);
        INSERT INTO index_upgrade_retained VALUES('preserve v9 payload');",
        )
        .unwrap();
    drop(storage_lifecycle::open(&directory.0).unwrap());
    let backups: Vec<_> = fs::read_dir(&knowledge)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| {
            path.file_name()
                .unwrap()
                .to_string_lossy()
                .contains("pre-v9-")
        })
        .collect();
    assert_eq!(backups.len(), 1);
    let backup = Connection::open(&backups[0]).unwrap();
    let (version, tables, value): (i64, i64, String) = backup
        .query_row(
            "SELECT (SELECT version FROM knowledge_schema),
         (SELECT count(*) FROM sqlite_master WHERE name LIKE 'knowledge_index_%'),
         (SELECT value FROM index_upgrade_retained)",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .unwrap();
    assert_eq!(
        (version, tables, value),
        (9, 0, "preserve v9 payload".into())
    );
    let upgraded: i64 = connection
        .query_row("SELECT version FROM knowledge_schema", [], |row| row.get(0))
        .unwrap();
    assert_eq!(
        upgraded,
        agistack_adapters_device::knowledge::KNOWLEDGE_SCHEMA_VERSION
    );
    drop(storage_lifecycle::open(&directory.0).unwrap());
    assert_eq!(
        fs::read_dir(&knowledge)
            .unwrap()
            .map(|entry| entry.unwrap().path())
            .filter(|path| path
                .file_name()
                .unwrap()
                .to_string_lossy()
                .contains("pre-v9-"))
            .count(),
        1
    );
}

#[test]
fn desired_config_upgrade_backs_up_v10_and_never_infers_selection_from_active_index() {
    let directory = TestDirectory::new();
    drop(storage_lifecycle::open(&directory.0).unwrap());
    let knowledge = directory.0.join("knowledge");
    let connection = Connection::open(knowledge.join("memories.db")).unwrap();
    connection
        .execute_batch(
            "DROP TABLE knowledge_index_configuration;
        ALTER TABLE knowledge_index_jobs DROP COLUMN config_revision;
        UPDATE knowledge_schema SET version=10;
        INSERT INTO knowledge_index_active VALUES('t','p','historical-build');",
        )
        .unwrap();
    let repo = storage_lifecycle::open(&directory.0).unwrap();
    let scope = agistack_core::knowledge::KnowledgeScope {
        tenant_id: "t".into(),
        project_id: "p".into(),
    };
    assert!(repo
        .desired_index_config_durable(&scope, &|| Ok(1))
        .unwrap()
        .is_none());
    let backups = fs::read_dir(&knowledge)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| {
            p.file_name()
                .unwrap()
                .to_string_lossy()
                .contains("pre-v10-")
        })
        .collect::<Vec<_>>();
    assert_eq!(backups.len(), 1);
    let backup = Connection::open(&backups[0]).unwrap();
    let before: (i64, i64, String) = backup
        .query_row(
            "SELECT (SELECT version FROM knowledge_schema),
        (SELECT count(*) FROM sqlite_master WHERE name='knowledge_index_configuration'),
        (SELECT build_id FROM knowledge_index_active)",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .unwrap();
    assert_eq!(before, (10, 0, "historical-build".into()));
    drop(repo);
    drop(storage_lifecycle::open(&directory.0).unwrap());
    assert_eq!(
        fs::read_dir(&knowledge)
            .unwrap()
            .filter(|e| e
                .as_ref()
                .unwrap()
                .file_name()
                .to_string_lossy()
                .contains("pre-v10-"))
            .count(),
        1
    );
}

#[tokio::test]
async fn metadata_upgrade_backs_up_v11_bytes_before_recovering_trusted_document_fields() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    let auth = authenticated(&state);
    let MemoryMutation::Create { memory } = mutation(&auth) else {
        panic!("fixture")
    };
    let scope = KnowledgeScope {
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
    };
    let repo = storage_lifecycle::open(&directory.0).unwrap();
    repo.create(&scope, memory.clone()).await.unwrap();
    drop(repo);
    let knowledge = directory.0.join("knowledge");
    let connection = Connection::open(knowledge.join("memories.db")).unwrap();
    connection.execute_batch("UPDATE knowledge_memories SET payload=json_remove(payload,'$.metadata'); UPDATE knowledge_processing_changes SET payload=json_remove(payload,'$.metadata'); UPDATE knowledge_schema SET version=11;").unwrap();
    let original: String = connection
        .query_row("SELECT payload FROM knowledge_memories", [], |r| r.get(0))
        .unwrap();
    let remote = json!({"memory_id":memory.id,"revision":1,"deleted":false,"author_id":memory.author_id,"created_at_ms":memory.created_at_ms,"content":{"title":memory.title,"content":memory.content,"content_type":"text","tags":[],"status":"ENABLED","metadata":{"restored":["可信",null,false]}}});
    connection
        .execute(
            "INSERT INTO knowledge_sync_remote_versions VALUES(?1,?2,?3,?4)",
            rusqlite::params![
                scope.tenant_id,
                scope.project_id,
                memory.id,
                remote.to_string()
            ],
        )
        .unwrap();
    let repo = storage_lifecycle::open(&directory.0).unwrap();
    assert_eq!(
        serde_json::to_value(
            repo.get(&scope, &memory.id)
                .await
                .unwrap()
                .unwrap()
                .metadata
        )
        .unwrap(),
        remote["content"]["metadata"]
    );
    let backups = fs::read_dir(&knowledge)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| {
            path.file_name()
                .unwrap()
                .to_string_lossy()
                .contains("pre-v11-")
        })
        .collect::<Vec<_>>();
    assert_eq!(backups.len(), 1);
    let backup = Connection::open(&backups[0]).unwrap();
    let saved:(i64,String)=backup.query_row("SELECT (SELECT version FROM knowledge_schema),(SELECT payload FROM knowledge_memories)",[],|row|Ok((row.get(0)?,row.get(1)?))).unwrap();
    assert_eq!(saved, (11, original));
    drop(repo);
    drop(storage_lifecycle::open(&directory.0).unwrap());
    assert_eq!(
        fs::read_dir(&knowledge)
            .unwrap()
            .filter(|entry| entry
                .as_ref()
                .unwrap()
                .file_name()
                .to_string_lossy()
                .contains("pre-v11-"))
            .count(),
        1
    );
}
