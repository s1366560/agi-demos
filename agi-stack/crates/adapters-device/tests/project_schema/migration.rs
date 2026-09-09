use agistack_adapters_device::knowledge::{SqliteKnowledgeRepository, KNOWLEDGE_SCHEMA_VERSION};
use agistack_core::knowledge::{KnowledgeMemory, ScopedMemoryRepository};
use futures::executor::block_on;

use super::support::*;

pub const REMOVE_PROJECT_SCHEMA: &str = "DROP TABLE knowledge_project_schema_heads;
    DROP TABLE knowledge_project_schema_changes; UPDATE knowledge_schema SET version=14;";

#[test]
fn reopen_retains_exact_receipts_journal_head_and_opaque_numbers() {
    let db = Database::new();
    let first = command(&scope(), 1);
    let accepted = {
        let repo = db.open();
        let receipt = repo
            .bootstrap_project_schema_durable(&scope(), "actor", &first, &current)
            .unwrap();
        repo.replace_project_schema_durable(&scope(), "actor", &command(&scope(), 2), &current)
            .unwrap();
        receipt
    };
    let repo = db.open();
    let replay = repo
        .bootstrap_project_schema_durable(&scope(), "actor", &first, &current)
        .unwrap();
    assert_eq!(replay.as_json(), accepted.as_json());
    assert_eq!(
        repo.project_schema_receipt_durable(&scope(), "actor", &first.change_id, &current)
            .unwrap(),
        Some(accepted)
    );
    assert_eq!(
        repo.read_project_schema_durable(&scope(), &current)
            .unwrap()
            .unwrap()
            .revision(),
        2
    );
    assert_eq!(
        repo.project_schema_changes_durable(&scope(), 0, 100, &current)
            .unwrap()
            .items
            .len(),
        2
    );
    assert_eq!(db.counts(), (1, 2));
}

#[test]
fn additive_v14_upgrade_preserves_memory_receipts_processing_and_sync_rows() {
    let db = Database::new();
    let repo = db.open();
    let memory = KnowledgeMemory {
        id: "retained-memory".into(),
        project_id: scope().project_id,
        title: "Retain".into(),
        content: "Opaque memory content".into(),
        author_id: "actor".into(),
        content_type: "text".into(),
        tags: vec![],
        entities: vec![],
        version: 1,
        status: "ENABLED".into(),
        created_at_ms: 1,
        metadata: Default::default(),
        embedding: None,
    };
    block_on(repo.create(&scope(), memory.clone())).unwrap();
    drop(repo);
    let sql = db.sql();
    let before:(String,u32,u32)=sql.query_row("SELECT (SELECT payload FROM knowledge_memories),
        (SELECT count(*) FROM knowledge_processing_changes),(SELECT count(*) FROM knowledge_sync_outbox)",[],
        |r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).unwrap();
    sql.execute_batch(REMOVE_PROJECT_SCHEMA).unwrap();
    let repo = db.open();
    let version: i64 = sql
        .query_row("SELECT version FROM knowledge_schema", [], |r| r.get(0))
        .unwrap();
    assert_eq!(version, KNOWLEDGE_SCHEMA_VERSION);
    assert_eq!(version, 16);
    assert_eq!(
        serde_json::to_value(block_on(repo.get(&scope(), &memory.id)).unwrap().unwrap()).unwrap(),
        serde_json::to_value(memory).unwrap()
    );
    let after:(String,u32,u32)=sql.query_row("SELECT (SELECT payload FROM knowledge_memories),
        (SELECT count(*) FROM knowledge_processing_changes),(SELECT count(*) FROM knowledge_sync_outbox)",[],
        |r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).unwrap();
    assert_eq!(before, after);
    assert_eq!(db.counts(), (0, 0));
    assert!(repo
        .read_project_schema_durable(&scope(), &current)
        .unwrap()
        .is_none());
}

#[test]
fn failed_migration_keeps_version_and_rolls_back_new_objects() {
    let db = Database::new();
    drop(db.open());
    let sql = db.sql();
    sql.execute_batch(REMOVE_PROJECT_SCHEMA).unwrap();
    sql.execute_batch("CREATE VIEW knowledge_project_schema_changes AS SELECT 1 AS invalid")
        .unwrap();
    assert!(SqliteKnowledgeRepository::open(db.0.to_str().unwrap()).is_err());
    let state: (u32, u32) = sql
        .query_row(
            "SELECT (SELECT version FROM knowledge_schema),
        (SELECT count(*) FROM sqlite_master WHERE name='knowledge_project_schema_heads')",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .unwrap();
    assert_eq!(state, (14, 0));
}

#[test]
fn current_schema_missing_guards_fails_closed_instead_of_silently_repairing() {
    let db = Database::new();
    drop(db.open());
    db.sql()
        .execute_batch("DROP TRIGGER knowledge_project_schema_change_immutable")
        .unwrap();
    assert!(SqliteKnowledgeRepository::open(db.0.to_str().unwrap()).is_err());
}
