//! Storage-only migration coverage: no schema API, authorization, outbox, or sync.
use super::*;
use agistack_core::knowledge::{KnowledgeScope, ScopedMemoryRepository};
use rusqlite::Connection;

#[tokio::test]
async fn v14_project_schema_upgrade_backs_up_wal_and_keeps_new_authority_empty() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    let auth = authenticated(&state);
    let scope = KnowledgeScope {
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
    db.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0;
        DROP TABLE knowledge_project_schema_heads;
        DROP TABLE knowledge_project_schema_changes;
        UPDATE knowledge_schema SET version=14;",
    )
    .unwrap();
    let repo = storage_lifecycle::open(&directory.0).unwrap();
    let backups: Vec<_> = fs::read_dir(&knowledge)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| {
            path.file_name()
                .unwrap()
                .to_string_lossy()
                .contains("pre-v14-")
        })
        .collect();
    assert_eq!(backups.len(), 1);
    let backup = Connection::open(&backups[0]).unwrap();
    let (version, tables, payload): (i64, u32, String) = backup
        .query_row(
            "SELECT (SELECT version FROM knowledge_schema),
        (SELECT count(*) FROM sqlite_master WHERE name IN
            ('knowledge_project_schema_heads','knowledge_project_schema_changes')),
        (SELECT payload FROM knowledge_memories)",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .unwrap();
    assert_eq!((version, tables), (14, 0));
    assert_eq!(
        serde_json::from_str::<Value>(&payload).unwrap(),
        serde_json::to_value(&source).unwrap()
    );
    assert!(repo
        .read_project_schema_durable(&scope, &|| Ok(()))
        .unwrap()
        .is_none());
    let (version, heads, changes): (i64, u32, u32) = db
        .query_row(
            "SELECT (SELECT version FROM knowledge_schema),
        (SELECT count(*) FROM knowledge_project_schema_heads),
        (SELECT count(*) FROM knowledge_project_schema_changes)",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .unwrap();
    assert_eq!((version, heads, changes), (16, 0, 0));
    drop(repo);
    let reopened = storage_lifecycle::open(&directory.0).unwrap();
    assert!(reopened
        .read_project_schema_durable(&scope, &|| Ok(()))
        .unwrap()
        .is_none());
    assert_eq!(
        fs::read_dir(&knowledge)
            .unwrap()
            .filter_map(Result::ok)
            .filter(|entry| entry.file_name().to_string_lossy().contains("pre-v14-"))
            .count(),
        1
    );
}
