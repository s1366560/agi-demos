use agistack_adapters_device::knowledge::project_schema::ProjectSchemaStorageError;

use super::support::*;

#[test]
fn head_failure_rolls_back_the_preceding_journal_insert() {
    let db = Database::new();
    let repo = db.open();
    repo.bootstrap_project_schema_durable(&scope(), "actor", &command(&scope(), 1), &current)
        .unwrap();
    let second = command(&scope(), 2);
    db.sql()
        .execute_batch(
            "CREATE TRIGGER injected_failure BEFORE UPDATE ON knowledge_project_schema_heads
        BEGIN SELECT RAISE(ABORT,'injected head failure'); END;",
        )
        .unwrap();
    assert!(repo
        .replace_project_schema_durable(&scope(), "actor", &second, &current)
        .is_err());
    assert_eq!(db.counts(), (1, 1));
    assert!(repo
        .project_schema_receipt_durable(&scope(), "actor", &second.change_id, &current)
        .unwrap()
        .is_none());
    assert_eq!(
        repo.read_project_schema_durable(&scope(), &current)
            .unwrap()
            .unwrap()
            .revision(),
        1
    );
}

#[test]
fn sql_guards_reject_mutated_history_unjournaled_heads_and_nonadjacent_steps() {
    let db = Database::new();
    let repo = db.open();
    repo.bootstrap_project_schema_durable(&scope(), "actor", &command(&scope(), 1), &current)
        .unwrap();
    for statement in [
        "UPDATE knowledge_project_schema_changes SET actor_id='other'",
        "DELETE FROM knowledge_project_schema_changes",
        "DELETE FROM knowledge_project_schema_heads",
        "INSERT OR REPLACE INTO knowledge_project_schema_heads SELECT * FROM knowledge_project_schema_heads",
        "UPDATE knowledge_project_schema_heads SET revision=2",
        "UPDATE knowledge_project_schema_heads SET document_json=json_set(document_json,'$.revision',2),revision=2",
        "UPDATE knowledge_project_schema_heads SET project_id='other'",
        "INSERT INTO knowledge_project_schema_changes SELECT * FROM knowledge_project_schema_changes",
        "INSERT INTO knowledge_project_schema_changes SELECT tenant_id,project_id,schema_id,revision+2,actor_id,
            '00000000-0000-4000-8000-000000000099',expected_revision+2,request_json,receipt_json FROM knowledge_project_schema_changes",
    ] { assert!(db.sql().execute_batch(statement).is_err(),"{statement}"); }
    assert_eq!(db.counts(), (1, 1));
    assert_eq!(
        repo.read_project_schema_durable(&scope(), &current)
            .unwrap()
            .unwrap()
            .revision(),
        1
    );
}

#[test]
fn tampered_receipt_cannot_be_returned_as_a_valid_document_or_replay() {
    let db = Database::new();
    let repo = db.open();
    let first = command(&scope(), 1);
    repo.bootstrap_project_schema_durable(&scope(), "actor", &first, &current)
        .unwrap();
    db.sql().execute_batch("DROP TRIGGER knowledge_project_schema_change_immutable;
        UPDATE knowledge_project_schema_changes SET receipt_json=json_set(receipt_json,'$.private_override',1);").unwrap();
    assert!(matches!(
        repo.read_project_schema_durable(&scope(), &current),
        Err(ProjectSchemaStorageError::CorruptStorage)
    ));
    assert!(matches!(
        repo.bootstrap_project_schema_durable(&scope(), "actor", &first, &current),
        Err(ProjectSchemaStorageError::CorruptStorage)
    ));
}
