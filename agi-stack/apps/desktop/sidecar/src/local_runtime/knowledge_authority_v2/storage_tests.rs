use super::*;
use rusqlite::Connection;

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
    connection.execute_batch("DROP TABLE knowledge_sync_pull_cursors; DROP TABLE knowledge_sync_pull_events; DROP TABLE knowledge_sync_pull_conflicts; DROP TABLE knowledge_sync_pushes; DROP TABLE knowledge_sync_remote_versions; DROP TABLE knowledge_sync_targets; UPDATE knowledge_schema SET version=3;").unwrap();
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
    connection.execute_batch("DROP TABLE knowledge_sync_pull_cursors; DROP TABLE knowledge_sync_pull_events; DROP TABLE knowledge_sync_pull_conflicts; DROP TABLE knowledge_sync_pushes; DROP TABLE knowledge_sync_remote_versions; DROP TABLE knowledge_sync_targets; DROP TABLE knowledge_sync_outbox; DROP TABLE knowledge_sync_links; DROP TABLE knowledge_replica; UPDATE knowledge_schema SET version=2;").unwrap();
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
    assert_eq!(migrated, 5);
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
